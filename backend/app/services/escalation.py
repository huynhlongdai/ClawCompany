"""M2e — chuỗi leo thang chung (hợp đồng dữ liệu M2e.3, SLA M2e.4): ai là NGƯỜI nhận khi một ghế không xử lý xong.

Thứ tự: chức danh cấp trên (``positions.reports_to_position_id``, ưu tiên người ngồi ghế là người) → quản lý trực
tiếp (``members.manager_id``) → trưởng phòng → chủ doanh nghiệp. Agent không nhận leo thang thay người: gặp agent thì
đi tiếp lên người quản lý (người) của agent đó (``inbox.human_recipients``)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Department, Member
from app.models.company_foundation import Position


def chain(db: Session, member: Member | None) -> list[tuple[int, str]]:
    """[(member_id, lý do)] theo thứ tự, chưa lọc người/agent, không trùng, không gồm chính ``member``."""
    out: list[tuple[int, str]] = []

    def add(mid: int | None, why: str) -> None:
        if mid and (member is None or mid != member.id) and mid not in [x for x, _ in out]:
            out.append((mid, why))
    if member is None:
        return out
    pos = db.get(Position, member.position_id) if getattr(member, "position_id", None) else None
    if pos is not None and pos.reports_to_position_id:
        boss = db.get(Position, pos.reports_to_position_id)
        seats = (db.query(Member).filter(Member.position_id == pos.reports_to_position_id,
                                         Member.status.notin_(("archived", "retired")))
                 .order_by(Member.member_type.desc(), Member.id).all())     # "human" > "agent"
        for s in seats:
            add(s.id, f"chức danh cấp trên {boss.title if boss else ''}".strip())
    add(member.manager_id, "quản lý trực tiếp")
    dept = db.get(Department, member.department_id) if member.department_id else None
    if dept is not None:
        add(dept.head_member_id, f"trưởng phòng {dept.name}")
    from app.services import authority
    add(authority.owner_member(db, member.organization_id, member.company_id), "chủ doanh nghiệp")
    return out


def human_target(db: Session, member: Member | None) -> tuple[int | None, str]:
    """NGƯỜI đầu tiên trong chuỗi (agent trong chuỗi → người quản lý của agent đó)."""
    from app.services import inbox
    for mid, why in chain(db, member):
        humans = [h for h in inbox.human_recipients(db, mid) if member is None or h != member.id]
        if humans:
            m = db.get(Member, mid)
            if m is not None and m.member_type != "human":
                why = f"{why} ({m.name} là agent → người quản lý của {m.name})"
            return humans[0], why
    return None, "không tìm thấy người nhận"
