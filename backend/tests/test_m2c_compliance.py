"""M2c D7 — lịch tuân thủ VN: luật là dữ liệu có căn cứ pháp lý, hạn sinh theo loại hình + kỳ kê khai, dời
cuối tuần, lệ phí môn bài đã bãi bỏ không sinh hạn, nhắc trước N ngày vào Hộp việc + giao việc cho chức danh
kế toán, nộp xong (việc xong) thì lịch đánh dấu đã nộp. ORM thật trên SQLite."""
from datetime import date

from app.models import Member, Task
from app.models.company_ops import ComplianceDeadline, ComplianceRule
from app.models.extended import InboxItem
from app.services import compliance_calendar as cc, task_lifecycle as lifecycle
from tests.test_m2b_company_foundation import E, mkpos  # noqa: F401  (fixture)
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def _company(E, entity="tnhh_1tv", **settings):
    assert E.c.put("/api/team/company-profile", json={"company_id": E.co.id, "entity_type": entity},
                   headers=E.tok("owner")).status_code == 200
    r = E.c.put("/api/team/compliance/settings", json={"company_id": E.co.id, **settings}, headers=E.tok("owner"))
    assert r.status_code == 200, r.text
    assert E.c.post("/api/team/compliance/seed", json={"company_id": E.co.id}, headers=E.tok("owner")).json()["created"] == 9
    acc = mkpos(E, title="Kế toán tổng hợp", department_id=E.sales.id)
    ktv = Member(organization_id=E.org.id, company_id=E.co.id, department_id=E.sales.id, name="Chị Kế Toán",
                 member_type="human", role="Kế toán", manager_id=E.boss.id, status="active")
    E.db.add(ktv); E.db.commit()
    E.c.post(f"/api/team/positions/{acc['id']}/seats", json={"member_id": ktv.id}, headers=E.tok("manager"))
    return acc, ktv


def test_period_math_weekend_shift_and_quarter_ends():
    r = ComplianceRule(name="x", frequency="monthly", due_rule={"type": "next_month_day", "day": 20})
    got = cc.periods(r, date(2026, 10, 1), date(2026, 12, 31))
    assert got == [("09/2026", date(2026, 10, 20)), ("10/2026", date(2026, 11, 20)), ("11/2026", date(2026, 12, 20))]
    q = ComplianceRule(name="q", frequency="quarterly", due_rule={"type": "next_quarter_first_month_end"})
    assert cc.periods(q, date(2026, 10, 1), date(2027, 2, 1)) == [("Q3/2026", date(2026, 10, 31)), ("Q4/2026", date(2027, 1, 31))]
    y = ComplianceRule(name="y", frequency="yearly", due_rule={"type": "months_after_year_end", "months": 3})
    assert cc.periods(y, date(2026, 10, 1), date(2027, 6, 1)) == [("2026", date(2027, 3, 31))]
    b = ComplianceRule(name="b", frequency="monthly", due_rule={"type": "next_month_end"})
    assert cc.periods(b, date(2026, 10, 1), date(2026, 11, 1))[0] == ("09/2026", date(2026, 10, 31))
    assert cc.shift_weekend(date(2026, 10, 31)) == date(2026, 11, 2)       # thứ Bảy → thứ Hai
    assert cc.shift_weekend(date(2026, 12, 20)) == date(2026, 12, 21)      # Chủ nhật → thứ Hai
    assert cc.shift_weekend(date(2026, 10, 20)) == date(2026, 10, 20)


def test_deadlines_follow_profile_and_mon_bai_is_abolished(E):
    acc, ktv = _company(E, vat_period="quarterly", pit_period="quarterly", has_employees=True)
    rules = {r["key"]: r for r in E.c.get(f"/api/team/compliance?company_id={E.co.id}", headers=E.tok("member")).json()["rules"]}
    assert all(r["legal_basis"] for r in rules.values())                    # mọi luật mặc định có căn cứ
    assert "198/2025/QH15" in rules["mon_bai"]["legal_basis"] and rules["mon_bai"]["enabled"] is False
    assert "41/2024/QH15" in rules["bhxh_monthly"]["legal_basis"] and "252/2026" in rules["vat_monthly"]["legal_basis"]
    assert rules["hkd_quarterly"]["needs_review"] is True and rules["hkd_quarterly"]["applies"] is False
    assert rules["vat_quarterly"]["applies"] and not rules["vat_monthly"]["applies"]
    out = cc.generate(E.db, E.org.id, E.co.id, today=date(2026, 10, 16))
    assert out["created"] > 0 and out["assignee"] == "Kế toán tổng hợp"
    got = E.c.get(f"/api/team/compliance?company_id={E.co.id}", headers=E.tok("member")).json()
    by = {(d["name"], d["period_label"]): d for d in got["deadlines"]}
    q3 = by[("Tờ khai thuế GTGT quý", "Q3/2026")]
    assert q3["statutory_date"] == "2026-10-31" and q3["due_date"] == "2026-11-02" and q3["shifted"] is True
    assert by[("Đóng BHXH, BHYT, BHTN tháng", "09/2026")]["due_date"] == "2026-11-02"
    assert by[("Tờ khai khấu trừ thuế TNCN quý", "Q3/2026")]["assignee"] == "Chị Kế Toán"
    assert not any(d["name"].startswith("Lệ phí môn bài") for d in got["deadlines"])
    assert not any(d["name"] == "Tờ khai thuế GTGT tháng" for d in got["deadlines"])
    assert "không phải tư vấn pháp lý" in got["disclaimer"]
    # đổi sang khai tháng → hạn tháng xuất hiện, chạy lại không nhân đôi
    E.c.put("/api/team/compliance/settings", json={"company_id": E.co.id, "vat_period": "monthly"}, headers=E.tok("owner"))
    cc.generate(E.db, E.org.id, E.co.id, today=date(2026, 10, 16))
    again = cc.generate(E.db, E.org.id, E.co.id, today=date(2026, 10, 16))
    assert again["created"] == 0
    names = {(d.rule_id, d.period_label) for d in E.db.query(ComplianceDeadline).all()}
    vat_m = E.db.query(ComplianceRule).filter(ComplianceRule.key == "vat_monthly").one()
    assert (vat_m.id, "09/2026") in names


