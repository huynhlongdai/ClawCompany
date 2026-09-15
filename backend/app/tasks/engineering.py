from app.worker import celery_app
from app.db.session import SessionLocal
from app.models import CICDRun, EngineeringInitiative
from app.services.cicd import execute_run
from app.services.engineering_orchestrator import run_initiative


@celery_app.task(name="engineering.execute_cicd_run")
def execute_cicd_run_task(run_id: int):
    db = SessionLocal()
    try:
        run = db.get(CICDRun, run_id)
        if not run:
            return {"error": "CI/CD run not found"}
        execute_run(db, run)
        return {"ci_run_id": run.id, "status": run.status}
    finally:
        db.close()


@celery_app.task(name="engineering.run_initiative")
def run_engineering_initiative_task(initiative_id: int, execute_deployment: bool = True, health_policy_id: int | None = None):
    db = SessionLocal()
    try:
        item = db.get(EngineeringInitiative, initiative_id)
        if not item:
            return {"error": "Engineering initiative not found"}
        run_initiative(db, item, execute_deployment=execute_deployment, health_policy_id=health_policy_id)
        return {"initiative_id": item.id, "status": item.status}
    finally:
        db.close()
