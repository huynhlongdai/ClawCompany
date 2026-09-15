from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import (
    InboxItem, Mission, Workflow, WorkflowRun, Automation, SOP, Decision,
    Conversation, ConversationMessage, Customer, CustomerAgentAssignment,
    Report, AnalyticsMetric, AuditEvent, Integration, Skill, Tool,
    MarketplaceTemplate, Subscription, OrganizationSetting, RoleBinding, PermissionPolicy, Agent, Company
)
from app.schemas.extended import *
from app.services.audit import log_event
from app.core.authz import Principal, get_principal, require_role, enforce_org, require_human
from app.core.tenancy import active_org, ensure_company, ensure_customer, ensure_agent, ensure_member, ensure_workflow

router = APIRouter(tags=["extended"])


def audited_create(db, model, payload, organization_id: int):
    obj = model(**payload.model_dump())
    db.add(obj); db.commit(); db.refresh(obj)
    log_event(db, organization_id, f"{model.__tablename__}.create", model.__tablename__, obj.id)
    return obj


def requested_org(value: int | None, principal: Principal) -> int:
    org_id = active_org(principal)
    if value is not None: enforce_org(value, principal)
    return org_id

# Inbox
@router.get("/inbox")
def list_inbox(organization_id:int|None=None, status:str|None=None, principal:Principal=Depends(require_human()), db:Session=Depends(get_db)):
    org_id=requested_org(organization_id,principal); q=db.query(InboxItem).filter(InboxItem.organization_id==org_id)
    if status:q=q.filter(InboxItem.status==status)
    return q.order_by(InboxItem.id.desc()).all()

@router.post("/inbox")
def create_inbox(payload:InboxCreate, principal:Principal=Depends(require_role("member")), db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal); return audited_create(db,InboxItem,payload,payload.organization_id)

@router.post("/inbox/{item_id}/read")
def mark_inbox_read(item_id:int, principal:Principal=Depends(require_human()), db:Session=Depends(get_db)):
    obj=db.get(InboxItem,item_id)
    if not obj: raise HTTPException(404,"Inbox item not found")
    enforce_org(obj.organization_id,principal); obj.status="read"; db.add(obj);db.commit();db.refresh(obj);return obj

# Missions
@router.get("/missions")
def list_missions(company_id:int|None=None, principal:Principal=Depends(require_human()), db:Session=Depends(get_db)):
    org_id=active_org(principal); q=db.query(Mission).join(Company, Company.id==Mission.company_id).filter(Company.organization_id==org_id)
    if company_id: ensure_company(db,company_id,principal); q=q.filter(Mission.company_id==company_id)
    return q.order_by(Mission.id.desc()).all()

@router.post("/missions")
def create_mission(payload:MissionCreate, principal:Principal=Depends(require_role("manager")), db:Session=Depends(get_db)):
    company=ensure_company(db,payload.company_id,principal); return audited_create(db,Mission,payload,company.organization_id)

# Workflows
@router.get("/workflows")
def list_workflows(organization_id:int|None=None, principal:Principal=Depends(require_human()), db:Session=Depends(get_db)):
    org_id=requested_org(organization_id,principal); return db.query(Workflow).filter(Workflow.organization_id==org_id).order_by(Workflow.id.desc()).all()

@router.post("/workflows")
def create_workflow(payload:WorkflowCreate, principal:Principal=Depends(require_role("manager")), db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal); return audited_create(db,Workflow,payload,payload.organization_id)

@router.post("/workflows/{workflow_id}/run")
def run_workflow(workflow_id:int, principal:Principal=Depends(require_role("member")), db:Session=Depends(get_db)):
    wf=ensure_workflow(db,workflow_id,principal); run=WorkflowRun(workflow_id=workflow_id,status="running",current_step=1);db.add(run);db.commit();db.refresh(run);return run

# Automations
@router.get("/automations")
def list_automations(organization_id:int|None=None, principal:Principal=Depends(require_human()), db:Session=Depends(get_db)):
    org_id=requested_org(organization_id,principal);return db.query(Automation).filter(Automation.organization_id==org_id).order_by(Automation.id.desc()).all()

@router.post("/automations")
def create_automation(payload:AutomationCreate, principal:Principal=Depends(require_role("manager")), db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);return audited_create(db,Automation,payload,payload.organization_id)

# SOP
@router.get("/sops")
def list_sops(organization_id:int|None=None, principal:Principal=Depends(require_human()), db:Session=Depends(get_db)):
    org_id=requested_org(organization_id,principal);return db.query(SOP).filter(SOP.organization_id==org_id).order_by(SOP.id.desc()).all()

@router.post("/sops")
def create_sop(payload:SOPCreate, principal:Principal=Depends(require_role("member")), db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);return audited_create(db,SOP,payload,payload.organization_id)

