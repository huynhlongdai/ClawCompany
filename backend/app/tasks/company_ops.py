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


@celery_app.task(name="kpi.snapshot")
def kpi_snapshot():
    """M2d.2: lưu số KPI của kỳ hiện tại (upsert) + đóng băng kỳ vừa qua, cho mọi công ty có KPI."""
    from app.db.session import SessionLocal
    from app.services import kpi_cascade
    db = SessionLocal()
    try:
        return kpi_cascade.tick(db)
    finally:
        db.close()


@celery_app.task(name="sla.tick")
def sla_tick():
    """M2e.4: bật đồng hồ SLA còn thiếu, quá hạn → leo thang, việc ngoài giờ của người → agent / xếp hàng."""
    from app.db.session import SessionLocal
    from app.services import operating_time
    db = SessionLocal()
    try:
        return operating_time.tick(db)
    finally:
        db.close()
