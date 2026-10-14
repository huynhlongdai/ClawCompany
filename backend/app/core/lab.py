"""Cờ Phòng thí nghiệm cho job nền (plan-v2-modules §2).

Ẩn 27 trang khỏi menu chưa đủ: 6 job Celery của các module đó vẫn chạy và
``v15.control_plane_tick`` ghi vào bảng ``approvals``. Cờ ``LAB_JOBS_ENABLED``
(mặc định tắt) chặn ở hai chỗ: beat không lập lịch (``app.worker``) và thân task
trả về ngay mà không mở phiên DB (``lab_job`` dưới đây).
"""
from functools import wraps

from app.core.config import settings

SKIPPED = {"skipped": "lab_jobs_disabled"}


def lab_jobs_enabled() -> bool:
    return bool(settings.lab_jobs_enabled)


def lab_job(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not lab_jobs_enabled():
            return dict(SKIPPED)
        return fn(*args, **kwargs)
    return wrapper