# Decisions
@router.get("/decisions")
def list_decisions(organization_id:int|None=None,status:str|None=None,principal:Principal=Depends(require_human()),db:Session=Depends(get_db)):
    org_id=requested_org(organization_id,principal);q=db.query(Decision).filter(Decision.organization_id==org_id)
    if status:q=q.filter(Decision.status==status)
    return q.order_by(Decision.id.desc()).all()

@router.post("/decisions")
def create_decision(payload:DecisionCreate,principal:Principal=Depends(require_role("manager")),db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);return audited_create(db,Decision,payload,payload.organization_id)

# Conversations
@router.get("/conversations")
def list_conversations(organization_id:int|None=None,principal:Principal=Depends(require_human()),db:Session=Depends(get_db)):
    org_id=requested_org(organization_id,principal);return db.query(Conversation).filter(Conversation.organization_id==org_id).order_by(Conversation.id.desc()).all()

@router.post("/conversations")
def create_conversation(payload:ConversationCreate,principal:Principal=Depends(require_role("member")),db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);return audited_create(db,Conversation,payload,payload.organization_id)

@router.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id:int,principal:Principal=Depends(require_human()),db:Session=Depends(get_db)):
    c=db.get(Conversation,conversation_id)
    if not c:raise HTTPException(404,"Conversation not found")
    enforce_org(c.organization_id,principal);return db.query(ConversationMessage).filter(ConversationMessage.conversation_id==conversation_id).order_by(ConversationMessage.id).all()

@router.post("/conversations/{conversation_id}/messages")
def add_message(conversation_id:int,payload:MessageCreate,principal:Principal=Depends(require_role("member")),db:Session=Depends(get_db)):
    c=db.get(Conversation,conversation_id)
    if not c:raise HTTPException(404,"Conversation not found")
    enforce_org(c.organization_id,principal);obj=ConversationMessage(conversation_id=conversation_id,**payload.model_dump());db.add(obj);db.commit();db.refresh(obj);return obj

# Customers
@router.get("/customers")
def list_customers(organization_id:int|None=None,principal:Principal=Depends(require_human()),db:Session=Depends(get_db)):
    org_id=requested_org(organization_id,principal);return db.query(Customer).filter(Customer.organization_id==org_id).order_by(Customer.id.desc()).all()

@router.post("/customers")
def create_customer(payload:CustomerCreate,principal:Principal=Depends(require_role("manager")),db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);return audited_create(db,Customer,payload,payload.organization_id)

@router.get("/customers/{customer_id}/agents")
def customer_agents(customer_id:int,principal:Principal=Depends(require_human()),db:Session=Depends(get_db)):
    ensure_customer(db,customer_id,principal);return db.query(CustomerAgentAssignment).filter(CustomerAgentAssignment.customer_id==customer_id).all()

@router.post("/customers/{customer_id}/agents")
def assign_customer_agent(customer_id:int,payload:CustomerAssignmentCreate,principal:Principal=Depends(require_role("manager")),db:Session=Depends(get_db)):
    if customer_id!=payload.customer_id:raise HTTPException(400,"customer_id mismatch")
    customer=ensure_customer(db,customer_id,principal);ensure_agent(db,payload.agent_id,principal);obj=CustomerAgentAssignment(**payload.model_dump());db.add(obj);db.commit();db.refresh(obj);log_event(db,customer.organization_id,"customer.agent.assign","customer_agent_assignments",obj.id);return obj

# Reports
@router.get("/reports")
def list_reports(organization_id:int|None=None,principal:Principal=Depends(require_human()),db:Session=Depends(get_db)):
    org_id=requested_org(organization_id,principal);return db.query(Report).filter(Report.organization_id==org_id).order_by(Report.id.desc()).all()

@router.post("/reports")
def create_report(payload:ReportCreate,principal:Principal=Depends(require_role("member")),db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);return audited_create(db,Report,payload,payload.organization_id)

# Analytics / audit
@router.get("/analytics")
def list_metrics(organization_id:int|None=None,principal:Principal=Depends(require_human()),db:Session=Depends(get_db)):
    org_id=requested_org(organization_id,principal);return db.query(AnalyticsMetric).filter(AnalyticsMetric.organization_id==org_id).order_by(AnalyticsMetric.metric_key).all()

@router.post("/analytics")
def create_metric(payload:MetricCreate,principal:Principal=Depends(require_role("manager")),db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);return audited_create(db,AnalyticsMetric,payload,payload.organization_id)

@router.get("/activity")
def list_activity(organization_id:int|None=None,limit:int=100,principal:Principal=Depends(require_human()),db:Session=Depends(get_db)):
    org_id=requested_org(organization_id,principal);return db.query(AuditEvent).filter(AuditEvent.organization_id==org_id).order_by(AuditEvent.id.desc()).limit(min(limit,500)).all()

