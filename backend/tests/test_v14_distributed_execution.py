import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.core.config import settings
from app.models import *
from app.services.runner_broker import register_node, acquire_lease, enqueue_job, claim_next_job, complete_job, release_lease, RunnerBrokerError
from app.services.workload_identity import issue_workload_token, verify_workload_token, WorkloadIdentityError
from app.services.supply_chain_signing import sign_artifact, verify_signature
from app.services.artifacts import register_artifact
from app.services.repository_delivery import initialize_repository
from app.services.scanner_adapters import run_scanner
from app.services.telemetry_slo import ingest_metric, evaluate_slo
from app.services.canary_delivery import run_canary
from app.services.nina_portfolio import review_portfolio


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db, tmp_path: Path):
    settings.repository_workspace_root = str(tmp_path / "repos")
    settings.traffic_router_config_root = str(tmp_path / "traffic")
    org = Organization(name="Nova v14", slug="nova-v14")
    db.add(org); db.commit(); db.refresh(org)
    company = Company(organization_id=org.id, name="Nova Labs", industry="AI")
    db.add(company); db.commit(); db.refresh(company)
    founder = Member(organization_id=org.id, company_id=company.id, name="Long", member_type="human", role="Founder")
    nina = Member(organization_id=org.id, company_id=company.id, name="Nina", member_type="agent", role="Chief of Staff")
    engineer = Member(organization_id=org.id, company_id=company.id, name="Engineer", member_type="agent", role="Engineer")
    db.add_all([founder, nina, engineer]); db.commit()
    for x in [founder, nina, engineer]: db.refresh(x)
    nina_agent = Agent(member_id=nina.id, runtime_agent_id="nina-v14", model="mock")
    eng_agent = Agent(member_id=engineer.id, runtime_agent_id="eng-v14", model="mock")
    db.add_all([nina_agent, eng_agent]); db.commit(); db.refresh(nina_agent); db.refresh(eng_agent)
    repo = Repository(organization_id=org.id, company_id=company.id, name="Product", provider="local", default_branch="main")
    db.add(repo); db.commit(); db.refresh(repo); initialize_repository(repo); db.add(repo); db.commit(); db.refresh(repo)
    env = DeploymentEnvironment(organization_id=org.id, company_id=company.id, repository_id=repo.id, name="Production",
                                slug="prod-v14", environment_type="production", provider="filesystem", require_approval=False)
    db.add(env); db.commit(); db.refresh(env)
    return org, company, founder, nina, engineer, nina_agent, eng_agent, repo, env


