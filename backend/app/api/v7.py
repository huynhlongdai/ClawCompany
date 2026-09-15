import json
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.core.authz import Principal, enforce_org, get_principal, require_role, require_human
from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.db.session import get_db, SessionLocal
from app.models import (
    Agent, BillingInvoice, Customer, CustomerAgentAssignment, CustomerPortalUser,
    CustomerProjectAssignment, Member, Project, Subscription, UsageEvent, Task, Company,
    Workflow, WorkflowRun, WorkflowStepRun,
)
from app.runtime.factory import get_runtime
from app.schemas.v7 import (
    CustomerProjectAssign, InvoiceCreate, NinaCommandRequest, PolicyCheckRequest,
    PortalLogin, PortalRegister, PortalToken, RuntimeStreamRequest, UsageEventCreate,
    VectorSearchRequest,
)
from app.services.metering import customer_usage_summary, generate_invoice, record_usage
from app.services.nina import executive_brief, handle_command
from app.services.policy import authorize
from app.services.vector_search import search_vectors
from app.services.workflow_executor import advance, create_run
from app.services.runtime_events import persist_runtime_event, run_context
from app.core.tenancy import ensure_customer, ensure_agent, ensure_task, ensure_project

router = APIRouter(tags=["v7"])
portal_bearer = HTTPBearer(auto_error=False)

