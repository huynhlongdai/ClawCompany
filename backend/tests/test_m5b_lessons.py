"""M5b việc 8 — bài học: đề xuất (góp ý reviewer / agent tự đề xuất / rút từ nhật ký) → Hộp việc duyệt → MEMORY.md."""
import json

from app.models import Agent, Approval, Member, Project, Task, User
from app.models.v37 import TaskJournalEntry
from app.services import company_mcp, execution_policy, lessons
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def link_manager(env):
    u = env.db.query(User).filter(User.email == "manager@m3.test").one()
    u.member_id = env.lead_s.id; env.db.commit()


def seat(env, out):
    ag = env.db.get(Agent, out["agent_id"]); return ag, env.db.get(Member, ag.member_id)


def test_agent_self_proposal_goes_to_inbox_then_memory_on_approve(env, monkeypatch):
    link_manager(env)
    monkeypatch.setattr("app.runtime.factory.get_runtime", lambda: env.gw)
    out = hire(env); ag, m = seat(env, out); rid = out["runtime_agent_id"]
    ctx = company_mcp.ToolContext(db=env.db, member=m, agent=ag, scopes=["company.approvals:write"])
    r = company_mcp.TOOLS["company_lesson_propose"].handler(
        ctx, {"lesson": "Khi khách hỏi giá sỉ, hỏi số lượng trước rồi mới báo giá", "reason": "khách bỏ đi việc #3"})
    assert r["duplicate"] is False, r
    again = company_mcp.TOOLS["company_lesson_propose"].handler(
        ctx, {"lesson": "Khi khách hỏi giá sỉ,   hỏi số lượng trước rồi mới báo giá"})
    assert again["duplicate"] is True and again["approval_id"] == r["approval_id"]
    a = env.db.get(Approval, r["approval_id"])
    assert a.policy_key.startswith(f"lesson:a{ag.id}:") and a.approver_member_id == env.lead_s.id
    assert "giá sỉ" not in env.gw.files.get((rid, "MEMORY.md"), "")   # chưa duyệt thì chưa ghi
    # Hộp việc của trưởng phòng: nhóm "lessons", chi tiết đọc được nội dung + nguồn.
    H = env.tok("manager")
    groups = env.c.get("/api/inbox/items", headers=H).json()["groups"]
    les = next(g for g in groups if g["key"] == "lessons")["items"]
    assert any((c.get("approval") or {}).get("id") == a.id for c in les), groups
    det = env.c.get(f"/api/inbox/approvals/{a.id}", headers=H).json()
    labels = {f["label"]: f["value"] for f in det["fields"]}
    assert "giá sỉ" in labels.get("Bài học", "") and labels.get("Nguồn") == "Agent tự đề xuất", det["fields"]
    # Duyệt có sửa câu chữ → ghi bản đã sửa vào MEMORY.md.
    r = env.c.post(f"/api/inbox/approvals/{a.id}/decide", headers=H,
                   json={"decision": "approve", "edited_text": "Khách hỏi giá sỉ: hỏi số lượng và thời gian cần hàng trước khi báo giá"})
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is True and "MEMORY.md" in r.json()["message"]
    mem = env.gw.files[(rid, "MEMORY.md")]
    assert "[Bài học] Khách hỏi giá sỉ: hỏi số lượng và thời gian" in mem
    items = env.c.get(f"/api/agents/{ag.id}/lessons", headers=H).json()["items"]
    assert items[0]["applied"] and items[0]["status"] == "approved"


