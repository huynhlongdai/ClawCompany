import json
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.core.config import settings
from app.models import (
    Agent, BuildRecord, CICDNodeRun, Company, DeploymentEnvironment, DeploymentHealthPolicy,
    DevWorkspace, EngineeringInitiative, Member, Organization, Release, Repository, SecurityFinding,
    SecurityReview,
)
from app.services.build_evidence import generate_build_evidence
from app.services.cicd import CICDError, create_graph, execute_run, start_run
from app.services.dev_cloud import provision_workspace
from app.services.engineering_orchestrator import run_initiative
from app.services.progressive_delivery import progressive_deploy
from app.services.release_manager import assess_release
from app.services.repository_delivery import initialize_repository
from app.services.security_review import scan_repository_commit
from app.services.workspace_gateway import WorkspaceGatewayError, open_gateway_session, read_text, snapshot_workspace, write_text


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db, tmp_path: Path):
    settings.repository_workspace_root = str(tmp_path / "repos")
    settings.dev_workspace_root = str(tmp_path / "workspaces")
    settings.deployment_workspace_root = str(tmp_path / "deployments")
    org = Organization(name="Nova v13", slug="nova-v13")
    db.add(org); db.commit(); db.refresh(org)
    company = Company(organization_id=org.id, name="Nova Labs", industry="AI")
    db.add(company); db.commit(); db.refresh(company)
    nina = Member(organization_id=org.id, company_id=company.id, name="Nina", member_type="agent", role="Chief of Staff")
    coder = Member(organization_id=org.id, company_id=company.id, name="Coder", member_type="agent", role="Engineer")
    founder = Member(organization_id=org.id, company_id=company.id, name="Long", member_type="human", role="Founder")
    db.add_all([nina, coder, founder]); db.commit()
    for x in [nina, coder, founder]: db.refresh(x)
    nina_agent = Agent(member_id=nina.id, runtime_agent_id="nina-v13", model="mock")
    coder_agent = Agent(member_id=coder.id, runtime_agent_id="coder-v13", model="mock")
    db.add_all([nina_agent, coder_agent]); db.commit(); db.refresh(nina_agent); db.refresh(coder_agent)
    repo = Repository(organization_id=org.id, company_id=company.id, name="Engineering Product", provider="local", default_branch="main")
    db.add(repo); db.commit(); db.refresh(repo)
    initialize_repository(repo); db.add(repo); db.commit(); db.refresh(repo)
    return org, company, nina, coder, founder, nina_agent, coder_agent, repo


def commit(repo: Repository, rel: str, content: str, message: str = "change") -> str:
    root = Path(repo.local_path); target = root / rel; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=V13 Test", "-c", "user.email=v13@example.local", "commit", "-m", message], cwd=root, check=True, capture_output=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def test_workspace_gateway_provider_neutral_handoff(tmp_path):
    db = session(); org, company, nina, coder, founder, nina_agent, coder_agent, repo = seed(db, tmp_path)
    ws = DevWorkspace(organization_id=org.id, company_id=company.id, repository_id=repo.id, owner_member_id=coder.id,
                      owner_agent_id=coder_agent.id, name="Claude workspace", workspace_key="provider-neutral", base_ref="main", status="provisioning")
    db.add(ws); db.commit(); db.refresh(ws); provision_workspace(db, ws, ttl_minutes=60)
    gateway = open_gateway_session(db, ws, member_id=coder.id, agent_id=coder_agent.id, provider="claude",
                                   provider_session_id="claude-session-1", capabilities=["read", "write", "snapshot"])
    write_text(db, gateway, ws, "src/feature.py", "VALUE = 13\n")
    assert read_text(db, gateway, ws, "src/feature.py")["content"] == "VALUE = 13\n"
    ids = snapshot_workspace(db, gateway, ws, bundle_key="handoff-v13", include_globs=["src/*.py"])
    assert len(ids) == 1
    with pytest.raises(WorkspaceGatewayError):
        write_text(db, gateway, ws, "../../escape.txt", "no")


def test_cicd_graph_rejects_cycles(tmp_path):
    db = session(); org, company, nina, coder, founder, nina_agent, coder_agent, repo = seed(db, tmp_path)
    with pytest.raises(CICDError):
        create_graph(db, organization_id=org.id, company_id=company.id, repository_id=repo.id, name="Cycle",
                     nodes=[{"key":"a","name":"A"},{"key":"b","name":"B"}],
                     edges=[{"source":"a","target":"b"},{"source":"b","target":"a"}])


