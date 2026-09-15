from sqlalchemy.orm import Session
from app.models import Artifact, ArtifactHandoff, DeliveryAutomationRule, DeliveryRun
from app.services.company_event_bus import emit_event


def auto_delivery_from_handoff(db: Session, handoff: ArtifactHandoff) -> list[DeliveryRun]:
    artifact = db.get(Artifact, handoff.artifact_id)
    if not artifact or not artifact.bundle_key:
        return []
    q = db.query(DeliveryAutomationRule).filter(
        DeliveryAutomationRule.organization_id == handoff.organization_id,
        DeliveryAutomationRule.enabled == True,  # noqa: E712
        DeliveryAutomationRule.handoff_purpose == handoff.purpose,
    )
    rules = q.all()
    created: list[DeliveryRun] = []
    for rule in rules:
        if rule.project_id is not None and artifact.project_id != rule.project_id:
            continue
        if rule.target_member_id is not None and handoff.to_member_id != rule.target_member_id:
            continue
        existing = db.query(DeliveryRun).filter(
            DeliveryRun.organization_id == handoff.organization_id,
            DeliveryRun.repository_id == rule.repository_id,
            DeliveryRun.artifact_bundle_key == artifact.bundle_key,
            DeliveryRun.task_id == handoff.task_id,
            DeliveryRun.status.notin_(["failed", "cancelled"]),
        ).first()
        if existing:
            continue
        run = DeliveryRun(
            organization_id=handoff.organization_id, repository_id=rule.repository_id,
            pipeline_id=rule.pipeline_id, project_id=artifact.project_id or rule.project_id,
            task_id=handoff.task_id, initiated_by_member_id=handoff.from_member_id,
            initiated_by_agent_id=artifact.created_by_agent_id, artifact_bundle_key=artifact.bundle_key,
            target_branch=rule.target_branch or "main", status="queued",
        )
        db.add(run); db.commit(); db.refresh(run); created.append(run)
        emit_event(db, organization_id=handoff.organization_id, company_id=artifact.company_id,
                   event_type="repository.delivery.auto_created", source="delivery_automation",
                   aggregate_type="delivery_run", aggregate_id=str(run.id), actor_member_id=handoff.from_member_id,
                   payload={"delivery_run_id": run.id, "handoff_id": handoff.id, "rule_id": rule.id,
                            "bundle_key": artifact.bundle_key})
        # Optional stages are queued through Celery only after the transaction exists.
        if rule.auto_prepare:
            try:
                from app.tasks.dev_cloud import auto_delivery_task
                auto_delivery_task.delay(run.id, bool(rule.auto_test))
            except Exception:
                # The DeliveryRun remains queued and can be replayed manually.
                pass
    return created
