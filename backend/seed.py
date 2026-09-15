import json
from app.db.base import Base
from app.db.session import engine, SessionLocal
from app.models import *
from app.core.security import hash_password
from app.services.vector_search import rebuild_document_vectors

Base.metadata.create_all(bind=engine)
db = SessionLocal()

# Organization
org = db.query(Organization).filter(Organization.slug == "nova-holding").first()
if not org:
    org = Organization(name="Nova Holding", slug="nova-holding")
    db.add(org); db.commit(); db.refresh(org)

# Companies
fashion = db.query(Company).filter(Company.organization_id == org.id, Company.name == "Nova Fashion").first()
if not fashion:
    fashion = Company(organization_id=org.id, name="Nova Fashion", industry="Fashion")
    db.add(fashion); db.commit(); db.refresh(fashion)
labs = db.query(Company).filter(Company.organization_id == org.id, Company.name == "Nova Labs").first()
if not labs:
    labs = Company(organization_id=org.id, name="Nova Labs", industry="AI Products")
    db.add(labs); db.commit(); db.refresh(labs)

# Departments
marketing = db.query(Department).filter(Department.company_id == fashion.id, Department.name == "Marketing").first()
if not marketing:
    marketing = Department(company_id=fashion.id, name="Marketing", access_level="restricted")
    db.add(marketing); db.commit(); db.refresh(marketing)
technology = db.query(Department).filter(Department.company_id == labs.id, Department.name == "Technology").first()
if not technology:
    technology = Department(company_id=labs.id, name="Technology", access_level="private")
    db.add(technology); db.commit(); db.refresh(technology)

# Members helper
def member(name, member_type, role, company_id=None, department_id=None):
    obj = db.query(Member).filter(Member.organization_id == org.id, Member.name == name).first()
    if not obj:
        obj = Member(organization_id=org.id, company_id=company_id, department_id=department_id, name=name, member_type=member_type, role=role)
        db.add(obj); db.commit(); db.refresh(obj)
    return obj

long = member("Long", "human", "Founder & CEO")
nina_m = member("Nina", "agent", "Chief of Staff")
sophia_m = member("Sophia", "agent", "CMO", fashion.id, marketing.id)
mia_m = member("Mia", "agent", "Content Lead", fashion.id, marketing.id)

nina_m.manager_id = long.id
sophia_m.manager_id = nina_m.id
mia_m.manager_id = sophia_m.id
db.add_all([nina_m, sophia_m, mia_m]); db.commit()

# Agents helper
def agent_for(member_obj, runtime_id, model, success, cost):
    obj = db.query(Agent).filter(Agent.member_id == member_obj.id).first()
    if not obj:
        obj = Agent(member_id=member_obj.id, runtime_agent_id=runtime_id, model=model, success_rate=success, cost_30d=cost)
        db.add(obj); db.commit(); db.refresh(obj)
    return obj

nina_agent = agent_for(nina_m, "nina", "GPT-4.1", 98, 28.4)
sophia_agent = agent_for(sophia_m, "sophia-cmo", "GPT-4.1", 96, 21.2)
mia_agent = agent_for(mia_m, "mia-content", "Gemini 1.5", 94, 18.4)

# Project / task
project = db.query(Project).filter(Project.company_id == fashion.id, Project.name == "Summer Dress Campaign").first()
if not project:
    project = Project(company_id=fashion.id, name="Summer Dress Campaign", owner_member_id=sophia_m.id, status="active", progress=68)
    db.add(project); db.commit(); db.refresh(project)

task = db.query(Task).filter(Task.project_id == project.id, Task.title == "Create 20 TikTok hooks").first()
if not task:
    task = Task(project_id=project.id, title="Create 20 TikTok hooks", description="Generate 20 hooks based on current trend research.", assignee_member_id=mia_m.id, status="backlog", priority="high")
    db.add(task); db.commit(); db.refresh(task)

# Knowledge + chunks/vectors
doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.organization_id == org.id, KnowledgeDocument.title == "Brand Guidelines v2.0").first()
if not doc:
    doc = KnowledgeDocument(organization_id=org.id, company_id=fashion.id, department_id=marketing.id, title="Brand Guidelines v2.0", source_type="upload", access_level="restricted", content="Brand voice is elegant, modern and approachable. TikTok hooks should be short, visual and product-first. Avoid exaggerated claims. Use clear fashion benefits and summer styling context.", indexed=True)
    db.add(doc); db.commit(); db.refresh(doc)
if db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == doc.id).count() == 0:
    db.add(KnowledgeChunk(document_id=doc.id, chunk_index=0, content=doc.content, embedding_provider="hash384"))
    db.commit()
rebuild_document_vectors(db, doc.id)

# Approval
if not db.query(Approval).filter(Approval.organization_id == org.id, Approval.action == "ads.spend", Approval.status == "pending").first():
    db.add(Approval(organization_id=org.id, company_id=fashion.id, requester_member_id=sophia_m.id, approver_member_id=long.id, action="ads.spend", risk="high", policy_key="ads-spend", evidence="Q4 campaign budget increase"))

# Inbox
if db.query(InboxItem).filter(InboxItem.organization_id == org.id).count() == 0:
    db.add_all([
        InboxItem(organization_id=org.id, recipient_member_id=long.id, source="Nina", title="3 quyết định cần bạn duyệt", item_type="approval", priority="high"),
        InboxItem(organization_id=org.id, recipient_member_id=long.id, source="Nova Fashion", title="Summer Launch có 2 task bị block", item_type="project", priority="high"),
    ])

