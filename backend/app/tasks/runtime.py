import asyncio
from app.worker import celery_app
from app.db.session import SessionLocal
from app.models import Task, BackgroundJob, Project, Company
from app.services.tasks import dispatch_task

@celery_app.task(name="runtime.dispatch_company_task")
def dispatch_company_task(task_id:int):
    db=SessionLocal();job=None
    try:
        task=db.get(Task,task_id)
        if not task:return {"status":"not_found"}
        project=db.get(Project,task.project_id);company=db.get(Company,project.company_id) if project else None
        job=BackgroundJob(organization_id=company.organization_id if company else None,job_type="runtime.dispatch",resource_type="task",resource_id=str(task.id),status="running")
        db.add(job);db.commit();db.refresh(job)
        result=asyncio.run(dispatch_task(db,task))
        job.status="completed";job.result_json=f'{{"task_id":{result.id}}}';db.add(job);db.commit()
        return {"status":"completed","task_id":result.id}
    except Exception as exc:
        if job:job.status="failed";job.error=str(exc);db.add(job);db.commit()
        raise
    finally:db.close()
