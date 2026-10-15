"""M2d.3 — ngày nghỉ lễ Việt Nam, CHỈ để tính hạn pháp lý của lịch tuân thủ.

Agent làm việc mọi ngày: giao việc, giao ban, nhắc hạn và hạn nội bộ của việc tuân thủ KHÔNG đọc module này.
Luật chỉ cho phép: hạn nộp hồ sơ khai thuế / nộp thuế rơi vào ngày nghỉ (cuối tuần, lễ, Tết) thì ngày cuối của
thời hạn là ngày làm việc liền kề sau ngày nghỉ đó — Điều 3 (giải thích từ ngữ — ngày hết thời hạn) Nghị định 252/2026/NĐ-CP (hướng dẫn Luật
Quản lý thuế 108/2025/QH15, từ 1/7/2026); trước đó Điều 86 Thông tư 80/2021/TT-BTC + khoản 5 Điều 148 BLDS 2015.
Lịch tuân thủ hiển thị ngày đó là "hạn pháp lý", phụ.

Dữ liệu: ``public_holidays`` theo tổ chức × năm, sửa được. Lần đầu đọc một năm → gieo bộ mặc định bên dưới
(lịch nghỉ của cơ quan hành chính — cơ quan thuế làm việc theo lịch này). Ngày chưa có thông báo chính thức
gắn ``needs_confirmation`` ("cần xác nhận").
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.company_ops import PublicHoliday

LEGAL_RULE = ("Hạn rơi vào ngày nghỉ (thứ Bảy, Chủ nhật, lễ, Tết) → hạn pháp lý là ngày làm việc liền kề sau: "
              "Điều 3 Nghị định 252/2026/NĐ-CP (trước 1/7/2026: Điều 86 Thông tư 80/2021/TT-BTC, khoản 5 Điều 148 BLDS "
              "2015). Agent vẫn làm theo hạn theo lịch — hạn pháp lý chỉ để đối chiếu.")
LEGAL_RULE_URL = "https://luatvietnam.vn/thue/nghi-dinh-252-2026-nd-cp-huong-dan-thi-hanh-luat-quan-ly-thue-chi-tiet-va-hieu-qua-439382-d1.html"

_TB2026 = "https://cdn.thuvienphapluat.vn/phap-luat/2022-2/PH/151025/9441-TB-BNV.pdf"
_GIOTO2026 = "https://thuvienphapluat.vn/phap-luat-doanh-nghiep/bai-viet/thong-bao-nghi-le-gio-to-2026-va-30-4-moi-nhat-cua-bo-noi-vu-20304.html"
_VPCP2027 = "https://moha.gov.vn/tin-tuc/chinh-phu-chot-phuong-an-nghi-mot-so-dip-le-tet-nam-2026-va-nam-2027---id19707"
_BLLD = "Bộ luật Lao động 2019, Điều 112 (nghỉ bù khi lễ trùng ngày nghỉ hằng tuần)"

# (ngày, tên, loại, trạng thái, nguồn, ghi chú) — lịch nghỉ khu vực hành chính
DEFAULTS: dict[int, list[tuple]] = {
    2026: [
        (date(2026, 1, 1), "Tết Dương lịch", "holiday", "official", "", _BLLD),
        *[(date(2026, 2, d), "Tết Nguyên đán Bính Ngọ", "holiday", "official", _TB2026, "TB 9441/TB-BNV: 16–20/2/2026")
          for d in range(16, 21)],
        (date(2026, 4, 27), "Nghỉ bù Giỗ Tổ Hùng Vương (10/3 âm lịch = CN 26/4)", "holiday", "official", _GIOTO2026,
         "CV 3383/BNV-CVL 10/4/2026"),
        (date(2026, 4, 30), "Ngày Chiến thắng 30/4", "holiday", "official", _GIOTO2026, ""),
        (date(2026, 5, 1), "Quốc tế Lao động 1/5", "holiday", "official", _GIOTO2026, ""),
        (date(2026, 8, 22), "Làm bù (đổi cho thứ Hai 31/8)", "makeup_workday", "official", _TB2026, "TB 9441/TB-BNV"),
        (date(2026, 8, 31), "Nghỉ hoán đổi dịp Quốc khánh", "holiday", "official", _TB2026, "TB 9441/TB-BNV"),
        (date(2026, 9, 1), "Quốc khánh (ngày liền kề)", "holiday", "official", _TB2026, ""),
        (date(2026, 9, 2), "Quốc khánh 2/9", "holiday", "official", _TB2026, ""),
        (date(2026, 11, 24), "Ngày Văn hóa Việt Nam", "holiday", "official", _VPCP2027, "CV 10065/VPCP-KGVX 2/10/2026"),
    ],
    2027: [
        (date(2027, 1, 1), "Tết Dương lịch", "holiday", "official", "", _BLLD),
        *[(date(2027, 2, d), "Tết Nguyên đán Đinh Mùi" + (" (nghỉ bù)" if d in (9, 10) else ""), "holiday", "official",
           _VPCP2027, "TB 11483/TB-BNV 9/10/2026: 4–10/2/2027") for d in (4, 5, 8, 9, 10)],
        (date(2027, 4, 16), "Giỗ Tổ Hùng Vương (10/3 âm lịch)", "holiday", "needs_confirmation", "",
         "Tính theo âm lịch; chưa có thông báo của Bộ Nội vụ"),
        (date(2027, 4, 30), "Ngày Chiến thắng 30/4", "holiday", "official", "", _BLLD),
        (date(2027, 5, 3), "Nghỉ bù Quốc tế Lao động (1/5 = thứ Bảy)", "holiday", "needs_confirmation", "",
         _BLLD + "; chưa có thông báo"),
        (date(2027, 9, 2), "Quốc khánh 2/9", "holiday", "official", _VPCP2027, "nghỉ 2–5/9/2027"),
        (date(2027, 9, 3), "Quốc khánh (ngày liền kề)", "holiday", "official", _VPCP2027, ""),
        (date(2027, 11, 24), "Ngày Văn hóa Việt Nam", "holiday", "needs_confirmation", "",
         "2026 được nghỉ; năm 2027 chờ thông báo"),
    ],
}
KINDS = ("holiday", "makeup_workday")
STATUSES = ("official", "needs_confirmation")


def ensure_year(db: Session, org_id: int, year: int) -> None:
    if year not in DEFAULTS:
        return
    if db.query(PublicHoliday).filter(PublicHoliday.organization_id == org_id, PublicHoliday.year == year).first():
        return
    for d, name, kind, status, url, note in DEFAULTS[year]:
        db.add(PublicHoliday(organization_id=org_id, year=year, day=d, name=name, kind=kind, status=status,
                             source_url=url, note=note))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def calendar_of(db: Session, org_id: int, years: set[int]) -> dict[date, PublicHoliday]:
    for y in years:
        ensure_year(db, org_id, y)
    rows = db.query(PublicHoliday).filter(PublicHoliday.organization_id == org_id, PublicHoliday.year.in_(years)).all()
    return {r.day: r for r in rows}


def legal_due(db: Session, org_id: int, d: date) -> tuple[date, str]:
    """(hạn pháp lý, lý do dời). Ngày làm việc = thứ Hai–Sáu không phải lễ, hoặc ngày làm bù."""
    cal = calendar_of(db, org_id, {d.year, d.year + 1})
    out, reasons = d, []
    for _ in range(40):
        h = cal.get(out)
        if h is not None and h.kind == "makeup_workday":
            break
        if h is not None and h.kind == "holiday":
            reasons.append(h.name)
        elif out.weekday() >= 5:
            reasons.append("cuối tuần")
        else:
            break
        out += timedelta(days=1)
    uniq = list(dict.fromkeys(reasons))
    return out, ", ".join(uniq)


def public(h: PublicHoliday) -> dict:
    return {"id": h.id, "year": h.year, "day": h.day.isoformat(), "name": h.name, "kind": h.kind, "status": h.status,
            "source_url": h.source_url, "note": h.note}


def list_year(db: Session, org_id: int, year: int) -> dict:
    ensure_year(db, org_id, year)
    rows = (db.query(PublicHoliday).filter(PublicHoliday.organization_id == org_id, PublicHoliday.year == year)
            .order_by(PublicHoliday.day).all())
    return {"year": year, "items": [public(h) for h in rows], "rule": LEGAL_RULE, "rule_url": LEGAL_RULE_URL,
            "has_defaults": year in DEFAULTS}


def _clean(data: dict, h: PublicHoliday | None = None) -> dict:
    out = {}
    if "day" in data or h is None:
        try:
            d = date.fromisoformat(str(data.get("day") or ""))
        except ValueError:
            raise HTTPException(422, "Ngày nghỉ cần dạng YYYY-MM-DD, ví dụ 2027-04-16.") from None
        out["day"], out["year"] = d, d.year
    if "name" in data or h is None:
        name = (data.get("name") or "").strip()
        if not name:
            raise HTTPException(422, "Ngày nghỉ cần có tên, ví dụ \"Giỗ Tổ Hùng Vương\".")
        out["name"] = name[:200]
    if "kind" in data:
        if data["kind"] not in KINDS:
            raise HTTPException(422, "Loại phải là holiday (nghỉ) hoặc makeup_workday (làm bù).")
        out["kind"] = data["kind"]
    if "status" in data:
        if data["status"] not in STATUSES:
            raise HTTPException(422, "Trạng thái phải là official hoặc needs_confirmation.")
        out["status"] = data["status"]
    for f, n in (("source_url", 400), ("note", 400)):
        if f in data:
            out[f] = (data.get(f) or "")[:n]
    return out


def create(db: Session, org_id: int, data: dict) -> dict:
    c = _clean(data)
    ensure_year(db, org_id, c["year"])
    if db.query(PublicHoliday).filter(PublicHoliday.organization_id == org_id, PublicHoliday.day == c["day"]).first():
        raise HTTPException(409, f"Ngày {c['day']:%d/%m/%Y} đã có trong lịch nghỉ — sửa dòng đó thay vì thêm mới.")
    h = PublicHoliday(organization_id=org_id, **c)
    db.add(h); db.commit(); db.refresh(h)
    return public(h)


def _get(db: Session, org_id: int, hid: int) -> PublicHoliday:
    h = db.get(PublicHoliday, hid)
    if h is None or h.organization_id != org_id:
        raise HTTPException(404, "Không thấy ngày nghỉ này.")
    return h


def update(db: Session, org_id: int, hid: int, data: dict) -> dict:
    h = _get(db, org_id, hid)
    for k, v in _clean(data, h).items():
        setattr(h, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Ngày này đã có trong lịch nghỉ.") from None
    return public(h)


def delete(db: Session, org_id: int, hid: int) -> dict:
    h = _get(db, org_id, hid)
    db.delete(h); db.commit()
    return {"id": hid, "deleted": True}