# Mission
if not db.query(Mission).filter(Mission.company_id == fashion.id, Mission.name == "Launch Gen Z Beauty Brand").first():
    db.add(Mission(company_id=fashion.id, name="Launch Gen Z Beauty Brand", outcome="Launch-ready brand", owner_member_id=nina_m.id, status="active", progress=78, target_date="2026-09-30"))

# Workflow sample - v7 structured steps
workflow = db.query(Workflow).filter(Workflow.organization_id == org.id, Workflow.name == "Content Production").first()
workflow_def = {
    "steps": [
        {"type": "tool", "name": "Prepare context", "tool": "noop", "args": {"stage": "prepare"}},
        {"type": "agent", "name": "Generate draft", "agent_id": mia_agent.id, "input": "Create a campaign content draft using the project context."},
        {"type": "approval", "name": "CMO review", "action": "content.publish", "risk": "medium", "policy_key": "content-publish"},
        {"type": "note", "name": "Ready to publish"},
    ]
}
if not workflow:
    workflow = Workflow(organization_id=org.id, company_id=fashion.id, name="Content Production", trigger_type="task_event", definition_json=json.dumps(workflow_def), owner_member_id=mia_m.id, status="active", success_rate=96)
    db.add(workflow)
else:
    workflow.definition_json = json.dumps(workflow_def); db.add(workflow)

# Automation / SOP / Decision
if not db.query(Automation).filter(Automation.organization_id == org.id, Automation.name == "Daily Executive Brief").first():
    db.add(Automation(organization_id=org.id, name="Daily Executive Brief", automation_type="scheduled", schedule="08:00 daily", owner_member_id=nina_m.id, status="active", last_result="success"))
if not db.query(SOP).filter(SOP.organization_id == org.id, SOP.title == "TikTok Publishing SOP").first():
    db.add(SOP(organization_id=org.id, department_id=marketing.id, title="TikTok Publishing SOP", version="v3.2", owner_member_id=sophia_m.id, content="Research > Draft > Review > Publish", status="approved", compliance_score=98))
if not db.query(Decision).filter(Decision.organization_id == org.id, Decision.title == "Increase Q4 Ads Budget").first():
    db.add(Decision(organization_id=org.id, company_id=fashion.id, title="Increase Q4 Ads Budget", context="Growth opportunity", alternatives="Keep / +20% / +40%", recommendation="+20%", owner_member_id=long.id, status="approved", impact="high"))

# Conversation
conv = db.query(Conversation).filter(Conversation.organization_id == org.id, Conversation.title == "Nina ↔ Long").first()
if not conv:
    conv = Conversation(organization_id=org.id, company_id=fashion.id, conversation_type="internal", title="Nina ↔ Long", session_key="exec_nina_long", channel="web")
    db.add(conv); db.commit(); db.refresh(conv)
if db.query(ConversationMessage).filter(ConversationMessage.conversation_id == conv.id).count() == 0:
    db.add(ConversationMessage(conversation_id=conv.id, sender_member_id=nina_m.id, sender_name="Nina", content="Chào Long! Tôi đã chuẩn bị executive brief.", message_type="text"))

# Customer + subscription + assignment
customer = db.query(Customer).filter(Customer.organization_id == org.id, Customer.tenant_key == "acme_001").first()
if not customer:
    customer = Customer(organization_id=org.id, name="Acme Fashion", plan="AI Team", tenant_key="acme_001", status="active", portal_enabled=True, usage_percent=61, mrr=299)
    db.add(customer); db.commit(); db.refresh(customer)
if not db.query(CustomerAgentAssignment).filter(CustomerAgentAssignment.customer_id == customer.id, CustomerAgentAssignment.agent_id == mia_agent.id).first():
    db.add(CustomerAgentAssignment(customer_id=customer.id, agent_id=mia_agent.id, role_label="Content Specialist", knowledge_scope="customer:acme", status="active"))
if not db.query(CustomerProjectAssignment).filter(CustomerProjectAssignment.customer_id == customer.id, CustomerProjectAssignment.project_id == project.id).first():
    db.add(CustomerProjectAssignment(customer_id=customer.id, project_id=project.id, visibility="customer"))
if not db.query(Subscription).filter(Subscription.customer_id == customer.id).first():
    db.add(Subscription(customer_id=customer.id, plan="AI Team", status="active", mrr=299, ai_cost=84, usage_percent=61, renewal_date="2026-10-08"))
if db.query(UsageEvent).filter(UsageEvent.customer_id == customer.id).count() == 0:
    db.add_all([
        UsageEvent(organization_id=org.id, customer_id=customer.id, agent_id=mia_agent.id, event_type="agent_run", quantity=42, unit="run", unit_cost=0.08, amount=3.36, metadata_json="{}"),
        UsageEvent(organization_id=org.id, customer_id=customer.id, agent_id=mia_agent.id, event_type="image_generation", quantity=18, unit="image", unit_cost=0.05, amount=0.90, metadata_json="{}"),
    ])

# Customer portal user
portal_user = db.query(CustomerPortalUser).filter(CustomerPortalUser.email == "client@acme.local").first()
if not portal_user:
    db.add(CustomerPortalUser(customer_id=customer.id, email="client@acme.local", password_hash=hash_password("ChangeMe123!"), display_name="Acme Team"))

