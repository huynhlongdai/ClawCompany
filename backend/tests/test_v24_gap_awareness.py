"""v24 tests: report what was missed, and recover the part that is recoverable.

Two claims. First, a takeover must leave a visible mark saying the transcript
has a hole in it, because re-subscribing does not replay anything. Second,
backfilled approval prompts must land in the queue by exactly the same rules
as live ones, so a repeated backfill cannot duplicate them.
"""
import asyncio
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
import app.models  # noqa: F401
from app.models import Approval, Company, Member, Organization, RuntimeEvent
from app.runtime import openclaw_protocol as ocp
from app.services import approval_backfill as backfill
from app.services import runtime_gap as gap
from app.services import runtime_stream as rs

SESSION = "agent:nina:company-task-7"


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
    organization = Organization(name="Nova Holding", slug="nova-holding-v24")
    db.add(organization); db.commit(); db.refresh(organization)
    company = Company(organization_id=organization.id, name="Nova Labs",
                      industry="ai", status="active")
    db.add(company); db.commit(); db.refresh(company)
    member = Member(organization_id=organization.id, company_id=company.id, name="Nina",
                    member_type="ai_agent", role="member", status="active")
    db.add(member); db.commit(); db.refresh(member)
    return organization


def _event(db, organization_id, *, minutes_ago=0):
    row = RuntimeEvent(
        organization_id=organization_id, runtime_run_id=SESSION, runtime_session_key=SESSION,
        event_type="chat", event_json="{}",
        created_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
    )
    db.add(row); db.commit()
    return row


# --- measuring the hole ----------------------------------------------------


def test_never_observed_session_is_not_a_zero_gap(db, org):
    """Unknown and zero are different answers; only one of them is true."""
    result = gap.measure(db, SESSION)
    assert result["observed"] is False
    assert result["gap_seconds"] is None
    assert result["significant"] is False


def test_gap_measured_from_the_last_recorded_event(db, org):
    _event(db, org.id, minutes_ago=30)
    _event(db, org.id, minutes_ago=4)
    result = gap.measure(db, SESSION)
    assert result["observed"] is True
    # Measured from the most recent event, not the first one.
    assert 200 < result["gap_seconds"] < 400
    assert result["significant"] is True


def test_takeover_round_trip_is_not_reported_as_a_gap(db, org):
    _event(db, org.id, minutes_ago=0)
    assert gap.record(db, organization_id=org.id, session_key=SESSION) is None


def test_recorded_gap_says_the_events_are_not_coming_back(db, org):
    _event(db, org.id, minutes_ago=10)
    payload = gap.record(db, organization_id=org.id, session_key=SESSION, task_id=7)
    assert payload is not None
    assert payload["replayed"] is False
    assert payload["gap_seconds"] > 500


def test_gap_is_written_into_the_transcript_itself(db, org):
    """A hole nobody can see is the bug v24 is fixing."""
    _event(db, org.id, minutes_ago=10)
    gap.record(db, organization_id=org.id, session_key=SESSION, task_id=7)
    marker = (
        db.query(RuntimeEvent)
        .filter(RuntimeEvent.event_type == gap.GAP_EVENT)
        .one()
    )
    assert marker.runtime_session_key == SESSION


# --- listing shapes --------------------------------------------------------


def test_bare_list_response_is_accepted():
    assert backfill.entries_from([{"id": "a"}]) == [{"id": "a"}]


def test_wrapped_list_response_is_accepted():
    assert backfill.entries_from({"approvals": [{"id": "a"}]}) == [{"id": "a"}]
    assert backfill.entries_from({"items": [{"id": "b"}]}) == [{"id": "b"}]


def test_junk_entries_are_dropped_not_coerced():
    """A string is not an approval; inventing one would be worse than none."""
    assert backfill.entries_from({"approvals": ["nope", {"id": "a"}]}) == [{"id": "a"}]
    assert backfill.entries_from({"unexpected": 1}) == []


# --- recording backfilled prompts -----------------------------------------


def test_backfilled_prompt_uses_the_live_policy_key(db, org):
    out = backfill.apply_entries(
        db, [{"id": "req-7", "tool": "shell"}],
        organization_id=org.id, session_key=SESSION,
    )
    assert len(out["recorded"]) == 1
    row = db.get(Approval, out["recorded"][0])
    assert row.policy_key == f"openclaw:{SESSION}:req-7"
    # Same risk rules as the live path: a denied tool is high risk.
    assert row.risk == "high"


def test_repeating_a_backfill_does_not_duplicate_the_queue(db, org):
    entries = [{"id": "req-7", "tool": "shell"}]
    first = backfill.apply_entries(db, entries, organization_id=org.id, session_key=SESSION)
    second = backfill.apply_entries(db, entries, organization_id=org.id, session_key=SESSION)
    assert first["recorded"] == second["recorded"]
    assert db.query(Approval).count() == 1


def test_already_resolved_entry_without_a_local_row_is_ignored(db, org):
    """We do not resurrect a prompt the operator already answered elsewhere."""
    out = backfill.apply_entries(
        db, [{"id": "req-9", "tool": "shell", "decision": "deny"}],
        organization_id=org.id, session_key=SESSION,
    )
    assert out["recorded"] == []
    assert out["ignored"] == 1


# --- readiness and the gateway call ---------------------------------------


def test_backfill_reports_unsupported_instead_of_empty(db, org, monkeypatch):
    """An empty list would read as "nothing pending", which is a lie."""
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", False)
    out = asyncio.run(backfill.backfill_session(
        db, organization_id=org.id, session_key=SESSION))
    assert out["supported"] is False
    assert "OPENCLAW_REQUEST_APPROVALS_SCOPE" in out["readiness"]["missing"]


def test_backfill_asks_the_gateway_then_records(db, org, monkeypatch):
    class FakeRuntime:
        def __init__(self):
            self.asked = []

        async def list_approvals(self, *, session_key=""):
            self.asked.append(session_key)
            return {"approvals": [{"id": "req-11", "tool": "fs_write"}]}

    runtime = FakeRuntime()
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", True)
    monkeypatch.setattr(backfill, "get_runtime", lambda: runtime)
    out = asyncio.run(backfill.backfill_session(
        db, organization_id=org.id, session_key=SESSION))
    assert out["supported"] is True
    assert runtime.asked == [SESSION]
    assert len(out["recorded"]) == 1


def test_listing_method_is_the_documented_one():
    assert ocp.M_EXEC_APPROVAL_LIST == "exec.approval.list"
    assert backfill.readiness()["method"] == ocp.M_EXEC_APPROVAL_LIST


def test_takeover_reports_its_gaps(db, org, monkeypatch):
    """claim_orphans must hand back the holes it created awareness of."""
    monkeypatch.setattr(rs, "claimable_sessions", lambda db_, limit=200: [])
    out = rs.claim_orphans(db, organization_id=org.id)
    assert out["gaps"] == []
