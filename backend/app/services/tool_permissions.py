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
_EXECUTOR_OFF = {"company_budget_check", "company_task_assign", "company_plan_submit"}  # D3.3: kế hoạch là của seat chiến lược  # D3.1: giao việc là của trưởng phòng


class _GatewayTool:
    """Tool của chính gateway OpenClaw (không qua MCP công ty) mà ClawCompany phân quyền.

    Không gọi được qua MCP; mức quyền được biên dịch thành cấu hình gateway
    (``seat_provision.seat_deny`` / ``exec.mode``)."""
    def __init__(self, name: str, description: str):
        self.name, self.group, self.writes, self.description = name, "gateway", True, description


SHELL = "gateway_shell"
GATEWAY_TOOLS = {
    SHELL: _GatewayTool(SHELL, "Chạy lệnh shell trên máy chủ gateway (exec/process). "
                               "Hỏi = lệnh chưa có trong danh sách cho phép phải chờ người duyệt; "
                               "duyệt \"luôn cho phép\" thì lần sau lệnh đó chạy thẳng."),
}
# Ghế điều hành có shell nhưng mặc định phải hỏi; thừa hành không có.
_GATEWAY_DEFAULTS = {"lead": {SHELL: "ask"}, "executor": {SHELL: "off"}}


# ------------------------------------------------------------- lưới quyền theo hành động
#
# Mỗi tool thuộc một loại hành động. Mức thật của một tool = mức CHẶT hơn giữa
# hàng của tool và hàng của loại hành động. Nhờ vậy "Trả tiền: Tắt" cho thừa
# hành chặn luôn mọi tool trả tiền kết nối sau này, không phải nhớ từng tool.
# Lưu chung bảng tool_permissions, tên ``action:<loại>``.

class _ActionClass:
    def __init__(self, key: str, label: str, description: str):
        self.name, self.group, self.writes = f"action:{key}", "action", key != "read"
        self.key, self.label, self.description = key, label, description


ACTION_CLASSES = {a.name: a for a in (
    _ActionClass("read", "Đọc", "Xem dữ liệu công ty: việc, tài liệu, sơ đồ, số liệu."),
    _ActionClass("draft", "Ghi nội bộ", "Tạo/sửa trong công ty: bình luận, đổi trạng thái, soạn tài liệu, nhắn đồng nghiệp."),
    _ActionClass("send", "Gửi ra ngoài", "Gửi email, tin nhắn cho khách hoặc đối tác bên ngoài công ty."),
    _ActionClass("pay", "Trả tiền", "Thanh toán, chuyển tiền, mua hàng, hoàn tiền."),
    _ActionClass("delete", "Xoá", "Xoá dữ liệu không khôi phục được."),
)}
# Tool chưa liệt kê: không ghi → read, có ghi → draft (nội bộ).
_TOOL_ACTION: dict[str, str] = {}
_ACTION_DEFAULTS = {
    "lead": {"read": "allowed", "draft": "allowed", "send": "ask", "pay": "ask", "delete": "ask"},
    "executor": {"read": "allowed", "draft": "allowed", "send": "ask", "pay": "off", "delete": "off"},
}
_STRICT = {"allowed": 0, "ask": 1, "off": 2}


def action_of(tool: str) -> str | None:
    """Loại hành động của một tool công ty (None với tool gateway/loại hành động)."""
    from app.services.company_mcp import TOOLS
    t = TOOLS.get(tool)
    if t is None:
        return None
    return _TOOL_ACTION.get(tool) or getattr(t, "action", None) or ("draft" if t.writes else "read")


def all_tools() -> dict:
    from app.services.company_mcp import TOOLS
    return {**TOOLS, **GATEWAY_TOOLS, **ACTION_CLASSES}


def _defaults() -> dict[str, dict[str, str]]:
    from app.services.company_mcp import TOOLS
    return {
        tier: {**base, **_GATEWAY_DEFAULTS[tier],
               **{f"action:{k}": v for k, v in _ACTION_DEFAULTS[tier].items()}}
        for tier, base in (
            ("lead", {name: "allowed" for name in TOOLS}),
            ("executor", {name: ("off" if name in _EXECUTOR_OFF else "allowed") for name in TOOLS}))
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
    """(mức, nguồn). Nguồn: ``member`` | ``tier:<bậc>`` | ``default:<bậc>`` | ``unknown_tool``
    | ``action:<loại>/<nguồn>`` khi loại hành động chặt hơn hàng của tool."""
    level, source = _resolve_one(db, member, tool)
    pos = _position_gate(db, member, tool)
    if pos is not None:
        return pos
    cls = action_of(tool)
    if tool.startswith("action:") and level != "off":
        cls_key = tool.split(":", 1)[1]
        floor = _authority_floor(db, member, cls_key)
        if floor and _STRICT[floor[0]] > _STRICT[level]:
            return floor
    if cls and level != "off":
        a_level, a_source = resolve(db, member, f"action:{cls}")
        if _STRICT[a_level] > _STRICT[level]:
            return a_level, f"action:{cls}/{a_source}"
    return level, source


def _authority_floor(db: Session, member: Member, action_class: str) -> tuple[str, str] | None:
    """M2b: ma trận phân quyền chỉ SIẾT lưới (agent chưa đủ cấp tự làm → ít nhất "Hỏi trước")."""
    try:
        from app.services import authority
        return authority.tool_floor(db, member, action_class)
    except Exception as exc:  # noqa: BLE001 — ma trận lỗi không được mở toang lưới, cũng không chặn đọc
        print(f"[authority] floor {exc}")
        return None


def _position_gate(db: Session, member: Member, tool: str) -> tuple[str, str] | None:
    """M2b: chức danh có danh sách công cụ → tool công ty ngoài danh sách bị tắt cho người ngồi ghế đó."""
    if not tool.startswith("company_") or not getattr(member, "position_id", None):
        return None
    from app.models.company_foundation import Position
    p = db.get(Position, member.position_id)
    allowed = (p.allowed_tools or []) if p is not None and p.status != "archived" else []
    if allowed and tool not in allowed:
        return "off", f"position:{p.id}"
    return None


def _resolve_one(db: Session, member: Member, tool: str) -> tuple[str, str]:
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
    d = None
    try:   # M2b: người duyệt theo ma trận phân quyền (loại hành động của tool)
        from app.services import authority
        cls = action_of(tool) or (tool.split(":", 1)[1] if tool.startswith("action:") else None)
        at = authority.TOOL_CLASS_TO_ACTION.get(cls or "")
        d = authority.decide(db, member, at) if at else None
    except Exception as exc:  # noqa: BLE001
        print(f"[authority] ask {exc}")
    approval = Approval(organization_id=member.organization_id, company_id=member.company_id,
                        requester_member_id=member.id, action=action, risk="medium",
                        approver_member_id=d.approver_member_id if d else None,
                        payload={"authority": d.card()} if d else None,
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
    TOOLS = all_tools()
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
                       "description": t.description, "action": action_of(t.name),
                       "label": getattr(t, "label", None)} for t in TOOLS.values()],
            "matrix": tiers, "member_overrides": overrides}
