"""Ba bài học tốc độ từ FastClaw, đo bằng hành vi chứ không grep.

1. Nina trả lời theo từng đoạn: token đầu tới tay người hỏi trước khi model
   viết xong; lỗi model đi ra thành ``error`` chứ không chờ tới hết giờ.
2. Gói ngữ cảnh ghép khối ít đổi trước, khối đổi mỗi lượt sau (prompt cache).
3. Kết quả tool MCP có trần; tài liệu dài đọc tiếp được bằng offset.

Frame gateway trong test lấy đúng hình dạng đã ghi trên gateway thật
(``_reports/evidence/d11/frames_ui.jsonl``).
"""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.api import mcp as mcp_api
from app.models.entities import Agent, Company, Department, Member, Organization
from app.runtime import openclaw_native as native
from app.runtime.openclaw_native import NativeOpenClawRuntime, chat_stream_events
from app.services import company_mcp, v36_insights

RUN = "clawcompany:agent:dev:main:abc:1234"
KEY = "agent:dev:main"


def frame(event, payload):
    return {"type": "event", "event": event, "payload": {"sessionKey": KEY, "runId": RUN, **payload}}


def text_msg(text):
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


# ------------------------------------------------------------ 1. stream

def test_delta_carries_the_accumulated_text_not_a_fragment():
    out = chat_stream_events(frame("chat", {"state": "delta", "deltaText": "lo",
                                            "message": text_msg("Hello")}), run_id=RUN, session_key=KEY)
    assert out == [{"kind": "delta", "text": "Hello"}]


def test_deltas_are_accumulated_whether_fragments_or_snapshots():
    """Đo trên gateway thật 2026.9.8: chat.delta là mảnh ("T", "ôi là Nina…")."""
    from app.runtime.openclaw_native import merge_delta
    text = ""
    for piece in ["T", "ôi là Nina", ", trợ lý."]:
        text = merge_delta(text, piece)
    assert text == "Tôi là Nina, trợ lý."
    assert merge_delta("Tôi là", "Tôi là Nina") == "Tôi là Nina"   # kiểu toàn văn
    assert merge_delta("abc", "") == "abc"


def test_frames_of_another_run_or_session_are_ignored():
    other_run = frame("chat", {"state": "delta", "message": text_msg("x")})
    other_run["payload"]["runId"] = "someone-else"
    other_session = frame("chat", {"state": "final", "message": text_msg("x")})
    other_session["payload"]["sessionKey"] = "agent:dev:company-task-9"
    assert chat_stream_events(other_run, run_id=RUN, session_key=KEY) == []
    assert chat_stream_events(other_session, run_id=RUN, session_key=KEY) == []


def test_final_error_abort_and_tool_items_are_recognised():
    final = chat_stream_events(frame("chat", {"state": "final", "stopReason": "stop",
                                              "message": text_msg("Xong.")}), run_id=RUN, session_key=KEY)
    assert final[0]["kind"] == "final" and final[0]["text"] == "Xong."
    err = chat_stream_events(frame("chat", {"state": "error", "errorMessage": "401 invalid key"}),
                             run_id=RUN, session_key=KEY)
    assert err[0]["kind"] == "error" and "401" in err[0]["message"]
    aborted = chat_stream_events(frame("chat", {"state": "aborted"}), run_id=RUN, session_key=KEY)
    assert aborted[0]["kind"] == "error"
    tool = chat_stream_events(frame("agent", {"stream": "item", "data": {
        "kind": "tool", "name": "exec", "title": "Exec print text", "phase": "start"}}),
        run_id=RUN, session_key=KEY)
    assert tool == [{"kind": "tool", "name": "exec", "title": "Exec print text", "phase": "start"}]


def test_no_reply_is_not_an_answer():
    out = chat_stream_events(frame("chat", {"state": "final", "message": text_msg("NO_REPLY")}),
                             run_id=RUN, session_key=KEY)
    assert out[0]["text"] == ""


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        org = Organization(name="Nova", slug="nova-speed"); db.add(org); db.commit()
        company = Company(organization_id=org.id, name="Nova", status="active"); db.add(company); db.commit()
        dept = Department(company_id=company.id, name="Điều hành", status="active"); db.add(dept); db.commit()
        member = Member(organization_id=org.id, company_id=company.id, department_id=dept.id,
                        name="Nina", member_type="agent", role="CoS", status="active")
        db.add(member); db.commit()
        db.add(Agent(member_id=member.id, runtime_provider="openclaw", runtime_agent_id="dev",
                     lifecycle="active", model="x")); db.commit()
        factory.org_id = org.id
    return factory


def fake_runtime(events):
    rt = NativeOpenClawRuntime.__new__(NativeOpenClawRuntime)

    async def list_agents():
        return [{"id": "dev"}]

    async def chat_stream(agent_id, message, *, session_key=None, timeout_seconds=120):
        rt.sent = (agent_id, message, session_key)
        for e in events:
            yield e

    rt.list_agents, rt.chat_stream = list_agents, chat_stream
    return rt


async def collect(factory, monkeypatch, events):
    rt = fake_runtime(events)
    monkeypatch.setattr("app.runtime.factory.get_runtime", lambda: rt)
    out = []
    async for chunk in v36_insights.ask_nina_stream(factory, factory.org_id, message="Chào"):
        name = chunk.split("\n", 1)[0].removeprefix("event: ")
        data = json.loads(chunk.split("data: ", 1)[1])
        out.append((name, data))
    return rt, out


