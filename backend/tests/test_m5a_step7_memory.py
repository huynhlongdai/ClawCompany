"""Phase B việc 7 — xem/sửa/quên ký ức riêng (MEMORY.md) và bộ nhớ chung theo phạm vi."""
from app.models import Agent, AuditEvent, Member, Project, Task
from app.services import agent_memory, company_mcp
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def mem(env, aid, who="member"):
    r = env.c.get(f"/api/agents/{aid}/memory", headers=env.tok(who))
    assert r.status_code == 200, r.text
    return r.json()


def change(env, aid, **body):
    return env.c.post(f"/api/agents/{aid}/memory", json=body, headers=env.tok("manager"))


def test_parse_render_roundtrip_keeps_headings_and_continuations():
    src = "# MEMORY.md\n\nGhi chú đầu\n\n- 2026-10-01: Khách A thích gốm men lam\n  hay mua dịp Tết\n\n## Bài học\n- Trả lời trước 5 phút\n"
    head, entries = agent_memory.parse(src)
    assert [e["date"] for e in entries] == ["2026-10-01", None]
    assert entries[0]["body"].startswith("Khách A") and "hay mua dịp Tết" in entries[0]["text"]
    assert agent_memory.render(head, entries) == src


def test_add_edit_forget_personal_memory_on_gateway(env):
    out = hire(env); aid, rid = out["agent_id"], out["runtime_agent_id"]
    m = mem(env, aid)
    assert len(m["entries"]) == 1 and "Được tuyển" in m["entries"][0]["text"]
    r = change(env, aid, op="add", text="Khách Lan dị ứng men chì, chỉ giới thiệu men không chì",
               expected_hash=m["hash"])
    assert r.status_code == 200, r.text
    m = r.json(); assert len(m["entries"]) == 2
    assert "Khách Lan dị ứng" in env.gw.files[(rid, "MEMORY.md")]
    new_id = m["entries"][1]["id"]
    r = change(env, aid, op="edit", entry_id=new_id, text="Khách Lan dị ứng men chì", expected_hash=m["hash"])
    assert r.status_code == 200, r.text
    m = r.json(); assert m["entries"][1]["body"] == "Khách Lan dị ứng men chì" and m["entries"][1]["date"]
    # Hash cũ (agent vừa ghi xen) → 409, không đè.
    stale = m["hash"]
    env.gw.files[(rid, "MEMORY.md")] += "- agent tự ghi\n"
    r = change(env, aid, op="forget", entry_id=m["entries"][1]["id"], expected_hash=stale)
    assert r.status_code == 409
    m = mem(env, aid)
    r = change(env, aid, op="forget", entry_id=m["entries"][1]["id"], expected_hash=m["hash"])
    assert r.status_code == 200, r.text
    content = env.gw.files[(rid, "MEMORY.md")]
    assert "dị ứng" not in content and "agent tự ghi" in content and content.startswith("# MEMORY.md")
    ev = env.db.query(AuditEvent).filter(AuditEvent.action == "agent.memory.forget").one()
    assert "dị ứng" not in (ev.payload_json or "") and "fingerprint" in (ev.payload_json or "")
    # Không bị coi là lệch: bản ClawCompany = bản vừa ghi.
    d = env.c.get(f"/api/agents/{aid}/drift", headers=env.tok("member")).json()
    mem_row = next(f for f in d["files"] if f["name"] == "MEMORY.md")
    assert mem_row["status"] in ("in_sync", "synced", "ok"), mem_row


def test_personal_memory_permissions(env):
    out = hire(env); aid = out["agent_id"]
    r = env.c.post(f"/api/agents/{aid}/memory", json={"op": "add", "text": "x"}, headers=env.tok("member"))
    assert r.status_code == 403
    assert env.c.get(f"/api/agents/{aid}/memory", headers=env.tok("other")).status_code == 404
    assert change(env, aid, op="forget", entry_id="khongco").status_code == 404
    assert change(env, aid, op="add", text="   ").status_code == 422


