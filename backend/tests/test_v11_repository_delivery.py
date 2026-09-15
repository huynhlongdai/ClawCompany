from pathlib import Path
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.core.config import settings
from app.models import (
    Organization, Company, Member, Agent, Repository, RepositoryIdentityCredential,
    RepositoryTestProfile, DeliveryPipeline, DeliveryRun, RepositoryReview,
)
from app.services.artifacts import register_artifact
from app.services.repository_delivery import (
    RepositoryDeliveryError, credential_allows, create_merge_request, create_review, decide_review,
    delivery_gate, initialize_repository, merge_delivery, prepare_delivery, repository_state,
    rollback_merge, run_tests, validate_ref,
)


def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def seed(db, tmp_path: Path):
    settings.repository_workspace_root = str(tmp_path / "repos-root")
    org = Organization(name="Nova v11", slug="nova-v11")
    db.add(org); db.commit(); db.refresh(org)
    company = Company(organization_id=org.id, name="Nova Labs", industry="AI")
    db.add(company); db.commit(); db.refresh(company)
    coder = Member(organization_id=org.id, company_id=company.id, name="Coder", member_type="agent", role="Engineer")
    reviewer = Member(organization_id=org.id, company_id=company.id, name="Reviewer", member_type="human", role="Reviewer")
    db.add_all([coder, reviewer]); db.commit(); db.refresh(coder); db.refresh(reviewer)
    agent = Agent(member_id=coder.id, runtime_agent_id="coder-v11", model="mock")
    db.add(agent); db.commit(); db.refresh(agent)
    repo = Repository(organization_id=org.id, company_id=company.id, name="Product", provider="local", default_branch="main")
    db.add(repo); db.commit(); db.refresh(repo)
    initialize_repository(repo); db.add(repo); db.commit(); db.refresh(repo)
    return org, company, coder, reviewer, agent, repo


def test_git_ref_guard():
    assert validate_ref("cc/delivery-12") == "cc/delivery-12"
    for bad in ["../main", "/root", "feature//bad", "main/", "bad ref"]:
        try:
            validate_ref(bad)
            assert False, bad
        except RepositoryDeliveryError:
            pass


def test_identity_credential_permission_scope(tmp_path):
    db = session(); org, company, coder, reviewer, agent, repo = seed(db, tmp_path)
    credential = RepositoryIdentityCredential(
        organization_id=org.id, repository_id=repo.id, member_id=coder.id, agent_id=agent.id,
        permissions_json=json.dumps(["read", "write_branch"]), branch_pattern="cc/*",
    )
    assert credential_allows(credential, "write_branch", "cc/delivery-1") is True
    assert credential_allows(credential, "merge", "main") is False
    assert credential_allows(credential, "write_branch", "main") is False


def test_artifact_bundle_prepares_real_git_commit_and_patch(tmp_path):
    db = session(); org, company, coder, reviewer, agent, repo = seed(db, tmp_path)
    register_artifact(
        db, organization_id=org.id, company_id=company.id, created_by_member_id=coder.id,
        created_by_agent_id=agent.id, name="feature.py", bundle_key="feature-11", logical_path="src/feature.py",
        artifact_type="source_code", mime_type="text/x-python", content_text="def answer():\n    return 42\n",
    )
    run = DeliveryRun(
        organization_id=org.id, repository_id=repo.id, artifact_bundle_key="feature-11",
        target_branch="main", initiated_by_member_id=coder.id, initiated_by_agent_id=agent.id,
    )
    db.add(run); db.commit(); db.refresh(run)
    prepare_delivery(db, run)
    assert run.status == "prepared"
    assert len(run.head_commit_sha) >= 7
    assert run.patch_artifact_id is not None
    assert Path(run.worktree_path, "src", "feature.py").read_text() == "def answer():\n    return 42\n"


