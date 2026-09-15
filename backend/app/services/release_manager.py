import json
from sqlalchemy.orm import Session

from app.models import (
    Approval, CICDRun, DeploymentStrategyRun, Release, ReleaseManagerRun, SecurityReview,
)
from app.services.company_event_bus import emit_event


class ReleaseManagerError(RuntimeError):
    pass


def assess_release(
    db: Session,
    release: Release,
    *,
    ci_run: CICDRun | None = None,
    security_review: SecurityReview | None = None,
    strategy_run: DeploymentStrategyRun | None = None,
    requested_by_member_id: int | None = None,
    requested_by_agent_id: int | None = None,
) -> ReleaseManagerRun:
    evidence: dict = {"release_id": release.id, "commit_sha": release.commit_sha}
    decision = "approve"; reason = "All supplied release gates passed"
    if ci_run is not None:
        evidence["ci_run"] = {"id": ci_run.id, "status": ci_run.status}
        if ci_run.status != "succeeded":
            decision = "reject"; reason = f"CI/CD run is {ci_run.status}"
    if security_review is not None:
        evidence["security_review"] = {"id": security_review.id, "verdict": security_review.verdict, "score": security_review.score}
        if security_review.verdict == "blocked":
            decision = "reject"; reason = "Security review blocked the release"
    if release.approval_id:
        approval = db.get(Approval, release.approval_id)
        evidence["approval"] = {"id": approval.id if approval else release.approval_id,
                                "status": approval.status if approval else "missing"}
        if not approval or approval.status != "approved":
            if decision != "reject":
                decision = "hold"; reason = "Release is waiting for governance approval"
    if strategy_run is not None:
        evidence["deployment_strategy"] = {"id": strategy_run.id, "status": strategy_run.status, "strategy": strategy_run.strategy}
        if strategy_run.status in {"failed", "rolled_back"}:
            decision = "reject"; reason = f"Deployment strategy ended as {strategy_run.status}"
        elif strategy_run.status in {"waiting_router", "queued", "running"} and decision != "reject":
            decision = "hold"; reason = f"Deployment strategy is {strategy_run.status}"
    item = ReleaseManagerRun(
        organization_id=release.organization_id, release_id=release.id, ci_run_id=ci_run.id if ci_run else None,
        security_review_id=security_review.id if security_review else None,
        strategy_run_id=strategy_run.id if strategy_run else None, requested_by_member_id=requested_by_member_id,
        requested_by_agent_id=requested_by_agent_id, status="completed", decision=decision, reason=reason,
        evidence_json=json.dumps(evidence, default=str),
    )
    db.add(item); db.commit(); db.refresh(item)
    emit_event(
        db, organization_id=release.organization_id, event_type="release_manager.decision", source="release_manager",
        aggregate_type="release_manager_run", aggregate_id=str(item.id), actor_member_id=requested_by_member_id,
        payload={"release_manager_run_id": item.id, "release_id": release.id, "decision": decision, "reason": reason},
    )
    return item
