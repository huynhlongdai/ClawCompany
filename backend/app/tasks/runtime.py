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


@celery_app.task(name="wakeups.drain")
def drain_wakeups():
    """D2.1: một vòng drain. Celery không giữ follower sống qua các task, nên
    follower do API gắn lại (``OPENCLAW_CLAIM_SWEEP_SECONDS``)."""
    import asyncio
    from app.db.session import SessionLocal
    from app.services import wakeup
    db = SessionLocal()
    try:
        return asyncio.run(wakeup.drain(db, follow=False))
    finally:
        db.close()


@celery_app.task(name="approvals.escalate_overdue")
def escalate_overdue_approvals():
    """D3.5: routine hệ thống — approval quá ``APPROVAL_TTL_HOURS`` chuyển lên quản lý."""
    from app.db.session import SessionLocal
    from app.services import inbox
    db = SessionLocal()
    try:
        return inbox.escalate_overdue(db)
    finally:
        db.close()


@celery_app.task(name="approvals.sweep_gateway")
def sweep_gateway_approvals():
    """Đưa mọi lệnh shell đang chờ duyệt trên gateway vào hộp duyệt (cả phiên chat trực tiếp)."""
    import asyncio
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.services import approval_backfill
    if (settings.openclaw_mode or "").lower() not in ("native", "gateway"):
        return {"skipped": "not native"}
    db = SessionLocal()
    try:
        return asyncio.run(approval_backfill.sweep_all(db))
    finally:
        db.close()


@celery_app.task(name="routines.tick")
def tick_routines():
    """D3.4: kích hoạt routine tới giờ (idempotency_key UNIQUE chặn chạy trùng)."""
    from app.db.session import SessionLocal
    from app.services import routines
    db = SessionLocal()
    try:
        return routines.tick(db)
    finally:
        db.close()


@celery_app.task(name="courses.tick")
def tick_courses():
    """M5b việc 9: buổi học / bài thi tới giờ (chỉ chạy với gateway thật)."""
    import asyncio
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.runtime.factory import get_runtime
    from app.services import courses
    if (settings.openclaw_mode or "").lower() not in ("native", "gateway"):
        return {"skipped": "not native"}
    db = SessionLocal()
    try:
        return asyncio.run(courses.tick(db, get_runtime()))
    finally:
        db.close()
