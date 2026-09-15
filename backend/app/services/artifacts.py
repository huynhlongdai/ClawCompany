import hashlib
import json
from pathlib import Path, PurePosixPath
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import Artifact, ArtifactHandoff, Agent, Member
from app.services.company_event_bus import emit_event
from app.services.agent_messaging import send_message


def _safe_logical_path(value: str) -> str:
    raw = (value or "artifact.txt").replace("\\", "/").lstrip("/")
    path = PurePosixPath(raw)
    if any(part in {"..", ""} for part in path.parts):
        raise ValueError("Invalid logical_path")
    return str(path)


def register_artifact(db: Session, *, organization_id: int, name: str, content_text: str = "",
                      company_id: int | None = None, project_id: int | None = None, task_id: int | None = None,
                      created_by_member_id: int | None = None, created_by_agent_id: int | None = None,
                      runtime_run_id: str = "", bundle_key: str = "", logical_path: str = "",
                      artifact_type: str = "deliverable", mime_type: str = "text/plain", uri: str = "",
                      metadata: dict | None = None, status: str = "ready") -> Artifact:
    if created_by_member_id is not None:
        member = db.get(Member, created_by_member_id)
        if not member or member.organization_id != organization_id:
            raise ValueError("Producer member does not belong to organization")
    if created_by_agent_id is not None:
        agent = db.get(Agent, created_by_agent_id)
        member = db.get(Member, agent.member_id) if agent else None
        if not agent or not member or member.organization_id != organization_id:
            raise ValueError("Producer agent does not belong to organization")
    logical_path = _safe_logical_path(logical_path or name)
    latest = db.query(Artifact).filter(
        Artifact.organization_id == organization_id,
        Artifact.bundle_key == (bundle_key or ""),
        Artifact.logical_path == logical_path,
    ).order_by(Artifact.version.desc()).first()
    version = (latest.version + 1) if latest else 1
    sha = hashlib.sha256(content_text.encode("utf-8")).hexdigest() if content_text else ""
    item = Artifact(
        organization_id=organization_id, company_id=company_id, project_id=project_id, task_id=task_id,
        created_by_member_id=created_by_member_id, created_by_agent_id=created_by_agent_id,
        runtime_run_id=runtime_run_id, bundle_key=bundle_key, logical_path=logical_path, name=name,
        artifact_type=artifact_type, mime_type=mime_type, storage_backend="inline" if content_text else "external",
        uri=uri, content_text=content_text, content_sha256=sha, version=version,
        parent_artifact_id=latest.id if latest else None, status=status,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False, default=str),
    )
    db.add(item); db.commit(); db.refresh(item)
    emit_event(
        db, organization_id=organization_id, company_id=company_id, event_type="artifact.created",
        source="artifact_registry", aggregate_type="artifact", aggregate_id=str(item.id), actor_member_id=created_by_member_id,
        payload={"artifact_id": item.id, "task_id": task_id, "bundle_key": bundle_key,
                 "logical_path": logical_path, "version": version, "type": artifact_type, "sha256": sha},
    )
    return item


def handoff_artifact(db: Session, artifact: Artifact, *, to_member_id: int, from_member_id: int | None = None,
                     task_id: int | None = None, purpose: str = "continue_work", instructions: str = "") -> ArtifactHandoff:
    target = db.get(Member, to_member_id)
    if not target or target.organization_id != artifact.organization_id:
        raise ValueError("Handoff target does not belong to organization")
    item = ArtifactHandoff(
        organization_id=artifact.organization_id, artifact_id=artifact.id, from_member_id=from_member_id,
        to_member_id=to_member_id, task_id=task_id or artifact.task_id, purpose=purpose,
        instructions=instructions, status="pending",
    )
    db.add(item); db.commit(); db.refresh(item)
    send_message(
        db, organization_id=artifact.organization_id, company_id=artifact.company_id,
        sender_member_id=from_member_id, recipient_member_id=to_member_id,
        thread_key=f"artifact:{artifact.bundle_key or artifact.id}", message_type="artifact_handoff",
        subject=f"Artifact handoff: {artifact.name}",
        content=instructions or f"Please continue work with {artifact.logical_path} v{artifact.version}.",
        task_id=item.task_id, artifact_id=artifact.id, priority="high", context={"handoff_id": item.id},
    )
    emit_event(
        db, organization_id=artifact.organization_id, company_id=artifact.company_id,
        event_type="artifact.handoff.requested", source="artifact_registry", aggregate_type="artifact_handoff",
        aggregate_id=str(item.id), actor_member_id=from_member_id,
        payload={"handoff_id": item.id, "artifact_id": artifact.id, "to_member_id": to_member_id,
                 "purpose": purpose, "task_id": item.task_id},
    )
    return item


def accept_handoff(db: Session, handoff: ArtifactHandoff, *, member_id: int) -> ArtifactHandoff:
    if handoff.to_member_id != member_id:
        raise ValueError("Only the target member can accept this handoff")
    if handoff.status not in {"pending", "sent"}:
        return handoff
    handoff.status = "accepted"; handoff.accepted_at = datetime.utcnow(); db.add(handoff); db.commit(); db.refresh(handoff)
    artifact = db.get(Artifact, handoff.artifact_id)
    emit_event(
        db, organization_id=handoff.organization_id, company_id=artifact.company_id if artifact else None,
        event_type="artifact.handoff.accepted", source="artifact_registry", aggregate_type="artifact_handoff",
        aggregate_id=str(handoff.id), actor_member_id=member_id,
        payload={"handoff_id": handoff.id, "artifact_id": handoff.artifact_id, "member_id": member_id},
    )
    # v12: accepted handoffs may create repository delivery runs through explicit
    # organization-scoped automation rules. The import is local to avoid coupling
    # the artifact registry to the repository delivery layer at module import time.
    try:
        from app.services.delivery_automation import auto_delivery_from_handoff
        auto_delivery_from_handoff(db, handoff)
    except Exception as exc:
        # Handoff acceptance is the source-of-truth operation. Automation failures
        # are fail-soft here and can be retried from the delivery automation API.
        emit_event(
            db, organization_id=handoff.organization_id, company_id=artifact.company_id if artifact else None,
            event_type="artifact.handoff.automation_failed", source="artifact_registry",
            aggregate_type="artifact_handoff", aggregate_id=str(handoff.id), actor_member_id=member_id,
            payload={"handoff_id": handoff.id, "error": str(exc)[:1000]},
        )
    return handoff


def materialize_artifact(artifact: Artifact) -> str:
    if not artifact.content_text:
        raise ValueError("Artifact has no inline content to materialize")
    logical = _safe_logical_path(artifact.logical_path or artifact.name)
    root = Path(settings.artifact_workspace_root).expanduser().resolve()
    bundle = artifact.bundle_key or f"artifact-{artifact.id}"
    safe_bundle = "".join(ch for ch in bundle if ch.isalnum() or ch in {"-", "_", "."})[:180] or f"artifact-{artifact.id}"
    target = (root / str(artifact.organization_id) / safe_bundle / logical).resolve()
    allowed_root = (root / str(artifact.organization_id) / safe_bundle).resolve()
    if allowed_root not in target.parents and target != allowed_root:
        raise ValueError("Artifact path escapes workspace root")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(artifact.content_text, encoding="utf-8")
    return str(target)
