import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session

from app.models import BuildProvenance, BuildRecord, Repository, SBOMDocument
from app.services.artifacts import register_artifact
from app.services.company_event_bus import emit_event


class BuildEvidenceError(RuntimeError):
    pass


def _git(repo: Repository, *args: str, text: bool = True) -> str:
    if not repo.local_path:
        raise BuildEvidenceError("Repository checkout is unavailable")
    proc = subprocess.run(["git", *args], cwd=Path(repo.local_path), text=text, capture_output=True)
    if proc.returncode != 0:
        raise BuildEvidenceError((proc.stderr or "git command failed")[-8000:])
    return proc.stdout


def resolve_commit(repo: Repository, ref: str) -> str:
    sha = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    if len(sha) < 7:
        raise BuildEvidenceError("Invalid Git commit")
    return sha


def source_manifest(repo: Repository, commit_sha: str, max_files: int = 5000) -> list[dict]:
    commit = resolve_commit(repo, commit_sha)
    output = _git(repo, "ls-tree", "-r", "--long", commit)
    items: list[dict] = []
    for raw in output.splitlines():
        if len(items) >= max_files:
            raise BuildEvidenceError("Repository exceeds evidence file limit")
        try:
            meta, path = raw.split("\t", 1)
            mode, kind, blob_sha, size_text = meta.split(" ", 3)
        except ValueError:
            continue
        if kind != "blob":
            continue
        try:
            size = int(size_text.strip())
        except ValueError:
            size = 0
        content = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=Path(repo.local_path), capture_output=True).stdout
        items.append({
            "path": path,
            "mode": mode,
            "git_blob_sha": blob_sha,
            "size": size,
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    return items


def _spdx_id(index: int) -> str:
    return f"SPDXRef-File-{index + 1}"


def generate_build_evidence(
    db: Session,
    repository: Repository,
    commit_sha: str,
    *,
    ci_run_id: int | None = None,
    release_id: int | None = None,
    producer_member_id: int | None = None,
    producer_agent_id: int | None = None,
) -> BuildRecord:
    commit = resolve_commit(repository, commit_sha)
    build = BuildRecord(
        organization_id=repository.organization_id, repository_id=repository.id, ci_run_id=ci_run_id,
        release_id=release_id, commit_sha=commit, status="building",
    )
    db.add(build); db.commit(); db.refresh(build)
    files = source_manifest(repository, commit)
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    bundle = f"build:{build.id}"
    manifest_artifact = register_artifact(
        db, organization_id=repository.organization_id, company_id=repository.company_id,
        project_id=repository.project_id, created_by_member_id=producer_member_id,
        created_by_agent_id=producer_agent_id, name="source-manifest.json",
        content_text=json.dumps({"commit_sha": commit, "source_digest": digest, "files": files}, indent=2),
        bundle_key=bundle, logical_path="evidence/source-manifest.json", artifact_type="build_manifest",
        mime_type="application/json", metadata={"build_id": build.id, "repository_id": repository.id},
    )
    namespace = f"https://clawcompany.local/spdx/{repository.organization_id}/{repository.id}/{build.id}/{digest[:16]}"
    spdx = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{repository.name}-{commit[:12]}",
        "documentNamespace": namespace,
        "creationInfo": {
            "created": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "creators": ["Tool: ClawCompany-v13"],
        },
        "files": [
            {
                "fileName": item["path"], "SPDXID": _spdx_id(index),
                "checksums": [{"algorithm": "SHA256", "checksumValue": item["sha256"]}],
            }
            for index, item in enumerate(files)
        ],
    }
    spdx_text = json.dumps(spdx, indent=2, sort_keys=True)
    sbom_artifact = register_artifact(
        db, organization_id=repository.organization_id, company_id=repository.company_id,
        project_id=repository.project_id, created_by_member_id=producer_member_id,
        created_by_agent_id=producer_agent_id, name="sbom.spdx.json", content_text=spdx_text,
        bundle_key=bundle, logical_path="evidence/sbom.spdx.json", artifact_type="sbom",
        mime_type="application/spdx+json", metadata={"build_id": build.id, "format": "SPDX-2.3"},
    )
    subject = [{"name": repository.name, "digest": {"sha256": digest}, "commit": commit}]
    provenance_doc = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": subject,
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://clawcompany.local/build/git-source/v1",
                "externalParameters": {"repository_id": repository.id, "commit_sha": commit},
                "resolvedDependencies": [{"uri": repository.remote_url or repository.local_path, "digest": {"gitCommit": commit}}],
            },
            "runDetails": {"builder": {"id": "clawcompany://builder/v13"}, "metadata": {"invocationId": str(build.id)}},
        },
    }
    provenance_text = json.dumps(provenance_doc, indent=2, sort_keys=True)
    provenance_artifact = register_artifact(
        db, organization_id=repository.organization_id, company_id=repository.company_id,
        project_id=repository.project_id, created_by_member_id=producer_member_id,
        created_by_agent_id=producer_agent_id, name="provenance.json", content_text=provenance_text,
        bundle_key=bundle, logical_path="evidence/provenance.json", artifact_type="provenance",
        mime_type="application/json", metadata={"build_id": build.id, "predicate_type": "https://slsa.dev/provenance/v1"},
    )
    sbom = SBOMDocument(
        organization_id=repository.organization_id, build_id=build.id, format="spdx-json", spec_version="SPDX-2.3",
        artifact_id=sbom_artifact.id, file_count=len(files), package_count=0,
        digest=hashlib.sha256(spdx_text.encode("utf-8")).hexdigest(),
    )
    provenance = BuildProvenance(
        organization_id=repository.organization_id, build_id=build.id, artifact_id=provenance_artifact.id,
        builder_id="clawcompany://builder/v13", predicate_type="https://slsa.dev/provenance/v1",
        invocation_json=json.dumps({"ci_run_id": ci_run_id, "build_id": build.id}),
        materials_json=json.dumps([{"repository_id": repository.id, "commit_sha": commit}]),
        subject_json=json.dumps(subject),
    )
    build.status = "completed"; build.source_digest = digest; build.manifest_artifact_id = manifest_artifact.id
    build.completed_at = datetime.utcnow()
    db.add_all([build, sbom, provenance]); db.commit(); db.refresh(build)
    emit_event(
        db, organization_id=repository.organization_id, company_id=repository.company_id,
        event_type="build.evidence.completed", source="engineering_org", aggregate_type="build", aggregate_id=str(build.id),
        actor_member_id=producer_member_id,
        payload={"build_id": build.id, "repository_id": repository.id, "commit_sha": commit,
                 "source_digest": digest, "sbom_artifact_id": sbom_artifact.id,
                 "provenance_artifact_id": provenance_artifact.id},
    )
    return build
