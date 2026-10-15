from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.models import PermissionPolicy, RoleBinding, Approval, Member
from app.core.authz import ROLE_ORDER

@dataclass
class PolicyDecision:
    decision: str
    reason: str
    policy_key: str = ""
    approval_id: int | None = None

def role_for_member(db: Session, organization_id: int, member_id: int | None, fallback_role: str = "member") -> str:
    if member_id is None:
        return fallback_role
    rb = db.query(RoleBinding).filter(
        RoleBinding.organization_id == organization_id,
        RoleBinding.member_id == member_id,
    ).order_by(RoleBinding.id.desc()).first()
    return rb.role if rb else fallback_role

def authorize(db: Session, organization_id: int, action: str, actor_member_id: int | None = None,
              fallback_role: str = "member", company_id: int | None = None, evidence: str = "",
              amount_usd: float | None = None, risk: str | None = None) -> PolicyDecision:
    # M2b: ma trận phân quyền đọc trước; không có luật khớp → hành vi cũ bên dưới.
    by_matrix = _authorize_by_matrix(db, organization_id, action, actor_member_id, company_id, evidence,
                                     amount_usd, risk)
    if by_matrix is not None:
        return by_matrix
    policy = db.query(PermissionPolicy).filter(
        PermissionPolicy.organization_id == organization_id,
        PermissionPolicy.action == action,
        PermissionPolicy.enabled == True,
    ).first()
    if not policy:
        # D1.6: với agent, "không có luật" nghĩa là "không được". Trước đây trả
        # allow, nên mọi hành động chưa ai nghĩ tới đều tự động được phép cho
        # agent. Người dùng giữ hành vi cũ.
        actor = db.get(Member, actor_member_id) if actor_member_id else None
        if actor is not None and actor.member_type == "agent":
            return PolicyDecision("deny", f"No policy grants '{action}' to agent seats "
                                          "(default deny)", "default_deny")
        return PolicyDecision("allow", "No restrictive policy matched")
    role = role_for_member(db, organization_id, actor_member_id, fallback_role)
    if ROLE_ORDER.get(role, -1) < ROLE_ORDER.get(policy.minimum_role, 999):
        return PolicyDecision("deny", f"Role {role} is below required {policy.minimum_role}", policy.key)
    if policy.requires_approval:
        existing = db.query(Approval).filter(
            Approval.organization_id == organization_id,
            Approval.requester_member_id == actor_member_id,
            Approval.action == action,
            Approval.status == "pending",
        ).order_by(Approval.id.desc()).first()
        if existing:
            return PolicyDecision("approval_required", "Existing approval is pending", policy.key, existing.id)
        approval = Approval(
            organization_id=organization_id, company_id=company_id,
            requester_member_id=actor_member_id, action=action, risk="high",
            policy_key=policy.key, evidence=evidence, status="pending",
        )
        db.add(approval); db.commit(); db.refresh(approval)
        return PolicyDecision("approval_required", "Policy requires human approval", policy.key, approval.id)
    return PolicyDecision("allow", f"Policy {policy.key} allows role {role}", policy.key)


def _authorize_by_matrix(db: Session, organization_id: int, action: str, actor_member_id: int | None,
                         company_id: int | None, evidence: str, amount_usd: float | None,
                         risk: str | None) -> PolicyDecision | None:
    from app.services import authority
    actor = db.get(Member, actor_member_id) if actor_member_id else None
    if actor is None or actor.organization_id != organization_id:
        return None
    d = authority.decide(db, actor, action, amount_usd=amount_usd, risk=risk, company_id=company_id or actor.company_id)
    if d is None:
        return None
    key = f"authority:r{d.rule_id}"
    if not d.requires_approval:
        return PolicyDecision("allow", f"{d.label}: {d.reason}", key)
    amount_txt = f" {authority.money(amount_usd)}" if amount_usd is not None else ""
    title = f"{authority.ACTION_TYPES[d.action_type]['vi']}{amount_txt}: {(evidence or action).strip().splitlines()[0]}"[:220]
    existing = db.query(Approval).filter(
        Approval.organization_id == organization_id, Approval.requester_member_id == actor.id,
        Approval.policy_key == key, Approval.action == title, Approval.status == "pending",
    ).order_by(Approval.id.desc()).first()
    if existing:
        return PolicyDecision("approval_required", f"Đang chờ {d.approver_name or 'người duyệt'} duyệt (luật #{d.rule_id})",
                              key, existing.id)
    import json
    approval = Approval(
        organization_id=organization_id, company_id=company_id or actor.company_id,
        requester_member_id=actor.id, approver_member_id=d.approver_member_id, action=title,
        risk=(risk or ("high" if d.approver_kind == "owner" else "medium"))[:24], policy_key=key,
        evidence=json.dumps({"summary": (evidence or action)[:2000], "action_type": d.action_type,
                             "amount_usd": amount_usd, "rule": d.label, "reason": d.reason,
                             "notes": d.notes}, ensure_ascii=False),
        status="pending", payload=authority.annotate(None, d),
    )
    db.add(approval); db.commit(); db.refresh(approval)
    return PolicyDecision("approval_required", f"{d.label}: {d.reason}", key, approval.id)
