import re
import subprocess
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session

from app.models import Repository, SecurityFinding, SecurityReview
from app.services.build_evidence import resolve_commit
from app.services.company_event_bus import emit_event


RULES = [
    ("SEC001", "critical", "secret", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "Private key committed to source"),
    ("SEC002", "high", "secret", re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key-shaped credential in source"),
    ("SEC003", "high", "command_execution", re.compile(r"subprocess\.(?:run|Popen|call)\([^\n]*shell\s*=\s*True"), "Shell execution enabled in subprocess"),
    ("SEC004", "high", "command_execution", re.compile(r"\bos\.system\s*\("), "os.system command execution"),
    ("SEC005", "medium", "dynamic_code", re.compile(r"\b(?:eval|exec)\s*\("), "Dynamic code execution"),
    ("SEC006", "medium", "deserialization", re.compile(r"\bpickle\.loads?\s*\("), "Unsafe pickle deserialization"),
    ("SEC007", "medium", "transport", re.compile(r"verify\s*=\s*False"), "TLS verification disabled"),
]

TEXT_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".sh", ".bash", ".yaml", ".yml", ".json", ".toml", ".env", ".txt", ".md"}


class SecurityReviewError(RuntimeError):
    pass


def _files_at_commit(repository: Repository, commit_sha: str, max_files: int = 3000):
    commit = resolve_commit(repository, commit_sha)
    proc = subprocess.run(["git", "ls-tree", "-r", "--name-only", commit], cwd=Path(repository.local_path), text=True, capture_output=True)
    if proc.returncode != 0:
        raise SecurityReviewError(proc.stderr[-8000:])
    count = 0
    for path in proc.stdout.splitlines():
        if count >= max_files:
            break
        if Path(path).suffix.lower() not in TEXT_EXTENSIONS and Path(path).name not in {"Dockerfile", "Makefile"}:
            continue
        raw = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=Path(repository.local_path), capture_output=True)
        if raw.returncode != 0 or len(raw.stdout) > 1_500_000:
            continue
        count += 1
        yield path, raw.stdout.decode("utf-8", "replace")


def scan_repository_commit(
    db: Session, repository: Repository, commit_sha: str, *, ci_run_id: int | None = None, build_id: int | None = None,
    reviewer_member_id: int | None = None, reviewer_agent_id: int | None = None,
    block_on: list[str] | None = None,
) -> SecurityReview:
    commit = resolve_commit(repository, commit_sha)
    review = SecurityReview(
        organization_id=repository.organization_id, repository_id=repository.id, ci_run_id=ci_run_id, build_id=build_id,
        reviewer_member_id=reviewer_member_id, reviewer_agent_id=reviewer_agent_id, commit_sha=commit, status="running",
    )
    db.add(review); db.commit(); db.refresh(review)
    weights = {"critical": 35, "high": 20, "medium": 8, "low": 2}
    findings: list[SecurityFinding] = []
    for path, content in _files_at_commit(repository, commit):
        for rule_id, severity, category, pattern, title in RULES:
            for match in pattern.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                evidence = match.group(0)[:240]
                finding = SecurityFinding(
                    organization_id=repository.organization_id, review_id=review.id, severity=severity,
                    category=category, rule_id=rule_id, path=path, line=line, title=title, evidence=evidence,
                )
                db.add(finding); findings.append(finding)
                if len(findings) >= 300:
                    break
            if len(findings) >= 300:
                break
        if len(findings) >= 300:
            break
    db.commit()
    blocked_levels = set(block_on or ["critical", "high"])
    blocked = any(f.severity in blocked_levels for f in findings)
    score = max(0.0, 100.0 - sum(weights.get(f.severity, 1) for f in findings))
    review.status = "completed"; review.verdict = "blocked" if blocked else ("warn" if findings else "pass")
    review.score = score
    review.summary = f"{len(findings)} deterministic source findings; verdict={review.verdict}. This is not a CVE/dependency scan."
    review.completed_at = datetime.utcnow(); db.add(review); db.commit(); db.refresh(review)
    emit_event(
        db, organization_id=repository.organization_id, company_id=repository.company_id,
        event_type="security.review.completed", source="engineering_org", aggregate_type="security_review",
        aggregate_id=str(review.id), actor_member_id=reviewer_member_id,
        payload={"review_id": review.id, "repository_id": repository.id, "commit_sha": commit,
                 "verdict": review.verdict, "score": review.score, "finding_count": len(findings)},
    )
    return review
