from app.worker import celery_app
from app.db.session import SessionLocal
from app.models import DeliveryPipeline, DeliveryRun, RepositoryTestProfile
from app.services.repository_delivery import RepositoryDeliveryError, prepare_delivery, run_tests


@celery_app.task(name="delivery.prepare")
def prepare_delivery_task(run_id: int):
    db = SessionLocal()
    try:
        run = db.get(DeliveryRun, run_id)
        if not run:
            return {"ok": False, "error": "delivery not found"}
        try:
            prepare_delivery(db, run)
            return {"ok": True, "delivery_run_id": run.id, "status": run.status, "head_commit_sha": run.head_commit_sha}
        except Exception as exc:
            run.status = "failed"; run.error = str(exc); db.add(run); db.commit()
            return {"ok": False, "delivery_run_id": run.id, "error": str(exc)}
    finally:
        db.close()


@celery_app.task(name="delivery.tests")
def run_delivery_tests_task(run_id: int):
    db = SessionLocal()
    try:
        run = db.get(DeliveryRun, run_id)
        if not run:
            return {"ok": False, "error": "delivery not found"}
        pipeline = db.get(DeliveryPipeline, run.pipeline_id) if run.pipeline_id else None
        profile = db.get(RepositoryTestProfile, pipeline.test_profile_id) if pipeline and pipeline.test_profile_id else None
        if not profile:
            return {"ok": False, "delivery_run_id": run.id, "error": "test profile not configured"}
        try:
            item = run_tests(db, run, profile)
            return {"ok": item.status == "passed", "delivery_run_id": run.id, "test_run_id": item.id, "status": item.status}
        except Exception as exc:
            return {"ok": False, "delivery_run_id": run.id, "error": str(exc)}
    finally:
        db.close()
