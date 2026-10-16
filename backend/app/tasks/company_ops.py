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


@celery_app.task(name="lease.tick")
def lease_tick():
    """R2: hợp đồng thuê agent — hết hạn → kết thúc + dọn ghế thuê; phí tháng; chạm trần → tạm dừng."""
    import asyncio
    from app.db.session import SessionLocal
    from app.runtime.factory import get_runtime
    from app.services import seat_leases
    db = SessionLocal()
    try:
        return asyncio.run(seat_leases.tick(db, get_runtime()))
    finally:
        db.close()


@celery_app.task(name="docs.tick")
def docs_tick():
    """M3a: thư viện tài liệu — ban hành bản đã duyệt tới ngày hiệu lực, lưu trữ bản hết hiệu lực, nhắc rà soát;
    tài liệu cốt lõi đổi → sinh lại AGENTS.md của tổ chức đó."""
    import asyncio
    from app.db.session import SessionLocal
    from app.runtime.factory import get_runtime
    from app.services import doc_library
    db = SessionLocal()
    try:
        out = doc_library.tick(db)
        try:   # M3c: nguồn đồng bộ (URL / Google Drive / Notion) tới hạn → bản nháp mới khi nguồn đổi
            from app.services import doc_ingest
            out["sources"] = doc_ingest.sync_due(db)
        except Exception as exc:  # noqa: BLE001 — một nguồn hỏng không được chặn nhịp tài liệu
            out["sources_error"] = str(exc)[:300]
        try:   # M3e vòng học: cờ → đề xuất, cụm lỗ hổng → đề xuất, đã ban hành → chạy lại eval
            from app.services import doc_feedback
            out["learning"] = doc_feedback.tick(db)
        except Exception as exc:  # noqa: BLE001
            db.rollback(); out["learning_error"] = str(exc)[:300]
        for org in out.get("core_orgs") or []:
            out.setdefault("regen", {})[org] = asyncio.run(doc_library.regen_agents(db, get_runtime(), org))
        return out
    finally:
        db.close()


@celery_app.task(name="business.tick")
def business_tick():
    """P1 (M3g–M3j): yêu cầu DLCN sắp/quá hạn, hợp đồng tới hạn báo trước / hết hạn, việc sau họp quá hạn, ngân sách chạm
    ngưỡng. Mỗi phần chạy riêng: một phần lỗi không chặn phần khác."""
    from app.db.session import SessionLocal
    from app.services import business_tick as bt
    db = SessionLocal()
    try:
        return bt.run(db)
    finally:
        db.close()
