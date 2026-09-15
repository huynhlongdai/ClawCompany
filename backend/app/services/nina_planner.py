import json
from sqlalchemy.orm import Session
from app.models import Agent, Company, Member, NinaExecutionPlan, NinaPlanStep, Project, Task
from app.services.audit import log_event
from app.services.tasks import dispatch_task

DEFAULT_STEPS = [
    ("Research & context", "Gather relevant company knowledge, constraints and current state."),
    ("Plan & strategy", "Create an execution approach with measurable output and risks."),
    ("Produce", "Execute the core work and create the requested deliverable."),
    ("Review & QA", "Review quality, policy, dependencies and edge cases."),
    ("Report", "Summarize outcome, evidence, open decisions and next actions."),
]


def _agents(db: Session, organization_id: int):
    return db.query(Member, Agent).join(Agent, Agent.member_id == Member.id).filter(
        Member.organization_id == organization_id, Member.status == "active", Agent.lifecycle == "active"
    ).all()


def _pick_agent(rows, title: str, index: int):
    if not rows: return None
    keywords = {
        "research": ["research", "analyst", "strategy"],
        "plan": ["strategy", "lead", "manager", "chief"],
        "produce": ["content", "engineer", "developer", "specialist", "creative"],
        "review": ["qa", "review", "risk", "legal", "manager"],
        "report": ["chief", "assistant", "operations", "analyst"],
    }
    key = next((k for k in keywords if k in title.lower()), "")
    for member, agent in rows:
        text = f"{member.name} {member.role}".lower()
        if key and any(word in text for word in keywords[key]): return member
    return rows[index % len(rows)][0]


def create_plan(db: Session, *, organization_id: int, user_id: int | None, objective: str, company_id: int | None,
                project_id: int | None, auto_create_tasks: bool, max_steps: int):
    rows = _agents(db, organization_id)
    if project_id:
        project = db.get(Project, project_id)
        if not project: raise ValueError("Project not found")
    elif auto_create_tasks and company_id:
        company = db.get(Company, company_id)
        if not company or company.organization_id != organization_id: raise ValueError("Company not found in organization")
        project = Project(company_id=company_id, name=f"Nina · {objective[:70]}", description=objective, status="active", progress=0)
        db.add(project); db.commit(); db.refresh(project); project_id = project.id
    plan = NinaExecutionPlan(
        organization_id=organization_id, requested_by_user_id=user_id, objective=objective, status="planned",
        strategy_json=json.dumps({"planner":"deterministic-v8","agent_count":len(rows),"project_id":project_id}, ensure_ascii=False),
        summary=f"Nina created an execution plan with up to {max_steps} steps.",
    )
    db.add(plan); db.commit(); db.refresh(plan)
    steps = []
    for idx, (title, description) in enumerate(DEFAULT_STEPS[:max_steps]):
        owner = _pick_agent(rows, title, idx)
        task = None
        if auto_create_tasks and project_id:
            task = Task(project_id=project_id, title=f"{title}: {objective[:100]}", description=description, assignee_member_id=owner.id if owner else None, status="backlog", priority="high" if idx < 2 else "medium")
            db.add(task); db.flush()
        step = NinaPlanStep(plan_id=plan.id, step_index=idx, title=title, description=description,
                            owner_member_id=owner.id if owner else None, project_id=project_id, task_id=task.id if task else None,
                            dependency_step_ids_json=json.dumps([idx-1] if idx else []), status="planned")
        db.add(step); steps.append(step)
    db.commit()
    for s in steps: db.refresh(s)
    log_event(db, organization_id, "nina.plan.create", "nina_execution_plans", plan.id, actor_name="Nina", payload={"objective":objective,"steps":len(steps)})
    return plan, steps


async def delegate_plan(db: Session, plan: NinaExecutionPlan, execute_unassigned: bool = False):
    steps = db.query(NinaPlanStep).filter(NinaPlanStep.plan_id == plan.id).order_by(NinaPlanStep.step_index).all()
    dispatched = []
    for step in steps:
        if not step.task_id: continue
        task = db.get(Task, step.task_id)
        if not task: continue
        if not task.assignee_member_id and not execute_unassigned: continue
        if task.assignee_member_id:
            member = db.get(Member, task.assignee_member_id)
            if member and member.member_type == "agent":
                try:
                    await dispatch_task(db, task)
                    step.status = "delegated"; dispatched.append(task.id)
                except Exception as exc:
                    step.status = "dispatch_failed"
        db.add(step)
    plan.status = "delegated" if dispatched else "planned"; db.add(plan); db.commit(); db.refresh(plan)
    return {"plan_id": plan.id, "status": plan.status, "dispatched_task_ids": dispatched}