def test_reminder_lands_in_inbox_assigns_accountant_and_task_done_marks_filed(E):
    acc, ktv = _company(E, vat_period="monthly", has_employees=False)
    cc.generate(E.db, E.org.id, E.co.id, today=date(2026, 10, 16))
    out = cc.remind(E.db, E.org.id, E.co.id, today=date(2026, 10, 16))
    assert out["reminded"] == 1                                             # chỉ GTGT 09/2026 (hạn 20/10, nhắc trước 7 ngày)
    d = E.db.query(ComplianceDeadline).filter(ComplianceDeadline.period_label == "09/2026").one()
    t = E.db.get(Task, d.task_id)
    assert t.assignee_member_id == ktv.id and "hạn 20/10/2026 (còn 4 ngày)" in t.title and "Căn cứ" in t.description
    assert t.due_at is not None and t.priority == "medium"
    items = E.db.query(InboxItem).filter(InboxItem.item_type == "compliance_due").all()
    assert {i.recipient_member_id for i in items} >= {ktv.id}
    assert cc.remind(E.db, E.org.id, E.co.id, today=date(2026, 10, 17))["reminded"] == 0     # mỗi hạn nhắc một lần
    for to in ("todo", "in_progress", "review", "done"):
        lifecycle.transition(E.db, t, to, system=True, reason="đã nộp tờ khai")
    got = E.c.get(f"/api/team/compliance?company_id={E.co.id}", headers=E.tok("member")).json()
    row = next(x for x in got["deadlines"] if x["id"] == d.id)
    assert row["status"] == "done" and row["overdue"] is False


def test_custom_license_rule_validation_and_permissions(E):
    _company(E)
    r = E.c.post("/api/team/compliance/rules", json={"company_id": E.co.id, "name": "Gia hạn giấy phép bán lẻ rượu",
                                                      "due_rule": {"type": "fixed_date", "date": "2026-12-01"}, "remind_days": 60},
                 headers=E.tok("manager"))
    assert r.status_code == 200 and r.json()["needs_review"] is True      # không ghi căn cứ → cần kiểm tra
    lic = r.json()
    cc.generate(E.db, E.org.id, E.co.id, today=date(2026, 10, 16))
    assert cc.remind(E.db, E.org.id, E.co.id, today=date(2026, 10, 16))["reminded"] >= 1
    d = E.db.query(ComplianceDeadline).filter(ComplianceDeadline.rule_id == lic["id"]).one()
    assert d.period_label == "01/12/2026" and d.reminded_at is not None
    bad = E.c.post("/api/team/compliance/rules", json={"company_id": E.co.id, "name": "x",
                                                        "due_rule": {"type": "fixed_date", "date": "01/12/2026"}}, headers=E.tok("manager"))
    assert bad.status_code == 422 and "YYYY-MM-DD" in bad.json()["detail"]
    r = E.c.put("/api/team/compliance/settings", json={"company_id": E.co.id, "vat_period": "yearly"}, headers=E.tok("owner"))
    assert r.status_code == 422 and "50 tỷ" in r.json()["detail"]
    assert E.c.put("/api/team/compliance/settings", json={"company_id": E.co.id}, headers=E.tok("manager")).status_code == 403
    # tắt một luật → các hạn chưa nhắc biến mất
    vat = E.db.query(ComplianceRule).filter(ComplianceRule.key == "vat_quarterly").one()
    assert E.c.patch(f"/api/team/compliance/rules/{vat.id}", json={"enabled": False}, headers=E.tok("owner")).status_code == 200
    assert E.db.query(ComplianceDeadline).filter(ComplianceDeadline.rule_id == vat.id, ComplianceDeadline.task_id.is_(None)).count() == 0
