from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.models import *  # noqa: F401,F403

from app.api.organizations import router as organizations_router
from app.api.companies import router as companies_router
from app.api.departments import router as departments_router
from app.api.members import router as members_router
from app.api.agents import router as agents_router
from app.api.projects import router as projects_router
from app.api.tasks import router as tasks_router
from app.api.knowledge import router as knowledge_router
from app.api.approvals import router as approvals_router
from app.api.extended import router as extended_router
from app.api.dashboard import router as dashboard_router
from app.api.auth import router as auth_router
from app.api.jobs import router as jobs_router
from app.api.realtime import router as realtime_router
from app.api.health import router as health_router
from app.api.v7 import router as v7_router
from app.api.company_tools import router as company_tools_router
from app.api.v8 import router as v8_router
from app.api.v9 import router as v9_router
from app.api.v10 import router as v10_router
from app.api.v11 import router as v11_router
from app.api.v12 import router as v12_router
from app.api.v13 import router as v13_router
from app.api.v14 import router as v14_router
from app.api.v15 import router as v15_router
from app.api.v16 import router as v16_router
from app.api.v17 import router as v17_router
from app.api.v18 import router as v18_router
from app.api.v19 import router as v19_router
from app.api.v20 import router as v20_router
from app.api.v21 import router as v21_router
from app.api.v22 import router as v22_router
from app.api.v24 import router as v24_router
from app.api.v25 import router as v25_router
from app.api.v26 import router as v26_router
from app.api.v27 import router as v27_router
from app.api.v28 import router as v28_router
from app.api.v29 import router as v29_router
from app.api.v30 import router as v30_router
from app.api.v31 import router as v31_router
from app.api.v32 import router as v32_router
from app.api.v33 import router as v33_router
from app.api.v34 import router as v34_router
from app.api.v35 import router as v35_router
from app.core.middleware import RequestContextMiddleware

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name, version="1.25.0")
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"status":"ok","service":"clawcompany-api","version":"1.25.0"}

app.include_router(organizations_router, prefix="/api")
app.include_router(companies_router, prefix="/api")
app.include_router(departments_router, prefix="/api")
app.include_router(members_router, prefix="/api")
app.include_router(agents_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(knowledge_router, prefix="/api")
app.include_router(approvals_router, prefix="/api")
app.include_router(extended_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
app.include_router(realtime_router, prefix="/api")
app.include_router(health_router, prefix="/api")
app.include_router(v7_router, prefix="/api")
app.include_router(company_tools_router, prefix="/api")
app.include_router(v8_router, prefix="/api")
app.include_router(v9_router, prefix="/api")

app.include_router(v10_router, prefix="/api")

app.include_router(v11_router, prefix="/api")

app.include_router(v12_router, prefix="/api")

app.include_router(v13_router, prefix="/api")

app.include_router(v14_router, prefix="/api")

app.include_router(v15_router, prefix="/api")
app.include_router(v16_router, prefix="/api")
app.include_router(v17_router, prefix="/api")
app.include_router(v18_router, prefix="/api")
app.include_router(v19_router, prefix="/api")
app.include_router(v20_router, prefix="/api")
app.include_router(v21_router, prefix="/api")
app.include_router(v22_router, prefix="/api")
app.include_router(v24_router, prefix="/api")
app.include_router(v25_router, prefix="/api")
app.include_router(v26_router, prefix="/api")
app.include_router(v27_router, prefix="/api")
app.include_router(v28_router, prefix="/api")
app.include_router(v29_router, prefix="/api")
app.include_router(v30_router, prefix="/api")
app.include_router(v31_router, prefix="/api")
app.include_router(v32_router, prefix="/api")
app.include_router(v33_router, prefix="/api")
app.include_router(v34_router, prefix="/api")
app.include_router(v35_router, prefix="/api")


@app.on_event("startup")
def resume_openclaw_followers() -> None:
    """v21: re-attach session followers for work that was mid-run on restart.

    Opt-in, because attaching followers on boot starts outbound gateway
    connections. Safe under multiple workers: the shared lease decides which
    process owns each session. Never blocks startup on a runtime problem.
    """
    if not settings.openclaw_resume_on_boot:
        return
    from app.db.session import SessionLocal
    from app.services.runtime_stream import resume_followers

    db = SessionLocal()
    try:
        resume_followers(db)
    except Exception as exc:  # noqa: BLE001 - a boot helper must not kill the app
        print(f"[v21] follower resume skipped: {exc}")
    finally:
        db.close()


@app.on_event("startup")
async def start_orphan_sweep() -> None:
    """v22: keep taking over sessions whose follower died.

    v21 stopped a follower that lost its lease but left the session unattended
    until someone pressed resume. This closes that window. Off by default
    (OPENCLAW_CLAIM_SWEEP_SECONDS=0) because it opens outbound gateway
    connections on its own schedule.
    """
    interval = settings.openclaw_claim_sweep_seconds
    if interval <= 0:
        return
    import asyncio

    from app.services.runtime_stream import sweep_orphans_forever

    try:
        asyncio.create_task(sweep_orphans_forever(interval), name="openclaw-orphan-sweep")
    except Exception as exc:  # noqa: BLE001 - never block startup
        print(f"[v22] orphan sweep not started: {exc}")