# Report / Analytics
if not db.query(Report).filter(Report.organization_id == org.id, Report.title == "Executive Daily").first():
    db.add(Report(organization_id=org.id, report_type="executive", title="Executive Daily", period="Daily", owner_member_id=nina_m.id, content="All companies healthy. Approvals need attention.", audience="CEO", status="ready"))
if db.query(AnalyticsMetric).filter(AnalyticsMetric.organization_id == org.id).count() == 0:
    db.add_all([
        AnalyticsMetric(organization_id=org.id, metric_key="revenue", current_value=1240000, previous_value=1070000, target_value=1300000, unit="USD"),
        AnalyticsMetric(organization_id=org.id, metric_key="task_success", current_value=94.7, previous_value=92.6, target_value=95, unit="%"),
    ])

# Integration / Skills / Tools / Marketplace
if not db.query(Integration).filter(Integration.organization_id == org.id, Integration.name == "Telegram").first():
    db.add(Integration(organization_id=org.id, name="Telegram", category="channel", provider="telegram", status="connected", last_sync="live"))
if not db.query(Skill).filter(Skill.organization_id == org.id, Skill.name == "tiktok-research").first():
    db.add(Skill(organization_id=org.id, name="tiktok-research", version="1.4", scope="marketing", description="TikTok trend research", status="enabled"))
if not db.query(Tool).filter(Tool.organization_id == org.id, Tool.name == "browser").first():
    db.add(Tool(organization_id=org.id, name="browser", tool_type="tool", scope="organization", policy="scoped", status="enabled"))
if not db.query(MarketplaceTemplate).filter(MarketplaceTemplate.organization_id == org.id, MarketplaceTemplate.name == "TikTok Manager").first():
    db.add(MarketplaceTemplate(organization_id=org.id, name="TikTok Manager", template_type="employee", publisher="Nova", version="2.3", price_monthly=49, status="published", installs=328))

# Settings / RBAC / policies
for key, value, cat in [("tenant_isolation", "strict", "security"), ("payment_approval", "required", "security")]:
    if not db.query(OrganizationSetting).filter(OrganizationSetting.organization_id == org.id, OrganizationSetting.key == key).first():
        db.add(OrganizationSetting(organization_id=org.id, key=key, value=value, category=cat))
if not db.query(RoleBinding).filter(RoleBinding.organization_id == org.id, RoleBinding.member_id == long.id).first():
    db.add(RoleBinding(organization_id=org.id, member_id=long.id, role="owner", scope_type="organization", scope_id=str(org.id)))
for key, action, role, approval in [
    ("ads-spend", "ads.spend", "manager", True),
    ("prod-deploy", "deploy.production", "manager", True),
    ("content-publish", "content.publish", "manager", True),
    ("agent-run", "agent.run", "member", False),
]:
    if not db.query(PermissionPolicy).filter(PermissionPolicy.organization_id == org.id, PermissionPolicy.key == key).first():
        db.add(PermissionPolicy(organization_id=org.id, key=key, action=action, minimum_role=role, requires_approval=approval, enabled=True))

db.commit()

# Admin user
admin = db.query(User).filter(User.email == "admin@clawcompany.local").first()
if not admin:
    admin = User(email="admin@clawcompany.local", password_hash=hash_password("ChangeMe123!"), display_name="Long", is_active=True, is_superuser=True, member_id=long.id)
    db.add(admin); db.commit(); db.refresh(admin)
if not db.query(UserOrganizationAccess).filter(UserOrganizationAccess.user_id == admin.id, UserOrganizationAccess.organization_id == org.id).first():
    db.add(UserOrganizationAccess(user_id=admin.id, organization_id=org.id, role="owner", is_default=True)); db.commit()

# v8 Company Factory template + runtime metering rules + workflow graph baseline
company_manifest = {
    "industry": "AI Commerce",
    "departments": [
        {"name": "Growth", "access_level": "restricted", "agents": [
            {"name": "Maya", "role": "Growth Lead", "model": "", "skills": ["research", "analytics"], "tools": ["browser"]},
            {"name": "Leo", "role": "Performance Marketer", "model": "", "skills": ["ads", "copywriting"], "tools": ["browser"]},
        ]},
        {"name": "Operations", "access_level": "restricted", "agents": [
            {"name": "Iris", "role": "Operations Manager", "model": "", "skills": ["planning", "reporting"]},
        ]},
    ],
}
company_template = db.query(MarketplaceTemplate).filter(
    MarketplaceTemplate.organization_id == org.id,
    MarketplaceTemplate.name == "AI Growth Studio Company",
).first()
if not company_template:
    company_template = MarketplaceTemplate(
        organization_id=org.id, name="AI Growth Studio Company", template_type="company",
        publisher="Nova", version="1.0", manifest_json=json.dumps(company_manifest),
        price_monthly=199, status="published", installs=0,
    )
    db.add(company_template)
else:
    company_template.manifest_json = json.dumps(company_manifest); db.add(company_template)

for event_type, unit, unit_cost, billable, price in [
    ("run.completed", "run", 0.02, True, 0.05),
    ("customer_chat_run", "run", 0.03, True, 0.08),
    ("task_dispatch", "run", 0.02, False, 0.0),
]:
    rule = db.query(UsageMeterRule).filter(
        UsageMeterRule.organization_id == org.id,
        UsageMeterRule.event_type == event_type,
    ).first()
    if not rule:
        db.add(UsageMeterRule(
            organization_id=org.id, event_type=event_type, unit=unit, unit_cost=unit_cost,
            customer_billable=billable, customer_unit_price=price, enabled=True,
        ))

