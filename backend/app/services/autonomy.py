from sqlalchemy.orm import Session
from app.models import AutonomyPolicy

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def get_policy(db: Session, organization_id: int, company_id: int | None = None) -> AutonomyPolicy:
    query = db.query(AutonomyPolicy).filter(AutonomyPolicy.organization_id == organization_id, AutonomyPolicy.enabled == True)  # noqa: E712
    policy = None
    if company_id is not None:
        policy = query.filter(AutonomyPolicy.company_id == company_id).order_by(AutonomyPolicy.id.desc()).first()
    if not policy:
        policy = query.filter(AutonomyPolicy.company_id.is_(None)).order_by(AutonomyPolicy.id.desc()).first()
    if policy:
        return policy
    policy = AutonomyPolicy(organization_id=organization_id, company_id=None, mode="supervised")
    db.add(policy); db.commit(); db.refresh(policy)
    return policy


def risk_allowed(risk: str, max_auto_risk: str) -> bool:
    return RISK_ORDER.get((risk or "medium").lower(), 1) <= RISK_ORDER.get((max_auto_risk or "low").lower(), 0)