def test_cicd_generates_evidence_security_and_release(tmp_path):
    db = session(); org, company, nina, coder, founder, nina_agent, coder_agent, repo = seed(db, tmp_path)
    sha = commit(repo, "src/app.py", "def add(a, b):\n    return a + b\n", "safe code")
    graph = create_graph(db, organization_id=org.id, company_id=company.id, repository_id=repo.id, name="Secure release",
                         nodes=[
                             {"key":"evidence","type":"evidence","name":"Build evidence"},
                             {"key":"security","type":"security","name":"Security review"},
                             {"key":"release","type":"release","name":"Release","config":{"version":"1.3.0-test"}},
                         ],
                         edges=[{"source":"evidence","target":"security"},{"source":"security","target":"release"}])
    run = start_run(db, graph, ref="main", commit_sha=sha, member_id=nina.id, agent_id=nina_agent.id)
    execute_run(db, run)
    assert run.status == "succeeded" and run.release_id is not None
    build = db.query(BuildRecord).filter(BuildRecord.ci_run_id == run.id).one()
    review = db.query(SecurityReview).filter(SecurityReview.ci_run_id == run.id).one()
    assert build.status == "completed" and len(build.source_digest) == 64
    assert review.verdict == "pass"
    assert db.query(CICDNodeRun).filter(CICDNodeRun.ci_run_id == run.id).count() == 3


def test_security_reviewer_blocks_command_execution(tmp_path):
    db = session(); org, company, nina, coder, founder, nina_agent, coder_agent, repo = seed(db, tmp_path)
    sha = commit(repo, "src/risky.py", "import os\nos.system(user_input)\n", "risky code")
    review = scan_repository_commit(db, repo, sha, reviewer_member_id=nina.id)
    assert review.verdict == "blocked"
    finding = db.query(SecurityFinding).filter(SecurityFinding.review_id == review.id, SecurityFinding.rule_id == "SEC004").one()
    assert finding.severity == "high"


def test_spdx_and_provenance_are_registered(tmp_path):
    db = session(); org, company, nina, coder, founder, nina_agent, coder_agent, repo = seed(db, tmp_path)
    sha = commit(repo, "package.json", '{"name":"demo","version":"1.0.0"}\n', "package")
    build = generate_build_evidence(db, repo, sha, producer_member_id=coder.id, producer_agent_id=coder_agent.id)
    from app.models import SBOMDocument, BuildProvenance, Artifact
    sbom = db.query(SBOMDocument).filter_by(build_id=build.id).one(); prov = db.query(BuildProvenance).filter_by(build_id=build.id).one()
    sbom_artifact = db.get(Artifact, sbom.artifact_id); prov_artifact = db.get(Artifact, prov.artifact_id)
    assert json.loads(sbom_artifact.content_text)["spdxVersion"] == "SPDX-2.3"
    assert json.loads(prov_artifact.content_text)["predicateType"] == "https://slsa.dev/provenance/v1"


def test_blue_green_health_preflight_and_release_manager(tmp_path):
    db = session(); org, company, nina, coder, founder, nina_agent, coder_agent, repo = seed(db, tmp_path)
    sha = commit(repo, "health.txt", "ok\n", "health")
    release = Release(organization_id=org.id, repository_id=repo.id, created_by_member_id=founder.id,
                      version="1.3.0", commit_sha=sha, status="ready")
    env = DeploymentEnvironment(organization_id=org.id, company_id=company.id, repository_id=repo.id, name="Production",
                                slug="production", environment_type="production", provider="filesystem", require_approval=False)
    db.add_all([release, env]); db.commit(); db.refresh(release); db.refresh(env)
    policy = DeploymentHealthPolicy(organization_id=org.id, environment_id=env.id, name="health file",
                                    check_type="filesystem_marker", target="health.txt", auto_rollback=True)
    db.add(policy); db.commit(); db.refresh(policy)
    strategy = progressive_deploy(db, release, env, strategy="blue_green", policy=policy, requested_by_member_id=founder.id)
    assert strategy.status == "completed" and strategy.deployment_id is not None
    manager = assess_release(db, release, strategy_run=strategy, requested_by_member_id=founder.id)
    assert manager.decision == "approve"
    current = Path(settings.deployment_workspace_root) / str(org.id) / "production" / "current"
    assert (current / "health.txt").read_text() == "ok\n"


def test_nina_initiative_runs_to_release_ready(tmp_path):
    db = session(); org, company, nina, coder, founder, nina_agent, coder_agent, repo = seed(db, tmp_path)
    sha = commit(repo, "src/service.py", "def ready():\n    return True\n", "ready")
    graph = create_graph(db, organization_id=org.id, company_id=company.id, repository_id=repo.id, name="Nina SDLC",
                         nodes=[{"key":"security","type":"security","name":"Security"},
                                {"key":"evidence","type":"evidence","name":"Evidence"}],
                         edges=[{"source":"security","target":"evidence"}])
    initiative = EngineeringInitiative(organization_id=org.id, company_id=company.id, repository_id=repo.id,
                                       pipeline_graph_id=graph.id, nina_member_id=nina.id, title="Ship safe feature",
                                       objective="Run the governed SDLC", ref=sha, release_version="1.3.1", status="planned")
    db.add(initiative); db.commit(); db.refresh(initiative)
    run_initiative(db, initiative, execute_deployment=False)
    assert initiative.status == "release_ready"
    assert initiative.current_ci_run_id is not None and initiative.current_release_id is not None
