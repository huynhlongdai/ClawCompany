"""D1.6 — seat agent được dùng tool nào, ở mức nào.

Hai lớp chặn: ``toolFilter.include`` ở gateway OpenClaw (lớp 1, cấu hình bên
ngoài) và hàm ``decide`` ở đây (lớp 2, API). Lớp 2 không tin lớp 1: một seat
thừa hành gọi ``company_budget_check`` bị 403 kể cả khi gateway đã cho qua.

Thứ tự ưu tiên: hàng theo ``member_id`` > hàng theo bậc seat > ``DEFAULTS``.
Tool không có trong danh mục → ``off`` (mặc định từ chối).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Approval, Department, Member, ToolPermission
from app.models.tool_access import TOOL_LEVELS

TIERS = ("lead", "executor")
ASK_GRANT_HOURS = 24

# Mặc định theo bậc seat. Thừa hành không xem ngân sách (việc của trưởng
# phòng); mọi thứ khác của một nhân viên bình thường đều được.
_EXECUTOR_OFF = {"company_budget_check", "company_task_assign"}  # D3.1: giao việc là của trưởng phòng


def _defaults() -> dict[str, dict[str, str]]:
    from app.services.company_mcp import TOOLS
    return {
        "lead": {name: "allowed" for name in TOOLS},
        "executor": {name: ("off" if name in _EXECUTOR_OFF else "allowed") for name in TOOLS},
    }


def seat_tier(db: Session, member: Member) -> str:
    """``lead`` = không thuộc phòng nào (điều hành), là trưởng phòng, hoặc có
    người báo cáo trực tiếp. Còn lại là ``executor`` (thừa hành)."""
    if not member.department_id:
        return "lead"
    head = db.execute(select(Department.id).where(Department.head_member_id == member.id)).first()
    if head:
        return "lead"
    report = db.execute(select(Member.id).where(Member.manager_id == member.id)).first()
    return "lead" if report else "executor"


def resolve(db: Session, member: Member, tool: str) -> tuple[str, str]:
    """(mức, nguồn). Nguồn: ``member`` | ``tier:<bậc>`` | ``default:<bậc>`` | ``unknown_tool``."""
    defaults = _defaults()
    tier = seat_tier(db, member)
    rows = db.execute(select(ToolPermission).where(
        ToolPermission.organization_id == member.organization_id,
        ToolPermission.tool == tool)).scalars().all()
    for r in rows:
        if r.member_id == member.id:
            return r.level, "member"
    for r in rows:
        if r.member_id is None and r.role == tier:
            return r.level, f"tier:{tier}"
    if tool not in defaults[tier]:
        return "off", "unknown_tool"
    return defaults[tier][tool], f"default:{tier}"


def ask_approval(db: Session, member: Member, tool: str, evidence: str) -> tuple[str, Approval | None]:
    """Mức ``ask``: có approval đã duyệt trong 24h → ``granted``; đang chờ →
    ``pending`` (dùng lại hàng cũ); chưa có → tạo hàng mới và ``pending``."""
    action = f"tool:{tool}"
    recent = db.execute(select(Approval).where(
        Approval.organization_id == member.organization_id,
        Approval.requester_member_id == member.id, Approval.action == action)
        .order_by(Approval.id.desc())).scalars().first()
    if recent is not None:
        if recent.status == "approved" and recent.updated_at and \
                recent.updated_at >= datetime.utcnow() - timedelta(hours=ASK_GRANT_HOURS):
            return "granted", recent
        if recent.status == "pending":
            return "pending", recent
    approval = Approval(organization_id=member.organization_id, company_id=member.company_id,
                        requester_member_id=member.id, action=action, risk="medium",
                        policy_key=action, evidence=evidence[:4000], status="pending")
    db.add(approval); db.commit(); db.refresh(approval)
    return "pending", approval


def set_level(db: Session, organization_id: int, tool: str, level: str, *,
              role: str | None = None, member_id: int | None = None,
              actor_member_id: int | None = None) -> ToolPermission | None:
    """Đặt mức; ``level=None``/``"inherit"`` thì xoá hàng (quay về mặc định)."""
    if (role is None) == (member_id is None):
        raise ValueError("cần đúng một trong role hoặc member_id")
    if role is not None and role not in TIERS:
        raise ValueError(f"role phải là một trong {', '.join(TIERS)}")
    row = db.execute(select(ToolPermission).where(
        ToolPermission.organization_id == organization_id, ToolPermission.tool == tool,
        ToolPermission.role.is_(None) if role is None else ToolPermission.role == role,
        ToolPermission.member_id.is_(None) if member_id is None
        else ToolPermission.member_id == member_id)).scalars().first()
    if level in (None, "inherit"):
        if row is not None:
            db.delete(row); db.commit()
        return None
    if level not in TOOL_LEVELS:
        raise ValueError(f"level phải là một trong {', '.join(TOOL_LEVELS)}")
    if row is None:
        row = ToolPermission(organization_id=organization_id, role=role, member_id=member_id,
                             tool=tool)
    row.level = level
    row.updated_by_member_id = actor_member_id
    db.add(row); db.commit(); db.refresh(row)
    return row


def matrix(db: Session, organization_id: int) -> dict:
    from app.services.company_mcp import TOOLS
    defaults = _defaults()
    rows = db.execute(select(ToolPermission).where(
        ToolPermission.organization_id == organization_id)).scalars().all()
    tiers = {t: {name: {"level": defaults[t][name], "source": "default"} for name in TOOLS}
             for t in TIERS}
    overrides = []
    for r in rows:
        if r.member_id is None and r.role in tiers and r.tool in TOOLS:
            tiers[r.role][r.tool] = {"level": r.level, "source": "override"}
        elif r.member_id is not None:
            overrides.append({"member_id": r.member_id, "tool": r.tool, "level": r.level})
    return {"levels": list(TOOL_LEVELS), "tiers": list(TIERS),
            "tools": [{"name": t.name, "group": t.group, "writes": t.writes,
                       "description": t.description} for t in TOOLS.values()],
            "matrix": tiers, "member_overrides": overrides}
