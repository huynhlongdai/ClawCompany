from pathlib import Path
import json
import os
import subprocess

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.core.config import settings
from app.models import (
    Approval, ArtifactHandoff, Company, DeliveryAutomationRule, DevWorkspace, DeploymentEnvironment,
    Member, Agent, Organization, Release, Repository, SandboxProfile, SandboxRun, SecretGrant, SecretReference,
)
from app.services.artifacts import accept_handoff, handoff_artifact, register_artifact
from app.services.dev_cloud import WorkspaceError, provision_workspace, workspace_path
from app.services.repository_delivery import initialize_repository
from app.services.releases import deploy_release, deployment_gate, rollback_environment
from app.services.sandbox_runner import docker_argv, execute_sandbox, profile_policy
from app.services.secret_store import secret_metadata


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db, tmp_path: Path):
    settings.repository_workspace_root = str(tmp_path / "repos")
    settings.dev_workspace_root = str(tmp_path / "workspaces")
    settings.deployment_workspace_root = str(tmp_path / "deployments")
    org = Organization(name="Nova v12", slug="nova-v12")
    db.add(org); db.commit(); db.refresh(org)
    company = Company(organization_id=org.id, name="Nova Labs", industry="AI")
    db.add(company); db.commit(); db.refresh(company)
    coder = Member(organization_id=org.id, company_id=company.id, name="Coder", member_type="agent", role="Engineer")
    commit_member = Member(organization_id=org.id, company_id=company.id, name="Commit Agent", member_type="agent", role="Release Engineer")
    founder = Member(organization_id=org.id, company_id=company.id, name="Long", member_type="human", role="Founder")
    db.add_all([coder, commit_member, founder]); db.commit()
    for x in [coder, commit_member, founder]: db.refresh(x)
    coder_agent = Agent(member_id=coder.id, runtime_agent_id="coder-v12", model="mock")
    commit_agent = Agent(member_id=commit_member.id, runtime_agent_id="commit-v12", model="mock")
    db.add_all([coder_agent, commit_agent]); db.commit(); db.refresh(coder_agent); db.refresh(commit_agent)
    repo = Repository(organization_id=org.id, company_id=company.id, name="Secure Product", provider="local", default_branch="main")
    db.add(repo); db.commit(); db.refresh(repo)
    initialize_repository(repo); db.add(repo); db.commit(); db.refresh(repo)
    return org, company, coder, commit_member, founder, coder_agent, commit_agent, repo


def git_commit(repo: Repository, rel: str, content: str, message: str) -> str:
    path = Path(repo.local_path)
    target = path / rel; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.local", "commit", "-m", message], cwd=path, check=True, capture_output=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=path, text=True).strip()


def test_workspace_provisioning_is_root_bounded(tmp_path):
    db = session(); org, company, coder, commit_member, founder, coder_agent, commit_agent, repo = seed(db, tmp_path)
    ws = DevWorkspace(organization_id=org.id, company_id=company.id, repository_id=repo.id, owner_member_id=coder.id,
                      name="Feature workspace", workspace_key="feature-12", base_ref="main", status="provisioning")
    db.add(ws); db.commit(); db.refresh(ws); provision_workspace(db, ws, ttl_minutes=30)
    assert Path(ws.root_path).exists()
    assert Path(settings.dev_workspace_root).resolve() in Path(ws.root_path).resolve().parents
    assert (Path(ws.root_path) / "README.md").exists()
    # Key normalization prevents traversal from escaping the configured root.
    path = workspace_path(org.id, "../../etc/passwd")
    assert Path(settings.dev_workspace_root).resolve() in path.parents


def test_docker_sandbox_command_has_security_controls(tmp_path):
    db = session(); org, company, coder, commit_member, founder, coder_agent, commit_agent, repo = seed(db, tmp_path)
    ws = DevWorkspace(organization_id=org.id, company_id=company.id, name="Empty", workspace_key="empty", status="provisioning")
    db.add(ws); db.commit(); db.refresh(ws); provision_workspace(db, ws)
    profile = SandboxProfile(organization_id=org.id, company_id=company.id, name="Locked", provider="docker", image="python:3.12-slim",
                             network_mode="none", read_only_root=True, cpu_limit=1, memory_mb=512, pids_limit=128,
                             allowed_commands_json=json.dumps(["python"]))
    db.add(profile); db.commit(); db.refresh(profile)
    argv = docker_argv(profile, ws, ["python", "-V"])
    joined = " ".join(argv)
    assert "--network none" in joined
    assert "--cap-drop ALL" in joined
    assert "no-new-privileges" in joined
    assert "--read-only" in argv
    assert "--pids-limit" in argv and "--memory" in argv and "--cpus" in argv
    assert profile_policy(profile)["secure_default"] is True