db.commit()

if not db.query(WorkflowGraphVersion).filter(WorkflowGraphVersion.workflow_id == workflow.id).first():
    graph = {
        "nodes": [
            {"id": "trigger", "type": "trigger", "label": "Task created"},
            {"id": "research", "type": "agent", "label": "Research context", "agent_id": sophia_agent.id, "input": "Research the campaign context, constraints and opportunities."},
            {"id": "draft", "type": "agent", "label": "Generate draft", "agent_id": mia_agent.id, "input": "Create the campaign content draft using approved context."},
            {"id": "approval", "type": "approval", "label": "CMO approval", "action": "content.publish", "risk": "medium", "policy_key": "content-publish"},
            {"id": "publish", "type": "tool", "label": "Publish output", "tool": "noop", "args": {"stage": "publish"}},
        ],
        "edges": [
            {"source": "trigger", "target": "research"},
            {"source": "research", "target": "draft"},
            {"source": "draft", "target": "approval"},
            {"source": "approval", "target": "publish"},
        ],
    }
    db.add(WorkflowGraphVersion(workflow_id=workflow.id, version=1, graph_json=json.dumps(graph), published=True, created_by_user_id=admin.id))
    db.commit()

# v9 Autonomous Operations baseline
policy = db.query(AutonomyPolicy).filter(AutonomyPolicy.organization_id == org.id, AutonomyPolicy.company_id.is_(None)).first()
if not policy:
    policy = AutonomyPolicy(
        organization_id=org.id, company_id=None, mode="supervised", max_concurrent_runs=4, retry_limit=2,
        max_auto_risk="low", daily_budget_limit=150, per_action_limit=20, pause_on_high_incident=True,
        require_approval_for_external_publish=True, enabled=True,
    )
    db.add(policy); db.commit(); db.refresh(policy)

goal = db.query(ExecutiveGoal).filter(ExecutiveGoal.organization_id == org.id, ExecutiveGoal.title == "Reach 100 qualified TikTok leads").first()
if not goal:
    goal = ExecutiveGoal(
        organization_id=org.id, company_id=fashion.id, created_by_user_id=admin.id,
        title="Reach 100 qualified TikTok leads",
        objective="Generate 100 qualified TikTok leads for Nova Fashion while preserving brand quality and keeping AI execution cost controlled.",
        expected_outcome="100 qualified leads with a reviewable experiment report", priority="high", risk="low",
        autonomy_mode="inherit", status="draft", progress=0, deadline="2026-10-01",
    )
    db.add(goal); db.commit(); db.refresh(goal)
if not db.query(BudgetEnvelope).filter(BudgetEnvelope.goal_id == goal.id).first():
    db.add(BudgetEnvelope(organization_id=org.id, company_id=fashion.id, goal_id=goal.id, name="TikTok Lead Goal", currency="USD", amount_limit=75, amount_reserved=0, amount_spent=0, status="active"))
if not db.query(OrganizationMemory).filter(OrganizationMemory.organization_id == org.id, OrganizationMemory.source_type == "seed", OrganizationMemory.source_id == "brand-priority").first():
    db.add(OrganizationMemory(
        organization_id=org.id, company_id=fashion.id, memory_type="principle",
        content="Nova Fashion prioritizes brand trust over short-term conversion. Avoid exaggerated claims and escalate public publishing when confidence is low.",
        source_type="seed", source_id="brand-priority", importance=5, confidence=1.0, tags_json=json.dumps(["brand","governance"]), status="active",
    ))
if not db.query(RecurringOperation).filter(RecurringOperation.organization_id == org.id, RecurringOperation.name == "Morning Executive Operating Cycle").first():
    from app.services.recurring_ops import compute_next
    recurring = RecurringOperation(
        organization_id=org.id, company_id=fashion.id, name="Morning Executive Operating Cycle", schedule="0 8 * * *",
        timezone="Asia/Ho_Chi_Minh", operation_type="nina_goal", enabled=True, last_status="never",
        payload_json=json.dumps({
            "title":"Daily growth & risk review",
            "objective":"Review active growth work, detect blockers, assign next actions and produce an executive summary.",
            "risk":"low", "priority":"high", "autonomy_mode":"inherit", "budget_limit":5, "max_steps":4,
            "auto_create_tasks":True, "execute":True, "estimated_cost_per_assignment":0.2
        }),
        next_run_at=compute_next("0 8 * * *", "Asia/Ho_Chi_Minh"),
    )
    db.add(recurring)
db.commit()

# v10 Event-Driven Company baseline
if not db.query(EventTrigger).filter(EventTrigger.organization_id == org.id, EventTrigger.name == "QA changes → notify Content Lead").first():
    db.add(EventTrigger(
        organization_id=org.id, company_id=fashion.id, name="QA changes → notify Content Lead",
        event_pattern="artifact.evaluation.changes_requested", condition_json="{}", action_type="message",
        action_json=json.dumps({
            "recipient_member_id": mia_m.id, "sender_member_id": nina_m.id, "subject": "QA requested changes",
            "content": "Please revise the artifact using the QA findings and submit a new version.", "priority": "high"
        }), cooldown_seconds=0, enabled=True,
    ))
