import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session
from app.core.config import settings
from app.models import DevWorkspace, SandboxProfile, SandboxRun
from app.services.secret_store import SecretAccessError, mounted_secret_directory, validate_grants
from app.services.company_event_bus import emit_event


class SandboxError(RuntimeError):
    pass


def profile_policy(profile: SandboxProfile) -> dict:
    warnings: list[str] = []
    if profile.network_mode != "none":
        warnings.append("restricted network requires a provider-specific egress policy")
    if not profile.read_only_root:
        warnings.append("root filesystem is writable")
    return {
        "provider": profile.provider,
        "network_mode": profile.network_mode,
        "read_only_root": profile.read_only_root,
        "cpu_limit": profile.cpu_limit,
        "memory_mb": profile.memory_mb,
        "pids_limit": profile.pids_limit,
        "warnings": warnings,
        "secure_default": profile.network_mode == "none" and profile.read_only_root,
    }


def validate_command(profile: SandboxProfile, command: list[str]) -> list[str]:
    if not command or any(not isinstance(x, str) or "\x00" in x for x in command):
        raise SandboxError("Command must be a non-empty argv array")
    executable = Path(command[0]).name
    try:
        allowed = set(json.loads(profile.allowed_commands_json or "[]"))
    except Exception:
        allowed = set()
    if allowed and executable not in allowed:
        raise SandboxError(f"Executable is not allowed by sandbox profile: {executable}")
    return command


def docker_argv(profile: SandboxProfile, workspace: DevWorkspace, command: list[str], secret_dir: Path | None = None) -> list[str]:
    validate_command(profile, command)
    if profile.network_mode == "restricted":
        raise SandboxError("Restricted egress needs a configured sandbox network provider; refusing open network")
    if not workspace.root_path:
        raise SandboxError("Workspace is not provisioned")
    args = [
        "docker", "run", "--rm", "--init", "--network", "none", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", str(profile.pids_limit),
        "--memory", f"{profile.memory_mb}m", "--cpus", str(profile.cpu_limit),
        "--user", settings.sandbox_docker_user,
        "--workdir", "/workspace", "--mount", f"type=bind,src={Path(workspace.root_path).resolve()},dst=/workspace",
        "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=128m",
    ]
    if profile.read_only_root:
        args.append("--read-only")
    if secret_dir:
        args += ["--mount", f"type=bind,src={secret_dir.resolve()},dst=/run/secrets,readonly"]
    args += [profile.image, *command]
    return args


def execute_sandbox(db: Session, run: SandboxRun) -> SandboxRun:
    workspace = db.get(DevWorkspace, run.workspace_id)
    profile = db.get(SandboxProfile, run.profile_id)
    if not workspace or workspace.organization_id != run.organization_id:
        raise SandboxError("Workspace not found")
    if not profile or profile.organization_id != run.organization_id or not profile.enabled:
        raise SandboxError("Sandbox profile is unavailable")
    try:
        command = json.loads(run.command_json or "[]")
        grant_ids = json.loads(run.secret_grant_ids_json or "[]")
    except Exception as exc:
        raise SandboxError("Invalid sandbox run payload") from exc
    validate_command(profile, command)
    pairs = validate_grants(db, run.organization_id, grant_ids, member_id=run.initiated_by_member_id,
                            agent_id=run.initiated_by_agent_id, sandbox_profile_id=profile.id)
    run.status = "running"; run.started_at = datetime.utcnow(); run.error = ""
    db.add(run); db.commit(); db.refresh(run)
    try:
        with mounted_secret_directory(pairs) as secret_dir:
            if profile.provider == "mock":
                run.provider_run_id = f"mock-sandbox-{run.id}"
                run.stdout_text = f"MOCK sandbox: {profile.image}\n$ {' '.join(command)}\npolicy={json.dumps(profile_policy(profile))}\n"
                run.stderr_text = ""; run.exit_code = 0
            elif profile.provider == "docker":
                if not settings.sandbox_docker_enabled:
                    raise SandboxError("Docker sandbox execution is disabled by configuration")
                if not shutil.which("docker"):
                    raise SandboxError("Docker CLI is unavailable")
                argv = docker_argv(profile, workspace, command, secret_dir if pairs else None)
                proc = subprocess.run(argv, text=True, capture_output=True, timeout=profile.timeout_seconds)
                run.provider_run_id = f"docker-local-{run.id}"
                run.stdout_text = proc.stdout[-200000:]
                run.stderr_text = proc.stderr[-200000:]
                run.exit_code = proc.returncode
            elif profile.provider == "microvm":
                raise SandboxError("MicroVM execution requires a separately deployed privileged runner adapter; none is configured")
            else:
                raise SandboxError("Kubernetes sandbox provider adapter is not configured")
        run.status = "passed" if run.exit_code == 0 else "failed"
        run.completed_at = datetime.utcnow()
    except (SandboxError, SecretAccessError, subprocess.TimeoutExpired) as exc:
        run.status = "failed"; run.error = str(exc); run.completed_at = datetime.utcnow()
        if isinstance(exc, subprocess.TimeoutExpired):
            run.error = f"Sandbox timeout after {profile.timeout_seconds}s"
        db.add(run); db.commit(); db.refresh(run)
        emit_event(db, organization_id=run.organization_id, event_type="sandbox.run.failed", source="dev_cloud",
                   aggregate_type="sandbox_run", aggregate_id=str(run.id), actor_member_id=run.initiated_by_member_id,
                   payload={"sandbox_run_id": run.id, "purpose": run.purpose, "error": run.error})
        return run
    db.add(run); db.commit(); db.refresh(run)
    emit_event(db, organization_id=run.organization_id, event_type="sandbox.run.completed", source="dev_cloud",
               aggregate_type="sandbox_run", aggregate_id=str(run.id), actor_member_id=run.initiated_by_member_id,
               payload={"sandbox_run_id": run.id, "purpose": run.purpose, "status": run.status, "exit_code": run.exit_code})
    return run
