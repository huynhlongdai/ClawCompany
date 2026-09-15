"""v25 tests: reconciliation has to happen without a human in the room.

v24 could report a gap and recover pending approvals, but only when someone
called the endpoint. These tests pin the three properties that make the
automatic version trustworthy: it runs on attach, it does not double-report
what a takeover already recorded, and it can never break the stream it is
reconciling.
"""
import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
import app.models  # noqa: F401
from app.models import Company, Member, Organization, RuntimeEvent
from app.services import approval_backfill as backfill
from app.services import runtime_gap as gap
from app.services import runtime_stream as rs
from app.services import stream_reconcile as rec

SESSION = "agent:nina:company-task-9"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def org(db):
    organization = Organization(name="Nova Holding", slug="nova-holding-v25")
    db.add(organization); db.commit(); db.refresh(organization)
    company = Company(organization_id=organization.id, name="Nova Labs",
                      industry="ai", status="active")
    db.add(company); db.commit(); db.refresh(company)
    member = Member(organization_id=organization.id, company_id=company.id, name="Nina",
                    member_type="ai_agent", role="member", status="active")
    db.add(member); db.commit(); db.refresh(member)
    return organization


@pytest.fixture(autouse=True)
def fresh_history():
    """The reconcile history is process-global; tests must not inherit it."""
    rec.clear()
    yield
    rec.clear()


def _event(db, organization_id, *, minutes_ago=0):
    row = RuntimeEvent(
        organization_id=organization_id, runtime_run_id=SESSION, runtime_session_key=SESSION,
        event_type="chat", event_json="{}",
        created_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
    )
    db.add(row); db.commit()
    return row


def _run(db, org, **kwargs):
    return asyncio.run(rec.reconcile(
        db, organization_id=org.id, session_key=SESSION, task_id=None, **kwargs))


# --- the trigger -----------------------------------------------------------


def test_attach_reports_the_gap_it_inherited(db, org):
    """The whole point: nobody had to ask for this."""
    _event(db, org.id, minutes_ago=10)
    outcome = _run(db, org)
    assert outcome["ran"] is True
    assert outcome["gap"] is not None
    assert outcome["gap"]["gap_seconds"] >= 600
    assert outcome["gap"]["replayed"] is False


def test_quiet_session_produces_no_noise(db, org):
    """A gap under the threshold is the round trip of attaching, not a hole."""
    _event(db, org.id, minutes_ago=0)
    outcome = _run(db, org)
    assert outcome["ran"] is True
    assert outcome["gap"] is None


def test_gap_already_recorded_by_a_takeover_is_not_reported_twice(db, org):
    """claim_orphans records its own gap; the follower must not echo it.

    This works because the recorded gap is itself the newest event for the
    session, so the second measurement legitimately finds nothing.
    """
    _event(db, org.id, minutes_ago=10)
    first = gap.record(db, organization_id=org.id, session_key=SESSION, reason="takeover")
    assert first is not None
    outcome = _run(db, org)
    assert outcome["gap"] is None


def test_disabled_flag_does_not_pretend_to_have_run(db, org, monkeypatch):
    monkeypatch.setattr(settings, "openclaw_auto_reconcile", False)
    _event(db, org.id, minutes_ago=10)
    outcome = _run(db, org)
    assert outcome["ran"] is False
    assert outcome["skipped"] == "disabled"
    assert outcome["gap"] is None


def test_flapping_lease_does_not_re_ask_the_gateway(db, org):
    """Re-attaching every few seconds must not become a polling loop."""
    _event(db, org.id, minutes_ago=10)
    assert _run(db, org)["ran"] is True
    second = _run(db, org)
    assert second["ran"] is False
    assert second["skipped"].startswith("cooldown:")


def test_an_operator_can_override_the_cooldown(db, org):
    _event(db, org.id, minutes_ago=10)
    _run(db, org)
    assert _run(db, org, force=True)["ran"] is True


def test_force_also_overrides_the_feature_flag(db, org, monkeypatch):
    """An explicit request carries better context than our default."""
    monkeypatch.setattr(settings, "openclaw_auto_reconcile", False)
    assert _run(db, org, force=True)["ran"] is True


# --- it must never break the stream ---------------------------------------


def test_gateway_failure_is_reported_not_raised(db, org, monkeypatch):
    async def explode(*args, **kwargs):
        raise RuntimeError("gateway refused the connection")

    monkeypatch.setattr(backfill, "backfill_session", explode)
    outcome = _run(db, org)
    assert outcome["ran"] is True
    assert "gateway refused" in outcome["error"]


def test_unsupported_runtime_reports_unsupported_not_empty(db, org):
    """A mock runtime must not look like "no approvals pending"."""
    outcome = _run(db, org)
    assert outcome["backfill"]["supported"] is False
    assert outcome["backfill"]["readiness"]["missing"]


def test_history_keeps_the_last_pass_per_session(db, org):
    _event(db, org.id, minutes_ago=10)
    _run(db, org)
    rows = rec.history(org.id)
    assert len(rows) == 1 and rows[0]["session_key"] == SESSION
    assert rec.history(org.id + 999) == []


def test_cooldown_skips_are_not_written_into_history(db, org):
    """History answers "when did we last actually reconcile", not "last call"."""
    _event(db, org.id, minutes_ago=10)
    _run(db, org)
    first_at = rec.history(org.id)[0]["at"]
    _run(db, org)
    assert rec.history(org.id)[0]["at"] == first_at


# --- wiring ----------------------------------------------------------------


def test_consumer_reconciles_before_reading_the_first_event(db, org, monkeypatch):
    """The attach path itself must call this, or none of the above matters."""
    order = []

    class FakeRuntime:
        async def stream_run(self, session_key):
            order.append("stream")
            yield {"type": "chat", "terminal": True, "raw": {}}

    class FakeLease:
        def renew(self, key):
            return True

        def release(self, key):
            return None

    class FakeRegistry:
        def publish(self, row):
            return None

        def withdraw(self, key):
            return None

    async def spy(db_, **kwargs):
        order.append("reconcile")
        return {"ran": True}

    monkeypatch.setattr(rs, "SessionLocal", lambda: db)
    monkeypatch.setattr(rs, "get_runtime", lambda: FakeRuntime())
    monkeypatch.setattr(rs, "lease_store", FakeLease())
    monkeypatch.setattr(rs, "registry", FakeRegistry())
    monkeypatch.setattr(rs.stream_reconcile, "reconcile", spy)

    state = rs.ConsumerState(session_key=SESSION, task_id=None, organization_id=org.id)
    asyncio.run(rs._consume(state))

    assert order[0] == "reconcile", "reconciliation must precede the first live event"
    assert state.status == "finished"