def commit(repo: Repository, rel: str, content: str) -> str:
    root = Path(repo.local_path); target = root / rel; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(content)
    subprocess.run(["git", "add", rel], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.name=V14 Test", "-c", "user.email=v14@example.local", "commit", "-m", "v14"], cwd=root, check=True, capture_output=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def test_runner_broker_capabilities_jobs_and_release(tmp_path):
    db = session(); org, company, founder, nina, engineer, nina_agent, eng_agent, repo, env = seed(db, tmp_path)
    pool = RunnerPool(organization_id=org.id, company_id=company.id, name="Secure runners", provider="remote", capabilities_json='["linux"]', selectors_json="{}")
    db.add(pool); db.commit(); db.refresh(pool)
    node = register_node(db, pool, node_key="runner-a", capabilities=["linux", "docker"], capacity=1)
    lease = acquire_lease(db, pool, agent_id=eng_agent.id, required_capabilities=["docker"], scopes=["workspace:read"], ttl_seconds=300)
    assert lease.runner_node_id == node.id
    try:
        acquire_lease(db, pool, required_capabilities=["docker"], ttl_seconds=300)
        assert False, "capacity must be enforced"
    except RunnerBrokerError:
        pass
    job = enqueue_job(db, lease, job_type="test", payload={"argv":["pytest","-q"]})
    claimed = claim_next_job(db, node); assert claimed.id == job.id and claimed.status == "running"
    complete_job(db, claimed, result={"exit_code":0}); assert claimed.status == "completed"
    release_lease(db, lease); db.refresh(node); assert node.active_leases == 0


def test_workload_identity_is_lease_bound(tmp_path):
    db = session(); org, company, founder, nina, engineer, nina_agent, eng_agent, repo, env = seed(db, tmp_path)
    settings.workload_identity_algorithm = "HS256"; settings.workload_identity_dev_secret = "unit-test-workload-secret"
    pool = RunnerPool(organization_id=org.id, name="Pool", provider="remote", capabilities_json="[]", selectors_json="{}")
    db.add(pool); db.commit(); db.refresh(pool); register_node(db, pool, node_key="runner-id", capabilities=[], capacity=2)
    lease = acquire_lease(db, pool, member_id=engineer.id, agent_id=eng_agent.id, scopes=["workspace:read","artifact:write"])
    token = issue_workload_token(db, lease, audience="runner-unit", ttl_seconds=120)
    claims = verify_workload_token(db, token["access_token"], audience="runner-unit")
    assert claims["org_id"] == org.id and claims["lease_id"] == lease.id and "artifact:write" in claims["scope"]
    release_lease(db, lease)
    try:
        verify_workload_token(db, token["access_token"], audience="runner-unit")
        assert False, "released lease must revoke workload token"
    except WorkloadIdentityError:
        pass


def test_supply_chain_signature_detects_content_change(tmp_path, monkeypatch):
    db = session(); org, company, founder, nina, engineer, nina_agent, eng_agent, repo, env = seed(db, tmp_path)
    monkeypatch.setenv("SUPPLY_CHAIN_SIGNING_KEY", "signing-secret")
    artifact = register_artifact(db, organization_id=org.id, company_id=company.id, name="sbom.json", logical_path="evidence/sbom.json", content_text='{"ok":true}')
    sig = sign_artifact(db, artifact, provider="local_hmac", key_ref="env:SUPPLY_CHAIN_SIGNING_KEY")
    verify_signature(db, sig); assert sig.verified is True
    artifact.content_text = '{"ok":false}'; db.add(artifact); db.commit()
    verify_signature(db, sig); assert sig.verified is False


def test_builtin_scanner_adapter_persists_normalized_findings(tmp_path):
    db = session(); org, company, founder, nina, engineer, nina_agent, eng_agent, repo, env = seed(db, tmp_path)
    sha = commit(repo, "src/risky.py", "import os\nos.system(user_input)\n")
    provider = ScannerProvider(organization_id=org.id, name="Builtin deterministic", provider_type="builtin", block_on="high")
    db.add(provider); db.commit(); db.refresh(provider)
    run = run_scanner(db, provider, repo, sha)
    assert run.status == "completed" and run.verdict == "blocked"
    findings = json.loads(run.findings_json); assert any(x["rule_id"] == "SEC004" for x in findings)


def test_slo_breach_opens_incident(tmp_path):
    db = session(); org, company, founder, nina, engineer, nina_agent, eng_agent, repo, env = seed(db, tmp_path)
    slo = SLODefinition(organization_id=org.id, environment_id=env.id, name="Error rate", metric_name="http.error_rate",
                        comparator="lte", threshold=0.01, min_samples=2, window_minutes=10, auto_incident=True, auto_rollback=True)
    db.add(slo); db.commit(); db.refresh(slo)
    ingest_metric(db, organization_id=org.id, environment_id=env.id, metric_name="http.error_rate", value=0.02)
    ingest_metric(db, organization_id=org.id, environment_id=env.id, metric_name="http.error_rate", value=0.03)
    ev = evaluate_slo(db, slo); assert ev.status == "breached" and ev.aggregate_value == 0.025
    incident = db.query(Incident).filter_by(slo_evaluation_id=ev.id).one(); assert incident.status == "open" and incident.severity == "high"


def test_canary_uses_traffic_router_and_slo_gate(tmp_path):
    db = session(); org, company, founder, nina, engineer, nina_agent, eng_agent, repo, env = seed(db, tmp_path)
    sha = commit(repo, "app.py", "print('ok')\n")
    old = Release(organization_id=org.id, repository_id=repo.id, version="1.3.9", commit_sha=sha, status="released")
    new = Release(organization_id=org.id, repository_id=repo.id, version="1.4.0", commit_sha=sha, status="ready")
    db.add_all([old,new]); db.commit(); db.refresh(old); db.refresh(new)
    router = TrafficRouter(organization_id=org.id, environment_id=env.id, name="Prod router", provider="database",
                           config_json="{}", current_weights_json=json.dumps({str(old.id):100,str(new.id):0}))
    slo = SLODefinition(organization_id=org.id, environment_id=env.id, name="P95", metric_name="http.p95_ms", comparator="lte",
                        threshold=500, min_samples=1, window_minutes=10, auto_incident=True, auto_rollback=True)
    db.add_all([router,slo]); db.commit(); db.refresh(router); db.refresh(slo)
    ingest_metric(db, organization_id=org.id, environment_id=env.id, release_id=new.id, metric_name="http.p95_ms", value=180, unit="ms")
    run = run_canary(db, new, env, router, slo_ids=[slo.id], steps=[10,50,100], requested_by_member_id=founder.id)
    db.refresh(router)
    assert run.status == "completed" and run.traffic_percent == 100
    weights = json.loads(router.current_weights_json); assert weights[str(new.id)] == 100 and weights[str(old.id)] == 0
    assert db.query(TrafficShift).filter_by(strategy_run_id=run.id).count() == 3


def test_canary_fails_closed_on_slo_breach(tmp_path):
    db = session(); org, company, founder, nina, engineer, nina_agent, eng_agent, repo, env = seed(db, tmp_path)
    sha = commit(repo, "app.py", "print('risk')\n")
    new = Release(organization_id=org.id, repository_id=repo.id, version="1.4.1", commit_sha=sha, status="ready")
    db.add(new); db.commit(); db.refresh(new)
    router = TrafficRouter(organization_id=org.id, environment_id=env.id, name="Router", provider="database", config_json="{}", current_weights_json="{}")
    slo = SLODefinition(organization_id=org.id, environment_id=env.id, name="Errors", metric_name="error_rate", comparator="lte",
                        threshold=0.01, min_samples=1, window_minutes=10, auto_incident=True, auto_rollback=True)
    db.add_all([router,slo]); db.commit(); db.refresh(router); db.refresh(slo)
    ingest_metric(db, organization_id=org.id, environment_id=env.id, release_id=new.id, metric_name="error_rate", value=0.2)
    run = run_canary(db, new, env, router, slo_ids=[slo.id], steps=[10,100], requested_by_member_id=founder.id); db.refresh(router)
    assert run.status == "rolled_back" and json.loads(router.current_weights_json)[str(new.id)] == 0
    assert db.query(Incident).filter(Incident.organization_id == org.id).count() >= 1


def test_nina_portfolio_review_reflects_operational_risk(tmp_path):
    db = session(); org, company, founder, nina, engineer, nina_agent, eng_agent, repo, env = seed(db, tmp_path)
    objective = PortfolioObjective(organization_id=org.id, company_id=company.id, owner_member_id=nina.id, title="Reliable velocity", objective="Ship safely")
    incident = Incident(organization_id=org.id, company_id=company.id, environment_id=env.id, title="Production outage", severity="critical", status="open")
    db.add_all([objective,incident]); db.commit(); db.refresh(objective)
    review = review_portfolio(db, organization_id=org.id, objective=objective, nina_member_id=nina.id)
    assert review.health == "red" and json.loads(review.metrics_json)["critical_incidents"] == 1