if not db.query(EventTrigger).filter(EventTrigger.organization_id == org.id, EventTrigger.name == "SLA breach → notify Nina").first():
    db.add(EventTrigger(
        organization_id=org.id, company_id=fashion.id, name="SLA breach → notify Nina",
        event_pattern="sla.breached", condition_json="{}", action_type="message",
        action_json=json.dumps({
            "recipient_member_id": nina_m.id, "subject": "SLA breach detected",
            "content": "Review the breached work item, identify blocker and escalate if needed.", "priority": "critical"
        }), cooldown_seconds=60, enabled=True,
    ))
if not db.query(SLAProfile).filter(SLAProfile.organization_id == org.id, SLAProfile.name == "High Priority Delivery SLA").first():
    db.add(SLAProfile(
        organization_id=org.id, company_id=fashion.id, name="High Priority Delivery SLA", resource_type="task",
        priority="high", response_minutes=30, completion_minutes=1440, escalation_after_minutes=30,
        escalation_target_member_id=nina_m.id, enabled=True,
    ))
if not db.query(DecisionLoop).filter(DecisionLoop.organization_id == org.id, DecisionLoop.name == "Nina Continuous Company Loop").first():
    db.add(DecisionLoop(
        organization_id=org.id, company_id=fashion.id, name="Nina Continuous Company Loop", mode="supervised",
        interval_seconds=60, policy_json=json.dumps({"incident_attention_threshold":1,"approval_attention_threshold":3}), enabled=True,
    ))
if not db.query(SimulationScenario).filter(SimulationScenario.organization_id == org.id, SimulationScenario.name == "Add 3 Growth Agents").first():
    db.add(SimulationScenario(
        organization_id=org.id, company_id=fashion.id, name="Add 3 Growth Agents",
        description="Estimate 30-day capacity and cost if Nova Fashion adds three AI growth employees.",
        assumptions_json=json.dumps({"add_agents":3,"tasks_per_agent_day":4,"failure_rate":0.07,"avg_cost_per_task":0.35,"horizon_days":30}),
        status="draft",
    ))

# Seed a source artifact that can be handed to a reviewer/commit agent.
seed_artifact = db.query(Artifact).filter(
    Artifact.organization_id == org.id, Artifact.bundle_key == "summer-hooks", Artifact.logical_path == "content/hooks.md", Artifact.version == 1
).first()
if not seed_artifact:
    import hashlib
    content = "# Summer hooks\n\n1. One dress, three summer moods.\n2. The easy yellow dress for sunny days.\n"
    seed_artifact = Artifact(
        organization_id=org.id, company_id=fashion.id, project_id=project.id, task_id=task.id,
        created_by_member_id=mia_m.id, created_by_agent_id=mia_agent.id, bundle_key="summer-hooks",
        logical_path="content/hooks.md", name="TikTok hooks draft", artifact_type="content", mime_type="text/markdown",
        storage_backend="inline", content_text=content, content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        version=1, status="ready", metadata_json=json.dumps({"seed":True}),
    )
    db.add(seed_artifact); db.commit(); db.refresh(seed_artifact)
if not db.query(ArtifactHandoff).filter(ArtifactHandoff.artifact_id == seed_artifact.id, ArtifactHandoff.to_member_id == sophia_m.id).first():
    db.add(ArtifactHandoff(
        organization_id=org.id, artifact_id=seed_artifact.id, from_member_id=mia_m.id, to_member_id=sophia_m.id,
        task_id=task.id, purpose="review", instructions="Review brand fit, then hand the approved version to the publishing/commit agent.", status="pending",
    ))
if not db.query(CompanyEvent).filter(CompanyEvent.organization_id == org.id, CompanyEvent.event_type == "company.v10.ready").first():
    db.add(CompanyEvent(
        organization_id=org.id, company_id=fashion.id, event_type="company.v10.ready", source="seed",
        aggregate_type="organization", aggregate_id=str(org.id), payload_json=json.dumps({"version":"v10","event_driven":True}), status="pending",
    ))

db.commit()