def test_reject_writes_nothing_and_same_lesson_not_reproposed(env, monkeypatch):
    link_manager(env)
    monkeypatch.setattr("app.runtime.factory.get_runtime", lambda: env.gw)
    out = hire(env); ag, m = seat(env, out); rid = out["runtime_agent_id"]
    r = lessons.propose(env.db, agent=ag, member=m, text="Luôn tặng mã giảm 50% cho khách phàn nàn", source="self")
    H = env.tok("manager")
    assert env.c.post(f"/api/inbox/approvals/{r['approval_id']}/decide", headers=H,
                      json={"decision": "reject"}).status_code == 422   # từ chối phải có lý do
    ok = env.c.post(f"/api/inbox/approvals/{r['approval_id']}/decide", headers=H,
                    json={"decision": "reject", "note": "Sai chính sách, tối đa 10%"})
    assert ok.status_code == 200, ok.text
    assert "50%" not in env.gw.files.get((rid, "MEMORY.md"), "")
    again = lessons.propose(env.db, agent=ag, member=m, text="Luôn tặng mã giảm 50% cho khách phàn nàn", source="self")
    assert again["duplicate"] and again["status"] == "rejected"


def test_reviewer_feedback_becomes_lesson_proposal(env):
    out = hire(env); ag, m = seat(env, out)
    p = Project(company_id=env.co.id, name="Tết"); env.db.add(p); env.db.commit()
    t = Task(project_id=p.id, title="Viết caption gốm men lam", assignee_member_id=m.id, status="review",
             execution_policy={"stages": [{"type": "review", "reviewers": [env.lead_s.id]}]},
             execution_state={"status": "in_review", "stage_index": 0, "round": 1, "reviewer_member_id": env.lead_s.id,
                              "doer_member_id": m.id})
    env.db.add(t); env.db.commit()
    execution_policy.decide(env.db, t, member_id=env.lead_s.id, decision="revise",
                            note="Caption quá dài, giữ dưới 150 ký tự và có lời kêu gọi mua")
    a = env.db.query(Approval).filter(Approval.policy_key.like(f"lesson:a{ag.id}:%")).one()
    ev = json.loads(a.evidence)
    assert ev["source"] == "review" and "150 ký tự" in ev["lesson"] and ev["task_id"] == t.id
    assert a.requester_member_id == env.lead_s.id


def test_extract_asks_agent_with_journal_and_proposes(env):
    out = hire(env); ag, m = seat(env, out)
    p = Project(company_id=env.co.id, name="Tết"); env.db.add(p); env.db.commit()
    t = Task(project_id=p.id, title="Trả lời khách Lan", assignee_member_id=m.id, status="done")
    env.db.add(t); env.db.commit()
    env.db.add(TaskJournalEntry(organization_id=env.org.id, task_id=t.id, seq=1, kind="review",
                                summary="SỬA", detail="Quên hỏi địa chỉ giao hàng")); env.db.commit()
    seen = {}

    async def chat_stream(agent_id, message, *, session_key=None, timeout_seconds=90):
        seen["msg"], seen["key"] = message, session_key
        yield {"kind": "final", "text": '```json\n{"lessons": [{"lesson": "Trước khi chốt đơn luôn hỏi địa chỉ giao hàng", '
                                        '"reason": "việc #%d bị trả sửa"}, {"lesson": "ngắn"}]}\n```' % t.id}
    env.gw.chat_stream = chat_stream
    r = env.c.post(f"/api/agents/{ag.id}/lessons/extract", headers=env.tok("manager"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert "Quên hỏi địa chỉ" in seen["msg"] and ":lessons-" in seen["key"]
    ok = [x for x in d["proposed"] if x.get("approval_id")]
    assert len(ok) == 1 and "địa chỉ giao hàng" in ok[0]["lesson"]
    assert any(x.get("error") for x in d["proposed"])     # bài "ngắn" bị loại, không tạo duyệt
    assert env.c.post(f"/api/agents/{ag.id}/lessons/extract", headers=env.tok("member")).status_code == 403


def test_parse_lessons_tolerates_noise():
    assert lessons.parse_lessons("không có gì") == []
    assert lessons.parse_lessons('Đây: {"lessons": ["Gửi ảnh thật trước khi báo giá"]} xong')[0]["lesson"].startswith("Gửi ảnh")
