from celery import Celery
from app.core.config import settings

celery_app = Celery("clawcompany", broker=settings.celery_broker_url, backend=settings.celery_result_backend)
celery_app.conf.imports = ("app.tasks.knowledge", "app.tasks.runtime", "app.tasks.operations", "app.tasks.events", "app.tasks.delivery", "app.tasks.webhooks", "app.tasks.dev_cloud", "app.tasks.engineering", "app.tasks.v14", "app.tasks.v15")

celery_app.conf.update(
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    beat_schedule={
        "scan-recurring-operations": {"task": "operations.scan_recurring", "schedule": 60.0},
        "tick-operating-cycles": {"task": "operations.tick_cycles", "schedule": 30.0},
        "dispatch-company-events": {"task": "events.dispatch_pending", "schedule": 10.0},
        "monitor-company-sla": {"task": "events.monitor_sla", "schedule": 60.0},
        "tick-nina-decision-loops": {"task": "events.tick_decision_loops", "schedule": 30.0},
        "dispatch-event-webhooks": {"task": "webhooks.dispatch_due", "schedule": 5.0},
        "cleanup-expired-dev-cloud-resources": {"task": "devcloud.cleanup_expired", "schedule": 300.0},
        "reap-v14-runner-leases": {"task": "v14.reap_runner_leases", "schedule": 30.0},
        "evaluate-v14-slos": {"task": "v14.evaluate_slos", "schedule": 60.0},
        "review-v14-engineering-portfolios": {"task": "v14.review_portfolios", "schedule": 300.0},
        "v15-control-plane-tick": {"task": "v15.control_plane_tick", "schedule": 20.0},
        "v15-export-telemetry": {"task": "v15.export_telemetry", "schedule": 60.0},
    },
)
celery_app.autodiscover_tasks(["app.tasks"])