# v11 Repository Delivery baseline
try:
    from app.services.repository_delivery import initialize_repository
    repo = db.query(Repository).filter(
        Repository.organization_id == org.id,
        Repository.name == "Nova Fashion Product Repo",
    ).first()
    if not repo:
        repo = Repository(
            organization_id=org.id, company_id=fashion.id, project_id=project.id,
            name="Nova Fashion Product Repo", provider="local", default_branch="main", status="active",
        )
        db.add(repo); db.commit(); db.refresh(repo)
    if not repo.local_path:
        try:
            initialize_repository(repo)
            db.add(repo); db.commit(); db.refresh(repo)
        except Exception as exc:
            repo.status = "setup_failed"
            db.add(repo); db.commit()

    profile = db.query(RepositoryTestProfile).filter(
        RepositoryTestProfile.organization_id == org.id,
        RepositoryTestProfile.repository_id == repo.id,
        RepositoryTestProfile.name == "Python compile smoke",
    ).first()
    if not profile:
        profile = RepositoryTestProfile(
            organization_id=org.id, repository_id=repo.id, name="Python compile smoke",
            commands_json=json.dumps(["python -m compileall src"]), timeout_seconds=120, enabled=True,
        )
        db.add(profile); db.commit(); db.refresh(profile)

    pipeline = db.query(DeliveryPipeline).filter(
        DeliveryPipeline.organization_id == org.id,
        DeliveryPipeline.repository_id == repo.id,
        DeliveryPipeline.name == "AI Commit → Review → Merge",
    ).first()
    if not pipeline:
        pipeline = DeliveryPipeline(
            organization_id=org.id, repository_id=repo.id, project_id=project.id,
            name="AI Commit → Review → Merge", target_branch="main", test_profile_id=profile.id,
            require_tests=True, require_review=True, required_approvals=1,
            merge_strategy="merge", auto_merge=False, enabled=True,
        )
        db.add(pipeline); db.commit(); db.refresh(pipeline)

    demo_source = db.query(Artifact).filter(
        Artifact.organization_id == org.id,
        Artifact.bundle_key == "v11-repo-demo",
        Artifact.logical_path == "src/demo_feature.py",
    ).order_by(Artifact.version.desc()).first()
    if not demo_source:
        from app.services.artifacts import register_artifact
        demo_source = register_artifact(
            db, organization_id=org.id, company_id=fashion.id, project_id=project.id, task_id=task.id,
            created_by_member_id=mia_m.id, created_by_agent_id=mia_agent.id,
            bundle_key="v11-repo-demo", logical_path="src/demo_feature.py", name="demo_feature.py",
            artifact_type="source_code", mime_type="text/x-python",
            content_text="def campaign_health(score: float) -> str:\n    return 'healthy' if score >= 0.8 else 'review'\n",
            metadata={"seed": True, "purpose": "v11 repository delivery demo"},
        )

    if not db.query(RepositoryIdentityCredential).filter(
        RepositoryIdentityCredential.repository_id == repo.id,
        RepositoryIdentityCredential.member_id == mia_m.id,
    ).first():
        db.add(RepositoryIdentityCredential(
            organization_id=org.id, repository_id=repo.id, member_id=mia_m.id, agent_id=mia_agent.id,
            provider_subject="mia-content", secret_ref="",
            permissions_json=json.dumps(["read", "write_branch", "create_pr"]),
            branch_pattern="cc/*", is_active=True,
        ))
    if not db.query(RepositoryIdentityCredential).filter(
        RepositoryIdentityCredential.repository_id == repo.id,
        RepositoryIdentityCredential.member_id == long.id,
    ).first():
        db.add(RepositoryIdentityCredential(
            organization_id=org.id, repository_id=repo.id, member_id=long.id,
            provider_subject="long-founder", secret_ref="",
            permissions_json=json.dumps(["read", "write_branch", "create_pr", "merge", "rollback"]),
            branch_pattern="*", is_active=True,
        ))
    db.commit()
except Exception as exc:
    print(f"v11 repository seed skipped: {exc}")

# v12 Secure AI Development Cloud baseline
try:
    repo12 = db.query(Repository).filter(Repository.organization_id == org.id, Repository.name == "Nova Fashion Product Repo").first()
    if repo12:
        sandbox = db.query(SandboxProfile).filter(
            SandboxProfile.organization_id == org.id, SandboxProfile.name == "Locked Python Sandbox"
        ).first()
        if not sandbox:
            sandbox = SandboxProfile(
                organization_id=org.id, company_id=fashion.id, name="Locked Python Sandbox",
                image="python:3.12-slim", provider="mock", cpu_limit=1, memory_mb=768, pids_limit=128,
                timeout_seconds=300, network_mode="none", read_only_root=True,
                allowed_commands_json=json.dumps(["python", "pytest"]), enabled=True,
            )
            db.add(sandbox); db.commit(); db.refresh(sandbox)

        for name, slug, env_type, approval in [
            ("Preview", "preview", "preview", False),
            ("Staging", "staging", "staging", False),
            ("Production", "production", "production", True),
        ]:
            existing = db.query(DeploymentEnvironment).filter(
                DeploymentEnvironment.organization_id == org.id,
                DeploymentEnvironment.repository_id == repo12.id,
                DeploymentEnvironment.slug == slug,
            ).first()
            if not existing:
                db.add(DeploymentEnvironment(
                    organization_id=org.id, company_id=fashion.id, project_id=project.id, repository_id=repo12.id,
                    name=name, slug=slug, environment_type=env_type, provider="filesystem",
                    require_approval=approval, approval_risk="critical" if env_type == "production" else "medium",
                    auto_deploy=False, is_active=True,
                ))
        db.commit()

        secret_ref = db.query(SecretReference).filter(
            SecretReference.organization_id == org.id, SecretReference.name == "OpenClaw API Token"
        ).first()
        if not secret_ref:
            db.add(SecretReference(
                organization_id=org.id, company_id=fashion.id, name="OpenClaw API Token",
                provider="env", external_ref="env:OPENCLAW_API_TOKEN",
                description="Metadata only. Value is resolved at execution time and never stored in ClawCompany DB.",
                classification="restricted", is_active=True,
            ))

        auto_rule = db.query(DeliveryAutomationRule).filter(
            DeliveryAutomationRule.organization_id == org.id, DeliveryAutomationRule.name == "Accepted commit handoff → Delivery"
        ).first()
        pipeline12 = db.query(DeliveryPipeline).filter(
            DeliveryPipeline.organization_id == org.id, DeliveryPipeline.repository_id == repo12.id
        ).order_by(DeliveryPipeline.id.asc()).first()
        if not auto_rule:
            db.add(DeliveryAutomationRule(
                organization_id=org.id, repository_id=repo12.id, pipeline_id=pipeline12.id if pipeline12 else None,
                project_id=project.id, name="Accepted commit handoff → Delivery", handoff_purpose="commit",
                target_member_id=long.id, target_branch="main", auto_prepare=False, auto_test=False, enabled=True,
            ))
        db.commit()