def test_delivery_test_review_merge_and_rollback(tmp_path):
    db = session(); org, company, coder, reviewer, agent, repo = seed(db, tmp_path)
    register_artifact(
        db, organization_id=org.id, company_id=company.id, created_by_member_id=coder.id,
        created_by_agent_id=agent.id, name="feature.py", bundle_key="release-11", logical_path="src/feature.py",
        artifact_type="source_code", mime_type="text/x-python", content_text="def add(a,b):\n    return a+b\n",
    )
    profile = RepositoryTestProfile(
        organization_id=org.id, repository_id=repo.id, name="compile",
        # "python" không tồn tại trên mọi máy (image Docker python:3.12-slim có,
        # nhiều sandbox chỉ có python3). Dùng python3 để test kiểm chứng được
        # ở cả hai nơi; cả hai đều nằm trong allowlist mặc định
        # REPOSITORY_TEST_ALLOWED_EXECUTABLES nên không nới quyền gì.
        commands_json=json.dumps(["python3 -m compileall src"]), timeout_seconds=30,
    )
    db.add(profile); db.commit(); db.refresh(profile)
    pipeline = DeliveryPipeline(
        organization_id=org.id, repository_id=repo.id, name="Safe merge", target_branch="main",
        test_profile_id=profile.id, require_tests=True, require_review=True, required_approvals=1,
        merge_strategy="merge",
    )
    db.add(pipeline); db.commit(); db.refresh(pipeline)
    run = DeliveryRun(
        organization_id=org.id, pipeline_id=pipeline.id, repository_id=repo.id,
        artifact_bundle_key="release-11", target_branch="main", initiated_by_member_id=coder.id,
        initiated_by_agent_id=agent.id,
    )
    db.add(run); db.commit(); db.refresh(run)
    prepare_delivery(db, run)
    test_run = run_tests(db, run, profile)
    assert test_run.status == "passed"
    review = create_review(db, run, reviewer_member_id=reviewer.id, reviewer_agent_id=None)
    decide_review(db, review, verdict="approve", score=96, summary="Ship it", findings=[])
    gate = delivery_gate(db, run)
    assert gate["allowed"] is True
    mr = create_merge_request(db, run, "Release v11 feature")
    mr = merge_delivery(db, run)
    assert mr.status == "merged"
    state = repository_state(repo)
    assert state["branch"] == "main"
    assert Path(repo.local_path, "src", "feature.py").exists()
    rollback = rollback_merge(db, mr, requested_by_member_id=reviewer.id, reason="test rollback")
    assert rollback.status == "completed"
    assert rollback.rollback_commit_sha
    assert not Path(repo.local_path, "src", "feature.py").exists()


def test_merge_gate_blocks_without_review(tmp_path):
    db = session(); org, company, coder, reviewer, agent, repo = seed(db, tmp_path)
    register_artifact(
        db, organization_id=org.id, company_id=company.id, name="x.txt", bundle_key="gate",
        logical_path="x.txt", content_text="hello", created_by_member_id=coder.id,
    )
    profile = RepositoryTestProfile(organization_id=org.id, repository_id=repo.id, name="noop", commands_json="[]")
    db.add(profile); db.commit(); db.refresh(profile)
    pipeline = DeliveryPipeline(
        organization_id=org.id, repository_id=repo.id, name="review required", target_branch="main",
        test_profile_id=profile.id, require_tests=True, require_review=True, required_approvals=1,
    )
    db.add(pipeline); db.commit(); db.refresh(pipeline)
    run = DeliveryRun(organization_id=org.id, pipeline_id=pipeline.id, repository_id=repo.id, artifact_bundle_key="gate", target_branch="main")
    db.add(run); db.commit(); db.refresh(run)
    prepare_delivery(db, run); run_tests(db, run, profile)
    assert delivery_gate(db, run)["allowed"] is False


