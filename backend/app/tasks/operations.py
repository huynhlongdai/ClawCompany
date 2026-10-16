import asyncio
from app.worker import celery_app
from app.db.session import SessionLocal
from app.models import OperatingCycle
from app.services.orchestration import tick_cycle
from app.services.recurring_ops import run_due


@celery_app.task(name="operations.scan_recurring")
def scan_recurring_operations():
    """W0: không còn trong beat (routines.tick là chủ); gọi tay vẫn an toàn nhờ claim CAS."""
    db = SessionLocal()
    try:
        results = run_due(db)
        return {"processed": len(results), "results": results}
    finally:
        db.close()


@celery_app.task(name="operations.tick_cycles")
def tick_operating_cycles():
    """W0: không còn trong beat (mục tiêu thuộc strategy/Nina). Gọi tay: bỏ qua chu kỳ của mục tiêu strategy giữ."""
    db = SessionLocal()
    results = []
    try:
        rows = db.query(OperatingCycle).filter(OperatingCycle.status.in_(["running", "waiting_approval"])).order_by(OperatingCycle.id).limit(50).all()
        for cycle in rows:
            try:
                summary = asyncio.run(tick_cycle(db, cycle, capture_runtime=True))
                results.append({"cycle_id": cycle.id, "status": summary["cycle"].status})
            except Exception as exc:
                results.append({"cycle_id": cycle.id, "error": str(exc)})
        return {"processed": len(results), "results": results}
    finally:
        db.close()