except Exception as exc:
    print(f"v12 dev cloud seed skipped: {exc}")


# v13 AI Engineering Organization baseline
try:
    repo13 = db.query(Repository).filter(
        Repository.organization_id == org.id,
        Repository.name == "Nova Fashion Product Repo",
    ).first()
    if repo13:
        graph13 = db.query(CICDPipelineGraph).filter(
            CICDPipelineGraph.organization_id == org.id,
            CICDPipelineGraph.repository_id == repo13.id,
            CICDPipelineGraph.name == "Nina Governed SDLC",
        ).first()
        if not graph13:
            from app.services.cicd import create_graph
            graph13 = create_graph(
                db,
                organization_id=org.id,
                company_id=fashion.id,
                project_id=project.id,
                repository_id=repo13.id,
                name="Nina Governed SDLC",
                created_by_member_id=nina_m.id,
                trigger={"type": "manual_or_nina", "source": "v13-seed"},
                status="active",
                nodes=[
                    {
                        "key": "security",
                        "type": "security",
                        "name": "Security Review",
                        "config": {"block_on": ["critical", "high"]},
                        "order_hint": 10,
                    },
                    {
                        "key": "evidence",
                        "type": "evidence",
                        "name": "SBOM + Provenance",
                        "config": {},
                        "order_hint": 20,
                    },
                    {
                        "key": "release",
                        "type": "release",
                        "name": "Immutable Release",
                        "config": {"release_notes": "Generated by Nina Governed SDLC"},
                        "order_hint": 30,
                    },
                ],
                edges=[
                    {"source": "security", "target": "evidence"},
                    {"source": "evidence", "target": "release"},
                ],
            )

        staging13 = db.query(DeploymentEnvironment).filter(
            DeploymentEnvironment.organization_id == org.id,
            DeploymentEnvironment.repository_id == repo13.id,
            DeploymentEnvironment.slug == "staging",
        ).first()
        if staging13:
            health13 = db.query(DeploymentHealthPolicy).filter(
                DeploymentHealthPolicy.organization_id == org.id,
                DeploymentHealthPolicy.environment_id == staging13.id,
                DeploymentHealthPolicy.name == "Staging filesystem health",
            ).first()
            if not health13:
                health13 = DeploymentHealthPolicy(
                    organization_id=org.id,
                    environment_id=staging13.id,
                    name="Staging filesystem health",
                    check_type="filesystem_marker",
                    target="",
                    expected_status=200,
                    timeout_seconds=5,
                    success_threshold=1,
                    failure_threshold=1,
                    auto_rollback=True,
                    enabled=True,
                )
                db.add(health13); db.commit(); db.refresh(health13)

            initiative13 = db.query(EngineeringInitiative).filter(
                EngineeringInitiative.organization_id == org.id,
                EngineeringInitiative.repository_id == repo13.id,
                EngineeringInitiative.title == "Ship governed AI feature",
            ).first()
            if not initiative13:
                initiative13 = EngineeringInitiative(
                    organization_id=org.id,
                    company_id=fashion.id,
                    project_id=project.id,
                    repository_id=repo13.id,
                    pipeline_graph_id=graph13.id,
                    desired_environment_id=staging13.id,
                    nina_member_id=nina_m.id,
                    title="Ship governed AI feature",
                    objective=(
                        "Demonstrate the v13 governed SDLC: security review, build evidence, "
                        "release-manager assessment and progressive staging deployment."
                    ),
                    ref="main",
                    release_version="",
                    deployment_strategy="blue_green",
                    status="planned",
                )
                db.add(initiative13); db.commit(); db.refresh(initiative13)
except Exception as exc:
    print(f"v13 engineering organization seed skipped: {exc}")


