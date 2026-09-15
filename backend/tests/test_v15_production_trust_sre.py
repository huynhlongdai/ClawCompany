import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.base import Base
from app.models import *
from app.services.runner_broker import register_node, acquire_lease
from app.services.runner_trust import create_authority, sign_runner_csr, verify_runner_fingerprint, revoke_runner_certificate, RunnerTrustError
from app.services.workload_keys import create_signing_key, set_key_status
from app.services.workload_identity import issue_workload_token, verify_workload_token, WorkloadIdentityError
from app.services.telemetry_export import ingest_otlp_json, render_prometheus
from app.services.secret_federation import issue_secret_lease, mounted_leased_secret
from app.services.scheduler_ha import register_scheduler_node, acquire_leadership
from app.services.incident_paging import queue_incident_notifications, dispatch_queued_notifications
from app.services.sre_recovery import plan_recovery, execute_recovery
from app.services.artifacts import register_artifact
from app.services.supply_chain_signing import sign_artifact
from app.services.evidence_trust import verify_evidence


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db):
    org = Organization(name="Nova v15", slug="nova-v15"); db.add(org); db.commit(); db.refresh(org)
    company = Company(organization_id=org.id, name="Nova Labs", industry="AI"); db.add(company); db.commit(); db.refresh(company)
    founder = Member(organization_id=org.id, company_id=company.id, name="Long", member_type="human", role="Founder")
    nina = Member(organization_id=org.id, company_id=company.id, name="Nina", member_type="agent", role="Chief of Staff")
    worker = Member(organization_id=org.id, company_id=company.id, name="Worker", member_type="agent", role="Engineer")
    db.add_all([founder,nina,worker]); db.commit()
    for x in (founder,nina,worker): db.refresh(x)
    agent = Agent(member_id=worker.id, runtime_agent_id="worker-v15", model="mock"); db.add(agent); db.commit(); db.refresh(agent)
    pool = RunnerPool(organization_id=org.id, company_id=company.id, name="Pool", provider="remote", capabilities_json='["linux"]', selectors_json="{}")
    db.add(pool); db.commit(); db.refresh(pool)
    node = register_node(db, pool, node_key="runner-v15", capabilities=["linux"], capacity=2)
    return org, company, founder, nina, worker, agent, pool, node


def generate_ca_and_csr(tmp_path: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ClawCompany Test Runner CA")])
    ca_cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(ca_key.public_key())
               .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=2))
               .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).sign(ca_key, hashes.SHA256()))
    key_path = tmp_path / "runner-ca.key"
    key_path.write_bytes(ca_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    client_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (x509.CertificateSigningRequestBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "runner-v15")]))
           .sign(client_key, hashes.SHA256()))
    return ca_cert.public_bytes(serialization.Encoding.PEM).decode(), f"file:{key_path}", csr.public_bytes(serialization.Encoding.PEM).decode()


def test_runner_mtls_certificate_issue_rotate_revoke(tmp_path):
    db=session(); org,company,founder,nina,worker,agent,pool,node=seed(db)
    ca_pem,key_ref,csr=generate_ca_and_csr(tmp_path)
    authority=create_authority(db, organization_id=org.id, name="Runner CA", issuer_cn="Runner CA", ca_cert_pem=ca_pem, private_key_ref=key_ref)
    cert1=sign_runner_csr(db, authority, node, csr_pem=csr, ttl_hours=4)
    assert verify_runner_fingerprint(db, organization_id=org.id, runner_node_id=node.id, fingerprint_sha256=cert1.fingerprint_sha256).id == cert1.id
    cert2=sign_runner_csr(db, authority, node, csr_pem=csr, ttl_hours=4, previous_certificate_id=cert1.id)
    db.refresh(cert1); assert cert1.status == "rotated" and cert2.status == "active"
    revoke_runner_certificate(db, cert2)
    try:
        verify_runner_fingerprint(db, organization_id=org.id, runner_node_id=node.id, fingerprint_sha256=cert2.fingerprint_sha256)
        assert False, "revoked certificate must not authenticate"
    except RunnerTrustError:
        pass


def test_workload_signing_key_rotation_preserves_then_revokes_old_tokens(monkeypatch):
    db=session(); org,company,founder,nina,worker,agent,pool,node=seed(db)
    lease=acquire_lease(db,pool,member_id=worker.id,agent_id=agent.id,scopes=["artifact:write"],ttl_seconds=600)
    monkeypatch.setenv("CC_WI_KEY_1","one-secret")
    monkeypatch.setenv("CC_WI_KEY_2","two-secret")
    k1=create_signing_key(db,organization_id=org.id,kid="k1",algorithm="HS256",public_key_pem="",private_key_ref="env:CC_WI_KEY_1",activate=True)
    tok1=issue_workload_token(db,lease,audience="v15-test",ttl_seconds=120)["access_token"]
    assert verify_workload_token(db,tok1,audience="v15-test")["org_id"] == org.id
    k2=create_signing_key(db,organization_id=org.id,kid="k2",algorithm="HS256",public_key_pem="",private_key_ref="env:CC_WI_KEY_2",activate=True)
    db.refresh(k1); assert k1.status == "retiring" and k2.status == "active"
    assert verify_workload_token(db,tok1,audience="v15-test")["lease_id"] == lease.id
    set_key_status(db,k1,"revoked")
    try:
        verify_workload_token(db,tok1,audience="v15-test")
        assert False, "revoked signing key must revoke old token verification"
    except WorkloadIdentityError:
        pass


