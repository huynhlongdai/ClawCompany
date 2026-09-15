from sqlalchemy.orm import Session
from app.models import InboxItem, Task

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
        task.status = args.get("status", "done")
        db.add(task); db.commit(); db.refresh(task)
        return {"ok": True, "task_id": task.id, "status": task.status}
    raise ValueError(f"Unknown company tool: {name}")
