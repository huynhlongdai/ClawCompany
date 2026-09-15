import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session
from app.models import Repository, ScannerProvider, ExternalScanRun, SecurityFinding
from app.services.security_review import scan_repository_commit


class ScannerAdapterError(RuntimeError):
    pass


SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _checkout(repo: Repository, sha: str):
    root = Path(repo.local_path or "").resolve()
    if not root.exists():
        raise ScannerAdapterError("Local repository checkout is unavailable")
    td = tempfile.TemporaryDirectory(prefix="cc-scan-")
    target = Path(td.name) / "repo"
    p = subprocess.run(["git", "worktree", "add", "--detach", str(target), sha], cwd=root, capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        td.cleanup(); raise ScannerAdapterError((p.stderr or p.stdout)[:4000])
    return td, target, root


def _remove_checkout(td, target: Path, root: Path):
    subprocess.run(["git", "worktree", "remove", "--force", str(target)], cwd=root, capture_output=True, timeout=60)
    td.cleanup()


def _verdict(severities: list[str], block_on: str) -> str:
    threshold = SEVERITY_RANK.get(block_on.lower(), 3)
    return "blocked" if any(SEVERITY_RANK.get(x.lower(), 0) >= threshold for x in severities) else "pass"


def _run_cli(provider: ScannerProvider, cwd: Path) -> tuple[int, dict, str]:
    exe = provider.executable or provider.provider_type
    exe_path = shutil.which(exe)
    if not exe_path:
        raise ScannerAdapterError(f"Scanner executable is unavailable: {exe}")
    if provider.provider_type == "semgrep":
        args = [exe_path, "scan", "--json", "--config", "auto", "."]
    elif provider.provider_type == "trivy":
        args = [exe_path, "fs", "--format", "json", "."]
    elif provider.provider_type == "osv":
        args = [exe_path, "scan", "--format", "json", "-r", "."]
    else:
        raise ScannerAdapterError(f"Unsupported scanner provider: {provider.provider_type}")
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=300)
    raw = p.stdout or "{}"
    try: data = json.loads(raw)
    except Exception: data = {"raw": raw[:20000]}
    return p.returncode, data, (p.stderr or "")[:8000]


def _normalize(provider_type: str, data: dict) -> list[dict]:
    findings: list[dict] = []
    if provider_type == "semgrep":
        for r in data.get("results", []) or []:
            extra = r.get("extra", {}) or {}; sev = str(extra.get("severity", "medium")).lower()
            findings.append({"severity": sev, "rule_id": r.get("check_id", "semgrep"), "path": r.get("path", ""),
                             "line": (r.get("start", {}) or {}).get("line"), "message": extra.get("message", "")})
    elif provider_type == "trivy":
        for result in data.get("Results", []) or []:
            for v in result.get("Vulnerabilities", []) or []:
                findings.append({"severity": str(v.get("Severity", "medium")).lower(), "rule_id": v.get("VulnerabilityID", "trivy"),
                                 "path": result.get("Target", ""), "message": v.get("Title", "")})
    elif provider_type == "osv":
        for result in data.get("results", []) or []:
            for pkg in result.get("packages", []) or []:
                for v in pkg.get("vulnerabilities", []) or []:
                    findings.append({"severity": "high", "rule_id": v.get("id", "osv"), "path": result.get("source", {}).get("path", ""),
                                     "message": (v.get("summary") or "Known vulnerability")[:1000]})
    return findings


def run_scanner(db: Session, provider: ScannerProvider, repo: Repository, commit_sha: str, *, ci_run_id: int | None = None) -> ExternalScanRun:
    if not provider.enabled or provider.organization_id != repo.organization_id:
        raise ScannerAdapterError("Scanner provider is unavailable for this organization")
    item = ExternalScanRun(organization_id=repo.organization_id, provider_id=provider.id, repository_id=repo.id,
                           ci_run_id=ci_run_id, commit_sha=commit_sha, status="running")
    db.add(item); db.commit(); db.refresh(item)
    try:
        if provider.provider_type == "builtin":
            threshold = SEVERITY_RANK.get((provider.block_on or "high").lower(), 3)
            blocked_levels = [name for name, rank in SEVERITY_RANK.items() if rank >= threshold]
            review = scan_repository_commit(db, repo, commit_sha, ci_run_id=ci_run_id, block_on=blocked_levels)
            rows = db.query(SecurityFinding).filter(SecurityFinding.review_id == review.id).all()
            findings = [{"severity": x.severity, "rule_id": x.rule_id, "path": x.path, "line": x.line, "message": x.title} for x in rows]
            item.exit_code = 0; item.verdict = review.verdict
        else:
            td, target, root = _checkout(repo, commit_sha)
            try:
                code, data, stderr = _run_cli(provider, target)
                findings = _normalize(provider.provider_type, data)
                item.exit_code = code
                # Tools often return non-zero when findings exist. Parse the report first; only execution errors without report fail the run.
                item.verdict = _verdict([x.get("severity", "info") for x in findings], provider.block_on)
                if stderr and not findings and code not in {0, 1}:
                    raise ScannerAdapterError(stderr)
            finally:
                _remove_checkout(td, target, root)
        item.findings_json = json.dumps(findings, ensure_ascii=False)
        item.summary_json = json.dumps({"count": len(findings), "by_severity": {s: sum(1 for x in findings if x.get("severity") == s) for s in SEVERITY_RANK}}, sort_keys=True)
        item.status = "completed"; item.completed_at = datetime.utcnow()
    except Exception as exc:
        item.status = "unavailable" if "unavailable" in str(exc).lower() else "failed"
        item.verdict = "blocked"; item.error = str(exc)[:8000]; item.completed_at = datetime.utcnow()
    db.add(item); db.commit(); db.refresh(item)
    return item
