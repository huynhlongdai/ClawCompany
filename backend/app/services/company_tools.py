from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models import InboxItem, Task
from app.services import task_lifecycle as lifecycle

def execute_company_tool(db: Session, name: str, args: dict):
    if name == "noop":
        return {"ok": True, "echo": args}
    if name == "create_inbox":
        obj = InboxItem(**args); db.add(obj); db.commit(); db.refresh(obj)
        return {"ok": True, "inbox_id": obj.id}
    if name == "update_task_status":
        task = db.get(Task, int(args["task_id"]))
        if not task:
            raise ValueError("Task not found")
        try:
            lifecycle.transition(db, task, args.get("status", "done"), via="workflow_tool",
                                 actor_member_id=args.get("actor_member_id"))
        except HTTPException as exc:
            raise ValueError(str(exc.detail)) from exc
        return {"ok": True, "task_id": task.id, "status": task.status}
    raise ValueError(f"Unknown company tool: {name}")
