"""M2c D7 — Lịch tuân thủ Việt Nam: hạn khai thuế GTGT/TNCN (tháng/quý), quyết toán năm + báo cáo tài
chính, đóng BHXH, gia hạn giấy phép… sinh từ hồ sơ công ty (loại hình, kỳ kê khai, có lao động), nhắc trước
N ngày vào Hộp việc và giao cho chức danh kế toán (một task trong dự án "Tuân thủ").

Luật là DỮ LIỆU (``compliance_rules``) — mỗi công ty có bản sao sửa được, mỗi luật ghi căn cứ pháp lý. Đây là
lịch THAM KHẢO, không phải tư vấn pháp lý: luật đổi thì sửa luật trong bảng; luật nào chưa chắc thì
``needs_review`` và giao diện nói rõ. Đối chiếu ngày 16/10/2026:

* Hạn khai tháng/quý/quyết toán: Điều 44 Luật Quản lý thuế 38/2019/QH14 (tới 30/6/2026); từ 1/7/2026 Luật
  Quản lý thuế 2025 giao Chính phủ quy định → Điều 10 Nghị định 252/2026/NĐ-CP giữ nguyên các mốc (tháng: ngày
  20 tháng sau; quý: ngày cuối tháng đầu quý sau; quyết toán: ngày cuối tháng thứ 3 sau kỳ).
* BHXH: khoản 4 Điều 34 Luật BHXH 41/2024/QH15 (hiệu lực 1/7/2025) — chậm nhất ngày cuối tháng tiếp theo.
* Lệ phí môn bài: chấm dứt thu từ 1/1/2026 (khoản 7 Điều 10 Nghị quyết 198/2025/QH15; Nghị định 362/2025/NĐ-CP
  bãi bỏ NĐ 139/2016 và 22/2020) → luật được giữ ở trạng thái TẮT để tra cứu.
* Hạn rơi vào thứ Bảy/Chủ nhật → dời sang thứ Hai (Điều 86 Thông tư 80/2021/TT-BTC, khoản 5 Điều 148 BLDS
  2015). Ngày lễ/Tết KHÔNG được tính (ghi rõ trong ghi chú) — kế toán kiểm tra lịch nghỉ lễ.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Company, Member, Project, Task
from app.models.company_foundation import CompanyProfile, Position
from app.models.company_ops import ComplianceDeadline, ComplianceRule
from app.services import holidays

DISCLAIMER = ("Lịch tham khảo do hệ thống tính từ căn cứ pháp lý ghi ở từng mục — không phải tư vấn pháp lý. "
              "Đối chiếu với kế toán hoặc cơ quan thuế trước khi nộp; ngày lễ chưa được tính.")
HORIZON_DAYS = 120
FREQUENCIES = ("monthly", "quarterly", "yearly", "once")
CATEGORIES = ("tax", "social", "report", "license")
DUE_TYPES = ("next_month_day", "next_month_end", "next_quarter_first_month_end", "months_after_year_end", "fixed_date")
COMPANY_TYPES = ["dntn", "tnhh_1tv", "tnhh_2tv", "co_phan", "hop_danh"]
QLT = ("Điều 44 Luật Quản lý thuế 38/2019/QH14 (tới 30/6/2026); từ 1/7/2026: Luật Quản lý thuế 2025 và "
       "Điều 10 Nghị định 252/2026/NĐ-CP")
WEEKEND_NOTE = ("Agent làm cả ngày nghỉ: việc tuân thủ nhắc và đặt hạn theo đúng ngày luật ghi (hạn theo lịch). Nếu ngày đó "
                "rơi vào cuối tuần/lễ/Tết thì luật cho nộp tới ngày làm việc liền kề sau — hiển thị là \"hạn pháp lý\" "
                "(khoản 14 Điều 3 NĐ 252/2026/NĐ-CP; trước 1/7/2026: Điều 86 TT 80/2021/TT-BTC).")

DEFAULT_RULES = [
    dict(key="vat_monthly", name="Tờ khai thuế GTGT tháng", category="tax", entity_types=COMPANY_TYPES,
         condition={"vat_period": "monthly"}, frequency="monthly", due_rule={"type": "next_month_day", "day": 20},
         legal_basis=f"{QLT}, khoản 2: chậm nhất ngày 20 của tháng tiếp theo.", remind_days=7),
    dict(key="vat_quarterly", name="Tờ khai thuế GTGT quý", category="tax", entity_types=COMPANY_TYPES,
         condition={"vat_period": "quarterly"}, frequency="quarterly", due_rule={"type": "next_quarter_first_month_end"},
         legal_basis=f"{QLT}, khoản 3: chậm nhất ngày cuối cùng của tháng đầu quý tiếp theo.", remind_days=7),
    dict(key="pit_monthly", name="Tờ khai khấu trừ thuế TNCN tháng", category="tax", entity_types=COMPANY_TYPES,
         condition={"has_employees": True, "pit_period": "monthly"}, frequency="monthly",
         due_rule={"type": "next_month_day", "day": 20},
         legal_basis=f"{QLT}, khoản 2. Chỉ khi tháng có khấu trừ thuế TNCN.", remind_days=7),
    dict(key="pit_quarterly", name="Tờ khai khấu trừ thuế TNCN quý", category="tax", entity_types=COMPANY_TYPES,
         condition={"has_employees": True, "pit_period": "quarterly"}, frequency="quarterly",
         due_rule={"type": "next_quarter_first_month_end"},
         legal_basis=f"{QLT}, khoản 3. Chỉ khi quý có khấu trừ thuế TNCN.", remind_days=7),
    dict(key="cit_finalization", name="Quyết toán thuế TNDN năm + Báo cáo tài chính", category="report",
         entity_types=COMPANY_TYPES, condition={}, frequency="yearly", due_rule={"type": "months_after_year_end", "months": 3},
         legal_basis=f"{QLT}, khoản 5 điểm a: chậm nhất ngày cuối cùng của tháng thứ 3 kể từ ngày kết thúc năm tài chính "
                     "(năm tài chính theo năm dương lịch). Báo cáo tài chính năm nộp kèm hồ sơ quyết toán.",
         remind_days=30),
    dict(key="pit_finalization", name="Quyết toán thuế TNCN (tổ chức trả thu nhập)", category="report",
         entity_types=COMPANY_TYPES, condition={"has_employees": True}, frequency="yearly",
         due_rule={"type": "months_after_year_end", "months": 3},
         legal_basis=f"{QLT}, khoản 5 điểm a: ngày cuối cùng của tháng thứ 3 kể từ khi kết thúc năm dương lịch.", remind_days=30),
    dict(key="bhxh_monthly", name="Đóng BHXH, BHYT, BHTN tháng", category="social", entity_types=[],
         condition={"has_employees": True}, frequency="monthly", due_rule={"type": "next_month_end"},
         legal_basis="Khoản 4 Điều 34 Luật Bảo hiểm xã hội 41/2024/QH15 (hiệu lực 1/7/2025): phương thức đóng hằng tháng — "
                     "chậm nhất ngày cuối cùng của tháng tiếp theo.", remind_days=7),
    dict(key="hkd_quarterly", name="Hộ kinh doanh: khai thuế GTGT, TNCN quý (mẫu 01/CNKD)", category="tax",
         entity_types=["ho_kinh_doanh"], condition={}, frequency="quarterly", due_rule={"type": "next_quarter_first_month_end"},
         legal_basis="Khoản 6 Điều 10 Nghị quyết 198/2025/QH15: hộ kinh doanh không áp dụng thuế khoán từ 1/1/2026, khai theo "
                     "pháp luật quản lý thuế; hạn quý theo Điều 10 Nghị định 252/2026/NĐ-CP.",
         note="Doanh thu năm trên 50 tỷ đồng khai theo tháng. Cần kiểm tra với cơ quan thuế quản lý trực tiếp.",
         needs_review=True, remind_days=10),
    dict(key="mon_bai", name="Lệ phí môn bài (đã bãi bỏ)", category="tax", entity_types=[], condition={}, frequency="yearly",
         due_rule={"type": "months_after_year_end", "months": 1}, enabled=False, effective_to=date(2025, 12, 31),
         legal_basis="Khoản 7 Điều 10 Nghị quyết 198/2025/QH15: chấm dứt thu, nộp lệ phí môn bài từ 1/1/2026; khoản 4 Điều 6 "
                     "Nghị định 362/2025/NĐ-CP bãi bỏ Nghị định 139/2016/NĐ-CP và 22/2020/NĐ-CP; Công văn 645/CT-CS ngày "
                     "23/1/2026 của Cục Thuế.",
         note="Không phải khai, nộp lệ phí môn bài từ năm 2026. Giữ lại để tra cứu; không sinh hạn.", remind_days=0),
]


def _err(status: int, msg: str) -> HTTPException:
    return HTTPException(status, msg)


# ------------------------------------------------------------------ ngày

def month_end(y: int, m: int) -> date:
    return date(y, m, calendar.monthrange(y, m)[1])


def shift_weekend(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7) if d.weekday() >= 5 else d


def periods(rule: ComplianceRule, start: date, end: date) -> list[tuple[str, date]]:
    """(nhãn kỳ, hạn theo luật) cho các kỳ có hạn trong [start, end]."""
    dr = rule.due_rule or {}
    t = dr.get("type")
    out: list[tuple[str, date]] = []
    if rule.frequency == "once" or t == "fixed_date":
        try:
            d = date.fromisoformat(dr.get("date") or "")
        except ValueError:
            return []
        return [(d.strftime("%d/%m/%Y"), d)] if start <= d <= end else []
    if rule.frequency == "monthly":
        y, m = start.year, start.month - 2
        for _ in range(16):
            while m < 1:
                m += 12; y -= 1
            while m > 12:
                m -= 12; y += 1
            ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
            due = date(ny, nm, min(int(dr.get("day") or 20), calendar.monthrange(ny, nm)[1])) if t == "next_month_day" \
                else month_end(ny, nm)
            if start <= due <= end:
                out.append((f"{m:02d}/{y}", due))
            m += 1
        return out
    if rule.frequency == "quarterly":
        for y in (start.year - 1, start.year, start.year + 1):
            for q in range(1, 5):
                ny, fm = (y + 1, 1) if q == 4 else (y, q * 3 + 1)
                due = month_end(ny, fm)
                if start <= due <= end:
                    out.append((f"Q{q}/{y}", due))
        return out
    if rule.frequency == "yearly":
        months = int(dr.get("months") or 3)
        for y in (start.year - 2, start.year - 1, start.year, start.year + 1):
            due = month_end(y + 1, months)
            if start <= due <= end:
                out.append((str(y), due))
        return out
    return out


# ------------------------------------------------------------------ cài đặt + luật

def _profile(db: Session, org_id: int, company_id: int | None) -> tuple[Company, CompanyProfile | None]:
    from app.services.company_foundation import _company, profile_row
    co = _company(db, org_id, company_id)
    return co, profile_row(db, co.id)


def settings_of(p: CompanyProfile | None) -> dict:
    s = dict((p.compliance if p is not None else None) or {})
    return {"vat_period": s.get("vat_period") or "quarterly", "pit_period": s.get("pit_period") or "quarterly",
            "has_employees": bool(s.get("has_employees", False)), "accounting_position_id": s.get("accounting_position_id"),
            "entity_type": (p.entity_type if p is not None else "") or "", "configured": bool(s)}


def save_settings(db: Session, org_id: int, company_id: int | None, data: dict) -> dict:
    from app.services.company_foundation import CompanyProfile as CP
    co, p = _profile(db, org_id, company_id)
    for f in ("vat_period", "pit_period"):
        if data.get(f) is not None and data[f] not in ("monthly", "quarterly"):
            raise _err(422, "Kỳ kê khai phải là monthly (tháng) hoặc quarterly (quý). Doanh nghiệp mới thành lập và doanh nghiệp "
                            "có doanh thu năm trước trên 50 tỷ đồng khai GTGT theo tháng — kiểm tra với kế toán.")
    if data.get("accounting_position_id") is not None:
        pos = db.get(Position, data["accounting_position_id"])
        if pos is None or pos.company_id != co.id:
            raise _err(422, "Chức danh kế toán phải là một chức danh của công ty này (tab Chức danh).")
    if p is None:
        p = CP(organization_id=org_id, company_id=co.id)
        db.add(p)
    cur = dict(p.compliance or {})
    for f in ("vat_period", "pit_period", "has_employees", "accounting_position_id"):
        if f in data:
            cur[f] = data[f]
    p.compliance = cur
    db.commit()
    return settings_of(p)


def seed_defaults(db: Session, org_id: int, company_id: int, *, replace: bool = False) -> dict:
    have = {r.key for r in db.query(ComplianceRule).filter(ComplianceRule.company_id == company_id,
                                                           ComplianceRule.source == "default").all()}
    if replace:
        for r in db.query(ComplianceRule).filter(ComplianceRule.company_id == company_id, ComplianceRule.source == "default").all():
            db.query(ComplianceDeadline).filter(ComplianceDeadline.rule_id == r.id).delete()
            db.delete(r)
        db.commit(); have = set()
    made = 0
    for spec in DEFAULT_RULES:
        if spec["key"] in have:
            continue
        db.add(ComplianceRule(organization_id=org_id, company_id=company_id, source="default",
                              **{k: v for k, v in spec.items()}))
        made += 1
    db.commit()
    return {"company_id": company_id, "created": made}


def applies(rule: ComplianceRule, s: dict, on: date) -> bool:
    if not rule.enabled:
        return False
    if rule.entity_types and s["entity_type"] and s["entity_type"] not in rule.entity_types:
        return False
    if rule.entity_types and not s["entity_type"] and rule.entity_types == ["ho_kinh_doanh"]:
        return False
    for k, v in (rule.condition or {}).items():
        if s.get(k) != v:
            return False
    return True


def public_rule(r: ComplianceRule) -> dict:
    return {"id": r.id, "key": r.key, "name": r.name, "category": r.category, "entity_types": r.entity_types or [],
            "condition": r.condition or {}, "frequency": r.frequency, "due_rule": r.due_rule or {},
            "legal_basis": r.legal_basis, "note": r.note, "remind_days": r.remind_days, "enabled": r.enabled,
            "needs_review": r.needs_review, "source": r.source,
            "effective_from": r.effective_from.isoformat() if r.effective_from else None,
            "effective_to": r.effective_to.isoformat() if r.effective_to else None}


def _rule(db: Session, org_id: int, rid: int) -> ComplianceRule:
    r = db.get(ComplianceRule, rid)
    if r is None or r.organization_id != org_id:
        raise _err(404, "Không thấy luật tuân thủ này. Tải lại tab Tuân thủ.")
    return r


def _apply_rule(r: ComplianceRule, data: dict) -> None:
    if "name" in data:
        if not (data.get("name") or "").strip():
            raise _err(422, "Nghĩa vụ cần có tên, ví dụ \"Gia hạn giấy phép kinh doanh rượu\".")
        r.name = data["name"].strip()[:200]
    if data.get("category") is not None:
        if data["category"] not in CATEGORIES:
            raise _err(422, "Nhóm phải là tax, social, report hoặc license.")
        r.category = data["category"]
    if data.get("frequency") is not None:
        if data["frequency"] not in FREQUENCIES:
            raise _err(422, "Tần suất phải là monthly, quarterly, yearly hoặc once (một lần, ví dụ giấy phép hết hạn).")
        r.frequency = data["frequency"]
    if data.get("due_rule") is not None:
        dr = data["due_rule"]
        if not isinstance(dr, dict) or dr.get("type") not in DUE_TYPES:
            raise _err(422, "Cách tính hạn không hợp lệ — chọn một trong: " + ", ".join(DUE_TYPES) + ".")
        if dr["type"] == "fixed_date":
            try:
                date.fromisoformat(dr.get("date") or "")
            except ValueError:
                raise _err(422, "Ngày hết hạn phải theo dạng YYYY-MM-DD, ví dụ 2027-03-31.")
        r.due_rule = dr
    for f in ("legal_basis", "note"):
        if f in data:
            setattr(r, f, (data.get(f) or "")[:4000])
    if data.get("remind_days") is not None:
        if not (0 <= int(data["remind_days"]) <= 180):
            raise _err(422, "Số ngày nhắc trước phải từ 0 tới 180.")
        r.remind_days = int(data["remind_days"])
    for f in ("enabled", "needs_review"):
        if data.get(f) is not None:
            setattr(r, f, bool(data[f]))
    if "entity_types" in data:
        r.entity_types = data.get("entity_types") or []
    if "condition" in data:
        r.condition = data.get("condition") or {}


def create_rule(db: Session, org_id: int, company_id: int | None, data: dict) -> dict:
    co, _ = _profile(db, org_id, company_id)
    r = ComplianceRule(organization_id=org_id, company_id=co.id, source="custom", key="custom", name="",
                       frequency="once", category="license", due_rule={"type": "fixed_date"}, remind_days=30)
    _apply_rule(r, {"name": "", **data})
    if not (r.legal_basis or "").strip():
        r.needs_review = True        # luật tự thêm không có căn cứ → đánh dấu cần kiểm tra
    db.add(r); db.commit(); db.refresh(r)
    return public_rule(r)


def update_rule(db: Session, org_id: int, rid: int, data: dict) -> dict:
    r = _rule(db, org_id, rid)
    _apply_rule(r, data)
    db.commit()
    if "enabled" in data and not r.enabled:   # tắt luật → bỏ các hạn chưa tới
        db.query(ComplianceDeadline).filter(ComplianceDeadline.rule_id == r.id, ComplianceDeadline.status == "upcoming",
                                            ComplianceDeadline.task_id.is_(None)).delete()
        db.commit()
    return public_rule(r)


def delete_rule(db: Session, org_id: int, rid: int) -> dict:
    r = _rule(db, org_id, rid)
    db.query(ComplianceDeadline).filter(ComplianceDeadline.rule_id == r.id).delete()
    db.delete(r); db.commit()
    return {"id": rid, "deleted": True}


# ------------------------------------------------------------------ sinh hạn + nhắc

def accountant(db: Session, org_id: int, co: Company, s: dict) -> tuple[int | None, str]:
    from app.services import authority
    from app.services.company_foundation import seats_of
    pos = db.get(Position, s["accounting_position_id"]) if s.get("accounting_position_id") else None
    if pos is None:
        pos = next((p for p in db.query(Position).filter(Position.company_id == co.id, Position.status != "archived")
                    .order_by(Position.id).all() if "kế toán" in (p.title or "").lower() or "thuế" in (p.title or "").lower()), None)
    if pos is not None:
        seats = seats_of(db, pos.id)
        if seats:
            return seats[0].id, pos.title
    return authority.owner_member(db, org_id, co.id), "chủ doanh nghiệp (chưa có chức danh kế toán)"


def generate(db: Session, org_id: int, company_id: int | None, *, today: date | None = None,
             horizon_days: int = HORIZON_DAYS) -> dict:
    co, p = _profile(db, org_id, company_id)
    s = settings_of(p)
    today = today or (datetime.utcnow() + timedelta(hours=7)).date()
    who, who_label = accountant(db, org_id, co, s)
    made = 0
    for r in db.query(ComplianceRule).filter(ComplianceRule.company_id == co.id).all():
        if not applies(r, s, today):
            continue
        # chỉ hạn từ hôm nay trở đi: công ty mới bật lịch không bị báo "quá hạn" cho kỳ đã qua mà hệ thống
        # không biết đã nộp hay chưa (beat chạy hằng giờ nên hạn luôn được sinh trước 120 ngày)
        for label, statutory in periods(r, today - timedelta(days=3), today + timedelta(days=horizon_days)):
            if statutory < today:      # M2d.3: hạn nội bộ = hạn theo lịch (không dời ngày nghỉ)
                continue
            if (r.effective_to and statutory > r.effective_to) or (r.effective_from and statutory < r.effective_from):
                continue
            if db.query(ComplianceDeadline).filter(ComplianceDeadline.rule_id == r.id, ComplianceDeadline.period_label == label).first():
                continue
            legal, _ = holidays.legal_due(db, org_id, statutory)
            db.add(ComplianceDeadline(organization_id=org_id, company_id=co.id, rule_id=r.id, period_label=label,
                                      statutory_date=statutory, due_date=statutory, legal_due_date=legal,
                                      assignee_member_id=who))
            try:
                db.commit(); made += 1
            except IntegrityError:
                db.rollback()
    refresh_legal(db, org_id, co.id)
    return {"company_id": co.id, "created": made, "assignee": who_label}


def refresh_legal(db: Session, org_id: int, company_id: int | None = None) -> int:
    """Tính lại hạn pháp lý của các hạn chưa nộp (sau khi sửa lịch nghỉ). Hạn nội bộ không đổi."""
    q = db.query(ComplianceDeadline).filter(ComplianceDeadline.organization_id == org_id,
                                            ComplianceDeadline.status == "upcoming")
    if company_id:
        q = q.filter(ComplianceDeadline.company_id == company_id)
    n = 0
    for d in q.all():
        legal, _ = holidays.legal_due(db, org_id, d.statutory_date)
        if d.legal_due_date != legal:
            d.legal_due_date = legal
            n += 1
    db.commit()
    return n


def _project(db: Session, company_id: int) -> Project:
    pr = db.query(Project).filter(Project.company_id == company_id, Project.name == "Tuân thủ").first()
    if pr is None:
        pr = Project(company_id=company_id, name="Tuân thủ", status="active",
                     description="Việc nhắc hạn thuế, BHXH, giấy phép (lịch tuân thủ M2c D7)")
        db.add(pr); db.commit(); db.refresh(pr)
    return pr


def remind(db: Session, org_id: int, company_id: int | None, *, today: date | None = None) -> dict:
    from app.services import authority, inbox
    from app.services import workspace_ops as ops
    co, _ = _profile(db, org_id, company_id)
    today = today or (datetime.utcnow() + timedelta(hours=7)).date()
    sent = 0
    rows = (db.query(ComplianceDeadline).filter(ComplianceDeadline.company_id == co.id, ComplianceDeadline.status == "upcoming",
                                                ComplianceDeadline.reminded_at.is_(None)).order_by(ComplianceDeadline.due_date).all())
    for d in rows:
        r = db.get(ComplianceRule, d.rule_id)
        if r is None or (d.due_date - today).days > (r.remind_days or 0):
            continue
        days = (d.due_date - today).days
        when = f"còn {days} ngày" if days > 0 else ("hôm nay" if days == 0 else f"QUÁ HẠN {-days} ngày")
        title = f"{r.name} kỳ {d.period_label} — hạn {d.due_date:%d/%m/%Y} ({when})"
        legal, why = holidays.legal_due(db, org_id, d.statutory_date)
        desc = "\n".join([f"**Nghĩa vụ:** {r.name} — kỳ {d.period_label}",
                          f"**Hạn (làm theo ngày này):** {d.due_date:%d/%m/%Y}",
                          *([f"**Hạn pháp lý:** {legal:%d/%m/%Y} — {d.due_date:%d/%m} rơi vào ngày nghỉ ({why}); luật cho "
                             f"nộp tới ngày làm việc liền kề, nhưng đừng chờ: nộp theo hạn trên."] if legal != d.due_date else []),
                          f"**Căn cứ:** {r.legal_basis}", *( [f"**Lưu ý:** {r.note}"] if r.note else []),
                          "", f"_{DISCLAIMER}_", "", "Nộp xong thì chuyển việc sang review → xong (lịch tự đánh dấu đã nộp)."])
        if d.task_id is None and d.assignee_member_id:
            t = ops.create_task(db, _project(db, co.id), org_id, title=title[:220], description=desc,
                                assignee_member_id=d.assignee_member_id, priority="high" if days <= 3 else "medium")
            t.due_at = datetime.combine(d.due_date, datetime.min.time()) + timedelta(hours=10)   # 17:00 giờ VN
            db.commit()
            d.task_id = t.id
        to = [d.assignee_member_id, authority.owner_member(db, org_id, co.id)]
        inbox.notify(db, organization_id=org_id, recipients=to, kind="compliance_due", title=title[:220], task_id=d.task_id,
                     related_type="compliance_deadline", related_id=str(d.id), priority="high" if days <= 3 else "normal",
                     line=title, source="compliance", commit=False)
        d.reminded_at = datetime.utcnow()
        db.commit(); sent += 1
    return {"company_id": co.id, "reminded": sent}


def _sync_done(db: Session, d: ComplianceDeadline) -> None:
    if d.status == "upcoming" and d.task_id:
        t = db.get(Task, d.task_id)
        if t is not None and t.status == "done":
            d.status, d.done_at = "done", t.updated_at or datetime.utcnow()
            db.commit()


def mark_done(db: Session, org_id: int, did: int) -> dict:
    d = db.get(ComplianceDeadline, did)
    if d is None or d.organization_id != org_id:
        raise _err(404, "Không thấy hạn này.")
    d.status, d.done_at = "done", datetime.utcnow()
    db.commit()
    return public_deadline(db, d)


def public_deadline(db: Session, d: ComplianceDeadline, today: date | None = None) -> dict:
    today = today or (datetime.utcnow() + timedelta(hours=7)).date()
    r = db.get(ComplianceRule, d.rule_id)
    m = db.get(Member, d.assignee_member_id) if d.assignee_member_id else None
    legal, why = (d.legal_due_date, "") if d.legal_due_date else (d.due_date, "")
    if legal != d.due_date:
        _, why = holidays.legal_due(db, d.organization_id, d.statutory_date)
    return {"id": d.id, "rule_id": d.rule_id, "name": r.name if r else "", "category": r.category if r else "",
            "period_label": d.period_label, "due_date": d.due_date.isoformat(), "statutory_date": d.statutory_date.isoformat(),
            "legal_due_date": legal.isoformat(), "legal_shift_reason": why,
            "shifted": legal != d.due_date, "days_left": (d.due_date - today).days, "status": d.status,
            "overdue": d.status == "upcoming" and d.due_date < today,
            "legal_overdue": d.status == "upcoming" and legal < today, "assignee": m.name if m else None,
            "task_id": d.task_id, "reminded": d.reminded_at is not None, "legal_basis": r.legal_basis if r else "",
            "needs_review": bool(r and r.needs_review)}


def overview(db: Session, org_id: int, company_id: int | None, *, today: date | None = None) -> dict:
    co, p = _profile(db, org_id, company_id)
    today = today or (datetime.utcnow() + timedelta(hours=7)).date()
    rows = (db.query(ComplianceDeadline).filter(ComplianceDeadline.company_id == co.id,
                                                ComplianceDeadline.due_date >= today - timedelta(days=60),
                                                ComplianceDeadline.due_date <= today + timedelta(days=HORIZON_DAYS))
            .order_by(ComplianceDeadline.due_date, ComplianceDeadline.id).all())
    for d in rows:
        _sync_done(db, d)
    rules = db.query(ComplianceRule).filter(ComplianceRule.company_id == co.id).order_by(ComplianceRule.id).all()
    s = settings_of(p)
    who, who_label = accountant(db, org_id, co, s)
    return {"company_id": co.id, "company_name": co.name, "today": today.isoformat(), "disclaimer": DISCLAIMER,
            "weekend_note": WEEKEND_NOTE, "legal_rule_url": holidays.LEGAL_RULE_URL, "settings": s, "assignee": who_label,
            "holidays": {y: [holidays.public(h) for h in sorted(
                [h for h in holidays.calendar_of(db, org_id, {y}).values()], key=lambda x: x.day)]
                for y in (today.year, today.year + 1)},
            "rules": [{**public_rule(r), "applies": applies(r, s, today)} for r in rules],
            "deadlines": [public_deadline(db, d, today) for d in rows],
            "positions": [{"id": x.id, "title": x.title} for x in db.query(Position).filter(
                Position.company_id == co.id, Position.status != "archived").order_by(Position.id).all()]}


def tick(db: Session, *, today: date | None = None) -> list[dict]:
    out = []
    for org_id, company_id in {(r.organization_id, r.company_id) for r in db.query(ComplianceRule).all()}:
        try:
            g = generate(db, org_id, company_id, today=today)
            m = remind(db, org_id, company_id, today=today)
            out.append({"company_id": company_id, "created": g["created"], "reminded": m["reminded"]})
        except Exception as exc:  # noqa: BLE001
            db.rollback(); out.append({"company_id": company_id, "error": str(exc)[:300]})
    return out