def test_mock_sandbox_uses_secret_grant_without_leaking_value(tmp_path, monkeypatch):
    db = session(); org, company, coder, commit_member, founder, coder_agent, commit_agent, repo = seed(db, tmp_path)
    ws = DevWorkspace(organization_id=org.id, company_id=company.id, name="Secret", workspace_key="secret", status="provisioning")
    db.add(ws); db.commit(); db.refresh(ws); provision_workspace(db, ws)
    profile = SandboxProfile(organization_id=org.id, name="Mock", provider="mock", network_mode="none", read_only_root=True,
                             allowed_commands_json=json.dumps(["python"]))
    db.add(profile); db.commit(); db.refresh(profile)
    ref = SecretReference(organization_id=org.id, company_id=company.id, name="API_TOKEN", provider="env", external_ref="env:TEST_V12_SECRET")
    db.add(ref); db.commit(); db.refresh(ref)
    grant = SecretGrant(organization_id=org.id, secret_reference_id=ref.id, member_id=coder.id,
                        sandbox_profile_id=profile.id, mount_name="api_token")
    db.add(grant); db.commit(); db.refresh(grant)
    monkeypatch.setenv("TEST_V12_SECRET", "super-secret-value")
    run = SandboxRun(organization_id=org.id, workspace_id=ws.id, profile_id=profile.id, initiated_by_member_id=coder.id,
                     initiated_by_agent_id=coder_agent.id, purpose="test", command_json=json.dumps(["python", "-V"]),
                     secret_grant_ids_json=json.dumps([grant.id]))
    db.add(run); db.commit(); db.refresh(run); execute_sandbox(db, run)
    assert run.status == "passed"
    assert "super-secret-value" not in run.stdout_text
    assert secret_metadata(ref)["value"] == "***redacted***"


def test_production_release_gate_creates_approval(tmp_path):
    db = session(); org, company, coder, commit_member, founder, coder_agent, commit_agent, repo = seed(db, tmp_path)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo.local_path, text=True).strip()
    release = Release(organization_id=org.id, repository_id=repo.id, created_by_member_id=founder.id,
                      version="1.0.0", commit_sha=sha, status="ready")
    env = DeploymentEnvironment(organization_id=org.id, company_id=company.id, repository_id=repo.id, name="Production",
                                slug="production", environment_type="production", provider="filesystem", require_approval=True)
    db.add_all([release, env]); db.commit(); db.refresh(release); db.refresh(env)
    gate = deployment_gate(db, release, env, founder.id)
    assert gate["allowed"] is False and gate["approval_required"] is True
    approval = db.get(Approval, gate["approval_id"]); assert approval and approval.status == "pending"
    approval.status = "approved"; db.add(approval); db.commit()
    gate2 = deployment_gate(db, release, env, founder.id); assert gate2["allowed"] is True


def test_filesystem_deploy_and_rollback_are_commit_pinned(tmp_path):
    db = session(); org, company, coder, commit_member, founder, coder_agent, commit_agent, repo = seed(db, tmp_path)
    sha1 = git_commit(repo, "app.txt", "v1\n", "v1")
    env = DeploymentEnvironment(organization_id=org.id, company_id=company.id, repository_id=repo.id, name="Staging",
                                slug="staging", environment_type="staging", provider="filesystem", require_approval=False)
    r1 = Release(organization_id=org.id, repository_id=repo.id, created_by_member_id=founder.id, version="1.0.0", commit_sha=sha1, status="ready")
    db.add_all([env,r1]); db.commit(); db.refresh(env); db.refresh(r1)
    d1 = deploy_release(db,r1,env,founder.id)
    assert Path(d1.deployed_path,"app.txt").read_text()=="v1\n"
    sha2 = git_commit(repo,"app.txt","v2\n","v2")
    r2 = Release(organization_id=org.id, repository_id=repo.id, created_by_member_id=founder.id, version="1.1.0", commit_sha=sha2, status="ready")
    db.add(r2); db.commit(); db.refresh(r2)
    d2 = deploy_release(db,r2,env,founder.id)
    current = Path(settings.deployment_workspace_root)/str(org.id)/"staging"/"current"
    assert (current/"app.txt").read_text()=="v2\n"
    rb = rollback_environment(db,d2,founder.id,"regression")
    assert rb.status=="completed" and (current/"app.txt").read_text()=="v1\n"


def test_artifact_handoff_can_auto_create_delivery(tmp_path):
    db = session(); org, company, coder, commit_member, founder, coder_agent, commit_agent, repo = seed(db, tmp_path)
    rule = DeliveryAutomationRule(organization_id=org.id, repository_id=repo.id, name="Commit handoff",
                                  handoff_purpose="commit", target_member_id=commit_member.id, target_branch="main", enabled=True)
    db.add(rule); db.commit(); db.refresh(rule)
    artifact = register_artifact(db, organization_id=org.id, company_id=company.id, created_by_member_id=coder.id,
                                 created_by_agent_id=coder_agent.id, name="feature.py", bundle_key="auto-12",
                                 logical_path="src/feature.py", artifact_type="source_code", content_text="x=12\n")
    handoff = handoff_artifact(db, artifact, to_member_id=commit_member.id, from_member_id=coder.id, purpose="commit")
    accept_handoff(db,handoff,member_id=commit_member.id)
    runs = db.query(__import__('app.models',fromlist=['DeliveryRun']).DeliveryRun).filter_by(organization_id=org.id, artifact_bundle_key="auto-12").all()
    assert len(runs)==1 and runs[0].repository_id==repo.id and runs[0].target_branch=="main"