def test_test_runner_rejects_unapproved_executable(tmp_path):
    db = session(); org, company, coder, reviewer, agent, repo = seed(db, tmp_path)
    register_artifact(db, organization_id=org.id, company_id=company.id, name="x.txt", bundle_key="unsafe", logical_path="x.txt", content_text="x")
    run = DeliveryRun(organization_id=org.id, repository_id=repo.id, artifact_bundle_key="unsafe", target_branch="main")
    db.add(run); db.commit(); db.refresh(run); prepare_delivery(db, run)
    profile = RepositoryTestProfile(organization_id=org.id, repository_id=repo.id, name="unsafe", commands_json=json.dumps(["bash -lc 'echo nope'"]))
    db.add(profile); db.commit(); db.refresh(profile)
    try:
        run_tests(db, run, profile)
        assert False
    except RepositoryDeliveryError as exc:
        assert "not allowed" in str(exc)


def test_conflict_resolution_revalidates_delivery(tmp_path):
    from app.models import RepositoryConflict
    from app.services.repository_delivery import resolve_delivery_conflicts
    db = session(); org, company, coder, reviewer, agent, repo = seed(db, tmp_path)
    register_artifact(
        db, organization_id=org.id, company_id=company.id, name="README.md", bundle_key="conflict",
        logical_path="README.md", content_text="# Source branch\n", created_by_member_id=coder.id,
    )
    pipeline = DeliveryPipeline(
        organization_id=org.id, repository_id=repo.id, name="no gates", target_branch="main",
        require_tests=False, require_review=False, required_approvals=0, merge_strategy="merge",
    )
    db.add(pipeline); db.commit(); db.refresh(pipeline)
    run = DeliveryRun(organization_id=org.id, pipeline_id=pipeline.id, repository_id=repo.id, artifact_bundle_key="conflict", target_branch="main")
    db.add(run); db.commit(); db.refresh(run); prepare_delivery(db, run)

    repo_path = Path(repo.local_path)
    (repo_path / "README.md").write_text("# Target branch\n", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True)
    subprocess.run(["git", "-c", "user.name=Target", "-c", "user.email=target@example.local", "commit", "-m", "Target change"], cwd=repo_path, check=True, capture_output=True)
    try:
        merge_delivery(db, run)
        assert False
    except RepositoryDeliveryError:
        pass
    db.refresh(run)
    assert run.status == "conflict"
    assert db.query(RepositoryConflict).filter(RepositoryConflict.delivery_run_id == run.id).count() >= 1
    resolve_delivery_conflicts(db, run, resolutions={"README.md": "# Resolved\n"}, note="combined source and target intent")
    assert run.status == "prepared"
    mr = merge_delivery(db, run)
    assert mr.status == "merged"
    assert (repo_path / "README.md").read_text() == "# Resolved\n"


def test_durable_webhook_outbox_and_delivery(tmp_path, monkeypatch):
    from app.models import EventWebhookDelivery, EventWebhookEndpoint
    from app.services.company_event_bus import emit_event
    from app.services.event_webhooks import deliver_webhook
    db = session(); org, company, coder, reviewer, agent, repo = seed(db, tmp_path)
    settings.event_webhook_allowed_hosts = "localhost,127.0.0.1"
    endpoint = EventWebhookEndpoint(
        organization_id=org.id, company_id=company.id, name="Local event sink",
        target_url="http://localhost/hook", event_pattern="repository.*", max_attempts=3, backoff_seconds=1,
    )
    db.add(endpoint); db.commit(); db.refresh(endpoint)
    event = emit_event(db, organization_id=org.id, company_id=company.id, event_type="repository.delivery.merged", payload={"run": 11})
    delivery = db.query(EventWebhookDelivery).filter(EventWebhookDelivery.event_id == event.id).one()

    class Response:
        status_code = 204
        text = "ok"
    monkeypatch.setattr("app.services.event_webhooks.httpx.post", lambda *a, **k: Response())
    deliver_webhook(db, delivery)
    assert delivery.status == "delivered"
    assert delivery.attempts == 1
