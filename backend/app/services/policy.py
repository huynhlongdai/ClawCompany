from dataclasses import dataclass
from sqlalchemy.orm import Session
from app.models import PermissionPolicy, RoleBinding, Approval
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
              fallback_role: str = "member", company_id: int | None = None, evidence: str = "") -> PolicyDecision:
    policy = db.query(PermissionPolicy).filter(
        PermissionPolicy.organization_id == organization_id,
        PermissionPolicy.action == action,
        PermissionPolicy.enabled == True,
    ).first()
    if not policy:
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
