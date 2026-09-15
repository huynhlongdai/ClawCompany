import fnmatch
import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from sqlalchemy.orm import Session

from app.models import DevWorkspace, WorkspaceGatewayOperation, WorkspaceGatewaySession
from app.services.artifacts import register_artifact
from app.services.company_event_bus import emit_event


class WorkspaceGatewayError(RuntimeError):
    pass


def _safe_relative(value: str) -> PurePosixPath:
    raw = (value or "").replace("\\", "/").lstrip("/")
    rel = PurePosixPath(raw)
    if not raw or any(part in {"", ".."} for part in rel.parts):
        raise WorkspaceGatewayError("Invalid workspace path")
    if rel.parts and rel.parts[0] == ".git":
        raise WorkspaceGatewayError("Direct .git access is not allowed through Workspace Gateway")
    return rel


def resolve_workspace_file(workspace: DevWorkspace, logical_path: str) -> Path:
    if workspace.status != "ready" or not workspace.root_path:
        raise WorkspaceGatewayError("Workspace is not ready")
    root = Path(workspace.root_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise WorkspaceGatewayError("Workspace root is unavailable")
    rel = _safe_relative(logical_path)
    target = (root / Path(*rel.parts)).resolve()
    if target != root and root not in target.parents:
        raise WorkspaceGatewayError("Workspace path escapes root")
    return target


def _assert_session(session: WorkspaceGatewaySession, workspace: DevWorkspace) -> None:
    if session.status != "active":
        raise WorkspaceGatewayError("Workspace Gateway session is not active")
    if session.expires_at and session.expires_at <= datetime.utcnow():
        session.status = "expired"
        raise WorkspaceGatewayError("Workspace Gateway session expired")
    if session.workspace_id != workspace.id or session.organization_id != workspace.organization_id:
        raise WorkspaceGatewayError("Workspace Gateway session mismatch")


def _capabilities(session: WorkspaceGatewaySession) -> set[str]:
    try:
        value = json.loads(session.capabilities_json or "[]")
        return {str(x) for x in value if isinstance(x, str)}
    except Exception:
        return set()


def _require_capability(session: WorkspaceGatewaySession, capability: str) -> None:
    caps = _capabilities(session)
    if "*" not in caps and capability not in caps:
        raise WorkspaceGatewayError(f"Workspace capability required: {capability}")


def open_gateway_session(
    db: Session,
    workspace: DevWorkspace,
    *,
    member_id: int | None,
    agent_id: int | None,
    provider: str,
    provider_session_id: str = "",
    capabilities: list[str] | None = None,
    ttl_minutes: int = 120,
) -> WorkspaceGatewaySession:
    if workspace.status != "ready" or not workspace.root_path:
        raise WorkspaceGatewayError("Workspace is not ready")
    item = WorkspaceGatewaySession(
        organization_id=workspace.organization_id,
        workspace_id=workspace.id,
        member_id=member_id,
        agent_id=agent_id,
        provider=(provider or "external")[:64],
        provider_session_id=(provider_session_id or "")[:240],
        session_key=f"wgs_{secrets.token_urlsafe(24)}",
        capabilities_json=json.dumps(capabilities or ["read", "write", "snapshot"]),
        status="active",
        expires_at=datetime.utcnow() + timedelta(minutes=ttl_minutes),
    )
    db.add(item); db.commit(); db.refresh(item)
    emit_event(
        db, organization_id=item.organization_id, event_type="workspace.gateway.opened", source="workspace_gateway",
        aggregate_type="workspace_gateway_session", aggregate_id=str(item.id), actor_member_id=member_id,
        payload={"session_id": item.id, "workspace_id": workspace.id, "provider": item.provider, "agent_id": agent_id},
    )
    return item


def _record_operation(db: Session, session: WorkspaceGatewaySession, operation_type: str, *, logical_path: str = "",
                      artifact_id: int | None = None, request: dict | None = None, response: dict | None = None,
                      status: str = "completed", error: str = "") -> WorkspaceGatewayOperation:
    item = WorkspaceGatewayOperation(
        organization_id=session.organization_id, session_id=session.id, operation_type=operation_type,
        logical_path=logical_path, artifact_id=artifact_id, request_json=json.dumps(request or {}, ensure_ascii=False),
        response_json=json.dumps(response or {}, ensure_ascii=False), status=status, error=error,
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


def write_text(db: Session, session: WorkspaceGatewaySession, workspace: DevWorkspace, logical_path: str, content: str) -> dict:
    _assert_session(session, workspace); _require_capability(session, "write")
    target = resolve_workspace_file(workspace, logical_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    result = {"logical_path": logical_path, "bytes": len(content.encode("utf-8"))}
    _record_operation(db, session, "write_text", logical_path=logical_path, response=result)
    return result


def read_text(db: Session, session: WorkspaceGatewaySession, workspace: DevWorkspace, logical_path: str, max_bytes: int = 200_000) -> dict:
    _assert_session(session, workspace); _require_capability(session, "read")
    target = resolve_workspace_file(workspace, logical_path)
    if not target.exists() or not target.is_file():
        raise WorkspaceGatewayError("Workspace file not found")
    if target.stat().st_size > max_bytes:
        raise WorkspaceGatewayError("Workspace file exceeds read limit")
    content = target.read_text(encoding="utf-8", errors="replace")
    result = {"logical_path": logical_path, "content": content, "bytes": target.stat().st_size}
    _record_operation(db, session, "read_text", logical_path=logical_path, response={"bytes": result["bytes"]})
    return result


def snapshot_workspace(db: Session, session: WorkspaceGatewaySession, workspace: DevWorkspace, *, bundle_key: str,
                       artifact_type: str = "source_code", include_globs: list[str] | None = None,
                       max_files: int = 250) -> list[int]:
    _assert_session(session, workspace); _require_capability(session, "snapshot")
    root = Path(workspace.root_path).resolve()
    globs = include_globs or []
    artifact_ids: list[int] = []
    for path in sorted(root.rglob("*")):
        if len(artifact_ids) >= max_files:
            break
        if not path.is_file() or ".git" in path.relative_to(root).parts:
            continue
        rel = path.relative_to(root).as_posix()
        if globs and not any(fnmatch.fnmatch(rel, pattern) for pattern in globs):
            continue
        if path.stat().st_size > 1_000_000:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        artifact = register_artifact(
            db, organization_id=workspace.organization_id, company_id=workspace.company_id,
            project_id=workspace.project_id, created_by_member_id=session.member_id,
            created_by_agent_id=session.agent_id, name=path.name, content_text=content,
            bundle_key=bundle_key, logical_path=rel, artifact_type=artifact_type,
            metadata={"workspace_id": workspace.id, "gateway_session_id": session.id, "provider": session.provider},
        )
        artifact_ids.append(artifact.id)
    _record_operation(db, session, "snapshot", request={"bundle_key": bundle_key, "include_globs": globs},
                      response={"artifact_ids": artifact_ids, "count": len(artifact_ids)})
    emit_event(
        db, organization_id=workspace.organization_id, company_id=workspace.company_id,
        event_type="workspace.gateway.snapshot.created", source="workspace_gateway",
        aggregate_type="workspace_gateway_session", aggregate_id=str(session.id), actor_member_id=session.member_id,
        payload={"session_id": session.id, "workspace_id": workspace.id, "bundle_key": bundle_key, "artifact_ids": artifact_ids},
    )
    return artifact_ids


def close_gateway_session(db: Session, session: WorkspaceGatewaySession) -> WorkspaceGatewaySession:
    if session.status == "active":
        session.status = "closed"; session.closed_at = datetime.utcnow(); db.add(session); db.commit(); db.refresh(session)
    return session
