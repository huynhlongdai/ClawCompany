from datetime import datetime
from app.worker import celery_app
from app.db.session import SessionLocal
from app.models import DevWorkspace, PreviewEnvironment, SandboxRun, Deployment, Release, DeploymentEnvironment
from app.services.dev_cloud import destroy_workspace
from app.services.sandbox_runner import execute_sandbox
from app.services.releases import deploy_release


@celery_app.task(name="devcloud.run_sandbox")
def run_sandbox_task(sandbox_run_id: int):
    db = SessionLocal()
    try:
        item = db.get(SandboxRun, sandbox_run_id)
        if not item:
            return {"ok": False, "error": "sandbox run not found"}
        execute_sandbox(db, item)
        return {"ok": item.status == "passed", "sandbox_run_id": item.id, "status": item.status}
    finally:
        db.close()


@celery_app.task(name="devcloud.deploy_release")
def deploy_release_task(release_id: int, environment_id: int, requested_by_member_id: int | None = None):
    db = SessionLocal()
    try:
        release = db.get(Release, release_id); env = db.get(DeploymentEnvironment, environment_id)
        if not release or not env:
            return {"ok": False, "error": "release or environment not found"}
        item = deploy_release(db, release, env, requested_by_member_id=requested_by_member_id)
        return {"ok": item.status == "deployed", "deployment_id": item.id, "status": item.status}
    finally:
        db.close()


@celery_app.task(name="devcloud.cleanup_expired")
def cleanup_expired_task():
    db = SessionLocal(); now = datetime.utcnow(); destroyed = 0
    try:
        for item in db.query(DevWorkspace).filter(DevWorkspace.expires_at.isnot(None), DevWorkspace.expires_at <= now, DevWorkspace.status != "destroyed").all():
            try:
                destroy_workspace(db, item); destroyed += 1
            except Exception:
                item.status = "cleanup_failed"; db.add(item); db.commit()
        previews = db.query(PreviewEnvironment).filter(
            PreviewEnvironment.expires_at.isnot(None), PreviewEnvironment.expires_at <= now,
            PreviewEnvironment.status.in_(["ready", "provisioning"]),
        ).all()
        for preview in previews:
            preview.status = "expired"; preview.destroyed_at = now; db.add(preview)
        db.commit()
        return {"workspaces_destroyed": destroyed, "previews_expired": len(previews)}
    finally:
        db.close()

@celery_app.task(name="devcloud.auto_delivery")
def auto_delivery_task(delivery_run_id: int, run_tests_after: bool = False):
    from app.models import DeliveryPipeline, DeliveryRun, RepositoryTestProfile
    from app.services.repository_delivery import prepare_delivery, run_tests
    db = SessionLocal()
    try:
        run = db.get(DeliveryRun, delivery_run_id)
        if not run:
            return {"ok": False, "error": "delivery run not found"}
        try:
            prepare_delivery(db, run)
            result = {"ok": True, "delivery_run_id": run.id, "status": run.status}
            if run_tests_after and run.status == "prepared":
                pipeline = db.get(DeliveryPipeline, run.pipeline_id) if run.pipeline_id else None
                profile = db.get(RepositoryTestProfile, pipeline.test_profile_id) if pipeline and pipeline.test_profile_id else None
                if not profile:
                    return {"ok": False, "delivery_run_id": run.id, "error": "auto_test requested but no test profile is configured"}
                test = run_tests(db, run, profile)
                result.update({"test_run_id": test.id, "test_status": test.status, "ok": test.status == "passed"})
            return result
        except Exception as exc:
            run.status = "failed"; run.error = str(exc); db.add(run); db.commit()
            return {"ok": False, "delivery_run_id": run.id, "error": str(exc)}
    finally:
        db.close()
