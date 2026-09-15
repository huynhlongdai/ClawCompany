import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from app.models import ExecutiveGoal, RecurringOperation
from app.services.audit import log_event
from app.services.orchestration import create_goal, plan_goal, create_cycle


def _cron_values(field: str, minimum: int, maximum: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            values.update(range(minimum, maximum + 1)); continue
        if part.startswith("*/"):
            step = int(part[2:])
            if step <= 0: raise ValueError("Cron step must be positive")
            values.update(range(minimum, maximum + 1, step)); continue
        if "-" in part:
            left, right = part.split("-", 1)
            a, b = int(left), int(right)
            if a > b: raise ValueError("Invalid cron range")
            values.update(range(a, b + 1)); continue
        values.add(int(part))
    if not values or min(values) < minimum or max(values) > maximum:
        raise ValueError(f"Cron field out of range {minimum}-{maximum}")
    return values


def compute_next(schedule: str, timezone_name: str, base: datetime | None = None) -> datetime:
    """Compute the next run for a practical five-field cron subset.

    Supports `*`, `*/n`, comma lists, ranges and integers. This deliberately
    avoids a scheduler-only dependency in the API process. Cron weekday uses
    Sunday=0/7, matching common cron notation.
    """
    zone = ZoneInfo(timezone_name or "UTC")
    parts = schedule.split()
    if len(parts) != 5:
        raise ValueError("Schedule must be a five-field cron expression")
    mins = _cron_values(parts[0], 0, 59)
    hours = _cron_values(parts[1], 0, 23)
    days = _cron_values(parts[2], 1, 31)
    months = _cron_values(parts[3], 1, 12)
    weekdays = {0 if x == 7 else x for x in _cron_values(parts[4], 0, 7)}
    current = base or datetime.now(zone)
    if current.tzinfo is None:
        current = current.replace(tzinfo=zone)
    current = current.astimezone(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
    max_checks = 60 * 24 * 370
    for _ in range(max_checks):
        cron_weekday = (current.weekday() + 1) % 7
        if (current.minute in mins and current.hour in hours and current.day in days and
                current.month in months and cron_weekday in weekdays):
            return current.astimezone(timezone.utc).replace(tzinfo=None)
        current += timedelta(minutes=1)
    raise ValueError("Could not find a matching cron time within 370 days")


def create_recurring_operation(db: Session, *, organization_id: int, company_id: int | None, name: str,
                               schedule: str, timezone_name: str, operation_type: str, payload: dict, enabled: bool):
    item = RecurringOperation(
        organization_id=organization_id, company_id=company_id, name=name, schedule=schedule,
        timezone=timezone_name, operation_type=operation_type, payload_json=json.dumps(payload, ensure_ascii=False),
        enabled=enabled, last_status="never",
    )
    if enabled:
        item.next_run_at = compute_next(schedule, timezone_name)
    db.add(item); db.commit(); db.refresh(item)
    return item


def _payload(item: RecurringOperation) -> dict:
    try:
        return json.loads(item.payload_json or "{}")
    except Exception:
        return {}


def execute_operation(db: Session, item: RecurringOperation, *, user_id: int | None = None):
    payload = _payload(item)
    result: dict = {"operation_id": item.id, "type": item.operation_type}
    try:
        if item.operation_type == "nina_goal":
            title = str(payload.get("title") or item.name)
            objective = str(payload.get("objective") or payload.get("prompt") or item.name)
            goal = create_goal(
                db, organization_id=item.organization_id, user_id=user_id, company_id=item.company_id,
                title=title, objective=objective, expected_outcome=str(payload.get("expected_outcome") or ""),
                priority=str(payload.get("priority") or "high"), risk=str(payload.get("risk") or "low"),
                autonomy_mode=str(payload.get("autonomy_mode") or "inherit"), deadline="",
                budget_limit=payload.get("budget_limit"), currency=str(payload.get("currency") or "USD"),
            )
            if payload.get("plan", True):
                plan_goal(
                    db, goal, user_id=user_id, max_steps=int(payload.get("max_steps") or 5),
                    project_id=payload.get("project_id"), auto_create_tasks=bool(payload.get("auto_create_tasks", True)),
                )
            cycle = None
            if payload.get("execute", True) and goal.execution_plan_id:
                cycle = create_cycle(db, goal, estimated_cost_per_assignment=float(payload.get("estimated_cost_per_assignment") or 0.25))
            result.update({"goal_id": goal.id, "cycle_id": cycle.id if cycle else None})
        elif item.operation_type == "progress_sync":
            # v34: the progress drift sweep is now a scheduled operation.
            # Imported lazily: progress_schedule imports this module for
            # compute_next/create_recurring_operation, so a top-level import
            # here would be a cycle.
            from app.services.progress_schedule import run_scheduled
            result.update(run_scheduled(db, item))
        else:
            raise ValueError(f"Unsupported recurring operation type: {item.operation_type}")
        item.last_status = "success"
    except Exception as exc:
        item.last_status = "failed"
        result["error"] = str(exc)
    item.last_run_at = datetime.utcnow()
    item.next_run_at = compute_next(item.schedule, item.timezone, datetime.now(ZoneInfo(item.timezone or "UTC"))) if item.enabled else None
    db.add(item); db.commit(); db.refresh(item)
    log_event(db, item.organization_id, "recurring_operation.run", "recurring_operations", item.id, actor_name="scheduler", result=item.last_status, payload=result)
    return result


def due_operations(db: Session, now: datetime | None = None):
    now = now or datetime.utcnow()
    return db.query(RecurringOperation).filter(
        RecurringOperation.enabled == True,  # noqa: E712
        RecurringOperation.next_run_at.is_not(None),
        RecurringOperation.next_run_at <= now,
    ).order_by(RecurringOperation.next_run_at).all()