@pytest.mark.asyncio
async def test_ask_stream_pushes_each_delta_then_one_final(session_factory, monkeypatch):
    rt, out = await collect(session_factory, monkeypatch, [
        {"kind": "delta", "text": "Chào"}, {"kind": "delta", "text": "Chào anh"},
        {"kind": "final", "text": "Chào anh."}])
    assert rt.sent == ("dev", "Chào", "agent:dev:main")
    assert [n for n, _ in out] == ["meta", "delta", "delta", "final"]
    assert out[0][1]["agent"] == "Nina"
    final = out[-1][1]
    assert final["answered"] is True and final["reply"] == "Chào anh."
    assert final["first_token_seconds"] is not None


@pytest.mark.asyncio
async def test_model_error_surfaces_instead_of_reporting_answered(session_factory, monkeypatch):
    """Lỗi đã biết: bản poll trả answered:true khi model 401."""
    _, out = await collect(session_factory, monkeypatch, [
        {"kind": "error", "message": "401 invalid key"}])
    assert out[-1][0] == "error"
    assert out[-1][1]["answered"] is False and "401" in out[-1][1]["message"]


@pytest.mark.asyncio
async def test_stream_that_ends_without_final_says_so(session_factory, monkeypatch):
    _, out = await collect(session_factory, monkeypatch, [{"kind": "delta", "text": "Nửa"}])
    assert out[-1][0] == "error" and out[-1][1]["partial"] == "Nửa"


@pytest.mark.asyncio
async def test_chat_stream_sends_on_the_same_socket_and_stops_at_final(monkeypatch):
    """Một WebSocket: subscribe → chat.send → nhận delta → final thì dừng."""
    sent = []

    class WS:
        def __init__(self):
            self.queue = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def send(self, raw):
            msg = json.loads(raw)
            sent.append(msg)
            if msg["method"] == "chat.send":
                rid = msg["params"]["idempotencyKey"]
                self.queue += [
                    {"type": "res", "id": msg["id"], "ok": True, "payload": {"runId": rid}},
                    {"type": "event", "event": "chat", "payload": {
                        "sessionKey": KEY, "runId": rid, "state": "delta", "message": text_msg("H")}},
                    {"type": "event", "event": "chat", "payload": {
                        "sessionKey": KEY, "runId": rid, "state": "delta", "message": text_msg("i")}},
                    {"type": "event", "event": "chat", "payload": {
                        "sessionKey": KEY, "runId": "other", "state": "final", "message": text_msg("x")}},
                    {"type": "event", "event": "chat", "payload": {
                        "sessionKey": KEY, "runId": rid, "state": "final", "message": text_msg("Hi!")}},
                ]
            else:
                self.queue.append({"type": "res", "id": msg["id"], "ok": True, "payload": {}})

        async def recv(self):
            return json.dumps(self.queue.pop(0))

    ws = WS()
    monkeypatch.setattr(native.websockets, "connect", lambda *a, **k: ws)
    rt = NativeOpenClawRuntime.__new__(NativeOpenClawRuntime)
    rt.url, rt.timeout = "ws://x", 5

    async def handshake(_ws):
        return {}
    rt._handshake = handshake
    rt._headers = lambda: None
    events = [e async for e in rt.chat_stream("dev", "Chào", session_key=KEY)]
    assert [m["method"] for m in sent] == ["sessions.messages.subscribe", "chat.send"]
    assert events == [{"kind": "delta", "text": "H"}, {"kind": "delta", "text": "Hi"},
                      {"kind": "final", "text": "Hi!", "stop_reason": None}]


# ------------------------------------------------------------ 2. thứ tự ghép

def test_pack_text_puts_stable_blocks_before_volatile_ones():
    from app.services import work_context as wc
    assert wc.EMIT_ORDER[:3] == (7, 1, 6)
    assert wc.EMIT_ORDER[-1] == 4                      # sổ ghi đổi mỗi lượt → cuối
    assert sorted(wc.EMIT_ORDER) == [1, 2, 3, 4, 5, 6, 7]


# ------------------------------------------------------------ 3. trần tool

def test_small_tool_result_keeps_structured_content():
    out = mcp_api.tool_result({"a": 1}, True)
    assert out["structuredContent"] == {"a": 1} and out["isError"] is False


def test_huge_tool_result_is_capped_head_and_tail():
    result = {"content": "A" * 50_000 + "ĐUÔI"}
    out = mcp_api.tool_result(result, True)
    text = out["content"][0]["text"]
    assert len(text) < mcp_api.MAX_TOOL_TEXT_CHARS + 300
    assert text.startswith('{"content": "AAA') and text.rstrip().endswith('ĐUÔI"}')
    assert "đã lược" in text and "structuredContent" not in out


def test_long_document_is_read_in_slices():
    content = "x" * 30_000
    first = company_mcp._slice(content, {})
    assert len(first["content"]) == company_mcp.READ_SLICE_CHARS
    assert first["next_offset"] == company_mcp.READ_SLICE_CHARS and "offset=" in first["note"]
    last = company_mcp._slice(content, {"offset": 24_000})
    assert len(last["content"]) == 6_000 and last["next_offset"] is None and "note" not in last
    with pytest.raises(company_mcp.ToolError):
        company_mcp._slice(content, {"offset": -1})