def test_shared_memory_scopes_and_mcp_visibility(env):
    a = hire(env); b = hire(env, name="Minh Khoa", department_id=env.mkt.id)
    seat_a = env.db.get(Agent, a["agent_id"]); seat_b = env.db.get(Agent, b["agent_id"])
    p = Project(company_id=env.co.id, name="Tết 2027"); env.db.add(p); env.db.commit()
    env.db.add(Task(project_id=p.id, title="Việc", assignee_member_id=seat_a.member_id, status="todo")); env.db.commit()
    H = env.tok("manager")
    mk = lambda **b_: env.c.post("/api/shared-memory", json=b_, headers=H)  # noqa: E731
    assert mk(content="Giờ làm 8h–17h", kind="policy").status_code == 200
    assert mk(scope="company", scope_id=env.co.id, content="Gốm Mộc giao hàng miễn phí từ 500k").status_code == 200
    assert mk(scope="department", scope_id=env.sales.id, content="CSKH trả lời trong 5 phút", kind="policy").status_code == 200
    assert mk(scope="department", scope_id=env.mkt.id, content="Marketing chốt lịch đăng thứ Hai").status_code == 200
    r = mk(scope="project", scope_id=p.id, content="Tết 2027: giảm 10% bộ ấm trà", kind="decision")
    assert r.status_code == 200 and r.json()["scope_name"] == "Tết 2027"
    assert mk(scope="agent", scope_id=seat_b.id, content="Khoa phụ trách TikTok").status_code == 200
    assert mk(scope="department", scope_id=99999, content="x").status_code == 404
    assert env.c.post("/api/shared-memory", json={"content": "x"}, headers=env.tok("member")).status_code == 403

    def seen(seat):
        member = env.db.get(Member, seat.member_id)
        ctx = company_mcp.ToolContext(db=env.db, member=member, agent=seat)
        return {i["content"] for i in company_mcp.TOOLS["company_memory_search"].handler(ctx, {})["items"]}

    sa, sb = seen(seat_a), seen(seat_b)
    assert sa == {"Giờ làm 8h–17h", "Gốm Mộc giao hàng miễn phí từ 500k", "CSKH trả lời trong 5 phút",
                  "Tết 2027: giảm 10% bộ ấm trà"}
    assert sb == {"Giờ làm 8h–17h", "Gốm Mộc giao hàng miễn phí từ 500k", "Marketing chốt lịch đăng thứ Hai",
                  "Khoa phụ trách TikTok"}
    member_a = env.db.get(Member, seat_a.member_id)
    hit = company_mcp.TOOLS["company_memory_search"].handler(
        company_mcp.ToolContext(db=env.db, member=member_a, agent=seat_a), {"query": "ấm trà"})
    assert [i["content"] for i in hit["items"]] == ["Tết 2027: giảm 10% bộ ấm trà"]

    items = env.c.get("/api/shared-memory?scope=department", headers=env.tok("member")).json()["items"]
    assert len(items) == 2
    mid = items[0]["id"]
    r = env.c.patch(f"/api/shared-memory/{mid}", json={"content": "Sửa rồi", "importance": 5}, headers=H)
    assert r.status_code == 200 and r.json()["importance"] == 5
    assert env.c.delete(f"/api/shared-memory/{mid}", headers=H).json()["forgotten"]
    assert env.c.delete(f"/api/shared-memory/{mid}", headers=H).status_code == 404
    assert env.c.get("/api/shared-memory?q=Sửa", headers=env.tok("member")).json()["items"] == []
    opts = env.c.get("/api/shared-memory/options", headers=env.tok("member")).json()
    assert {s["key"] for s in opts["scopes"]} == set(agent_memory.SCOPES) and opts["projects"]
    assert env.c.get("/api/shared-memory", headers=env.tok("other")).json()["items"] == []
