from fastapi import APIRouter
from sqlalchemy import text
from app.db.session import engine
from app.core.config import settings
from app.runtime.factory import get_runtime

router=APIRouter(prefix="/health",tags=["health"])

@router.get("/live")
def live():return {"status":"ok"}

@router.get("/ready")
async def ready():
    result={"status":"ok","db":"unknown","redis":"unknown","runtime":"unknown"}
    try:
        with engine.connect() as conn:conn.execute(text("SELECT 1"))
        result["db"]="ok"
    except Exception as exc:result["db"]=f"error:{exc}";result["status"]="degraded"
    try:
        import redis
        r=redis.from_url(settings.redis_url,socket_timeout=1);r.ping();result["redis"]="ok"
    except Exception as exc:result["redis"]=f"error:{exc}";result["status"]="degraded"
    try:result["runtime"]=(await get_runtime().health()).get("status","unknown")
    except Exception as exc:result["runtime"]=f"error:{exc}";result["status"]="degraded"
    return result


@router.get("/lab")
def lab():
    """Cờ Phòng thí nghiệm: 6 job nền của module bị ẩn có được lập lịch/chạy không."""
    from app.worker import LAB_TASK_NAMES
    return {"lab_jobs_enabled": bool(settings.lab_jobs_enabled), "env": "LAB_JOBS_ENABLED", "jobs": list(LAB_TASK_NAMES)}
