"""M6 việc 12b — A2A hai chiều: mở seat cho bên ngoài + thuê agent ngoài, thử vòng kín (công ty tự gọi chính mình)."""
from urllib.parse import urlparse

from app.models import Agent, Member
from app.models.a2a import ExternalAgent
from app.services import a2a, company_mcp
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def _loop_http(env):
    """Định tuyến HTTP ra ngoài của a2a vào chính TestClient — agent 'ngoài' là seat của công ty mình."""
    def http(method, url, body=None, headers=None, timeout=120):
        path = urlparse(url).path
        r = env.c.get(path, headers=headers or {}) if method == "GET" else env.c.post(path, json=body, headers=headers or {})
        return r.status_code, r.json()
    return http


def test_expose_card_rpc_and_hire_back_through_a2a(env, monkeypatch):
    seat = hire(env, name="Thu Trang", role="Chăm sóc khách hàng")
    caller = hire(env, name="Minh Khoa", role="Trưởng phòng bán hàng")
    asked = []

    async def chat_stream(agent_id, message, *, session_key=None, timeout_seconds=90):
        asked.append((agent_id, session_key, message))
        yield {"kind": "final", "text": "Dạ, hàng vỡ anh gửi ảnh qua Zalo trong 48 giờ, shop gửi bù miễn phí ạ."}
    env.gw.chat_stream = chat_stream
    monkeypatch.setattr("app.api.a2a.get_runtime", lambda: env.gw)
    monkeypatch.setattr(a2a, "_http", _loop_http(env))

    # tắt thì không ai thấy
    rid = seat["runtime_agent_id"]
    assert env.c.get(f"/api/a2a/agents/{rid}/.well-known/agent-card.json").status_code == 404
    assert env.c.post(f"/api/a2a/expose/{seat['agent_id']}", json={}, headers=env.tok("member")).status_code == 403
    x = env.c.post(f"/api/a2a/expose/{seat['agent_id']}", json={"enabled": True}, headers=env.tok("manager")).json()
    token = x["token"]
    assert token.startswith("cca2a_") and x["card_url"].endswith(f"/api/a2a/agents/{rid}/.well-known/agent-card.json")
    assert "token" not in env.c.get(f"/api/a2a/expose/{seat['agent_id']}", headers=env.tok("member")).json()
    card = env.c.get(f"/api/a2a/agents/{rid}/.well-known/agent-card.json").json()
    assert card["name"].startswith("Thu Trang") and card["url"].endswith(f"/api/a2a/agents/{rid}")

    # sai khoá → lỗi JSON-RPC, không chạy agent
    bad = env.c.post(f"/api/a2a/agents/{rid}", json={"jsonrpc": "2.0", "id": 1, "method": "message/send",
                     "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": "hi"}]}}},
                     headers={"Authorization": "Bearer sai"}).json()
    assert bad["error"]["code"] == -32004 and not asked

    # thuê lại chính seat đó như một agent ngoài, bằng Agent Card
    ext = env.c.post("/api/a2a/external", json={"card_url": x["card_url"], "auth_header": f"Bearer {token}"},
                     headers=env.tok("manager")).json()
    assert ext["name"].startswith("Thu Trang") and ext["has_auth"] and "auth_header" not in ext

    # nhân sự AI khác giao việc qua tool MCP
    c_ag = env.db.get(Agent, caller["agent_id"]); c_m = env.db.get(Member, c_ag.member_id)
    ctx = company_mcp.ToolContext(db=env.db, member=c_m, agent=c_ag, scopes=["company.messages:write"])
    listed = company_mcp.TOOLS["company_external_agents"].handler(ctx, {})
    assert [i["id"] for i in listed["items"]] == [ext["id"]]
    out = company_mcp.TOOLS["company_delegate_external"].handler(ctx, {"external_agent_id": ext["id"],
                                                                      "message": "Khách báo bình bị vỡ, xử lý sao?"})
    assert "Zalo" in out["reply"] and out["context_id"]
    assert asked[-1][0] == rid and asked[-1][1] == f"agent:{rid}:a2a-{out['context_id']}"
    # hỏi tiếp cùng mạch → cùng phiên
    out2 = company_mcp.TOOLS["company_delegate_external"].handler(ctx, {"external_agent_id": ext["id"], "message": "Còn 72 giờ?",
                                                                       "context_id": out["context_id"]})
    assert asked[-1][1] == asked[-2][1] and out2["context_id"] == out["context_id"]
    env.db.expire_all()
    assert env.db.get(ExternalAgent, ext["id"]).calls == 2

    # tắt agent ngoài → tool báo lỗi; tắt mở seat → bên ngoài nhận lỗi
    env.c.patch(f"/api/a2a/external/{ext['id']}", json={"enabled": False}, headers=env.tok("manager"))
    try:
        company_mcp.TOOLS["company_delegate_external"].handler(ctx, {"external_agent_id": ext["id"], "message": "x"})
        raise AssertionError("phải lỗi")
    except company_mcp.ToolError as e:
        assert "đang tắt" in str(e.message if hasattr(e, "message") else e)
    env.c.post(f"/api/a2a/expose/{seat['agent_id']}", json={"enabled": False}, headers=env.tok("manager"))
    assert env.c.get(f"/api/a2a/agents/{rid}/.well-known/agent-card.json").status_code == 404


def test_reply_text_reads_task_artifacts():
    assert a2a.reply_text({"kind": "task", "status": {"state": "completed"},
                           "artifacts": [{"parts": [{"kind": "text", "text": "Kết quả"}]}]}) == "Kết quả"
    assert a2a.reply_text({"kind": "task", "status": {"state": "input-required", "message": {"parts": [{"kind": "text", "text": "Cần mã đơn"}]}}}) == "Cần mã đơn"


def test_remote_agent_error_is_424_and_recorded_on_the_external_agent(env, monkeypatch):
    """M2d.4 (smoke VM): agent ngoài trả lỗi JSON-RPC (vd. -32003 hết trần chi) → 424 kèm lý do, không phải 502
    "máy chủ lỗi"; số lần gọi và lỗi gần nhất vẫn được ghi để UI hiện."""
    ext = ExternalAgent(organization_id=env.org.id, name="Shop bạn", card_url="https://x.example/.well-known/agent-card.json",
                        endpoint_url="https://x.example/a2a", enabled=True)
    env.db.add(ext); env.db.commit()
    monkeypatch.setattr(a2a, "_http", lambda *a, **k: (200, {"jsonrpc": "2.0", "id": "1",
                                                              "error": {"code": -32003, "message": "budget: trần chi ngày"}}))
    r = env.c.post(f"/api/a2a/external/{ext.id}/send", json={"text": "ping"}, headers=env.tok("manager"))
    assert r.status_code == 424 and "-32003" in r.json()["detail"]
    env.db.expire_all()
    got = env.db.get(ExternalAgent, ext.id)
    assert got.calls == 1 and "trần chi" in got.last_error
