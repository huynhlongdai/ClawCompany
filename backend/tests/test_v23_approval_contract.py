"""v23 tests: the approval reply matches the documented upstream contract.

v21 shipped a *guessed* payload (sessionKey + requestId + approved: bool +
note). The upstream gateway docs say approvals are resolved by id through
``exec.approval.resolve`` with a three-valued decision, and that the approval
record has no resolution-reason field. These tests pin that shape so nobody
quietly reintroduces the boolean.

v35.1: tham số đã được đối chiếu trực tiếp với schema upstream
``packages/gateway-protocol/src/schema/exec-approvals.ts``:

    ExecApprovalResolveParamsSchema = closedObject({
      id, decision, reviewer?, grantExpiresInDays?
    })

``closedObject`` = additionalProperties: false, nên ``sessionKey`` mà v23 gửi
kèm là một field ngoài schema và bị gateway từ chối. Điều còn chưa kiểm chứng
là hành vi của một gateway đang chạy thật, không còn là tên tham số.
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
import app.models  # noqa: F401
from app.models import Approval, Company, Member, Organization
from app.runtime import openclaw_protocol as ocp
from app.services import approval_bridge as bridge


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
def pending(db):
    org = Organization(name="Nova Holding", slug="nova-holding-v23")
    db.add(org); db.commit(); db.refresh(org)
    labs = Company(organization_id=org.id, name="Nova Labs", industry="AI", status="active")
    db.add(labs); db.commit(); db.refresh(labs)
    db.add(Member(organization_id=org.id, company_id=labs.id, name="Nina",
                  member_type="agent", role="Chief of Staff", status="active"))
    db.commit()
    row = Approval(organization_id=org.id, company_id=labs.id,
                   action="exec: rm -rf build", risk="high", status="pending",
                   policy_key="openclaw:agent:nina:main:req-7", evidence="{}")
    db.add(row); db.commit(); db.refresh(row)
    return row


class Recorder:
    """Captures exactly what the bridge hands to the runtime."""

    def __init__(self):
        self.calls = []

    async def respond_approval(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True}


def _configured(monkeypatch, *, allow_always=False):
    monkeypatch.setattr(settings, "openclaw_approval_reply_method",
                        ocp.M_EXEC_APPROVAL_RESOLVE, raising=False)
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", True, raising=False)
    monkeypatch.setattr(settings, "openclaw_approval_allow_always_enabled",
                        allow_always, raising=False)


# --- the documented vocabulary -------------------------------------------

def test_protocol_pins_the_documented_method_and_decisions():
    assert ocp.M_EXEC_APPROVAL_RESOLVE == "exec.approval.resolve"
    assert ocp.M_EXEC_APPROVAL_LIST == "exec.approval.list"
    assert ocp.APPROVAL_DECISIONS == {"allow-once", "allow-always", "deny"}
    # Resolving needs the approvals scope, which stays opt-in.
    assert ocp.SCOPE_APPROVALS == "operator.approvals"


def test_company_decisions_map_onto_upstream_decisions():
    assert bridge.DECISIONS["approved"] == ocp.D_ALLOW_ONCE
    assert bridge.DECISIONS["approved_always"] == ocp.D_ALLOW_ALWAYS
    assert bridge.DECISIONS["denied"] == ocp.D_DENY
    # "approved" must never silently become a standing grant.
    assert bridge.DECISIONS["approved"] != ocp.D_ALLOW_ALWAYS


# --- what actually goes over the wire ------------------------------------

def test_approval_sends_allow_once_by_id_not_a_boolean(db, pending, monkeypatch):
    _configured(monkeypatch)
    runtime = Recorder()
    monkeypatch.setattr(bridge, "get_runtime", lambda: runtime)

    result = asyncio.run(bridge.decide(db, pending, decision="approved", note="fine"))

    assert result["delivered"] is True
    assert result["upstream_decision"] == ocp.D_ALLOW_ONCE
    call = runtime.calls[0]
    assert call["request_id"] == "req-7"
    assert call["decision"] == ocp.D_ALLOW_ONCE
    assert "approved" not in call  # the v21 boolean is gone


def test_the_reviewer_note_is_never_sent_upstream(db, pending, monkeypatch):
    """The gateway record has no resolution-reason field, so we do not fake one."""
    _configured(monkeypatch)
    runtime = Recorder()
    monkeypatch.setattr(bridge, "get_runtime", lambda: runtime)

    result = asyncio.run(bridge.decide(db, pending, decision="denied", note="not during freeze"))

    assert "note" not in runtime.calls[0]
    assert result["note_delivered_upstream"] is False
    # The audit trail says so in words, not just in a flag.
    assert "stayed in ClawCompany" in pending.resolution_note
    assert "not during freeze" in pending.resolution_note


def test_allow_always_is_refused_unless_explicitly_enabled(db, pending, monkeypatch):
    _configured(monkeypatch, allow_always=False)
    runtime = Recorder()
    monkeypatch.setattr(bridge, "get_runtime", lambda: runtime)

    with pytest.raises(bridge.ApprovalBridgeError) as exc:
        asyncio.run(bridge.decide(db, pending, decision="approved_always"))

    assert "standing grant" in str(exc.value)
    assert runtime.calls == []      # nothing reached the gateway
    assert pending.status == "pending"  # and nothing was recorded either


def test_allow_always_is_delivered_when_enabled_and_still_reads_as_approved(db, pending, monkeypatch):
    _configured(monkeypatch, allow_always=True)
    runtime = Recorder()
    monkeypatch.setattr(bridge, "get_runtime", lambda: runtime)

    result = asyncio.run(bridge.decide(db, pending, decision="approved_always"))

    assert runtime.calls[0]["decision"] == ocp.D_ALLOW_ALWAYS
    # Local status stays in the queue's own vocabulary.
    assert pending.status == "approved"
    assert result["upstream_decision"] == ocp.D_ALLOW_ALWAYS


def test_unknown_decision_is_still_rejected(db, pending, monkeypatch):
    _configured(monkeypatch)
    with pytest.raises(bridge.ApprovalBridgeError):
        asyncio.run(bridge.decide(db, pending, decision="allow-once"))  # upstream word, not ours


# --- readiness is explicit about how trustworthy the method name is ------

def test_readiness_marks_the_default_method_as_documented(monkeypatch):
    _configured(monkeypatch)
    readiness = bridge.upstream_readiness()
    assert readiness["ready"] is True
    assert readiness["method"] == ocp.M_EXEC_APPROVAL_RESOLVE
    assert readiness["method_source"] == "documented default"
    assert readiness["note_delivered_upstream"] is False
    assert readiness["scope"] == ocp.SCOPE_APPROVALS


def test_readiness_flags_an_operator_override_as_unverified(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(settings, "openclaw_approval_reply_method",
                        "session.approval.respond", raising=False)
    assert bridge.upstream_readiness()["method_source"] == "operator override"


def test_readiness_still_reports_a_missing_scope(monkeypatch):
    _configured(monkeypatch)
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", False, raising=False)
    readiness = bridge.upstream_readiness()
    assert readiness["ready"] is False
    assert readiness["missing"] == ["OPENCLAW_REQUEST_APPROVALS_SCOPE"]
    assert ocp.SCOPE_APPROVALS in readiness["hint"]


# --- the native runtime payload ------------------------------------------

def test_native_payload_uses_id_and_decision(monkeypatch):
    from app.runtime.openclaw_native import NativeOpenClawRuntime

    _configured(monkeypatch)
    runtime = NativeOpenClawRuntime()
    seen = {}

    async def fake_rpc(method, params):
        seen.update(method=method, params=params)
        return {"ok": True}

    monkeypatch.setattr(runtime, "_rpc", fake_rpc)
    asyncio.run(runtime.respond_approval(request_id="req-7", decision=ocp.D_ALLOW_ONCE,
                                         session_key="agent:nina:main"))

    assert seen["method"] == ocp.M_EXEC_APPROVAL_RESOLVE
    assert seen["params"]["id"] == "req-7"
    assert seen["params"]["decision"] == ocp.D_ALLOW_ONCE
    assert "approved" not in seen["params"] and "requestId" not in seen["params"]
    # Schema upstream là closedObject: thừa một khoá là bị từ chối cả lượt gọi.
    # session_key được truyền vào ở trên và PHẢI không xuất hiện trong payload.
    assert set(seen["params"]) == {"id", "decision"}


def test_native_never_sends_session_key_because_schema_is_closed(monkeypatch):
    """sessionKey không nằm trong ExecApprovalResolveParamsSchema.

    v23 gửi nó "như một disambiguator". Vì schema là closedObject
    (additionalProperties: false), mọi lượt trả lời có session_key đều bị
    gateway từ chối bằng INVALID_REQUEST trước khi tới handler -- tức tính
    năng trả lời approval chưa từng chạy được với gateway thật.
    """
    from app.runtime.openclaw_native import NativeOpenClawRuntime

    _configured(monkeypatch)
    runtime = NativeOpenClawRuntime()
    seen = {}

    async def fake_rpc(method, params):
        seen.update(params=params)
        return {"ok": True}

    monkeypatch.setattr(runtime, "_rpc", fake_rpc)
    asyncio.run(runtime.respond_approval(request_id="req-7", decision=ocp.D_DENY,
                                         session_key="agent:nina:company-task-9"))
    assert set(seen["params"]) == {"id", "decision"}


def test_native_omits_the_session_key_when_we_do_not_have_one(monkeypatch):
    from app.runtime.openclaw_native import NativeOpenClawRuntime

    _configured(monkeypatch)
    runtime = NativeOpenClawRuntime()
    seen = {}

    async def fake_rpc(method, params):
        seen.update(params=params)
        return {"ok": True}

    monkeypatch.setattr(runtime, "_rpc", fake_rpc)
    asyncio.run(runtime.respond_approval(request_id="req-7", decision=ocp.D_DENY))
    assert "sessionKey" not in seen["params"]


def test_native_rejects_a_decision_outside_the_upstream_vocabulary(monkeypatch):
    from app.runtime.openclaw_native import NativeOpenClawRuntime, OpenClawProtocolError

    _configured(monkeypatch)
    runtime = NativeOpenClawRuntime()
    with pytest.raises(OpenClawProtocolError):
        asyncio.run(runtime.respond_approval(request_id="req-7", decision="approve"))


def test_native_still_refuses_when_the_approvals_scope_was_not_requested(monkeypatch):
    from app.runtime.openclaw_native import NativeOpenClawRuntime, OpenClawProtocolError

    _configured(monkeypatch)
    monkeypatch.setattr(settings, "openclaw_request_approvals_scope", False, raising=False)
    runtime = NativeOpenClawRuntime()
    with pytest.raises(OpenClawProtocolError):
        asyncio.run(runtime.respond_approval(request_id="req-7", decision=ocp.D_ALLOW_ONCE))
