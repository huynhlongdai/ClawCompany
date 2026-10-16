"""M3i (P1) — họp & quyết định: biên bản duyệt xong khoá sửa + thành hồ sơ meeting_minutes (Luật DN Đ11 k1 d); 3 việc sau họp
thành 3 task đúng người; quyết định có người quyết + căn cứ thẩm quyền (ma trận: người không đủ quyền → 409), thay thế quyết định
cũ; company_decision_log trả quyết định MỚI NHẤT đang hiệu lực, không lộ công ty khác, tài liệu liên kết nhận cờ cần cập nhật."""
from datetime import timedelta

from app.models import Agent, Decision, InboxItem, KnowledgeDocument, Member, Task
from app.services import company_mcp, meetings
from tests.test_m2b_company_foundation import E  # noqa: F401  (fixture)
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)
from tests.test_m3a_document_library import _seats, mk


def test_minutes_lock_after_approval_and_three_actions_become_three_tasks(E):
    thao = _seats(E)
    r = E.c.post("/api/team/meetings", json={"company_id": E.co.id, "kind": "weekly", "title": "Họp tuần 42",
                                            "held_at": "2026-10-16T02:00:00", "attendee_ids": [E.boss.id, E.lead_s.id, thao.id],
                                            "agenda": "1. Doanh số tuần\n2. Đổi nhà vận chuyển",
                                            "notes": "Doanh số tăng 8%. Thống nhất thử GHN 1 tháng."}, headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["status"] == "draft" and len(m["attendees"]) == 3
    assert E.c.post("/api/team/meetings", json={"company_id": E.co.id, "title": "x"}, headers=E.tok("member")).status_code == 403
    # 3 việc sau họp → 3 task đúng người + thẻ Hộp việc
    acts = E.c.post(f"/api/team/meetings/{m['id']}/actions", json={"items": [
        {"title": "Ký thử GHN", "assignee_member_id": E.boss.id, "due_date": "2026-10-20"},
        {"title": "Báo giá vận chuyển mới cho khách", "assignee_member_id": E.lead_s.id},
        {"title": "Cập nhật chính sách giao hàng", "assignee_member_id": thao.id, "due_date": "2026-10-23"}]}, headers=E.tok("manager"))
    assert acts.status_code == 200, acts.text
    rows = acts.json()["actions"]
    assert len(rows) == 3 and len({a["task_id"] for a in rows}) == 3
    for a, who in zip(rows, (E.boss.id, E.lead_s.id, thao.id)):
        assert E.db.get(Task, a["task_id"]).assignee_member_id == who
    assert E.db.get(Task, rows[0]["task_id"]).due_at is not None
    assert E.db.query(InboxItem).filter(InboxItem.item_type == "meeting_action").count() >= 3
    assert E.c.post(f"/api/team/meetings/{m['id']}/actions", json={"items": [{"title": "không người"}]},
                    headers=E.tok("manager")).json()["detail"]["error"] == "assignee_required"
    # biên bản nháp tất định từ ghi chú
    d = E.c.post(f"/api/team/meetings/{m['id']}/draft-minutes", headers=E.tok("manager")).json()
    assert "BIÊN BẢN" in d["minutes"] and "Thống nhất thử GHN" in d["minutes"] and "Ký thử GHN" in d["minutes"]
    # gửi duyệt: chủ toạ (người tạo = Chị Thảo) là người → chị duyệt; người khác không duyệt được
    s = E.c.post(f"/api/team/meetings/{m['id']}/submit", headers=E.tok("manager")).json()
    assert s["status"] == "in_review" and s["approver_member_id"] == thao.id
    assert E.c.patch(f"/api/team/meetings/{m['id']}", json={"minutes": "sửa"}, headers=E.tok("manager")).json()["detail"]["error"] == "minutes_in_review"
    assert E.c.post(f"/api/team/meetings/{m['id']}/decide", json={"decision": "approved"}, headers=E.tok("member")).status_code == 403
    ok = E.c.post(f"/api/team/meetings/{m['id']}/decide", json={"decision": "approved"}, headers=E.tok("manager"))
    assert ok.status_code == 200, ok.text
    out = ok.json()
    assert out["status"] == "approved" and out["locked"] and out["minutes_document"]
    doc = E.db.get(KnowledgeDocument, out["minutes_document"]["id"])
    assert doc.doc_type == "meeting_minutes" and doc.doc_class == "record" and doc.company_id == E.co.id
    r = E.c.patch(f"/api/team/meetings/{m['id']}", json={"minutes": "sửa lén"}, headers=E.tok("owner"))
    assert r.status_code == 409 and r.json()["detail"]["error"] == "minutes_locked"
    assert E.c.post(f"/api/team/meetings/{m['id']}/draft-minutes", headers=E.tok("manager")).status_code == 409
    assert E.c.get(f"/api/team/meetings/{m['id']}", headers=E.tok("other")).status_code == 404


def test_decisions_authority_supersede_and_agent_reads_latest_in_effect(E):
    thao = _seats(E)
    from app.services import authority
    authority.seed_defaults(E.db, E.org.id, E.co.id)
    pol = mk(E, title="Chính sách giao hàng", doc_type="policy", content="Giao hàng trong 3 ngày làm việc toàn quốc. " * 3).json()
    # căn cứ: thiếu → 422; theo ma trận "contract" (chủ) — nhân viên quyết → 409; chủ quyết → được
    base = {"company_id": E.co.id, "title": "Đổi đơn vị vận chuyển sang GHN", "body": "Từ 01/11 dùng GHN cho mọi đơn nội thành."}
    assert E.c.post("/api/team/decision-log", json=base, headers=E.tok("manager")).json()["detail"]["error"] == "basis_required"
    r = E.c.post("/api/team/decision-log", json={**base, "action_type": "contract", "decided_by_member_id": thao.id}, headers=E.tok("manager"))
    assert r.status_code == 409 and r.json()["detail"]["error"] == "decider_lacks_authority"
    a = hire(E)
    ag = E.db.get(Agent, a["agent_id"])
    r = E.c.post("/api/team/decision-log", json={**base, "authority_basis": "x" * 10, "decided_by_member_id": ag.member_id}, headers=E.tok("manager"))
    assert r.json()["detail"]["error"] == "decider_must_be_human"
    d1 = E.c.post("/api/team/decision-log", json={**base, "action_type": "contract", "decided_by_member_id": E.boss.id,
                                                 "effective_from": "2026-10-01", "linked": {"doc_ids": [pol["id"]]}},
                  headers=E.tok("manager")).json()
    assert d1["number"].startswith("QĐ-") and d1["status"] == "decided" and "Ma trận thẩm quyền" in d1["authority_basis"]
    assert d1["authority_rule_id"] and d1["docs_flagged"] == 1
    # thay thế: d2 thay d1 → d1 superseded, hết hiệu lực từ ngày d2
    d2 = E.c.post("/api/team/decision-log", json={"company_id": E.co.id, "title": "Vận chuyển: GHN + Viettel Post",
                                                 "body": "Từ 15/10 dùng GHN nội thành, Viettel Post ngoại tỉnh.",
                                                 "authority_basis": "Điều lệ công ty Đ12: giám đốc quyết định vận hành",
                                                 "decided_by_member_id": E.boss.id, "supersedes_id": d1["id"], "effective_from": "2026-10-15"},
                  headers=E.tok("manager")).json()
    old = E.db.get(Decision, d1["id"]); E.db.refresh(old)
    assert old.status == "superseded" and old.effective_to.isoformat() == "2026-10-15"
    assert E.c.post("/api/team/decision-log", json={**base, "authority_basis": "x" * 10, "supersedes_id": d1["id"]},
                    headers=E.tok("manager")).json()["detail"]["error"] == "not_in_effect"
    # quyết định ẩn với agent + quyết định của công ty khác
    E.c.post("/api/team/decision-log", json={"company_id": E.co.id, "title": "Lương thưởng quý", "body": "Thưởng 1 tháng lương.",
                                            "authority_basis": "Chủ sở hữu quyết", "decided_by_member_id": E.boss.id, "agent_visible": False},
             headers=E.tok("owner"))
    from app.models import Company
    other = Company(organization_id=E.org.id, name="Công ty khác", status="active"); E.db.add(other); E.db.commit()
    E.db.add(Decision(organization_id=E.org.id, company_id=other.id, title="Vận chuyển công ty khác", status="decided", number="QĐ-X-1",
                      body="GHTK", effective_from=meetings.today_vn() - timedelta(days=1))); E.db.commit()
    ctx = company_mcp.ToolContext(db=E.db, member=E.db.get(Member, ag.member_id), agent=ag)
    ok, res = company_mcp.call(ctx, "company_decision_log", {"query": "Vận chuyển"})
    assert ok, res
    nums = [x["number"] for x in res["decisions"]]
    assert nums == [d2["number"]], res                       # mới nhất đang hiệu lực; d1 thay thế, công ty khác, ẩn → không
    assert res["decisions"][0]["decided_by"] == E.boss.name and res["decisions"][0]["cite"].startswith("[QĐ:")
    ok, res = company_mcp.call(ctx, "company_decision_log", {"query": "Lương"})
    assert res["decisions"] == []
    ok, res = company_mcp.call(ctx, "company_decision_log", {"query": "Vận chuyển", "include_history": True})
    assert {x["status"] for x in res["decisions"]} == {"decided", "superseded"}
    # huỷ cần lý do; huỷ xong agent không thấy
    assert E.c.post(f"/api/team/decision-log/{d2['id']}/revoke", json={"note": ""}, headers=E.tok("manager")).status_code == 422
    assert E.c.post(f"/api/team/decision-log/{d2['id']}/revoke", json={"note": "Hợp đồng GHN không ký được"}, headers=E.tok("manager")).json()["status"] == "revoked"
    assert company_mcp.call(ctx, "company_decision_log", {"query": "Vận chuyển"})[1]["decisions"] == []
    lst = E.c.get(f"/api/team/meetings?company_id={E.co.id}", headers=E.tok("member")).json()
    assert lst["counts"]["decisions_in_effect"] == 1 and len(lst["decisions"]) == 3      # d1 thay thế, d2 huỷ, "Lương thưởng" còn hiệu lực; công ty khác không


def test_org_level_seat_can_chair_and_decide_but_other_company_member_cannot(E):
    """Lỗi thật thấy trên VM: chủ tổ chức ngồi ghế cấp tổ chức (members.company_id NULL) — trước bản sửa bị 404 khi làm
    người quyết / chủ toạ ở công ty con. Thành viên của công ty KHÁC vẫn bị chặn."""
    _seats(E)
    from app.models import Company
    org_seat = Member(organization_id=E.org.id, company_id=None, name="Chủ tổ chức", member_type="human", role="Owner")
    other = Company(organization_id=E.org.id, name="Công ty khác", status="active"); E.db.add_all([org_seat, other]); E.db.commit()
    stranger = Member(organization_id=E.org.id, company_id=other.id, name="Người công ty khác", member_type="human")
    E.db.add(stranger); E.db.commit()
    base = {"company_id": E.co.id, "title": "Mở cửa hàng thứ hai", "body": "Mở chi nhánh Q3.", "authority_basis": "Chủ sở hữu quyết"}
    r = E.c.post("/api/team/decision-log", json={**base, "decided_by_member_id": org_seat.id}, headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    assert E.c.post("/api/team/decision-log", json={**base, "decided_by_member_id": stranger.id}, headers=E.tok("manager")).status_code == 404
    m = E.c.post("/api/team/meetings", json={"company_id": E.co.id, "title": "Họp chủ sở hữu", "chair_member_id": org_seat.id,
                                            "attendee_ids": [org_seat.id]}, headers=E.tok("manager"))
    assert m.status_code == 200 and m.json()["chair"] == "Chủ tổ chức"
    assert any(x["id"] == org_seat.id for x in E.c.get(f"/api/team/meetings?company_id={E.co.id}", headers=E.tok("member")).json()["members"])
