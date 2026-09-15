import json
from sqlalchemy.orm import Session
from app.models import PortfolioObjective, PortfolioReview, EngineeringInitiative, CICDRun, Incident, SLOEvaluation, DeploymentStrategyRun


def review_portfolio(db: Session, *, organization_id: int, objective: PortfolioObjective | None = None,
                     nina_member_id: int | None = None) -> PortfolioReview:
    iq = db.query(EngineeringInitiative).filter(EngineeringInitiative.organization_id == organization_id)
    if objective and objective.company_id is not None:
        iq = iq.filter(EngineeringInitiative.company_id == objective.company_id)
    initiatives = iq.all()
    ci = db.query(CICDRun).filter(CICDRun.organization_id == organization_id).order_by(CICDRun.id.desc()).limit(100).all()
    incidents = db.query(Incident).filter(Incident.organization_id == organization_id, Incident.status != "resolved").all()
    slo = db.query(SLOEvaluation).filter(SLOEvaluation.organization_id == organization_id).order_by(SLOEvaluation.id.desc()).limit(100).all()
    deploys = db.query(DeploymentStrategyRun).filter(DeploymentStrategyRun.organization_id == organization_id).order_by(DeploymentStrategyRun.id.desc()).limit(100).all()
    failed_ci = sum(1 for x in ci if x.status in {"failed", "blocked"})
    breached_slo = sum(1 for x in slo if x.status == "breached")
    failed_deploys = sum(1 for x in deploys if x.status in {"failed", "rolled_back"})
    critical_incidents = sum(1 for x in incidents if x.severity == "critical")
    active = sum(1 for x in initiatives if x.status not in {"completed", "cancelled"})
    risk_score = critical_incidents * 5 + len(incidents) * 2 + breached_slo * 2 + failed_deploys * 2 + failed_ci
    health = "red" if critical_incidents or risk_score >= 8 else "amber" if risk_score >= 3 else "green"
    recommendations = []
    if incidents: recommendations.append(f"Resolve {len(incidents)} open engineering incident(s) before increasing release velocity.")
    if breached_slo: recommendations.append(f"Investigate {breached_slo} recent SLO breach evaluation(s) and protect canary promotion gates.")
    if failed_ci: recommendations.append(f"Review {failed_ci} failed/blocked CI runs and allocate engineering capacity to pipeline reliability.")
    if not recommendations: recommendations.append("Portfolio is stable; continue governed delivery and monitor SLO trends.")
    metrics = {"active_initiatives": active, "ci_runs": len(ci), "failed_ci": failed_ci, "open_incidents": len(incidents),
               "critical_incidents": critical_incidents, "slo_breaches": breached_slo, "failed_or_rolled_back_deploys": failed_deploys,
               "risk_score": risk_score}
    summary = f"Engineering portfolio health is {health.upper()}: {active} active initiatives, {len(incidents)} open incidents, {breached_slo} SLO breaches."
    item = PortfolioReview(organization_id=organization_id, objective_id=objective.id if objective else None,
                           nina_member_id=nina_member_id, status="completed", health=health, summary=summary,
                           metrics_json=json.dumps(metrics, sort_keys=True), recommendations_json=json.dumps(recommendations, ensure_ascii=False))
    db.add(item); db.commit(); db.refresh(item)
    return item
