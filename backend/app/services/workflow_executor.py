import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import Workflow, WorkflowRun, WorkflowStepRun, Agent, Approval
from app.runtime.factory import get_runtime
from app.services.company_tools import execute_company_tool

def definition(workflow: Workflow):
    try:
        data = json.loads(workflow.definition_json or "{}")
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}

def create_run(db: Session, workflow: Workflow, input_data: dict | None = None):
    run = WorkflowRun(
        workflow_id=workflow.id, status="running", current_step=0,
        input_json=json.dumps(input_data or {}, ensure_ascii=False),
    )
    db.add(run); db.commit(); db.refresh(run)
    return run

async def advance(db: Session, run: WorkflowRun, external_result: dict | None = None):
    wf = db.get(Workflow, run.workflow_id)
    if not wf:
        raise ValueError("Workflow not found")
    steps = definition(wf).get("steps", [])

    if run.current_step >= len(steps):
        run.status = "completed"; db.add(run); db.commit(); db.refresh(run)
        return {"run_id": run.id, "state": "completed", "current_step": run.current_step}

    if run.status in {"waiting_runtime", "waiting_approval"}:
        sr = db.query(WorkflowStepRun).filter(
            WorkflowStepRun.workflow_run_id == run.id,
            WorkflowStepRun.step_index == run.current_step,
        ).first()
        if run.status == "waiting_approval":
            if not sr or not sr.approval_id:
                return {"run_id": run.id, "state": "waiting_approval"}
            approval = db.get(Approval, sr.approval_id)
            if not approval or approval.status == "pending":
                return {"run_id": run.id, "state": "waiting_approval", "approval_id": sr.approval_id}
            if approval.status == "rejected":
                sr.status = "failed"; sr.completed_at = datetime.utcnow()
                run.status = "failed"; run.error = "Approval rejected"
                db.add_all([sr, run]); db.commit()
                return {"run_id": run.id, "state": "failed", "reason": "approval_rejected"}
            sr.status = "completed"; sr.completed_at = datetime.utcnow()
            sr.output_json = json.dumps({"approval_status": approval.status})
            run.current_step += 1; run.status = "running"
            db.add_all([sr, run]); db.commit()
        elif run.status == "waiting_runtime":
            if external_result is None:
                return {"run_id": run.id, "state": "waiting_runtime", "runtime_run_id": sr.runtime_run_id if sr else ""}
            if sr:
                sr.status = "completed"; sr.completed_at = datetime.utcnow()
                sr.output_json = json.dumps(external_result, ensure_ascii=False); db.add(sr)
            run.current_step += 1; run.status = "running"; db.add(run); db.commit()

    if run.current_step >= len(steps):
        run.status = "completed"; db.add(run); db.commit(); db.refresh(run)
        return {"run_id": run.id, "state": "completed", "current_step": run.current_step}

    raw_step = steps[run.current_step]
    step = raw_step if isinstance(raw_step, dict) else {"type": "note", "name": str(raw_step)}
    typ = step.get("type", "note")
    sr = WorkflowStepRun(
        workflow_run_id=run.id, step_index=run.current_step, step_type=typ,
        name=step.get("name", typ), status="running",
        input_json=json.dumps(step, ensure_ascii=False), started_at=datetime.utcnow(),
    )
    db.add(sr); db.commit(); db.refresh(sr)

    if typ == "approval":
        approval = Approval(
            organization_id=wf.organization_id, company_id=wf.company_id,
            requester_member_id=wf.owner_member_id, action=step.get("action", wf.name),
            risk=step.get("risk", "medium"), policy_key=step.get("policy_key", "workflow-step"),
            evidence=step.get("evidence", ""), status="pending",
        )
        db.add(approval); db.commit(); db.refresh(approval)
        sr.approval_id = approval.id; sr.status = "waiting"
        run.status = "waiting_approval"
        db.add_all([sr, run]); db.commit()
        return {"run_id": run.id, "state": "waiting_approval", "approval_id": approval.id}

    if typ == "agent":
        agent_id = step.get("agent_id")
        agent = db.get(Agent, int(agent_id)) if agent_id else None
        if not agent:
            raise ValueError("Workflow agent step requires valid agent_id")
        rt = get_runtime()
        rr = await rt.run_agent(
            agent.runtime_agent_id,
            step.get("input", step.get("prompt", wf.name)),
            {"workflow_run_id": run.id, "workflow_step": run.current_step},
        )
        sr.agent_id = agent.id; sr.runtime_run_id = rr.run_id; sr.status = "waiting"
        run.status = "waiting_runtime"
        db.add_all([sr, run]); db.commit()
        return {"run_id": run.id, "state": "waiting_runtime", "runtime_run_id": rr.run_id}

    if typ == "tool":
        result = execute_company_tool(db, step.get("tool", "noop"), step.get("args", {}))
        sr.status = "completed"; sr.output_json = json.dumps(result, ensure_ascii=False); sr.completed_at = datetime.utcnow()
        run.current_step += 1; run.status = "running"
        db.add_all([sr, run]); db.commit()
        return await advance(db, run)

    sr.status = "completed"; sr.output_json = json.dumps({"note": step.get("name", "")}, ensure_ascii=False); sr.completed_at = datetime.utcnow()
    run.current_step += 1; run.status = "running"
    db.add_all([sr, run]); db.commit()
    return await advance(db, run)
