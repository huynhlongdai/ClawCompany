"""M2d.3 — ngày lễ chỉ để tính hạn pháp lý: agent làm mọi ngày nên việc tuân thủ nhắc + đặt hạn theo ngày luật
ghi (không dời cuối tuần/lễ); hạn pháp lý (ngày làm việc liền kề sau, khoản 14 Điều 3 NĐ 252/2026) là trường
phụ; lịch nghỉ là dữ liệu sửa được theo năm, gieo 2026/2027, ngày chưa công bố gắn "cần xác nhận"."""
from datetime import date, datetime

from app.models import Task
from app.models.company_ops import ComplianceDeadline, ComplianceRule, PublicHoliday
from app.services import compliance_calendar as cc
from app.services import holidays
from tests.test_m2b_company_foundation import E, mkpos  # noqa: F401  (fixture)
from tests.test_m2c_compliance import _company
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def test_legal_due_skips_weekends_holidays_and_respects_makeup_workdays(E):
    lg = lambda d: holidays.legal_due(E.db, E.org.id, d)  # noqa: E731
    # Q1/2026: 30/4 (lễ) → 1/5 (lễ) → 2–3/5 cuối tuần → thứ Hai 4/5 (khớp hướng dẫn của cơ quan thuế)
    assert lg(date(2026, 4, 30)) == (date(2026, 5, 4), "Ngày Chiến thắng 30/4, Quốc tế Lao động 1/5, cuối tuần")
    assert lg(date(2026, 2, 20))[0] == date(2026, 2, 23)                  # GTGT tháng 1/2026 rơi vào Tết
    assert lg(date(2026, 10, 31)) == (date(2026, 11, 2), "cuối tuần")
    assert lg(date(2026, 10, 20)) == (date(2026, 10, 20), "")
    assert lg(date(2026, 8, 22))[0] == date(2026, 8, 22)                  # thứ Bảy làm bù = ngày làm việc
    assert lg(date(2027, 2, 6))[0] == date(2027, 2, 11)                   # Tết Đinh Mùi 4–10/2/2027
    rows = {h.day: h for h in E.db.query(PublicHoliday).filter(PublicHoliday.organization_id == E.org.id).all()}
    assert rows[date(2027, 4, 16)].status == "needs_confirmation"         # Giỗ Tổ 2027 chưa công bố
    assert rows[date(2026, 2, 16)].status == "official" and rows[date(2026, 2, 16)].source_url


def test_reminder_and_task_due_follow_calendar_deadline_not_legal_one(E):
    acc, ktv = _company(E, vat_period="quarterly", pit_period="quarterly", has_employees=True)
    cc.generate(E.db, E.org.id, E.co.id, today=date(2026, 10, 16))
    d = (E.db.query(ComplianceDeadline).join(ComplianceRule, ComplianceRule.id == ComplianceDeadline.rule_id)
         .filter(ComplianceRule.key == "vat_quarterly", ComplianceDeadline.period_label == "Q3/2026").one())
    assert d.due_date == date(2026, 10, 31) and d.legal_due_date == date(2026, 11, 2)
    # nhắc trước 7 ngày tính từ 31/10 (thứ Bảy) → 24/10, không phải từ hạn pháp lý 2/11
    assert cc.remind(E.db, E.org.id, E.co.id, today=date(2026, 10, 23))["reminded"] == 0
    assert cc.remind(E.db, E.org.id, E.co.id, today=date(2026, 10, 24))["reminded"] >= 1
    E.db.refresh(d)
    t = E.db.get(Task, d.task_id)
    assert t.due_at == datetime(2026, 10, 31, 10, 0)                       # 17:00 giờ VN ngày 31/10 — làm cả thứ Bảy
    assert "hạn 31/10/2026" in t.title and "Hạn pháp lý:** 02/11/2026" in t.description
    got = E.c.get(f"/api/team/compliance?company_id={E.co.id}", headers=E.tok("member")).json()
    row = next(x for x in got["deadlines"] if x["id"] == d.id)
    assert row["due_date"] == "2026-10-31" and row["legal_due_date"] == "2026-11-02" and row["legal_shift_reason"] == "cuối tuần"
    assert "252/2026" in got["weekend_note"] and got["holidays"]["2026"]


def test_editing_holidays_recomputes_legal_due_only_and_is_admin_scoped(E):
    _company(E, vat_period="quarterly", pit_period="quarterly", has_employees=True)
    cc.generate(E.db, E.org.id, E.co.id, today=date(2026, 10, 16))
    lst = E.c.get("/api/team/compliance/holidays?year=2026", headers=E.tok("member")).json()
    assert any(h["name"] == "Ngày Văn hóa Việt Nam" for h in lst["items"]) and "252/2026" in lst["rule"]
    body = {"day": "2026-11-02", "name": "Nghỉ đột xuất (thử)", "kind": "holiday", "status": "needs_confirmation"}
    assert E.c.post("/api/team/compliance/holidays", json=body, headers=E.tok("manager")).status_code == 403
    r = E.c.post("/api/team/compliance/holidays", json=body, headers=E.tok("owner"))
    assert r.status_code == 200 and r.json()["legal_due_updated"] >= 1
    d = (E.db.query(ComplianceDeadline).filter(ComplianceDeadline.period_label == "Q3/2026").first())
    E.db.refresh(d)
    assert d.due_date == date(2026, 10, 31) and d.legal_due_date == date(2026, 11, 3)
    assert E.c.post("/api/team/compliance/holidays", json=body, headers=E.tok("owner")).status_code == 409
    assert E.c.post("/api/team/compliance/holidays", json={**body, "day": "31/10"}, headers=E.tok("owner")).status_code == 422
    assert E.c.delete(f"/api/team/compliance/holidays/{r.json()['id']}", headers=E.tok("other")).status_code in (403, 404)
    E.c.delete(f"/api/team/compliance/holidays/{r.json()['id']}", headers=E.tok("owner"))
    E.db.refresh(d)
    assert d.legal_due_date == date(2026, 11, 2)
