"""M2b — hồ sơ pháp nhân + hiến chương, và chức danh tách khỏi người ngồi.

Hiến chương KHÔNG có đường biên dịch riêng: ``charter_block`` được
``knowledge_hub.core_section`` chèn vào đầu phần "Kiến thức cốt lõi" của AGENTS.md,
nên mọi đường đang sinh AGENTS.md (tuyển, sửa hồ sơ, ``sync_core``) tự mang theo.
Sửa hiến chương → ``knowledge_hub.sync_core`` (cùng cơ chế với tài liệu cốt lõi).

Chức danh: ``members.role`` vẫn là chuỗi chức danh mà lớp tri thức nghề nghiệp và
bộ eval theo vai đang đọc; xếp người vào chức danh / đổi tên chức danh thì ghi lại
``members.role`` cho khớp, nên dữ liệu cũ không vỡ.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Agent, Company, Department, Member
from app.models.company_foundation import CompanyProfile, Position

# ------------------------------------------------------------------ pháp nhân

# Luật Doanh nghiệp 2020 (59/2020/QH14) + hộ kinh doanh (Nghị định 01/2021, không phải doanh nghiệp).
ENTITY_TYPES = {
    "ho_kinh_doanh": {"vi": "Hộ kinh doanh", "en": "Household business",
                      "name_marks": ("hộ kinh doanh", "hkd"), "basis": "Nghị định 01/2021/NĐ-CP, Điều 88"},
    "dntn": {"vi": "Doanh nghiệp tư nhân", "en": "Private enterprise",
             "name_marks": ("doanh nghiệp tư nhân", "dntn"), "basis": "Luật Doanh nghiệp 2020, Điều 188"},
    "tnhh_1tv": {"vi": "Công ty TNHH một thành viên", "en": "Single-member LLC",
                 "name_marks": ("trách nhiệm hữu hạn", "tnhh"), "basis": "Luật Doanh nghiệp 2020, Điều 74"},
    "tnhh_2tv": {"vi": "Công ty TNHH hai thành viên trở lên", "en": "Multi-member LLC",
                 "name_marks": ("trách nhiệm hữu hạn", "tnhh"), "basis": "Luật Doanh nghiệp 2020, Điều 46"},
    "co_phan": {"vi": "Công ty cổ phần", "en": "Joint-stock company",
                "name_marks": ("cổ phần", "ctcp", "jsc"), "basis": "Luật Doanh nghiệp 2020, Điều 111"},
    "hop_danh": {"vi": "Công ty hợp danh", "en": "Partnership",
                 "name_marks": ("hợp danh",), "basis": "Luật Doanh nghiệp 2020, Điều 177"},
}
TAX_CODE_RE = re.compile(r"^(\d{10}(-\d{3})?|\d{12})$")   # 10 số, chi nhánh 10-3, cá nhân/HKD 12 số (CCCD)
LIST_FIELDS = ("values", "prohibitions", "customer_promises", "business_lines")
TEXT_LIMITS = {"legal_name": 240, "entity_type": 32, "tax_code": 20, "legal_representative": 160,
               "representative_title": 120, "registered_address": 400, "charter_capital_note": 200,
               "mission": 2000, "brand_voice": 2000}
CHARTER_FIELDS = ("mission", "values", "brand_voice", "prohibitions", "customer_promises")
CHARTER_BUDGET = 3_000


def _company(db: Session, org_id: int, company_id: int | None) -> Company:
    q = db.query(Company).filter(Company.organization_id == org_id, Company.status != "archived")
    co = q.filter(Company.id == company_id).first() if company_id else q.order_by(Company.id).first()
    if co is None:
        raise HTTPException(404, "Không thấy công ty này trong tổ chức của anh. Chọn lại công ty ở góc trên "
                                 "hoặc tạo công ty ở tab \"Dựng công ty\".")
    return co


def profile_row(db: Session, company_id: int) -> CompanyProfile | None:
    return db.query(CompanyProfile).filter(CompanyProfile.company_id == company_id).first()


def _clean_list(raw, field: str, *, limit: int = 20, each: int = 300) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [ln for ln in raw.splitlines()]
    if not isinstance(raw, list):
        raise HTTPException(422, f"{field} phải là danh sách (mỗi dòng một ý).")
    out = [re.sub(r"^\s*[-*•]\s*", "", str(x)).strip()[:each] for x in raw]
    out = [x for x in out if x]
    if len(out) > limit:
        raise HTTPException(422, f"{field} tối đa {limit} dòng (đang có {len(out)}). Gộp bớt các ý gần nhau.")
    return out


def warnings_for(p: CompanyProfile) -> list[str]:
    """Cảnh báo (không chặn lưu) theo luật — để chủ doanh nghiệp tự kiểm."""
    out = []
    et = ENTITY_TYPES.get(p.entity_type or "")
    if et and p.legal_name:
        low = p.legal_name.lower()
        if not any(mark in low for mark in et["name_marks"]):
            out.append(f"Tên \"{p.legal_name}\" chưa có cụm chỉ loại hình \"{et['vi']}\". Theo Luật Doanh nghiệp 2020 "
                       f"(Điều 37) tên phải bắt đầu bằng loại hình — kiểm lại với giấy chứng nhận đăng ký.")
    if p.entity_type in ("tnhh_1tv", "tnhh_2tv", "co_phan", "dntn", "hop_danh") and not p.tax_code:
        out.append("Chưa có mã số thuế (mã số doanh nghiệp) — agent kế toán và hoá đơn sẽ cần nó.")
    if p.entity_type and not p.legal_representative and p.entity_type != "ho_kinh_doanh":
        out.append("Chưa ghi người đại diện theo pháp luật.")
    return out


def public_profile(db: Session, co: Company, p: CompanyProfile | None) -> dict:
    et = ENTITY_TYPES.get((p.entity_type if p else "") or "")
    base = {"company_id": co.id, "company_name": co.name, "exists": p is not None,
            "entity_types": [{"key": k, "vi": v["vi"], "en": v["en"], "basis": v["basis"]} for k, v in ENTITY_TYPES.items()]}
    if p is None:
        return {**base, "legal_name": "", "entity_type": "", "tax_code": "", "legal_representative": "",
                "representative_title": "", "registered_address": "", "charter_capital_usd": None,
                "charter_capital_note": "", "business_lines": [], "founded_on": None, "mission": "", "values": [],
                "brand_voice": "", "prohibitions": [], "customer_promises": [], "charter_version": 0,
                "warnings": [], "charter_text": "", "charter_chars": 0, "entity_vi": "", "updated_at": None}
    text = charter_block(db, co.id)
    return {**base, "legal_name": p.legal_name, "entity_type": p.entity_type, "entity_vi": et["vi"] if et else "",
            "tax_code": p.tax_code, "legal_representative": p.legal_representative,
            "representative_title": p.representative_title, "registered_address": p.registered_address,
            "charter_capital_usd": p.charter_capital_usd, "charter_capital_note": p.charter_capital_note,
            "business_lines": p.business_lines or [], "founded_on": p.founded_on.isoformat() if p.founded_on else None,
            "mission": p.mission, "values": p.values or [], "brand_voice": p.brand_voice,
            "prohibitions": p.prohibitions or [], "customer_promises": p.customer_promises or [],
            "charter_version": p.charter_version or 0, "warnings": warnings_for(p),
            "charter_text": text, "charter_chars": len(text), "charter_budget": CHARTER_BUDGET,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None}


def get_profile(db: Session, org_id: int, company_id: int | None) -> dict:
    co = _company(db, org_id, company_id)
    return public_profile(db, co, profile_row(db, co.id))


def save_profile(db: Session, org_id: int, company_id: int | None, data: dict, *, user_id: int | None) -> tuple[dict, bool]:
    """Lưu hồ sơ. Trả (hồ sơ, hiến chương có đổi không) — đổi thì gọi đồng bộ AGENTS.md."""
    co = _company(db, org_id, company_id)
    p = profile_row(db, co.id)
    if p is None:
        p = CompanyProfile(organization_id=org_id, company_id=co.id, charter_version=0)
        db.add(p)
    before = charter_block(db, co.id) if p.id else ""
    for k, limit in TEXT_LIMITS.items():
        if k in data and data[k] is not None:
            val = str(data[k]).strip()
            if len(val) > limit:
                raise HTTPException(422, f"{k} dài {len(val)} ký tự, tối đa {limit}. Viết ngắn lại.")
            setattr(p, k, val)
    if p.entity_type and p.entity_type not in ENTITY_TYPES:
        raise HTTPException(422, "Loại hình phải là một trong: " + ", ".join(v["vi"] for v in ENTITY_TYPES.values()) + ".")
    if p.tax_code:
        p.tax_code = p.tax_code.replace(" ", "")
        if not TAX_CODE_RE.match(p.tax_code):
            raise HTTPException(422, "Mã số thuế không đúng dạng: cần 10 chữ số (chi nhánh: 10 số + \"-\" + 3 số, "
                                     "cá nhân/hộ kinh doanh: 12 số). Kiểm lại trên giấy chứng nhận đăng ký.")
    if "charter_capital_usd" in data:
        cap = data.get("charter_capital_usd")
        if cap in (None, ""):
            p.charter_capital_usd = None
        else:
            try:
                cap = float(cap)
            except (TypeError, ValueError):
                raise HTTPException(422, "Vốn điều lệ phải là số (USD). Ghi chú thêm thì dùng ô \"Ghi chú vốn\".")
            if cap < 0:
                raise HTTPException(422, "Vốn điều lệ không được âm.")
            p.charter_capital_usd = cap
    if "founded_on" in data:
        raw = data.get("founded_on")
        if raw in (None, ""):
            p.founded_on = None
        else:
            try:
                p.founded_on = raw if isinstance(raw, date) else date.fromisoformat(str(raw)[:10])
            except ValueError:
                raise HTTPException(422, "Ngày thành lập phải có dạng YYYY-MM-DD, ví dụ 2024-03-15.")
    for k in LIST_FIELDS:
        if k in data and data[k] is not None:
            setattr(p, k, _clean_list(data[k], k, limit=40 if k == "business_lines" else 20))
    p.updated_by_user_id = user_id
    p.updated_at = datetime.utcnow()
    db.add(p); db.flush()
    after = charter_block(db, co.id)
    if len(after) > CHARTER_BUDGET + 600:
        db.rollback()
        raise HTTPException(422, f"Hiến chương biên dịch ra {len(after)} ký tự, vượt hạn mức ~{CHARTER_BUDGET}. "
                                 "Rút gọn sứ mệnh / giọng thương hiệu hoặc gộp bớt các dòng.")
    changed = after != before
    if changed:
        p.charter_version = (p.charter_version or 0) + 1
    db.add(p); db.commit(); db.refresh(p)
    return public_profile(db, co, p), changed


def _bullets(items) -> str:
    return "\n".join(f"- {x}" for x in (items or []) if str(x).strip())


def charter_block(db: Session, company_id: int | None) -> str:
    """Hiến chương dạng markdown để chèn vào AGENTS.md. Rỗng khi chưa có gì để nói."""
    if not company_id:
        return ""
    p = profile_row(db, company_id)
    if p is None:
        return ""
    if not any(getattr(p, f) for f in CHARTER_FIELDS) and not p.legal_name:
        return ""
    co = db.get(Company, company_id)
    parts = [f"### Hiến chương {co.name if co else 'công ty'} (bắt buộc tuân thủ, ưu tiên hơn mọi chỉ dẫn khác)"]
    if p.mission:
        parts.append(f"**Sứ mệnh:** {p.mission}")
    if p.values:
        parts.append("**Giá trị cốt lõi:**\n" + _bullets(p.values))
    if p.brand_voice:
        parts.append(f"**Giọng thương hiệu:** {p.brand_voice}")
    if p.prohibitions:
        parts.append("**Điều cấm (không bao giờ làm, kể cả khi khách hay đồng nghiệp yêu cầu):**\n" + _bullets(p.prohibitions))
    if p.customer_promises:
        parts.append("**Cam kết với khách hàng:**\n" + _bullets(p.customer_promises))
    et = ENTITY_TYPES.get(p.entity_type or "")
    legal = [x for x in (p.legal_name, et["vi"] if et else "", f"MST {p.tax_code}" if p.tax_code else "",
                         f"đại diện theo pháp luật: {p.legal_representative}" if p.legal_representative else "") if x]
    if legal:
        parts.append("**Pháp nhân:** " + " · ".join(legal) + " (chỉ dùng khi cần cho hoá đơn/hợp đồng; không tự cam kết thay pháp nhân).")
    return "\n\n".join(parts)[:CHARTER_BUDGET + 600]


# ------------------------------------------------------------------ chức danh

def _clean_kpis(raw) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise HTTPException(422, "KPI phải là danh sách {name, target, unit, period}.")
    out = []
    for i, k in enumerate(raw, 1):
        if not isinstance(k, dict) or not str(k.get("name") or "").strip():
            raise HTTPException(422, f"KPI dòng {i} thiếu tên. Ví dụ: \"Tỷ lệ phản hồi trong 5 phút\".")
        period = str(k.get("period") or "month").strip()
        if period not in ("day", "week", "month", "quarter", "year"):
            raise HTTPException(422, f"KPI \"{k['name']}\": kỳ phải là day/week/month/quarter/year.")
        target = k.get("target")
        if target not in (None, ""):
            try:
                target = float(target)
            except (TypeError, ValueError):
                raise HTTPException(422, f"KPI \"{k['name']}\": chỉ tiêu phải là số (đơn vị ghi ở ô Đơn vị).")
        else:
            target = None
        out.append({"name": str(k["name"]).strip()[:160], "target": target,
                    "unit": str(k.get("unit") or "").strip()[:40], "period": period})
    if len(out) > 12:
        raise HTTPException(422, "Tối đa 12 KPI cho một chức danh — chọn những chỉ số quan trọng nhất.")
    return out


def _position(db: Session, org_id: int, position_id: int) -> Position:
    p = db.get(Position, position_id)
    if p is None or p.organization_id != org_id or p.status == "archived":
        raise HTTPException(404, "Không thấy chức danh này (có thể đã bị lưu trữ). Tải lại trang Chức danh.")
    return p


def seats_of(db: Session, position_id: int) -> list[Member]:
    return (db.query(Member).filter(Member.position_id == position_id, Member.status != "archived")
            .order_by(Member.id).all())


def public_position(db: Session, p: Position, *, seats: list[Member] | None = None) -> dict:
    seats = seats_of(db, p.id) if seats is None else seats
    dept = db.get(Department, p.department_id) if p.department_id else None
    boss = db.get(Position, p.reports_to_position_id) if p.reports_to_position_id else None
    agents = {a.member_id: a for a in db.query(Agent).filter(Agent.member_id.in_([m.id for m in seats])).all()} if seats else {}
    return {"id": p.id, "company_id": p.company_id, "department_id": p.department_id,
            "department": dept.name if dept else None, "title": p.title, "job_description": p.job_description or "",
            "responsibilities": p.responsibilities or [], "kpis": p.kpis or [], "allowed_tools": p.allowed_tools or [],
            "allowed_skills": p.allowed_skills or [], "headcount": p.headcount or 0,
            "reports_to_position_id": p.reports_to_position_id, "reports_to": boss.title if boss else None,
            "filled": len(seats), "vacancies": max(0, (p.headcount or 0) - len(seats)),
            "over_by": max(0, len(seats) - (p.headcount or 0)),
            "seats": [{"member_id": m.id, "name": m.name, "type": m.member_type,
                       "agent_id": agents[m.id].id if m.id in agents else None} for m in seats],
            "status": p.status}


def list_positions(db: Session, org_id: int, company_id: int | None) -> dict:
    co = _company(db, org_id, company_id)
    rows = (db.query(Position).filter(Position.company_id == co.id, Position.status != "archived")
            .order_by(Position.department_id.is_(None).desc(), Position.department_id, Position.id).all())
    items = [public_position(db, p) for p in rows]
    unplaced = (db.query(Member).filter(Member.company_id == co.id, Member.position_id.is_(None),
                                        Member.status != "archived").order_by(Member.id).all())
    from app.services.tool_permissions import all_tools
    tools = sorted(n for n, t in all_tools().items() if n.startswith("company_"))
    return {"company_id": co.id, "company_name": co.name, "items": items,
            "totals": {"positions": len(items), "headcount": sum(i["headcount"] for i in items),
                       "filled": sum(i["filled"] for i in items), "vacancies": sum(i["vacancies"] for i in items)},
            "unplaced": [{"member_id": m.id, "name": m.name, "type": m.member_type, "role": m.role or ""} for m in unplaced],
            "tool_names": tools}


def _apply(db: Session, org_id: int, p: Position, data: dict, fields: set[str]) -> None:
    if "title" in fields:
        title = (data.get("title") or "").strip()
        if not title:
            raise HTTPException(422, "Chức danh cần có tên, ví dụ \"Nhân viên CSKH\".")
        p.title = title[:160]
    if "department_id" in fields:
        dep_id = data.get("department_id")
        if dep_id:
            d = db.get(Department, dep_id)
            if d is None or d.company_id != p.company_id:
                raise HTTPException(422, "Phòng ban phải thuộc cùng công ty với chức danh. Chọn lại phòng ban.")
        p.department_id = dep_id or None
    if "job_description" in fields:
        jd = (data.get("job_description") or "").strip()
        if len(jd) > 4000:
            raise HTTPException(422, f"Mô tả công việc dài {len(jd)} ký tự, tối đa 4000.")
        p.job_description = jd
    if "responsibilities" in fields:
        p.responsibilities = _clean_list(data.get("responsibilities"), "Trách nhiệm", limit=20)
    if "kpis" in fields:
        p.kpis = _clean_kpis(data.get("kpis"))
    if "allowed_tools" in fields:
        from app.services.tool_permissions import all_tools
        names = _clean_list(data.get("allowed_tools"), "Công cụ được phép", limit=60, each=80)
        bad = [n for n in names if n not in all_tools()]
        if bad:
            raise HTTPException(422, "Không có công cụ: " + ", ".join(bad) + ". Chọn từ danh sách công cụ công ty.")
        p.allowed_tools = names
    if "allowed_skills" in fields:
        p.allowed_skills = _clean_list(data.get("allowed_skills"), "Kỹ năng", limit=30, each=80)
    if "headcount" in fields:
        hc = data.get("headcount")
        if hc is None or int(hc) < 0 or int(hc) > 500:
            raise HTTPException(422, "Định biên phải từ 0 đến 500.")
        filled = len(seats_of(db, p.id)) if p.id else 0
        if int(hc) < filled:
            raise HTTPException(409, f"Đang có {filled} người/agent ngồi chức danh này, không hạ định biên xuống {hc} được. "
                                     "Gỡ bớt người khỏi chức danh trước.")
        p.headcount = int(hc)
    if "reports_to_position_id" in fields:
        boss = data.get("reports_to_position_id")
        if boss:
            b = _position(db, org_id, boss)
            if b.company_id != p.company_id:
                raise HTTPException(422, "Chức danh cấp trên phải cùng công ty.")
            seen, cur = {p.id}, b
            while cur is not None:
                if cur.id in seen:
                    raise HTTPException(422, "Báo cáo vòng tròn: chức danh cấp trên lại báo cáo (gián tiếp) cho chức danh này.")
                seen.add(cur.id)
                cur = db.get(Position, cur.reports_to_position_id) if cur.reports_to_position_id else None
        p.reports_to_position_id = boss or None


def create_position(db: Session, org_id: int, data: dict) -> Position:
    co = _company(db, org_id, data.get("company_id"))
    p = Position(organization_id=org_id, company_id=co.id, title="", headcount=1, status="active")
    fields = {k for k in data if k != "company_id"} | {"title"}
    _apply(db, org_id, p, {"headcount": 1, **data}, fields | {"headcount"} if "headcount" not in data else fields)
    db.add(p); db.commit(); db.refresh(p)
    return p


def update_position(db: Session, org_id: int, position_id: int, data: dict, fields: set[str]) -> tuple[Position, bool]:
    """Trả (chức danh, có ảnh hưởng tới AGENTS.md của người ngồi không)."""
    p = _position(db, org_id, position_id)
    before = (p.title, p.job_description, p.responsibilities, p.kpis, p.allowed_tools, p.allowed_skills, p.headcount)
    _apply(db, org_id, p, data, fields)
    db.add(p)
    if "title" in fields:
        for m in seats_of(db, p.id):          # members.role = chức danh: giữ khớp cho tri thức nghề + eval
            m.role = p.title; db.add(m)
    db.commit(); db.refresh(p)
    after = (p.title, p.job_description, p.responsibilities, p.kpis, p.allowed_tools, p.allowed_skills, p.headcount)
    return p, before != after


def archive_position(db: Session, org_id: int, position_id: int) -> dict:
    p = _position(db, org_id, position_id)
    seats = seats_of(db, p.id)
    if seats:
        raise HTTPException(409, f"Chức danh còn {len(seats)} người ngồi ({', '.join(m.name for m in seats[:3])}). "
                                 "Chuyển họ sang chức danh khác rồi mới lưu trữ.")
    for child in db.query(Position).filter(Position.reports_to_position_id == p.id).all():
        child.reports_to_position_id = p.reports_to_position_id; db.add(child)
    p.status = "archived"; db.add(p); db.commit()
    return {"id": p.id, "status": "archived"}


def assign_seat(db: Session, org_id: int, position_id: int, member_id: int, *, allow_over: bool = False) -> dict:
    p = _position(db, org_id, position_id)
    m = db.get(Member, member_id)
    if m is None or m.organization_id != org_id or m.status == "archived":
        raise HTTPException(404, "Không thấy người/agent này.")
    if m.company_id != p.company_id:
        raise HTTPException(422, "Người/agent và chức danh phải cùng công ty.")
    if m.position_id == p.id:
        return public_position(db, p)
    filled = len(seats_of(db, p.id))
    if filled >= (p.headcount or 0) and not allow_over:
        raise HTTPException(409, f"Chức danh \"{p.title}\" đã đủ định biên ({filled}/{p.headcount}). "
                                 "Tăng định biên hoặc gỡ một người ra trước.")
    m.position_id = p.id
    m.role = p.title
    if p.department_id and m.department_id != p.department_id:
        m.department_id = p.department_id
    db.add(m); db.commit()
    return public_position(db, p)


def unassign_seat(db: Session, org_id: int, position_id: int, member_id: int) -> dict:
    p = _position(db, org_id, position_id)
    m = db.get(Member, member_id)
    if m is None or m.position_id != p.id:
        raise HTTPException(404, "Người/agent này không ngồi chức danh đó.")
    m.position_id = None; db.add(m); db.commit()
    return public_position(db, p)


def position_of(db: Session, member: Member | None) -> Position | None:
    if member is None or not getattr(member, "position_id", None):
        return None
    p = db.get(Position, member.position_id)
    return p if p is not None and p.status != "archived" else None


def position_brief(db: Session, member: Member | None) -> dict | None:
    """Phần chức danh để biên dịch vào AGENTS.md (None khi chưa xếp ghế)."""
    return brief_of(db, position_of(db, member))


def brief_of(db: Session, p: Position | None) -> dict | None:
    if p is None:
        return None
    boss = db.get(Position, p.reports_to_position_id) if p.reports_to_position_id else None
    return {"title": p.title, "job_description": p.job_description or "", "responsibilities": p.responsibilities or [],
            "kpis": p.kpis or [], "allowed_tools": p.allowed_tools or [], "allowed_skills": p.allowed_skills or [],
            "headcount": p.headcount or 0, "reports_to": boss.title if boss else ""}


PERIOD_VI = {"day": "ngày", "week": "tuần", "month": "tháng", "quarter": "quý", "year": "năm"}


def kpi_line(k: dict) -> str:
    tgt = k.get("target")
    tgt_s = (f"{tgt:g}" if isinstance(tgt, (int, float)) else str(tgt or "")).strip()
    goal = f": {tgt_s}{(' ' + k['unit']) if k.get('unit') else ''}" if tgt_s else ""
    return f"- {k['name']}{goal} / {PERIOD_VI.get(k.get('period') or 'month', k.get('period') or '')}"


def seated_agent_ids(db: Session, position_id: int) -> list[int]:
    return [a.id for a in db.query(Agent).join(Member, Member.id == Agent.member_id)
            .filter(Member.position_id == position_id, Agent.lifecycle.notin_(("retired",))).all()]


def positions_from_members(db: Session, org_id: int, company_id: int, *, jd_by_title: dict[str, str] | None = None) -> dict:
    """Người/agent chưa có chức danh → gom theo (phòng, chức danh) thành chức danh và xếp ghế.
    Cùng luật với migration 0038; dùng cho mẫu công ty, nhập CSV và nút "Tạo từ người đang có"."""
    members = (db.query(Member).filter(Member.company_id == company_id, Member.position_id.is_(None),
                                       Member.status != "archived").order_by(Member.id).all())
    groups: dict[tuple, list[Member]] = {}
    for m in members:
        if (m.role or "").strip():
            groups.setdefault((m.department_id, m.role.strip()), []).append(m)
    created, placed = 0, 0
    pos_of: dict[int, Position] = {}
    for (dept, title), ms in groups.items():
        p = (db.query(Position).filter(Position.company_id == company_id, Position.department_id == dept,
                                       Position.title == title, Position.status != "archived").first())
        if p is None:
            p = Position(organization_id=org_id, company_id=company_id, department_id=dept, title=title[:160],
                         job_description=(jd_by_title or {}).get(title, ""), headcount=len(ms), status="active")
            db.add(p); db.flush(); created += 1
        else:
            p.headcount = max(p.headcount or 0, len(seats_of(db, p.id)) + len(ms))
        for m in ms:
            m.position_id = p.id; db.add(m); placed += 1; pos_of[m.id] = p
    db.flush()
    for (dept, title), ms in groups.items():
        p = pos_of[ms[0].id]
        if p.reports_to_position_id:
            continue
        boss = next((db.get(Member, m.manager_id) for m in ms if m.manager_id), None)
        if boss is not None and boss.position_id and boss.position_id != p.id:
            p.reports_to_position_id = boss.position_id; db.add(p)
    db.commit()
    return {"created": created, "placed": placed}