# Integrations / skills / tools
@router.get("/integrations")
def list_integrations(organization_id:int|None=None,principal:Principal=Depends(require_human()),db:Session=Depends(get_db)):
    org_id=requested_org(organization_id,principal);return db.query(Integration).filter(Integration.organization_id==org_id).order_by(Integration.id.desc()).all()

@router.post("/integrations")
def create_integration(payload:IntegrationCreate,principal:Principal=Depends(require_role("admin")),db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);return audited_create(db,Integration,payload,payload.organization_id)

@router.get("/skills")
def list_skills(organization_id:int|None=None,principal:Principal=Depends(require_human()),db:Session=Depends(get_db)):
    org_id=requested_org(organization_id,principal);return db.query(Skill).filter(Skill.organization_id==org_id).order_by(Skill.name).all()

@router.post("/skills")
def create_skill(payload:SkillCreate,principal:Principal=Depends(require_role("admin")),db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);return audited_create(db,Skill,payload,payload.organization_id)

@router.get("/tools")
def list_tools(organization_id:int|None=None,principal:Principal=Depends(require_human()),db:Session=Depends(get_db)):
    org_id=requested_org(organization_id,principal);return db.query(Tool).filter(Tool.organization_id==org_id).order_by(Tool.name).all()

@router.post("/tools")
def create_tool(payload:ToolCreate,principal:Principal=Depends(require_role("admin")),db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);return audited_create(db,Tool,payload,payload.organization_id)

# Marketplace
@router.get("/marketplace")
def list_templates(organization_id:int|None=None,principal:Principal=Depends(require_human()),db:Session=Depends(get_db)):
    org_id=requested_org(organization_id,principal);return db.query(MarketplaceTemplate).filter(MarketplaceTemplate.organization_id==org_id).order_by(MarketplaceTemplate.id.desc()).all()

@router.post("/marketplace")
def create_template(payload:MarketplaceCreate,principal:Principal=Depends(require_role("admin")),db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);return audited_create(db,MarketplaceTemplate,payload,payload.organization_id)

# Billing
@router.get("/billing/subscriptions")
def list_subscriptions(customer_id:int|None=None,principal:Principal=Depends(require_human()),db:Session=Depends(get_db)):
    q=db.query(Subscription)
    if customer_id:
        ensure_customer(db,customer_id,principal);q=q.filter(Subscription.customer_id==customer_id)
    else:
        ids=[x[0] for x in db.query(Customer.id).filter(Customer.organization_id==active_org(principal)).all()];q=q.filter(Subscription.customer_id.in_(ids)) if ids else q.filter(Subscription.id==-1)
    return q.order_by(Subscription.id.desc()).all()

@router.post("/billing/subscriptions")
def create_subscription(payload:SubscriptionCreate,principal:Principal=Depends(require_role("manager")),db:Session=Depends(get_db)):
    ensure_customer(db,payload.customer_id,principal);obj=Subscription(**payload.model_dump());db.add(obj);db.commit();db.refresh(obj);return obj

# Settings / RBAC
@router.get("/settings")
def list_settings(organization_id:int,principal:Principal=Depends(require_human()),db:Session=Depends(get_db)):
    enforce_org(organization_id,principal);return db.query(OrganizationSetting).filter(OrganizationSetting.organization_id==organization_id).order_by(OrganizationSetting.key).all()

@router.post("/settings")
def upsert_setting(payload:SettingUpsert,principal:Principal=Depends(require_role("admin")),db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);obj=db.query(OrganizationSetting).filter(OrganizationSetting.organization_id==payload.organization_id,OrganizationSetting.key==payload.key).first()
    if not obj:obj=OrganizationSetting(**payload.model_dump())
    else:obj.value=payload.value;obj.category=payload.category
    db.add(obj);db.commit();db.refresh(obj);return obj

@router.get("/roles")
def list_roles(organization_id:int,principal:Principal=Depends(require_role("admin")),db:Session=Depends(get_db)):
    enforce_org(organization_id,principal);return db.query(RoleBinding).filter(RoleBinding.organization_id==organization_id).all()

@router.post("/roles")
def create_role(payload:RoleBindingCreate,principal:Principal=Depends(require_role("admin")),db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);ensure_member(db,payload.member_id,principal);return audited_create(db,RoleBinding,payload,payload.organization_id)

@router.get("/policies")
def list_policies(organization_id:int,principal:Principal=Depends(require_role("admin")),db:Session=Depends(get_db)):
    enforce_org(organization_id,principal);return db.query(PermissionPolicy).filter(PermissionPolicy.organization_id==organization_id).all()

@router.post("/policies")
def create_policy(payload:PolicyCreate,principal:Principal=Depends(require_role("admin")),db:Session=Depends(get_db)):
    enforce_org(payload.organization_id,principal);return audited_create(db,PermissionPolicy,payload,payload.organization_id)
