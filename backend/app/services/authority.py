"""M2b — Ma trận phân quyền (Delegation of Authority): một chỗ quyết ai duyệt gì.

Một luật = loại việc × dải tiền USD [min, max) × mức rủi ro tối thiểu → người duyệt
(none | manager | department_head | position | owner) + cấp tự chủ tối thiểu để một
agent được tự làm (probation < standard < trusted; rỗng = không bao giờ).

``decide`` là adapter mà các đường cũ gọi trước khi rơi về hành vi cũ:

* ``policy.authorize`` (tool MCP ``company_approval_request`` / ``company_policy_check``)
* ``tool_permissions.resolve`` + ``ask_approval`` (lưới gửi/trả tiền/xoá của seat)
* ``budget_scope`` (chi tiếp khi chạm nấc dừng mềm)
* ``runtime_stream`` (lệnh exec agent xin chạy trên gateway)
* ``orchestration.create_cycle`` (chạy kế hoạch tự động — thay ngưỡng max_auto_risk)
* ``agent_hr.hire`` (tuyển agent)

Không có luật khớp → ``None`` → nơi gọi giữ nguyên hành vi trước M2b.

Giới hạn tự khai (enforced vs advisory):
* với lưới tool (send/pay/delete) ma trận CHỈ siết, không nới: mức thật = chặt hơn giữa
  lưới và ma trận. Lưới là cổng runtime cứng; ma trận không mở được thứ lưới đã tắt.
* tool gọi qua lưới không mang số tiền → dùng dải thấp nhất của loại việc đó. Số tiền
  chỉ được xét khi agent xin duyệt qua ``company_approval_request`` kèm ``amount_usd``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Agent, Company, Department, Member, User, UserOrganizationAccess
from app.models.company_foundation import AuthorityRule, Position

ACTION_TYPES = {
    "spend": {"vi": "Chi tiền / mua hàng", "en": "Spend / purchase", "money": True},
    "refund": {"vi": "Hoàn tiền / giảm giá", "en": "Refund / discount", "money": True},
    "external_message": {"vi": "Gửi tin / đăng ra ngoài", "en": "External message / publish", "money": False},
    "contract": {"vi": "Ký hợp đồng / cam kết", "en": "Contract / commitment", "money": True},
    "data_export": {"vi": "Xuất dữ liệu", "en": "Data export", "money": False},
    "data_delete": {"vi": "Xoá dữ liệu", "en": "Delete data", "money": False},
    "exec": {"vi": "Chạy lệnh / công cụ hệ thống", "en": "Run command / system tool", "money": False},
    "hire_agent": {"vi": "Tuyển agent", "en": "Hire an agent", "money": True},
    "budget_overrun": {"vi": "Chạy tiếp khi vượt nấc ngân sách", "en": "Continue past budget stop", "money": True},
    "goal_execute": {"vi": "Chạy kế hoạch tự động", "en": "Auto-run a plan", "money": True},
}
# Từ đồng nghĩa agent hay dùng khi gọi company_approval_request(action=…)
ALIASES = {
    "pay": "spend", "payment": "spend", "purchase": "spend", "chi": "spend", "chi tiền": "spend", "mua": "spend",
    "discount": "refund", "hoàn tiền": "refund", "hoan tien": "refund", "giảm giá": "refund", "voucher": "refund",
    "send": "external_message", "publish": "external_message", "post": "external_message",
    "gửi khách": "external_message", "đăng bài": "external_message",
    "sign_contract": "contract", "hợp đồng": "contract",
    "export": "data_export", "xuất dữ liệu": "data_export",
    "delete": "data_delete", "xoá": "data_delete", "xóa": "data_delete",
    "shell": "exec", "command": "exec",
    "hire": "hire_agent",
}
TOOL_CLASS_TO_ACTION = {"send": "external_message", "pay": "spend", "delete": "data_delete"}
APPROVER_KINDS = {
    "none": {"vi": "Không cần duyệt", "en": "No approval"},
    "manager": {"vi": "Quản lý trực tiếp", "en": "Direct manager"},
    "department_head": {"vi": "Trưởng phòng", "en": "Department head"},
    "position": {"vi": "Chức danh cụ thể", "en": "Specific position"},
    "owner": {"vi": "Chủ doanh nghiệp", "en": "Owner"},
}
LEVELS = ("probation", "standard", "trusted")
LEVEL_VI = {"": "Không bao giờ", "probation": "Từ thử việc", "standard": "Từ chính thức", "trusted": "Chỉ tin cậy"}
RISKS = ("low", "medium", "high", "critical")
RISK_ORDER = {r: i for i, r in enumerate(RISKS)}


@dataclass
class AuthorityDecision:
    rule_id: int
    action_type: str
    label: str                       # "Hoàn tiền / giảm giá · $50–$200 → Trưởng phòng"
    approver_kind: str
    requires_approval: bool          # người xin (với mức tự chủ hiện tại) có phải xin duyệt không
    approver_member_id: int | None
    approver_name: str | None
    agent_may_act_alone: bool | None  # None khi người xin là người
    reason: str
    notes: list[str] = field(default_factory=list)

    min_amount_usd: float | None = None
    max_amount_usd: float | None = None

    def card(self) -> dict:
        """Phần lưu vào approvals.payload["authority"] để Hộp việc hiện luật nào đã kích hoạt."""
        return {"rule_id": self.rule_id, "action_type": self.action_type, "label": self.label,
                "approver_kind": self.approver_kind, "approver_name": self.approver_name, "reason": self.reason,
                "min_amount_usd": self.min_amount_usd, "max_amount_usd": self.max_amount_usd}

    def as_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ chuẩn hoá

def normalize_action(action: str | None) -> str | None:
    a = (action or "").strip().lower()
    if not a:
        return None
    if a in ACTION_TYPES:
        return a
    if a in ALIASES:
        return ALIASES[a]
    head = a.split(":", 1)[0].split(".", 1)[0].strip()
    if head in ACTION_TYPES:
        return head
    return ALIASES.get(head)


def money(v: float | None) -> str:
    if v is None:
        return ""
    return f"${v:,.0f}" if float(v).is_integer() else f"${v:,.2f}"


def band_label(r: AuthorityRule) -> str:
    lo, hi = r.min_amount_usd, r.max_amount_usd
    if lo is None and hi is None:
        return "mọi mức tiền" if ACTION_TYPES.get(r.action_type, {}).get("money") else ""
    if lo in (None, 0) and hi is not None:
        return f"dưới {money(hi)}"
    if hi is None:
        return f"từ {money(lo)}"
    return f"{money(lo)}–{money(hi)}"


def rule_label(db: Session, r: AuthorityRule) -> str:
    at = ACTION_TYPES.get(r.action_type, {}).get("vi", r.action_type)
    band = band_label(r)
    who = APPROVER_KINDS.get(r.approver_kind, {}).get("vi", r.approver_kind)
    if r.approver_kind == "position" and r.approver_position_id:
        p = db.get(Position, r.approver_position_id)
        who = f"chức danh {p.title}" if p else who
    risk = f" · rủi ro từ {r.min_risk}" if r.min_risk else ""
    return f"{at}{' · ' + band if band else ''}{risk} → {who}"


# ------------------------------------------------------------------ chọn luật

def _rules(db: Session, company_id: int | None, action_type: str) -> list[AuthorityRule]:
    if not company_id:
        return []
    return (db.query(AuthorityRule).filter(AuthorityRule.company_id == company_id,
                                           AuthorityRule.action_type == action_type,
                                           AuthorityRule.enabled.is_(True)).order_by(AuthorityRule.id).all())


def match(db: Session, company_id: int | None, action_type: str, amount_usd: float | None = None,
          risk: str | None = None) -> AuthorityRule | None:
    """Luật khớp chặt nhất. Không biết số tiền → dải thấp nhất (luật có min nhỏ nhất)."""
    rules = _rules(db, company_id, action_type)
    rr = RISK_ORDER.get((risk or "").lower())
    ok = []
    for r in rules:
        if r.min_risk:
            if rr is None or rr < RISK_ORDER.get(r.min_risk, 0):
                continue
        if amount_usd is not None:
            if r.min_amount_usd is not None and amount_usd < r.min_amount_usd:
                continue
            if r.max_amount_usd is not None and amount_usd >= r.max_amount_usd:
                continue
        ok.append(r)
    if not ok:
        return None
    if amount_usd is None:
        lowest = min((r.min_amount_usd or 0) for r in ok)
        ok = [r for r in ok if (r.min_amount_usd or 0) == lowest]
    # chặt nhất: dải cao nhất, rồi luật có điều kiện rủi ro, rồi id nhỏ
    ok.sort(key=lambda r: (-(r.min_amount_usd or 0), -RISK_ORDER.get(r.min_risk or "", -1), r.id))
    return ok[0]


# ------------------------------------------------------------------ người duyệt

def _first_human(db: Session, member_id: int | None) -> int | None:
    from app.services import inbox
    got = inbox.human_recipients(db, member_id) if member_id else []
    return got[0] if got else None


def owner_member(db: Session, organization_id: int, company_id: int | None) -> int | None:
    rows = (db.query(User.member_id).join(UserOrganizationAccess, UserOrganizationAccess.user_id == User.id)
            .filter(UserOrganizationAccess.organization_id == organization_id, UserOrganizationAccess.role == "owner",
                    UserOrganizationAccess.status == "active", User.member_id.isnot(None))
            .order_by(UserOrganizationAccess.id).all())
    for (mid,) in rows:
        m = db.get(Member, mid)
        if m is not None and m.status != "archived" and (company_id is None or m.company_id in (None, company_id)):
            return m.id
    from app.services.inbox import _top_humans
    top = _top_humans(db, organization_id, company_id)
    return top[0] if top else None


def resolve_approver(db: Session, r: AuthorityRule, requester: Member | None) -> tuple[int | None, list[str]]:
    """(member_id người duyệt là NGƯỜI, ghi chú khi phải chuyển lên). Agent không duyệt thay người."""
    notes: list[str] = []
    org = r.organization_id
    if r.approver_kind == "none":
        return None, notes
    target = None
    if r.approver_kind == "manager" and requester is not None:
        target = requester.manager_id
        if target is None:
            notes.append("Người xin chưa có quản lý trực tiếp → chuyển chủ doanh nghiệp.")
    elif r.approver_kind == "department_head" and requester is not None:
        dept = db.get(Department, requester.department_id) if requester.department_id else None
        target = dept.head_member_id if dept else None
        if target is None:
            notes.append("Phòng của người xin chưa có trưởng phòng → chuyển chủ doanh nghiệp.")
        elif requester is not None and target == requester.id:
            target = requester.manager_id
            notes.append("Người xin chính là trưởng phòng → chuyển lên quản lý của trưởng phòng.")
    elif r.approver_kind == "position" and r.approver_position_id:
        seats = (db.query(Member).filter(Member.position_id == r.approver_position_id, Member.status != "archived")
                 .order_by(Member.member_type.desc(), Member.id).all())   # "human" > "agent"
        target = seats[0].id if seats else None
        if target is None:
            notes.append("Chức danh duyệt đang trống người → chuyển chủ doanh nghiệp.")
    if r.approver_kind != "owner" and target is not None:
        human = _first_human(db, target)
        tm = db.get(Member, target)
        if tm is not None and tm.member_type != "human" and human:
            hm = db.get(Member, human)
            notes.append(f"Người duyệt theo luật là agent ({tm.name}) → chuyển lên người quản lý {hm.name if hm else ''}.".strip())
        if human and requester is not None and human == requester.id:
            human = _first_human(db, requester.manager_id) if requester.manager_id else None
        if human:
            return human, notes
    return owner_member(db, org, requester.company_id if requester else None), notes


# ------------------------------------------------------------------ quyết

def career_level(db: Session, member: Member) -> str:
    """Cấp tự chủ của seat agent (M6 career); người → ''."""
    if member.member_type != "agent":
        return ""
    ag = db.query(Agent).filter(Agent.member_id == member.id).first()
    if ag is None:
        return "probation"
    from app.services import agent_hr
    try:
        return (agent_hr.hire_spec(db, ag).get("career_level") or "standard")
    except Exception:  # noqa: BLE001
        return "standard"


def decide(db: Session, requester: Member | None, action_type: str | None, *, amount_usd: float | None = None,
           risk: str | None = None, company_id: int | None = None) -> AuthorityDecision | None:
    at = normalize_action(action_type)
    if at is None:
        return None
    cid = company_id or (requester.company_id if requester is not None else None)
    r = match(db, cid, at, amount_usd, risk)
    if r is None:
        return None
    label = rule_label(db, r)
    approver, notes = resolve_approver(db, r, requester)
    approver_name = (db.get(Member, approver).name if approver else None)
    is_agent = requester is not None and requester.member_type == "agent"
    alone = None
    if r.approver_kind == "none":
        needs, reason = False, "Luật cho phép làm không cần duyệt."
        alone = True if is_agent else None
    elif is_agent:
        lvl = career_level(db, requester)
        min_lvl = r.agent_alone_level or ""
        alone = bool(min_lvl) and LEVELS.index(lvl) >= LEVELS.index(min_lvl) if lvl in LEVELS else False
        needs = not alone
        reason = (f"Agent cấp {lvl} được tự làm (luật cho phép {LEVEL_VI.get(min_lvl, min_lvl).lower()})." if alone
                  else f"Agent cấp {lvl} chưa được tự làm ({LEVEL_VI.get(min_lvl, min_lvl).lower()}) → cần {approver_name or 'người duyệt'} duyệt.")
    else:
        needs = approver is not None and requester is not None and approver != requester.id
        reason = f"Cần {approver_name} duyệt." if needs else "Người xin chính là người có quyền duyệt."
    return AuthorityDecision(rule_id=r.id, action_type=at, label=label, approver_kind=r.approver_kind,
                             requires_approval=needs, approver_member_id=approver, approver_name=approver_name,
                             agent_may_act_alone=alone, reason=reason, notes=notes,
                             min_amount_usd=r.min_amount_usd, max_amount_usd=r.max_amount_usd)


def tool_floor(db: Session, member: Member, action_class: str) -> tuple[str, str] | None:
    """Mức tối thiểu ma trận đặt cho lưới tool (send/pay/delete): ``("ask", nguồn)`` khi agent
    chưa được tự làm, ``None`` khi ma trận không có ý kiến / cho tự làm (không nới lưới)."""
    at = TOOL_CLASS_TO_ACTION.get(action_class)
    if not at or member.member_type != "agent":
        return None
    d = decide(db, member, at)
    if d is None or not d.requires_approval:
        return None
    return "ask", f"authority:r{d.rule_id}"


def annotate(payload: dict | None, d: AuthorityDecision | None) -> dict | None:
    if d is None:
        return payload
    return {**(payload or {}), "authority": d.card()}


# ------------------------------------------------------------------ CRUD

def _company(db: Session, org_id: int, company_id: int | None) -> Company:
    from app.services.company_foundation import _company as c
    return c(db, org_id, company_id)


def public_rule(db: Session, r: AuthorityRule) -> dict:
    return {"id": r.id, "company_id": r.company_id, "action_type": r.action_type,
            "action_vi": ACTION_TYPES.get(r.action_type, {}).get("vi", r.action_type),
            "min_amount_usd": r.min_amount_usd, "max_amount_usd": r.max_amount_usd, "band": band_label(r),
            "min_risk": r.min_risk or "", "approver_kind": r.approver_kind, "approver_position_id": r.approver_position_id,
            "agent_alone_level": r.agent_alone_level or "", "note": r.note or "", "enabled": bool(r.enabled),
            "source": r.source, "label": rule_label(db, r)}


def list_rules(db: Session, org_id: int, company_id: int | None) -> dict:
    co = _company(db, org_id, company_id)
    rows = (db.query(AuthorityRule).filter(AuthorityRule.company_id == co.id)
            .order_by(AuthorityRule.action_type, AuthorityRule.min_amount_usd.is_(None).desc(),
                      AuthorityRule.min_amount_usd, AuthorityRule.id).all())
    order = list(ACTION_TYPES)
    rows.sort(key=lambda r: (order.index(r.action_type) if r.action_type in order else 99, r.min_amount_usd or 0, r.id))
    return {"company_id": co.id, "company_name": co.name, "rules": [public_rule(db, r) for r in rows],
            "action_types": [{"key": k, **v} for k, v in ACTION_TYPES.items()],
            "approver_kinds": [{"key": k, **v} for k, v in APPROVER_KINDS.items()],
            "levels": [{"key": k, "vi": LEVEL_VI[k]} for k in ("", *LEVELS)], "risks": list(RISKS),
            "currency": "USD"}


def _apply(db: Session, r: AuthorityRule, data: dict, fields: set[str]) -> None:
    if "action_type" in fields:
        at = normalize_action(data.get("action_type"))
        if at is None:
            raise HTTPException(422, "Loại việc không hợp lệ. Chọn một trong: " + ", ".join(v["vi"] for v in ACTION_TYPES.values()) + ".")
        r.action_type = at
    for k in ("min_amount_usd", "max_amount_usd"):
        if k in fields:
            v = data.get(k)
            if v in (None, ""):
                setattr(r, k, None)
            else:
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    raise HTTPException(422, "Mức tiền phải là số (USD).")
                if v < 0:
                    raise HTTPException(422, "Mức tiền không được âm.")
                setattr(r, k, v)
    if r.min_amount_usd is not None and r.max_amount_usd is not None and r.max_amount_usd <= r.min_amount_usd:
        raise HTTPException(422, f"Dải tiền sai: \"đến\" ({money(r.max_amount_usd)}) phải lớn hơn \"từ\" ({money(r.min_amount_usd)}).")
    if "min_risk" in fields:
        v = (data.get("min_risk") or "").strip().lower()
        if v and v not in RISKS:
            raise HTTPException(422, "Mức rủi ro phải là low / medium / high / critical (hoặc để trống = mọi mức).")
        r.min_risk = v
    if "approver_kind" in fields:
        v = data.get("approver_kind") or ""
        if v not in APPROVER_KINDS:
            raise HTTPException(422, "Người duyệt phải là: " + ", ".join(x["vi"] for x in APPROVER_KINDS.values()) + ".")
        r.approver_kind = v
    if "approver_position_id" in fields:
        pid = data.get("approver_position_id")
        if pid:
            p = db.get(Position, pid)
            if p is None or p.company_id != r.company_id or p.status == "archived":
                raise HTTPException(422, "Chức danh duyệt phải thuộc cùng công ty (tab Chức danh).")
        r.approver_position_id = pid or None
    if r.approver_kind == "position" and not r.approver_position_id:
        raise HTTPException(422, "Đã chọn người duyệt là \"Chức danh cụ thể\" thì cần chọn chức danh.")
    if "agent_alone_level" in fields:
        v = data.get("agent_alone_level") or ""
        if v and v not in LEVELS:
            raise HTTPException(422, "Cấp agent được tự làm phải là: thử việc / chính thức / tin cậy, hoặc để trống = không bao giờ.")
        r.agent_alone_level = v
    if "note" in fields:
        r.note = (data.get("note") or "").strip()[:400]
    if "enabled" in fields and data.get("enabled") is not None:
        r.enabled = bool(data["enabled"])


def _overlap_check(db: Session, r: AuthorityRule) -> None:
    lo, hi = r.min_amount_usd or 0.0, r.max_amount_usd if r.max_amount_usd is not None else float("inf")
    for o in _rules(db, r.company_id, r.action_type):
        if o.id == r.id or (o.min_risk or "") != (r.min_risk or ""):
            continue
        olo, ohi = o.min_amount_usd or 0.0, o.max_amount_usd if o.max_amount_usd is not None else float("inf")
        if lo < ohi and olo < hi:
            raise HTTPException(409, f"Trùng dải tiền với luật đang có: \"{rule_label(db, o)}\". "
                                     "Sửa luật cũ hoặc chọn dải không chồng lên nhau.")


def create_rule(db: Session, org_id: int, data: dict) -> AuthorityRule:
    co = _company(db, org_id, data.get("company_id"))
    r = AuthorityRule(organization_id=org_id, company_id=co.id, action_type="spend", approver_kind="manager",
                      source="custom", enabled=True, min_risk="", agent_alone_level="", note="")
    fields = set(data) - {"company_id"}
    if "action_type" not in fields or "approver_kind" not in fields:
        raise HTTPException(422, "Cần chọn loại việc và người duyệt.")
    _apply(db, r, data, fields)
    if r.enabled:
        _overlap_check(db, r)
    db.add(r); db.commit(); db.refresh(r)
    return r


def _rule(db: Session, org_id: int, rule_id: int) -> AuthorityRule:
    r = db.get(AuthorityRule, rule_id)
    if r is None or r.organization_id != org_id:
        raise HTTPException(404, "Không thấy luật này. Tải lại tab Phân quyền.")
    return r


def update_rule(db: Session, org_id: int, rule_id: int, data: dict, fields: set[str]) -> AuthorityRule:
    r = _rule(db, org_id, rule_id)
    _apply(db, r, data, fields)
    if r.enabled:
        _overlap_check(db, r)
    if r.source != "custom":
        r.source = "custom"
    db.add(r); db.commit(); db.refresh(r)
    return r


def delete_rule(db: Session, org_id: int, rule_id: int) -> dict:
    r = _rule(db, org_id, rule_id)
    db.delete(r); db.commit()
    return {"id": rule_id, "deleted": True}


# ------------------------------------------------------------------ mặc định

def _R(action, lo, hi, who, alone="", note="", risk=""):
    return {"action_type": action, "min_amount_usd": lo, "max_amount_usd": hi, "approver_kind": who,
            "agent_alone_level": alone, "note": note, "min_risk": risk}


# Ma trận mặc định cho mọi công ty. Với lưới tool hiện có (gửi/trả tiền/xoá đều "Hỏi trước")
# nó không đổi hành vi nào — chỉ thêm người duyệt đúng + dải tiền.
DEFAULT_MATRIX = [
    _R("spend", 0, 20, "manager", "trusted", "Khoản nhỏ: agent tin cậy tự chi, còn lại quản lý duyệt."),
    _R("spend", 20, 200, "department_head"),
    _R("spend", 200, None, "owner"),
    _R("refund", 0, 20, "manager", "standard"),
    _R("refund", 20, 100, "department_head"),
    _R("refund", 100, None, "owner"),
    _R("external_message", None, None, "manager", "trusted", "Tin gửi khách/đối tác, bài đăng công khai."),
    _R("contract", None, None, "owner", "", "Mọi cam kết ràng buộc pháp nhân."),
    _R("data_export", None, None, "department_head"),
    _R("data_delete", None, None, "owner"),
    _R("exec", None, None, "manager", "trusted"),
    _R("hire_agent", None, None, "department_head", "", "Người tuyển phải có quyền trưởng phòng trở lên."),
    _R("budget_overrun", None, None, "manager"),
    _R("goal_execute", None, None, "none", "", "Kế hoạch rủi ro thấp/vừa chạy thẳng.", ),
    _R("goal_execute", None, None, "owner", "", "Kế hoạch rủi ro cao trở lên chờ chủ duyệt.", "high"),
]
TEMPLATE_OVERRIDES = {
    "shop": {   # CSKH trả lời khách liên tục; hoàn tiền nhỏ là việc hằng ngày
        "external_message": [_R("external_message", None, None, "manager", "standard", "CSKH chuẩn được trả lời khách.")],
        "refund": [_R("refund", 0, 30, "manager", "standard", "Đổi trả nhỏ theo chính sách."),
                   _R("refund", 30, 100, "department_head"), _R("refund", 100, None, "owner")],
    },
    "agency": {  # tiền quảng cáo đi qua trưởng media; hợp đồng là của giám đốc
        "spend": [_R("spend", 0, 50, "manager", "trusted"), _R("spend", 50, 500, "department_head", "", "Ngân sách ads."),
                  _R("spend", 500, None, "owner")],
        "external_message": [_R("external_message", None, None, "department_head", "", "Mọi thứ gửi khách qua trưởng account.")],
    },
    "ketoan": {  # dữ liệu tài chính của khách: xuất ra là việc của giám đốc
        "data_export": [_R("data_export", None, None, "owner", "", "Hồ sơ tài chính của khách hàng.")],
        "external_message": [_R("external_message", None, None, "department_head", "", "Tờ khai/báo cáo gửi khách hoặc cơ quan thuế.")],
        "spend": [_R("spend", 0, 10, "manager", "trusted"), _R("spend", 10, 100, "department_head"),
                  _R("spend", 100, None, "owner")],
    },
}


def default_matrix(template: str | None = None) -> list[dict]:
    over = TEMPLATE_OVERRIDES.get(template or "", {})
    out = [r for r in DEFAULT_MATRIX if r["action_type"] not in over]
    for rows in over.values():
        out += rows
    order = list(ACTION_TYPES)
    return sorted(out, key=lambda r: (order.index(r["action_type"]), r["min_amount_usd"] or 0, r["min_risk"]))


def seed_defaults(db: Session, organization_id: int, company_id: int, *, template: str | None = None,
                  replace: bool = False) -> dict:
    """Gieo ma trận mặc định. Không đè luật đang có trừ khi ``replace``."""
    existing = db.query(AuthorityRule).filter(AuthorityRule.company_id == company_id).all()
    if existing and not replace:
        return {"seeded": 0, "kept": len(existing)}
    for r in existing:
        db.delete(r)
    src = f"template:{template}" if template in TEMPLATE_OVERRIDES else "default"
    rows = default_matrix(template)
    for spec in rows:
        db.add(AuthorityRule(organization_id=organization_id, company_id=company_id, enabled=True, source=src, **spec))
    db.commit()
    return {"seeded": len(rows), "kept": 0, "source": src}


def require_hire_right(db: Session, principal, company_id: int | None) -> AuthorityDecision | None:
    """Tuyển agent: ma trận nói ai được tuyển. Người dùng không đủ quyền → 403 có cách xử lý."""
    from app.core.authz import ROLE_ORDER
    if not company_id:
        return None
    r = match(db, company_id, "hire_agent")
    if r is None or r.approver_kind == "none":
        return None
    need = "owner" if r.approver_kind == "owner" else "manager"
    # quản trị viên được coi như chủ khi tuyển (họ đã có quyền dựng cả công ty)
    if ROLE_ORDER.get(principal.role, -1) < ROLE_ORDER[need] and principal.role != "admin":
        who = APPROVER_KINDS[r.approver_kind]["vi"].lower()
        raise HTTPException(403, f"Theo ma trận phân quyền (luật #{r.id}: {rule_label(db, r)}), tuyển agent cần {who}. "
                                 "Nhờ người có quyền tuyển, hoặc chủ doanh nghiệp sửa luật ở Đội ngũ → Phân quyền.")
    return None