# v14 Distributed Secure Execution + Observability baseline
try:
    pool14 = db.query(RunnerPool).filter(
        RunnerPool.organization_id == org.id, RunnerPool.name == "Nova Secure Runner Pool"
    ).first()
    if not pool14:
        pool14 = RunnerPool(
            organization_id=org.id, company_id=labs.id, name="Nova Secure Runner Pool", provider="remote",
            capabilities_json=json.dumps(["linux", "docker", "python", "node"]), selectors_json=json.dumps({"trust":"company-managed"}),
            max_concurrency=8, enabled=True,
        )
        db.add(pool14); db.commit(); db.refresh(pool14)
    demo_node = db.query(RunnerNode).filter(
        RunnerNode.organization_id == org.id, RunnerNode.node_key == "demo-runner-v14"
    ).first()
    if not demo_node:
        demo_node = RunnerNode(
            organization_id=org.id, pool_id=pool14.id, node_key="demo-runner-v14", provider="remote",
            endpoint="runner://configure-a-real-runner", capabilities_json=json.dumps(["linux", "python", "node"]),
            labels_json=json.dumps({"demo": True}), status="offline", active_leases=0, capacity=2,
        )
        db.add(demo_node)

    scanner14 = db.query(ScannerProvider).filter(
        ScannerProvider.organization_id == org.id, ScannerProvider.name == "ClawCompany deterministic source scanner"
    ).first()
    if not scanner14:
        db.add(ScannerProvider(
            organization_id=org.id, name="ClawCompany deterministic source scanner", provider_type="builtin",
            executable="", config_json="{}", block_on="high", enabled=True,
        ))

    repo14 = db.query(Repository).filter(
        Repository.organization_id == org.id, Repository.name == "Nova Fashion Product Repo"
    ).first()
    production14 = None
    if repo14:
        production14 = db.query(DeploymentEnvironment).filter(
            DeploymentEnvironment.organization_id == org.id, DeploymentEnvironment.repository_id == repo14.id,
            DeploymentEnvironment.slug == "production",
        ).first()
    if production14:
        router14 = db.query(TrafficRouter).filter(
            TrafficRouter.organization_id == org.id, TrafficRouter.environment_id == production14.id,
            TrafficRouter.name == "Production canary router",
        ).first()
        if not router14:
            db.add(TrafficRouter(
                organization_id=org.id, environment_id=production14.id, name="Production canary router",
                provider="database", config_json=json.dumps({"note":"Switch provider to kubernetes only after infra authorization"}),
                current_weights_json="{}", enabled=True,
            ))
        slo14 = db.query(SLODefinition).filter(
            SLODefinition.organization_id == org.id, SLODefinition.environment_id == production14.id,
            SLODefinition.name == "Production P95 latency",
        ).first()
        if not slo14:
            db.add(SLODefinition(
                organization_id=org.id, environment_id=production14.id, name="Production P95 latency",
                metric_name="http.p95_ms", comparator="lte", threshold=500.0, window_minutes=5, min_samples=3,
                auto_incident=True, auto_rollback=True, severity="high", enabled=True,
            ))

    objective14 = db.query(PortfolioObjective).filter(
        PortfolioObjective.organization_id == org.id, PortfolioObjective.title == "Reliable autonomous engineering"
    ).first()
    if not objective14:
        db.add(PortfolioObjective(
            organization_id=org.id, company_id=labs.id, owner_member_id=nina_m.id,
            title="Reliable autonomous engineering",
            objective="Increase AI engineering delivery velocity while preserving SLO, security and release governance.",
            priority="high", status="active",
            target_json=json.dumps({"deployment_success_rate":0.99,"critical_incidents":0,"security_block_escape":0}),
        ))
    db.commit()
except Exception as exc:
    print(f"v14 distributed execution seed skipped: {exc}")


# v15 Production Trust, Telemetry Federation & Autonomous SRE baseline
try:
    exporter15 = db.query(TelemetryExporter).filter(
        TelemetryExporter.organization_id == org.id, TelemetryExporter.name == "ClawCompany Prometheus Pull"
    ).first()
    if not exporter15:
        db.add(TelemetryExporter(
            organization_id=org.id, name="ClawCompany Prometheus Pull", provider="prometheus_pull",
            endpoint="", auth_secret_ref="", config_json=json.dumps({"path":"/api/v15/metrics"}), enabled=True,
        ))

    provider15 = db.query(SecretProviderConnection).filter(
        SecretProviderConnection.organization_id == org.id, SecretProviderConnection.name == "Execution Environment Secrets"
    ).first()
    if not provider15:
        db.add(SecretProviderConnection(
            organization_id=org.id, company_id=labs.id, name="Execution Environment Secrets", provider="env",
            endpoint="", auth_ref="", config_json="{}", enabled=True,
        ))

    page15 = db.query(IncidentPagingRoute).filter(
        IncidentPagingRoute.organization_id == org.id, IncidentPagingRoute.name == "Founder Console Paging"
    ).first()
    if not page15:
        db.add(IncidentPagingRoute(
            organization_id=org.id, company_id=None, name="Founder Console Paging", provider="console",
            endpoint="", secret_ref="", severities_json=json.dumps(["critical","high"]), enabled=True,
        ))

    recovery15 = db.query(SRERecoveryPolicy).filter(
        SRERecoveryPolicy.organization_id == org.id, SRERecoveryPolicy.name == "Nina Governed Production Recovery"
    ).first()
    if not recovery15:
        db.add(SRERecoveryPolicy(
            organization_id=org.id, company_id=None, name="Nina Governed Production Recovery",
            severities_json=json.dumps(["critical","high"]),
            actions_json=json.dumps(["page","mark_mitigating","re_evaluate_slo","rollback"]),
            max_attempts=2, approval_required_for_json=json.dumps(["critical"]), enabled=True,
        ))

    trust15 = db.query(EvidenceTrustPolicy).filter(
        EvidenceTrustPolicy.organization_id == org.id, EvidenceTrustPolicy.name == "Production Cosign Trust (configure key)"
    ).first()
    if not trust15:
        db.add(EvidenceTrustPolicy(
            organization_id=org.id, name="Production Cosign Trust (configure key)", signature_type="cosign",
            key_ref="", expected_signer="sigstore://cosign", expected_issuer="", config_json=json.dumps({"mode":"pinned-key","note":"Enable after configuring a production public key reference."}), enabled=False,
        ))

    sched15 = db.query(SchedulerNode).filter(
        SchedulerNode.organization_id == org.id, SchedulerNode.node_key == "demo-control-plane-v15"
    ).first()
    if not sched15:
        db.add(SchedulerNode(
            organization_id=org.id, node_key="demo-control-plane-v15", status="offline", capacity=1,
            labels_json=json.dumps({"role":"sre-control-plane","demo":True}),
        ))
    db.commit()
except Exception as exc:
    print(f"v15 production trust/SRE seed skipped: {exc}")

print("Seed complete")
print("Admin: admin@clawcompany.local / ChangeMe123!")
print("Portal: client@acme.local / ChangeMe123!")
db.close()