def test_otlp_json_ingest_and_prometheus_exposition():
    db=session(); org,*_=seed(db)
    payload={"resourceMetrics":[{"resource":{"attributes":[{"key":"service.name","value":{"stringValue":"checkout"}}]},"scopeMetrics":[{"metrics":[{"name":"http.error_rate","unit":"1","gauge":{"dataPoints":[{"asDouble":0.012,"attributes":[{"key":"route","value":{"stringValue":"/pay"}}]}]}}]}]}]}
    count=ingest_otlp_json(db,organization_id=org.id,payload=payload)
    assert count == 1
    text=render_prometheus(db,org.id)
    assert "clawcompany_external_http_error_rate" in text and 'service.name="checkout"' in text and 'route="/pay"' in text


def test_secret_federation_env_lease_is_ephemeral(monkeypatch):
    db=session(); org,company,founder,nina,worker,agent,pool,node=seed(db)
    monkeypatch.setenv("V15_TEST_SECRET","s3cr3t")
    ref=SecretReference(organization_id=org.id,company_id=company.id,name="deploy-token",provider="env",external_ref="env:V15_TEST_SECRET",classification="restricted")
    db.add(ref); db.commit(); db.refresh(ref)
    runner=acquire_lease(db,pool,agent_id=agent.id,ttl_seconds=300)
    lease=issue_secret_lease(db,organization_id=org.id,secret_reference_id=ref.id,runner_lease_id=runner.id,agent_id=agent.id,mount_name="token",ttl_seconds=120)
    with mounted_leased_secret(db,lease) as root:
        assert (Path(root)/"token").read_text() == "s3cr3t"
    assert "s3cr3t" not in json.dumps({c.name:getattr(lease,c.name) for c in lease.__table__.columns}, default=str)


def test_scheduler_leader_lease_fencing():
    db=session(); org,*_=seed(db)
    a=register_scheduler_node(db,organization_id=org.id,node_key="a"); b=register_scheduler_node(db,organization_id=org.id,node_key="b")
    lease,ok=acquire_leadership(db,a,lease_name="sre",ttl_seconds=30); assert ok and lease.fencing_token == 1
    lease2,ok2=acquire_leadership(db,b,lease_name="sre",ttl_seconds=30); assert not ok2 and lease2.holder_node_id == a.id
    lease.expires_at=datetime.utcnow()-timedelta(seconds=1); db.add(lease); db.commit()
    lease3,ok3=acquire_leadership(db,b,lease_name="sre",ttl_seconds=30); assert ok3 and lease3.fencing_token == 2 and lease3.holder_node_id == b.id


def test_paging_and_nina_sre_recovery_requires_approval_for_critical():
    db=session(); org,company,founder,nina,worker,agent,pool,node=seed(db)
    route=IncidentPagingRoute(organization_id=org.id,company_id=company.id,name="Console pager",provider="console",severities_json='["critical","high"]')
    policy=SRERecoveryPolicy(organization_id=org.id,company_id=company.id,name="Nina safe recovery",severities_json='["critical","high"]',actions_json='["page","mark_mitigating"]',approval_required_for_json='["critical"]')
    db.add_all([route,policy]); db.commit()
    high=Incident(organization_id=org.id,company_id=company.id,title="High latency",severity="high",status="open",source="test",summary="latency")
    critical=Incident(organization_id=org.id,company_id=company.id,title="Data risk",severity="critical",status="open",source="test",summary="risk")
    db.add_all([high,critical]); db.commit(); db.refresh(high); db.refresh(critical)
    run=plan_recovery(db,high,nina_member_id=nina.id); assert run.status == "planned"
    execute_recovery(db,run); db.refresh(high); assert run.status == "completed" and high.status == "mitigating"
    assert dispatch_queued_notifications(db,organization_id=org.id)["failed"] == 0
    critical_run=plan_recovery(db,critical,nina_member_id=nina.id); assert critical_run.status == "approval_required" and critical_run.approval_id
    execute_recovery(db,critical_run); assert critical_run.status == "approval_required"


def test_evidence_trust_policy_records_verification(monkeypatch):
    db=session(); org,company,*_=seed(db)
    monkeypatch.setenv("V15_SIGNING","evidence-secret")
    artifact=register_artifact(db,organization_id=org.id,company_id=company.id,name="provenance.json",logical_path="evidence/provenance.json",content_text='{"build":"ok"}')
    sig=sign_artifact(db,artifact,provider="local_hmac",key_ref="env:V15_SIGNING")
    policy=EvidenceTrustPolicy(organization_id=org.id,name="Local pinned evidence",signature_type="hmac-sha256",expected_signer="clawcompany://signer/local-hmac")
    db.add(policy); db.commit(); db.refresh(policy)
    verification=verify_evidence(db,sig,policy); assert verification.status == "verified"
