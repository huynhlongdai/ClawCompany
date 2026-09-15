"""v36 API: lịch sử chỉ số, lịch, số theo ngày của agent, hạn chót dự án.

Bốn khối mà bản thiết kế UI cần và hệ thống chưa có nguồn. Mọi endpoint đọc
đều mang theo lời thừa nhận về nguồn dữ liệu, cùng lối viết của v35: người
soát xét không phải tin vào giao diện.
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_role, require_scope
from app.core.tenancy import active_org, ensure_project
from app.db.session import get_db
from app.services import v36_insights as insights

router = APIRouter(prefix="/v36", tags=["v36-insights"])

READ = "company.context:read"
WRITE = "company.workspace:write"


def writer(minimum_role: str = "member"):
    """Người thì chặn theo vai, agent thì chặn theo scope — như v18 tới v35."""
    def dep(principal: Principal = Depends(require_scope(WRITE))) -> Principal:
        if principal.auth_type != "api_key":
            return require_role(minimum_role)(principal)
        return principal
    return dep


# ------------------------------------------------------------------ coverage

@router.get("/coverage")
def coverage(principal: Principal = Depends(require_scope(READ))):
    """Trần năng lực của v36, đọc được qua API.

    Bốn khối này sinh ra vì bản thiết kế cần chúng. Mỗi khối nói rõ nguồn và
    chỗ yếu, để không ai nhìn biểu đồ rồi tưởng nó là chuỗi đo liên tục.
    """
    return {
        "metric_history": {
            "table": "metric_samples",
            "source": "analytics_metrics qua snapshot, cộng backfill hai mốc",
            "continuous_measurements": False,
            "note": "Bảng cũ chỉ giữ trị hiện tại và trị kỳ trước, nên chuỗi bắt "
                    "đầu từ hai điểm. Gọi POST /api/v36/metrics/snapshot theo cron "
                    "để chuỗi dài ra bằng số thật.",
        },
        "calendar": {
            "table": "calendar_events",
            "synced_from_provider": False,
            "note": "Lịch do người và agent tạo. Chưa nối Google/Outlook, nên "
                    "lịch trống nghĩa là chưa ai tạo mục nào.",
        },
        "agent_daily_stats": {
            "table": "agent_daily_stats",
            "derived_from": ["usage_events", "company_events"],
            "writable_by_hand": False,
            "note": "company_events không mang agent_id, nên kết quả việc chỉ quy "
                    "được về agent khi payload có runtime_agent_id.",
        },
        "project_due_date": {
            "column": "projects.due_date",
            "nullable": True,
            "note": "Chưa đặt hạn là câu trả lời hợp lệ; dự án không có hạn không "
                    "xuất hiện trong danh sách deadline.",
        },
    }


# ------------------------------------------------------------------- chỉ số

@router.get("/metrics/history")
def metric_history(metric_key: str | None = None, limit: int = Query(200, ge=1, le=500),
                   db: Session = Depends(get_db),
                   principal: Principal = Depends(require_scope(READ))):
    return insights.metric_history(db, active_org(principal),
                                   metric_key=metric_key, limit=limit)


@router.post("/metrics/snapshot")
def snapshot_metrics(grain: str = Query("month", pattern="^(month|day)$"),
                     db: Session = Depends(get_db),
                     principal: Principal = Depends(writer("manager"))):
    """Chốt trị hiện tại của mọi chỉ số vào kỳ đang xét.

    Gọi lại trong cùng kỳ thì ghi đè đúng điểm đó, nên một cron hằng ngày
    không nhân bản biểu đồ.
    """
    return insights.snapshot_metrics(db, active_org(principal), grain=grain)


# ---------------------------------------------------------------------- lịch

class CalendarIn(BaseModel):
    title: str = Field(min_length=1, max_length=220)
    starts_at: datetime
    ends_at: datetime | None = None
    event_type: str = Field(default="meeting", pattern="^(meeting|deadline|milestone|review)$")
    description: str = ""
    location: str = ""
    company_id: int | None = None
    project_id: int | None = None
    owner_member_id: int | None = None


@router.get("/calendar")
def calendar(day: date | None = None, days: int = Query(1, ge=1, le=31),
             db: Session = Depends(get_db),
             principal: Principal = Depends(require_scope(READ))):
    return insights.calendar(db, active_org(principal), day=day, days=days)


@router.post("/calendar")
def create_calendar_event(payload: CalendarIn, db: Session = Depends(get_db),
                          principal: Principal = Depends(writer("member"))):
    try:
        event = insights.create_calendar_event(
            db, active_org(principal), title=payload.title,
            starts_at=payload.starts_at, ends_at=payload.ends_at,
            event_type=payload.event_type, description=payload.description,
            location=payload.location, company_id=payload.company_id,
            project_id=payload.project_id, owner_member_id=payload.owner_member_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"id": event.id, "title": event.title,
            "starts_at": event.starts_at.isoformat(), "event_type": event.event_type}


# ------------------------------------------------------- số theo ngày agent

@router.get("/agent-stats")
def agent_stats(agent_id: int | None = None, days: int = Query(30, ge=1, le=90),
                db: Session = Depends(get_db),
                principal: Principal = Depends(require_scope(READ))):
    return insights.agent_series(db, active_org(principal), agent_id=agent_id, days=days)


@router.post("/agent-stats/derive")
def derive_agent_stats(days: int = Query(30, ge=1, le=90),
                       db: Session = Depends(get_db),
                       principal: Principal = Depends(writer("manager"))):
    """Tính lại số theo ngày từ usage_events và company_events."""
    return insights.derive_agent_stats(db, active_org(principal), days=days)


# ------------------------------------------------------------------ hỏi Nina

class AskIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    timeout_seconds: int = Field(default=60, ge=5, le=120)


@router.post("/nina/ask")
async def ask_nina(payload: AskIn, db: Session = Depends(get_db),
                   principal: Principal = Depends(writer("member"))):
    """Hỏi Nina qua gateway OpenClaw, tức có model thật trả lời.

    Khác ``/api/nina/command``: endpoint đó là bộ phân tích ý định theo luật,
    trả lời đúng vài câu đã lập trình sẵn. Endpoint này đi qua chat.send tới
    gateway, nên trả lời được câu tự do — và cũng tốn tiền model thật.

    ``async def`` là bắt buộc: bên trong await runtime. Một endpoint sync sẽ
    chạy trong threadpool và không có event loop — đúng lỗi mà v20 follow vừa
    mắc phải.
    """
    return await insights.ask_nina(db, active_org(principal),
                                   message=payload.message,
                                   timeout_seconds=payload.timeout_seconds)


# ------------------------------------------------------------------ hạn chót

class DueDateIn(BaseModel):
    # None nghĩa là bỏ hạn — khác với không truyền trường này.
    due_date: date | None = Field(...)


@router.get("/deadlines")
def deadlines(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db),
              principal: Principal = Depends(require_scope(READ))):
    return insights.upcoming_deadlines(db, active_org(principal), days=days)


@router.post("/projects/{project_id}/due-date")
def set_due_date(project_id: int, payload: DueDateIn, db: Session = Depends(get_db),
                 principal: Principal = Depends(writer("member"))):
    project = ensure_project(db, project_id, principal)
    updated = insights.set_project_due_date(db, project, payload.due_date)
    return {"project_id": updated.id, "name": updated.name,
            "due_date": updated.due_date.isoformat() if updated.due_date else None}
