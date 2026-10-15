from celery import Celery
from app.core.config import settings

celery_app = Celery("clawcompany", broker=settings.celery_broker_url, backend=settings.celery_result_backend)
celery_app.conf.imports = ("app.tasks.knowledge", "app.tasks.runtime", "app.tasks.operations", "app.tasks.events", "app.tasks.delivery", "app.tasks.webhooks", "app.tasks.dev_cloud", "app.tasks.engineering", "app.tasks.v14", "app.tasks.v15")

# Job nền của các module Phòng thí nghiệm (plan-v2-modules §2). Chỉ lập lịch khi
# LAB_JOBS_ENABLED=true; thân task cũng tự kiểm cờ (app.core.lab.lab_job) nên gọi tay
# hay beat cũ còn sót lịch cũng không chạy khi cờ tắt.
LAB_BEAT_SCHEDULE = {
    "cleanup-expired-dev-cloud-resources": {"task": "devcloud.cleanup_expired", "schedule": 300.0},
    "reap-v14-runner-leases": {"task": "v14.reap_runner_leases", "schedule": 30.0},
    "evaluate-v14-slos": {"task": "v14.evaluate_slos", "schedule": 60.0},
    "review-v14-engineering-portfolios": {"task": "v14.review_portfolios", "schedule": 300.0},
    "v15-control-plane-tick": {"task": "v15.control_plane_tick", "schedule": 20.0},
    "v15-export-telemetry": {"task": "v15.export_telemetry", "schedule": 60.0},
}
LAB_TASK_NAMES = tuple(v["task"] for v in LAB_BEAT_SCHEDULE.values())

CORE_BEAT_SCHEDULE = {
    "scan-recurring-operations": {"task": "operations.scan_recurring", "schedule": 60.0},
    "tick-operating-cycles": {"task": "operations.tick_cycles", "schedule": 30.0},
    "dispatch-company-events": {"task": "events.dispatch_pending", "schedule": 10.0},
    "monitor-company-sla": {"task": "events.monitor_sla", "schedule": 60.0},
    "tick-nina-decision-loops": {"task": "events.tick_decision_loops", "schedule": 30.0},
    "dispatch-event-webhooks": {"task": "webhooks.dispatch_due", "schedule": 5.0},
    # D2.1: biến lý do đánh thức thành lượt chạy (gộp trong cửa sổ 10 giây).
    "drain-wakeups": {"task": "wakeups.drain", "schedule": 5.0},
    # D3.5: approval quá hạn → chuyển lên quản lý (audit approval.escalated).
    # Lệnh shell chờ duyệt (exec.mode=ask) → hộp duyệt, kể cả khi chat trực tiếp.
    "sweep-gateway-approvals": {"task": "approvals.sweep_gateway", "schedule": 10.0},
    "escalate-overdue-approvals": {"task": "approvals.escalate_overdue", "schedule": 60.0},
    # D3.4: routines — giờ hẹn cron theo múi giờ, chạy bù, kết cục từng lần chạy.
    "tick-routines": {"task": "routines.tick", "schedule": 30.0},
    # M5b việc 9: tới giờ học của khoá → mỗi agent học/thi một bước mỗi ngày.
    "tick-courses": {"task": "courses.tick", "schedule": 600.0},
    # M5b việc 10: đề xuất kỹ năng của agent (Skill Workshop) → Hộp việc.
    "sync-skill-proposals": {"task": "skills.sync_workshop", "schedule": 300.0},
}


def build_beat_schedule(lab_jobs_enabled: bool) -> dict:
    schedule = dict(CORE_BEAT_SCHEDULE)
    if lab_jobs_enabled:
        schedule.update(LAB_BEAT_SCHEDULE)
    return schedule


celery_app.conf.update(
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    beat_schedule=build_beat_schedule(settings.lab_jobs_enabled),
)
celery_app.autodiscover_tasks(["app.tasks"])
