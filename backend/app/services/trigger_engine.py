import fnmatch
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import Approval, CompanyEvent, EventTrigger, TriggerExecution, Workflow, WorkflowRun
from app.services.agent_messaging import send_message
from app.services.company_event_bus import payload_of
from app.services.orchestration import create_goal


def _json(value: str | None, fallback):
    try:
        parsed = json.loads(value or "")
        return parsed
    except Exception:
        return fallback


def _get_path(payload: dict, path: str):
    current = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _condition_matches(payload: dict, condition: dict) -> bool:
    for key, expected in condition.items():
        actual = _get_path(payload, key)
        if isinstance(expected, dict):
            if "eq" in expected and actual != expected["eq"]: return False
            if "ne" in expected and actual == expected["ne"]: return False
            if "in" in expected and actual not in expected["in"]: return False
            if "gte" in expected:
                try:
                    if float(actual) < float(expected["gte"]): return False
                except Exception: return False
            if "lte" in expected:
                try:
                    if float(actual) > float(expected["lte"]): return False
                except Exception: return False
        elif actual != expected:
            return False
    return True


def trigger_matches(trigger: EventTrigger, event: CompanyEvent) -> bool:
    if not trigger.enabled or trigger.organization_id != event.organization_id:
        return False
    if trigger.company_id is not None and trigger.company_id != event.company_id:
        return False
    if not fnmatch.fnmatchcase(event.event_type, trigger.event_pattern or "*"):
        return False
    if trigger.cooldown_seconds and trigger.last_fired_at:
        if trigger.last_fired_at + timedelta(seconds=trigger.cooldown_seconds) > datetime.utcnow():
            return False
    return _condition_matches(payload_of(event), _json(trigger.condition_json, {}))


def _execute_action(db: Session, trigger: EventTrigger, event: CompanyEvent):
    action = _json(trigger.action_json, {})
    payload = payload_of(event)
    if trigger.action_type == "message":
        recipient = action.get("recipient_member_id")
        if recipient is None:
            raise ValueError("message trigger requires recipient_member_id")
        msg = send_message(
            db, organization_id=event.organization_id, company_id=event.company_id,
            sender_member_id=action.get("sender_member_id"), recipient_member_id=int(recipient),
            thread_key=action.get("thread_key", f"event:{event.correlation_id}"),
            message_type=action.get("message_type", "event_notification"),
            subject=action.get("subject", f"Event: {event.event_type}"),
            content=action.get("content", f"Event {event.event_type} fired trigger {trigger.name}."),
            priority=action.get("priority", "normal"),
            context={"event_id": event.id, "event_type": event.event_type, "event_payload": payload}, emit=False,
        )
        return "agent_message", msg.id, {"message_id": msg.id}
    if trigger.action_type == "goal":
        goal = create_goal(
            db, organization_id=event.organization_id, user_id=None, company_id=event.company_id,
            title=action.get("title", f"Respond to {event.event_type}"),
            objective=action.get("objective", f"Respond to company event {event.event_type}: {json.dumps(payload, ensure_ascii=False)}"),
            expected_outcome=action.get("expected_outcome", "Event resolved and outcome recorded."),
            priority=action.get("priority", "high"), risk=action.get("risk", "medium"),
            autonomy_mode=action.get("autonomy_mode", "inherit"), budget_limit=action.get("budget_limit"),
        )
        return "executive_goal", goal.id, {"goal_id": goal.id}
    if trigger.action_type == "approval":
        approval = Approval(
            organization_id=event.organization_id, company_id=event.company_id,
            requester_member_id=action.get("requester_member_id"), approver_member_id=action.get("approver_member_id"),
            action=action.get("action", event.event_type), risk=action.get("risk", "medium"),
            policy_key=action.get("policy_key", f"event.{event.event_type}"), status="pending",
            evidence=json.dumps({"event_id": event.id, "payload": payload}, ensure_ascii=False),
        )
        db.add(approval); db.commit(); db.refresh(approval)
        return "approval", approval.id, {"approval_id": approval.id}
    if trigger.action_type == "workflow":
        workflow_id = action.get("workflow_id")
        workflow = db.get(Workflow, int(workflow_id)) if workflow_id else None
        if not workflow or workflow.organization_id != event.organization_id:
            raise ValueError("workflow trigger requires a valid workflow_id in the same organization")
        run = WorkflowRun(
            workflow_id=workflow.id, status="queued", current_step=0,
            input_json=json.dumps({"event_id": event.id, "event_type": event.event_type, "payload": payload}, ensure_ascii=False),
            output_json="{}", error="",
        )
        db.add(run); db.commit(); db.refresh(run)
        return "workflow_run", run.id, {"workflow_run_id": run.id}
    raise ValueError(f"Unsupported trigger action_type: {trigger.action_type}")


def process_event(db: Session, event: CompanyEvent) -> dict:
    if event.status == "processed":
        rows = db.query(TriggerExecution).filter(TriggerExecution.event_id == event.id).all()
        return {"event": event, "executions": rows, "already_processed": True}
    executions = []
    triggers = db.query(EventTrigger).filter(
        EventTrigger.organization_id == event.organization_id,
        EventTrigger.enabled == True,  # noqa: E712
    ).order_by(EventTrigger.id).all()
    had_error = False
    for trigger in triggers:
        if not trigger_matches(trigger, event):
            continue
        execution = TriggerExecution(
            organization_id=event.organization_id, trigger_id=trigger.id, event_id=event.id,
            status="running", result_type="", result_id="", result_json="{}", error="",
        )
        db.add(execution); db.commit(); db.refresh(execution)
        try:
            result_type, result_id, result = _execute_action(db, trigger, event)
            execution.status = "completed"; execution.result_type = result_type; execution.result_id = str(result_id)
            execution.result_json = json.dumps(result, ensure_ascii=False, default=str)
            trigger.last_fired_at = datetime.utcnow()
            db.add_all([execution, trigger]); db.commit(); db.refresh(execution)
        except Exception as exc:
            execution.status = "failed"; execution.error = str(exc); db.add(execution); db.commit(); db.refresh(execution)
            had_error = True
        executions.append(execution)
    event.status = "error" if had_error else "processed"
    event.error = "One or more trigger executions failed" if had_error else ""
    event.processed_at = datetime.utcnow()
    db.add(event); db.commit(); db.refresh(event)
    return {"event": event, "executions": executions, "already_processed": False}
