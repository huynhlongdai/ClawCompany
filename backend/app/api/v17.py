"""v17 workspace cockpit API — aggregate reads that back the business UI screens."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.authz import Principal, enforce_org, require_scope
from app.core.tenancy import active_org
from app.db.session import get_db
from app.models import Company
from app.services import workspace_cockpit as cockpit

router = APIRouter(prefix="/v17", tags=["v17-workspace-cockpit"])

READ = "company.context:read"


@router.get("/workspace/overview")
def overview(principal: Principal = Depends(require_scope(READ)), db: Session = Depends(get_db)):
    return cockpit.org_overview(db, active_org(principal))


@router.get("/workspace/org-chart")
def org_chart(principal: Principal = Depends(require_scope(READ)), db: Session = Depends(get_db)):
    return cockpit.org_chart(db, active_org(principal))


@router.get("/workspace/companies/{company_id}")
def company_detail(company_id: int, principal: Principal = Depends(require_scope(READ)),
                   db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, "Company not found")
    enforce_org(company.organization_id, principal)
    return cockpit.company_detail(db, company)


@router.get("/workspace/people")
def people(member_type: str | None = None, company_id: int | None = None,
           principal: Principal = Depends(require_scope(READ)), db: Session = Depends(get_db)):
    if member_type and member_type not in ("human", "agent"):
        raise HTTPException(400, "member_type must be human or agent")
    return cockpit.people_directory(db, active_org(principal), member_type=member_type, company_id=company_id)


@router.get("/workspace/projects")
def projects(company_id: int | None = None, principal: Principal = Depends(require_scope(READ)),
             db: Session = Depends(get_db)):
    return cockpit.project_board(db, active_org(principal), company_id=company_id)


@router.get("/workspace/tasks")
def tasks(status: str | None = None, assignee_member_id: int | None = None,
          principal: Principal = Depends(require_scope(READ)), db: Session = Depends(get_db)):
    return cockpit.task_queue(db, active_org(principal), status=status, assignee_member_id=assignee_member_id)


@router.get("/workspace/knowledge")
def knowledge(company_id: int | None = None, principal: Principal = Depends(require_scope(READ)),
              db: Session = Depends(get_db)):
    return cockpit.knowledge_library(db, active_org(principal), company_id=company_id)