# ---------- Knowledge vector search ----------
@router.post("/knowledge/vector-search")
def vector_search(payload: VectorSearchRequest, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    return search_vectors(
        db, payload.organization_id, payload.query,
        company_id=payload.company_id, department_id=payload.department_id,
        project_id=payload.project_id, limit=payload.limit,
    )

# ---------- Policy engine ----------
@router.post("/policies/check")
def policy_check(payload: PolicyCheckRequest, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    decision = authorize(
        db, payload.organization_id, payload.action,
        actor_member_id=payload.actor_member_id,
        fallback_role=principal.role if principal.role != "api" else "member",
        company_id=payload.company_id, evidence=payload.evidence,
    )
    return {
        "decision": decision.decision, "reason": decision.reason,
        "policy_key": decision.policy_key, "approval_id": decision.approval_id,
    }

# ---------- Workflow executor ----------
@router.post("/workflow-runs/{workflow_id}/start")
async def workflow_start(workflow_id: int, input_data: dict = Body(default={}), principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    wf = db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    enforce_org(wf.organization_id, principal)
    run = create_run(db, wf, input_data)
    return await advance(db, run)

@router.post("/workflow-runs/{run_id}/advance")
async def workflow_advance(run_id: int, external_result: dict | None = Body(default=None), principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    run = db.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(404, "Workflow run not found")
    wf = db.get(Workflow, run.workflow_id)
    enforce_org(wf.organization_id, principal)
    return await advance(db, run, external_result=external_result)

@router.get("/workflow-runs/{run_id}")
def workflow_run_detail(run_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    run = db.get(WorkflowRun, run_id)
    if not run:
        raise HTTPException(404, "Workflow run not found")
    wf = db.get(Workflow, run.workflow_id)
    enforce_org(wf.organization_id, principal)
    steps = db.query(WorkflowStepRun).filter(WorkflowStepRun.workflow_run_id == run_id).order_by(WorkflowStepRun.step_index).all()
    return {"run": run, "steps": steps}

# ---------- Runtime run + SSE stream ----------
@router.post("/runtime/run")
async def runtime_run(payload: RuntimeStreamRequest, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    if principal.organization_id is None:
        raise HTTPException(400, "No organization selected")
    agent = db.query(Agent).join(Member, Member.id == Agent.member_id).filter(
        Agent.runtime_agent_id == payload.runtime_agent_id,
        Member.organization_id == principal.organization_id,
    ).first()
    if not agent:
        raise HTTPException(404, "Agent not found in active tenant")
    decision = authorize(db, principal.organization_id, "agent.run", actor_member_id=None, fallback_role=principal.role)
    if decision.decision == "deny":
        raise HTTPException(403, decision.reason)
    if decision.decision == "approval_required":
        return {"status": "approval_required", "approval_id": decision.approval_id}
    rt = get_runtime()
    customer_id = payload.metadata.get("customer_id") if isinstance(payload.metadata, dict) else None
    if customer_id is not None:
        customer = db.get(Customer, int(customer_id))
        if not customer or customer.organization_id != principal.organization_id:
            raise HTTPException(403, "Customer is outside active tenant")
    session_key = payload.metadata.get("session_key") if isinstance(payload.metadata, dict) else None
    run = await rt.run_agent(payload.runtime_agent_id, payload.input, payload.metadata, session_key=session_key)
    record_usage(
        db, organization_id=principal.organization_id, customer_id=customer_id,
        agent_id=agent.id, runtime_run_id=run.run_id, event_type="agent_run",
        quantity=1, unit="run", unit_cost=0, metadata={"runtime_agent_id": payload.runtime_agent_id, "session_key": run.session_key},
    )
    return {"task_id": run.task_id, "run_id": run.run_id, "session_key": run.session_key, "status": run.status}

@router.get("/runtime/runs/{run_id}/events")
async def runtime_events(run_id: str, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    if principal.organization_id is None:
        raise HTTPException(400, "No organization selected")
    context = run_context(db, principal.organization_id, run_id)
    if not context:
        raise HTTPException(404, "Run not found in active tenant")
    rt = get_runtime()
    org_id = int(principal.organization_id)
    async def generate():
        stream_db = SessionLocal()
        try:
            async for event in rt.stream_run(run_id):
                persist_runtime_event(stream_db, organization_id=org_id, run_id=run_id, event=event,
                                      agent_id=context.get("agent_id"), customer_id=context.get("customer_id"),
                                      task_id=context.get("task_id"))
                yield {"event": str(event.get("type") or "runtime"), "data": json.dumps(event, ensure_ascii=False)}
        finally:
            stream_db.close()
    return EventSourceResponse(generate())

@router.get("/runtime/protocol")
def runtime_protocol(principal: Principal = Depends(require_role("admin"))):
    return {
        "create_agent": settings.openclaw_rpc_create_agent,
        "run_agent": settings.openclaw_rpc_run_agent,
        "cancel_run": settings.openclaw_rpc_cancel_run,
        "gateway_status": settings.openclaw_rpc_gateway_status,
        "subscribe_run": settings.openclaw_rpc_subscribe_run,
        "event_run_id_key": settings.openclaw_event_run_id_key,
        "event_type_key": settings.openclaw_event_type_key,
    }

# ---------- Usage + billing ----------
@router.post("/usage/events")
def add_usage(payload: UsageEventCreate, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.customer_id is not None:
        ensure_customer(db, payload.customer_id, principal)
    if payload.agent_id is not None:
        ensure_agent(db, payload.agent_id, principal)
    if payload.task_id is not None:
        ensure_task(db, payload.task_id, principal)
    data = payload.model_dump()
    metadata = data.pop("metadata")
    return record_usage(db, **data, metadata=metadata)

@router.get("/usage/customers/{customer_id}/summary")
def usage_summary(customer_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    enforce_org(customer.organization_id, principal)
    return customer_usage_summary(db, customer_id)

@router.post("/billing/invoices")
def create_invoice(payload: InvoiceCreate, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    customer = db.get(Customer, payload.customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    enforce_org(customer.organization_id, principal)
    try:
        return generate_invoice(db, payload.customer_id, payload.period_start, payload.period_end, payload.currency)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

@router.get("/billing/invoices")
def list_invoices(customer_id: int | None = None, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    q = db.query(BillingInvoice)
    if customer_id is not None:
        customer = db.get(Customer, customer_id)
        if not customer:
            raise HTTPException(404, "Customer not found")
        enforce_org(customer.organization_id, principal)
        q = q.filter(BillingInvoice.customer_id == customer_id)
    elif principal.organization_id is not None:
        customer_ids = [x[0] for x in db.query(Customer.id).filter(Customer.organization_id == principal.organization_id).all()]
        q = q.filter(BillingInvoice.customer_id.in_(customer_ids)) if customer_ids else q.filter(BillingInvoice.id == -1)
    return q.order_by(BillingInvoice.id.desc()).all()

# ---------- Customer portal auth ----------
def create_portal_token(user: CustomerPortalUser) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": str(user.id), "customer_id": user.customer_id, "kind": "customer_portal",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.customer_portal_token_minutes)).timestamp()),
    }, settings.jwt_secret, algorithm=settings.jwt_algorithm)

def portal_principal(credentials: HTTPAuthorizationCredentials | None = Depends(portal_bearer), db: Session = Depends(get_db)) -> CustomerPortalUser:
    if not credentials:
        raise HTTPException(401, "Portal authentication required")
    try:
        claims = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        raise HTTPException(401, "Invalid portal token")
    if claims.get("kind") != "customer_portal":
        raise HTTPException(401, "Wrong token audience")
    user = db.get(CustomerPortalUser, int(claims["sub"]))
    if not user or not user.is_active:
        raise HTTPException(401, "Portal user inactive")
    if int(claims.get("customer_id", -1)) != int(user.customer_id):
        raise HTTPException(401, "Portal token/customer mismatch")
    return user

@router.post("/portal/users")
def create_portal_user(payload: PortalRegister, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    customer = db.get(Customer, payload.customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    enforce_org(customer.organization_id, principal)
    if db.query(CustomerPortalUser).filter(CustomerPortalUser.email == payload.email).first():
        raise HTTPException(409, "Portal email already exists")
    user = CustomerPortalUser(
        customer_id=payload.customer_id, email=payload.email,
        password_hash=hash_password(payload.password), display_name=payload.display_name,
    )
    db.add(user); db.commit(); db.refresh(user)
    return {"id": user.id, "email": user.email, "customer_id": user.customer_id}

@router.post("/portal/auth/login", response_model=PortalToken)
def portal_login(payload: PortalLogin, db: Session = Depends(get_db)):
    user = db.query(CustomerPortalUser).filter(CustomerPortalUser.email == payload.email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    return PortalToken(access_token=create_portal_token(user), customer_id=user.customer_id)

@router.get("/portal/me")
def portal_me(user: CustomerPortalUser = Depends(portal_principal), db: Session = Depends(get_db)):
    customer = db.get(Customer, user.customer_id)
    if not customer or not customer.portal_enabled or customer.status != "active":
        raise HTTPException(403, "Customer portal disabled")
    assignments = db.query(CustomerAgentAssignment).filter(CustomerAgentAssignment.customer_id == customer.id, CustomerAgentAssignment.status == "active").all()
    agent_rows = []
    for assignment in assignments:
        agent = db.get(Agent, assignment.agent_id)
        member = db.get(Member, agent.member_id) if agent else None
        agent_rows.append({
            "assignment_id": assignment.id, "agent_id": agent.id if agent else None,
            "name": member.name if member else "Unknown", "role": assignment.role_label or (member.role if member else ""),
            "status": agent.lifecycle if agent else "unknown",
        })
    project_assignments = db.query(CustomerProjectAssignment).filter(CustomerProjectAssignment.customer_id == customer.id).all()
    projects = []
    for pa in project_assignments:
        project = db.get(Project, pa.project_id)
        if project:
            projects.append({"id": project.id, "name": project.name, "status": project.status, "progress": project.progress, "visibility": pa.visibility})
    sub = db.query(Subscription).filter(Subscription.customer_id == customer.id).order_by(Subscription.id.desc()).first()
    return {
        "user": {"id": user.id, "email": user.email, "display_name": user.display_name},
        "customer": {"id": customer.id, "name": customer.name, "plan": customer.plan, "usage_percent": customer.usage_percent},
        "agents": agent_rows, "projects": projects,
        "subscription": {"plan": sub.plan, "mrr": sub.mrr, "status": sub.status, "renewal_date": sub.renewal_date} if sub else None,
        "usage": customer_usage_summary(db, customer.id),
    }

@router.post("/customers/{customer_id}/projects")
def assign_customer_project(customer_id: int, payload: CustomerProjectAssign, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    if customer_id != payload.customer_id:
        raise HTTPException(400, "customer_id mismatch")
    customer = db.get(Customer, customer_id)
    project = db.get(Project, payload.project_id)
    if not customer or not project:
        raise HTTPException(404, "Customer or project not found")
    enforce_org(customer.organization_id, principal)
    project_checked = ensure_project(db, payload.project_id, principal)
    project_company = db.get(Company, project_checked.company_id)
    if not project_company or project_company.organization_id != customer.organization_id:
        raise HTTPException(403, "Project is outside customer tenant organization")
    item = CustomerProjectAssignment(**payload.model_dump())
    db.add(item); db.commit(); db.refresh(item)
    return item

# ---------- Nina ----------
@router.get("/nina/brief")
def nina_brief(organization_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    enforce_org(organization_id, principal)
    return executive_brief(db, organization_id)

@router.post("/nina/command")
def nina_command(payload: NinaCommandRequest, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    return handle_command(db, payload.organization_id, principal.user_id, payload.message)
