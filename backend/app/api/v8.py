import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.v7 import portal_principal
from app.core.authz import Principal, get_principal, require_role, enforce_org, require_human
from app.core.tenancy import ensure_company, ensure_department, ensure_member, ensure_workflow, ensure_project
from app.db.session import get_db, SessionLocal
from app.models import (
    Agent, AgentProvisioningJob, CompanyProvisioningJob, Conversation, ConversationMessage,
    Customer, CustomerAgentAssignment, CustomerChatBinding, CustomerPortalUser,
    NinaExecutionPlan, NinaPlanStep, RuntimeEvent, UsageEvent, UsageMeterRule,
    WorkflowGraphVersion, Member,
)
from app.runtime.factory import get_runtime
from app.schemas.v8 import (
    AgentHireRequest, CompanyFactoryRequest, CustomerChatMessage, CustomerChatStart,
    NinaDelegateRequest, NinaPlanRequest, UsageMeterRuleCreate, WorkflowGraphSave,
)
from app.services.metering import record_usage
from app.services.nina_planner import create_plan, delegate_plan
from app.services.provisioning import provision_agent, provision_company
from app.services.runtime_events import persist_runtime_event, run_context
from app.services.workflow_graph import save_graph

router = APIRouter(tags=["v8"])


# ---------------- AI Employee hiring / provisioning ----------------
@router.post("/workforce/hire")
async def hire_agent(payload: AgentHireRequest, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.department_id is not None: ensure_department(db, payload.department_id, principal)
    if payload.manager_member_id is not None: ensure_member(db, payload.manager_member_id, principal)
    job = await provision_agent(
        db, organization_id=payload.organization_id, company_id=payload.company_id, department_id=payload.department_id,
        name=payload.name, role=payload.role, model=payload.model, runtime_agent_id=payload.runtime_agent_id,
        manager_member_id=payload.manager_member_id, template_id=payload.template_id, manifest=payload.manifest,
        requested_by_user_id=principal.user_id,
    )
    return job

@router.get("/workforce/provisioning-jobs")
def provisioning_jobs(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    if principal.organization_id is None: return []
    return db.query(AgentProvisioningJob).filter(AgentProvisioningJob.organization_id == principal.organization_id).order_by(AgentProvisioningJob.id.desc()).limit(100).all()


# ---------------- Company Factory ----------------
@router.post("/company-factory/install")
async def company_factory(payload: CompanyFactoryRequest, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    job = await provision_company(
        db, organization_id=payload.organization_id, company_name=payload.company_name, industry=payload.industry,
        template_id=payload.template_id, manifest=payload.manifest, requested_by_user_id=principal.user_id,
    )
    return job

@router.get("/company-factory/jobs")
def company_factory_jobs(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    if principal.organization_id is None: return []
    return db.query(CompanyProvisioningJob).filter(CompanyProvisioningJob.organization_id == principal.organization_id).order_by(CompanyProvisioningJob.id.desc()).limit(100).all()


# ---------------- Nina planner / delegation ----------------
@router.post("/nina/plans")
def nina_create_plan(payload: NinaPlanRequest, principal: Principal = Depends(require_role("member")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    if payload.company_id is not None: ensure_company(db, payload.company_id, principal)
    if payload.project_id is not None: ensure_project(db, payload.project_id, principal)
    try:
        plan, steps = create_plan(
            db, organization_id=payload.organization_id, user_id=principal.user_id, objective=payload.objective,
            company_id=payload.company_id, project_id=payload.project_id, auto_create_tasks=payload.auto_create_tasks,
            max_steps=payload.max_steps,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"plan": plan, "steps": steps}

@router.get("/nina/plans")
def nina_list_plans(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    if principal.organization_id is None: return []
    return db.query(NinaExecutionPlan).filter(NinaExecutionPlan.organization_id == principal.organization_id).order_by(NinaExecutionPlan.id.desc()).limit(100).all()

@router.get("/nina/plans/{plan_id}")
def nina_get_plan(plan_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    plan = db.get(NinaExecutionPlan, plan_id)
    if not plan: raise HTTPException(404, "Plan not found")
    enforce_org(plan.organization_id, principal)
    steps = db.query(NinaPlanStep).filter(NinaPlanStep.plan_id == plan.id).order_by(NinaPlanStep.step_index).all()
    return {"plan": plan, "steps": steps}

@router.post("/nina/plans/{plan_id}/delegate")
async def nina_delegate(plan_id: int, payload: NinaDelegateRequest, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    plan = db.get(NinaExecutionPlan, plan_id)
    if not plan: raise HTTPException(404, "Plan not found")
    enforce_org(plan.organization_id, principal)
    return await delegate_plan(db, plan, payload.execute_unassigned)


# ---------------- Workflow visual graph versions ----------------
@router.post("/workflows/{workflow_id}/graph")
def workflow_save_graph(workflow_id: int, payload: WorkflowGraphSave, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    wf = ensure_workflow(db, workflow_id, principal)
    try: return save_graph(db, wf, payload.graph, payload.publish, principal.user_id)
    except ValueError as exc: raise HTTPException(400, str(exc))

@router.get("/workflows/{workflow_id}/graph/versions")
def workflow_graph_versions(workflow_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    ensure_workflow(db, workflow_id, principal)
    return db.query(WorkflowGraphVersion).filter(WorkflowGraphVersion.workflow_id == workflow_id).order_by(WorkflowGraphVersion.version.desc()).all()


# ---------------- Runtime event history + automatic metering ----------------
@router.get("/runtime/runs/{run_id}/history")
def runtime_history(run_id: str, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    if principal.organization_id is None: return []
    return db.query(RuntimeEvent).filter(RuntimeEvent.organization_id == principal.organization_id, RuntimeEvent.runtime_run_id == run_id).order_by(RuntimeEvent.id).all()

@router.post("/usage/meter-rules")
def create_meter_rule(payload: UsageMeterRuleCreate, principal: Principal = Depends(require_role("admin")), db: Session = Depends(get_db)):
    enforce_org(payload.organization_id, principal)
    item = UsageMeterRule(**payload.model_dump())
    db.add(item); db.commit(); db.refresh(item); return item

@router.get("/usage/meter-rules")
def list_meter_rules(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    if principal.organization_id is None: return []
    return db.query(UsageMeterRule).filter(UsageMeterRule.organization_id == principal.organization_id).order_by(UsageMeterRule.event_type).all()


# ---------------- Customer portal chat -> OpenClaw session ----------------
def _portal_customer(db: Session, user: CustomerPortalUser) -> Customer:
    customer = db.get(Customer, user.customer_id)
    if not customer or not customer.portal_enabled or customer.status != "active":
        raise HTTPException(403, "Customer portal disabled")
    return customer


def _binding_for_user(db: Session, binding_id: int, user: CustomerPortalUser) -> CustomerChatBinding:
    item = db.get(CustomerChatBinding, binding_id)
    if not item or item.customer_id != user.customer_id or not item.is_active:
        raise HTTPException(404, "Chat not found")
    return item

@router.post("/portal/chats")
def portal_start_chat(payload: CustomerChatStart, user: CustomerPortalUser = Depends(portal_principal), db: Session = Depends(get_db)):
    customer = _portal_customer(db, user)
    assignment = db.query(CustomerAgentAssignment).filter(
        CustomerAgentAssignment.customer_id == customer.id,
        CustomerAgentAssignment.agent_id == payload.agent_id,
        CustomerAgentAssignment.status == "active",
    ).first()
    if not assignment: raise HTTPException(403, "Agent is not assigned to this customer")
    agent = db.get(Agent, payload.agent_id); member = db.get(Member, agent.member_id) if agent else None
    if not agent or not member: raise HTTPException(404, "Agent not found")
    existing = db.query(CustomerChatBinding).filter(
        CustomerChatBinding.customer_id == customer.id,
        CustomerChatBinding.portal_user_id == user.id,
        CustomerChatBinding.agent_id == agent.id,
        CustomerChatBinding.is_active == True,
    ).order_by(CustomerChatBinding.id.desc()).first()  # noqa: E712
    if existing:
        existing_conv = db.get(Conversation, existing.conversation_id)
        return {"id": existing.id, "conversation_id": existing.conversation_id, "agent_id": agent.id, "agent_name": member.name, "title": existing_conv.title if existing_conv else payload.title, "runtime_session_key": existing.runtime_session_key}
    conversation = Conversation(
        organization_id=customer.organization_id, company_id=member.company_id, conversation_type="customer",
        title=payload.title or f"Chat with {member.name}", channel="web", related_type="customer", related_id=str(customer.id), status="active",
    )
    db.add(conversation); db.flush()
    binding = CustomerChatBinding(customer_id=customer.id, portal_user_id=user.id, agent_id=agent.id, conversation_id=conversation.id, channel="web")
    db.add(binding); db.commit(); db.refresh(binding)
    return {"id": binding.id, "conversation_id": conversation.id, "agent_id": agent.id, "agent_name": member.name, "title": conversation.title, "runtime_session_key": binding.runtime_session_key}

@router.get("/portal/chats")
def portal_list_chats(user: CustomerPortalUser = Depends(portal_principal), db: Session = Depends(get_db)):
    _portal_customer(db, user)
    rows = db.query(CustomerChatBinding).filter(CustomerChatBinding.customer_id == user.customer_id, CustomerChatBinding.is_active == True).order_by(CustomerChatBinding.id.desc()).all()  # noqa: E712
    result=[]
    for row in rows:
        agent=db.get(Agent,row.agent_id); member=db.get(Member,agent.member_id) if agent else None; conv=db.get(Conversation,row.conversation_id)
        result.append({"id":row.id,"conversation_id":row.conversation_id,"agent_id":row.agent_id,"agent_name":member.name if member else "AI Employee","title":conv.title if conv else "Chat","runtime_session_key":row.runtime_session_key})
    return result

@router.get("/portal/chats/{binding_id}/messages")
def portal_chat_messages(binding_id: int, user: CustomerPortalUser = Depends(portal_principal), db: Session = Depends(get_db)):
    binding=_binding_for_user(db,binding_id,user)
    return db.query(ConversationMessage).filter(ConversationMessage.conversation_id == binding.conversation_id).order_by(ConversationMessage.id).all()

@router.post("/portal/chats/{binding_id}/messages")
async def portal_send_message(binding_id: int, payload: CustomerChatMessage, user: CustomerPortalUser = Depends(portal_principal), db: Session = Depends(get_db)):
    customer=_portal_customer(db,user); binding=_binding_for_user(db,binding_id,user)
    agent=db.get(Agent,binding.agent_id); member=db.get(Member,agent.member_id) if agent else None
    if not agent or not member: raise HTTPException(404,"Assigned agent not found")
    inbound=ConversationMessage(conversation_id=binding.conversation_id,sender_member_id=None,sender_name=user.display_name or customer.name,content=payload.content,message_type="text")
    db.add(inbound);db.commit();db.refresh(inbound)
    run=await get_runtime().run_agent(
        agent.runtime_agent_id,payload.content,
        metadata={"customer_id":customer.id,"portal_user_id":user.id,"conversation_id":binding.conversation_id,"binding_id":binding.id},
        session_key=binding.runtime_session_key or None,
    )
    binding.runtime_session_key=run.session_key;conv=db.get(Conversation,binding.conversation_id);conv.session_key=run.session_key
    db.add_all([binding,conv]);db.commit()
    record_usage(db,organization_id=customer.organization_id,customer_id=customer.id,agent_id=agent.id,runtime_run_id=run.run_id,event_type="customer_chat_run",quantity=1,unit="run",unit_cost=0,metadata={"binding_id":binding.id})
    return {"message_id":inbound.id,"run_id":run.run_id,"task_id":run.task_id,"session_key":run.session_key,"status":run.status}

@router.get("/portal/chats/{binding_id}/runs/{run_id}/events")
async def portal_chat_events(binding_id: int, run_id: str, user: CustomerPortalUser = Depends(portal_principal), db: Session = Depends(get_db)):
    customer=_portal_customer(db,user); binding=_binding_for_user(db,binding_id,user); agent=db.get(Agent,binding.agent_id)
    usage=db.query(UsageEvent).filter(UsageEvent.customer_id==customer.id,UsageEvent.agent_id==agent.id,UsageEvent.runtime_run_id==run_id).first()
    if not usage: raise HTTPException(404,"Run not found")
    rt=get_runtime()
    org_id=customer.organization_id; customer_id=customer.id; agent_id=agent.id; conversation_id=binding.conversation_id; session_key=binding.runtime_session_key
    async def generate():
        stream_db=SessionLocal(); final_text=""
        try:
            async for event in rt.stream_run(run_id):
                persist_runtime_event(stream_db,organization_id=org_id,run_id=run_id,event=event,agent_id=agent_id,customer_id=customer_id,session_key=session_key)
                result=event.get("result")
                if isinstance(result,dict): final_text=str(result.get("output") or result.get("content") or result.get("text") or "")
                elif isinstance(result,str): final_text=result
                if not final_text and str(event.get("type") or "").endswith("message"): final_text=str(event.get("content") or event.get("message") or "")
                yield {"event":str(event.get("type") or "runtime"),"data":json.dumps(event,ensure_ascii=False)}
            if final_text:
                streamed_agent=stream_db.get(Agent,agent_id)
                msg=ConversationMessage(conversation_id=conversation_id,sender_member_id=streamed_agent.member_id if streamed_agent else None,sender_name="AI Employee",content=final_text,message_type="text")
                stream_db.add(msg);stream_db.commit()
        finally:
            stream_db.close()
    return EventSourceResponse(generate())
