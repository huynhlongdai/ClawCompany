from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.db.session import get_db
from app.models import BackgroundJob, KnowledgeDocument, Task, Project, Company
from app.tasks.knowledge import index_document
from app.tasks.runtime import dispatch_company_task
from app.core.authz import require_role, Principal

router=APIRouter(prefix="/jobs",tags=["jobs"])

@router.get("")
def list_jobs(limit:int=50,db:Session=Depends(get_db),principal:Principal=Depends(require_role("member"))):
    q=db.query(BackgroundJob)
    if principal.organization_id is not None:q=q.filter(or_(BackgroundJob.organization_id==principal.organization_id,BackgroundJob.organization_id==None))
    return q.order_by(BackgroundJob.id.desc()).limit(min(limit,200)).all()

@router.post("/knowledge/{document_id}/index")
def enqueue_index(document_id:int,db:Session=Depends(get_db),principal:Principal=Depends(require_role("member"))):
    doc=db.get(KnowledgeDocument,document_id)
    if not doc:raise HTTPException(404,"Document not found")
    if principal.organization_id is not None and doc.organization_id!=principal.organization_id:raise HTTPException(403,"Cross-tenant access denied")
    task=index_document.delay(document_id);return {"queued":True,"celery_task_id":task.id}

@router.post("/tasks/{task_id}/dispatch")
def enqueue_dispatch(task_id:int,db:Session=Depends(get_db),principal:Principal=Depends(require_role("member"))):
    task=db.get(Task,task_id)
    if not task:raise HTTPException(404,"Task not found")
    project=db.get(Project,task.project_id);company=db.get(Company,project.company_id) if project else None
    if principal.organization_id is not None and company and company.organization_id!=principal.organization_id:raise HTTPException(403,"Cross-tenant access denied")
    queued=dispatch_company_task.delay(task_id);return {"queued":True,"celery_task_id":queued.id}
