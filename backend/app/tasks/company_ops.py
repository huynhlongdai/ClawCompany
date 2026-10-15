"""M2c — job nền của vận hành công ty: D6 giao ban/báo cáo tuần, D7 nhắc hạn tuân thủ."""
from app.worker import celery_app


@celery_app.task(name="rhythm.tick")
def rhythm_tick():
    """D6: tới giờ giao ban / báo cáo tuần của công ty nào thì sinh + gửi Hộp việc (idempotent theo kỳ)."""
    import asyncio
    from app.core.config import settings
    from app.db.session import SessionLocal
    from app.services import operating_rhythm
    rt = None
    if (settings.openclaw_mode or "").lower() in ("native", "gateway"):
        from app.runtime.factory import get_runtime
        rt = get_runtime()
    db = SessionLocal()
    try:
        return asyncio.run(operating_rhythm.tick(db, runtime=rt))
    finally:
        db.close()


@celery_app.task(name="compliance.tick")
def compliance_tick():
    """D7: sinh hạn tuân thủ 120 ngày tới + nhắc trước N ngày vào Hộp việc, giao chức danh kế toán."""
    from app.db.session import SessionLocal
    from app.services import compliance_calendar
    db = SessionLocal()
    try:
        return compliance_calendar.tick(db)
    finally:
        db.close()
