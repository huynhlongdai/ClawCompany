import json
from sqlalchemy.orm import Session

from app.models import (
    CICDPipelineGraph, CICDRun, DeploymentEnvironment, DeploymentHealthPolicy, EngineeringInitiative,
    Release, Repository, SecurityReview,
)
from app.services.cicd import execute_run, start_run
from app.services.company_event_bus import emit_event
from app.services.progressive_delivery import progressive_deploy
from app.services.release_manager import assess_release
from app.services.releases import deployment_gate
from app.services.security_review import scan_repository_commit


class EngineeringOrchestrationError(RuntimeError):
    pass


def run_initiative(db: Session, initiative: EngineeringInitiative, *, execute_deployment: bool = True,
                   health_policy_id: int | None = None) -> EngineeringInitiative:
    graph = db.get(CICDPipelineGraph, initiative.pipeline_graph_id)
    repo = db.get(Repository, initiative.repository_id)
    if not graph or not repo or graph.organization_id != initiative.organization_id or repo.organization_id != initiative.organization_id:
        raise EngineeringOrchestrationError("Engineering initiative graph or repository is unavailable")
    initiative.status = "running"; db.add(initiative); db.commit(); db.refresh(initiative)
    ci_run = db.get(CICDRun, initiative.current_ci_run_id) if initiative.current_ci_run_id else None
    if not ci_run or ci_run.status not in {"succeeded"}:
        ci_run = start_run(db, graph, ref=initiative.ref, member_id=initiative.nina_member_id)
        initiative.current_ci_run_id = ci_run.id; db.add(initiative); db.commit(); db.refresh(initiative)
        execute_run(db, ci_run)
    if ci_run.status != "succeeded":
        initiative.status = "blocked"; initiative.result_json = json.dumps({"ci_run_id": ci_run.id, "error": ci_run.error})
        db.add(initiative); db.commit(); db.refresh(initiative); return initiative
    release = db.get(Release, initiative.current_release_id) if initiative.current_release_id else None
    if not release and ci_run.release_id:
        release = db.get(Release, ci_run.release_id)
    if not release:
        release = Release(
            organization_id=initiative.organization_id, repository_id=repo.id, project_id=initiative.project_id,
            created_by_member_id=initiative.nina_member_id, version=initiative.release_version or f"initiative-{initiative.id}-{ci_run.commit_sha[:8]}",
            commit_sha=ci_run.commit_sha, status="ready", release_notes=f"Nina engineering initiative: {initiative.title}",
            manifest_json=json.dumps({"initiative_id": initiative.id, "ci_run_id": ci_run.id}),
        )
        db.add(release); db.commit(); db.refresh(release)
    initiative.current_release_id = release.id
    security = db.query(SecurityReview).filter(SecurityReview.ci_run_id == ci_run.id).order_by(SecurityReview.id.desc()).first()
    if not security:
        security = scan_repository_commit(db, repo, ci_run.commit_sha, ci_run_id=ci_run.id,
                                          reviewer_member_id=initiative.nina_member_id)
    manager = assess_release(db, release, ci_run=ci_run, security_review=security,
                             requested_by_member_id=initiative.nina_member_id)
    initiative.release_manager_run_id = manager.id
    if manager.decision == "reject":
        initiative.status = "blocked"; initiative.result_json = json.dumps({"ci_run_id": ci_run.id, "release_id": release.id,
                                                                             "security_review_id": security.id,
                                                                             "release_manager_run_id": manager.id,
                                                                             "reason": manager.reason})
        db.add(initiative); db.commit(); db.refresh(initiative); return initiative
    if not execute_deployment or initiative.desired_environment_id is None:
        initiative.status = "release_ready"; initiative.result_json = json.dumps({"ci_run_id": ci_run.id, "release_id": release.id,
                                                                                   "security_review_id": security.id,
                                                                                   "release_manager_run_id": manager.id})
        db.add(initiative); db.commit(); db.refresh(initiative); return initiative
    env = db.get(DeploymentEnvironment, initiative.desired_environment_id)
    if not env or env.organization_id != initiative.organization_id or env.repository_id != repo.id:
        raise EngineeringOrchestrationError("Desired deployment environment is unavailable")
    gate = deployment_gate(db, release, env, initiative.nina_member_id)
    if not gate["allowed"]:
        manager = assess_release(db, release, ci_run=ci_run, security_review=security,
                                 requested_by_member_id=initiative.nina_member_id)
        initiative.release_manager_run_id = manager.id; initiative.status = "waiting_approval"
        initiative.result_json = json.dumps({"ci_run_id": ci_run.id, "release_id": release.id, "gate": gate,
                                             "release_manager_run_id": manager.id})
        db.add(initiative); db.commit(); db.refresh(initiative); return initiative
    policy = db.get(DeploymentHealthPolicy, health_policy_id) if health_policy_id else None
    strategy = progressive_deploy(db, release, env, strategy=initiative.deployment_strategy,
                                  policy=policy, requested_by_member_id=initiative.nina_member_id)
    manager = assess_release(db, release, ci_run=ci_run, security_review=security, strategy_run=strategy,
                             requested_by_member_id=initiative.nina_member_id)
    initiative.release_manager_run_id = manager.id
    if strategy.status == "completed" and manager.decision == "approve": initiative.status = "deployed"
    elif strategy.status == "waiting_router": initiative.status = "waiting_router"
    else: initiative.status = "blocked"
    initiative.result_json = json.dumps({"ci_run_id": ci_run.id, "release_id": release.id,
                                         "security_review_id": security.id, "strategy_run_id": strategy.id,
                                         "release_manager_run_id": manager.id, "decision": manager.decision})
    db.add(initiative); db.commit(); db.refresh(initiative)
    emit_event(
        db, organization_id=initiative.organization_id, company_id=initiative.company_id,
        event_type="engineering.initiative.updated", source="nina_engineering",
        aggregate_type="engineering_initiative", aggregate_id=str(initiative.id), actor_member_id=initiative.nina_member_id,
        payload={"initiative_id": initiative.id, "status": initiative.status, "ci_run_id": ci_run.id,
                 "release_id": release.id, "release_manager_run_id": manager.id},
    )
    return initiative
