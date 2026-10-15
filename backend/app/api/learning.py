"""M5b việc 9 — kho tri thức hợp nhất, lỗ hổng kiến thức, khoá học của agent."""
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.authz import Principal, require_human, require_role
from app.core.tenancy import active_org
from app.db.session import get_db
from app.runtime.factory import get_runtime
from app.services import courses, knowledge_hub

router = APIRouter(prefix="/learning", tags=["learning"])


class Scope(BaseModel):
    company_id: int | None = None
    department_id: int | None = None
    project_id: int | None = None
    agent_id: int | None = None


class DocIn(Scope):
    title: str = Field(default="", max_length=220)
    content: str = Field(default="", max_length=400_000)
    url: str = Field(default="", max_length=1000)


@router.get("/docs")
def docs(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return {"items": knowledge_hub.list_docs(db, active_org(principal))}


@router.post("/docs")
def add_doc(payload: DocIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """Nạp văn bản dán trực tiếp, hoặc một URL (tải về, bỏ menu/script, giữ tiêu đề)."""
    org = active_org(principal)
    scope = payload.model_dump(include={"company_id", "department_id", "project_id", "agent_id"})
    if payload.url:
        title, text = knowledge_hub.fetch_url(payload.url)
        return knowledge_hub.ingest(db, org, title=payload.title or title or payload.url, content=text,
                                    source_type="url", source_url=payload.url, scope=scope)
    return knowledge_hub.ingest(db, org, title=payload.title, content=payload.content, source_type="text", scope=scope)


@router.post("/docs/upload")
async def upload_doc(file: UploadFile = File(...), title: str = Form(default=""),
                     company_id: int | None = Form(default=None), department_id: int | None = Form(default=None),
                     project_id: int | None = Form(default=None), agent_id: int | None = Form(default=None),
                     principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """Nạp tệp PDF / DOCX / Markdown / TXT / CSV / HTML (tối đa 20 MB)."""
    from fastapi import HTTPException
    data = await file.read()
    if len(data) > 20_000_000:
        raise HTTPException(422, "Tệp tối đa 20 MB")
    text = knowledge_hub.extract_text(file.filename or "", data)
    return knowledge_hub.ingest(db, active_org(principal), title=title or (file.filename or "Tài liệu").rsplit(".", 1)[0],
                                content=text, source_type="upload",
                                scope={"company_id": company_id, "department_id": department_id,
                                       "project_id": project_id, "agent_id": agent_id})


@router.post("/docs/{doc_id}/resync")
def resync_doc(doc_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """Tải lại URL nguồn; nội dung đổi → chỉ mục lại + học viên các khoá dùng tài liệu này chuyển sang 'Cần ôn'."""
    return knowledge_hub.resync(db, active_org(principal), doc_id)


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return knowledge_hub.delete(db, active_org(principal), doc_id)


@router.get("/search")
def search(q: str, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    """Tra thử như agent tra (có trích dẫn). Người tra không ghi lỗ hổng."""
    return knowledge_hub.search(db, active_org(principal), q, log_gap=False)


@router.get("/gaps")
def gaps(status: str = "open", principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return {"items": knowledge_hub.list_gaps(db, active_org(principal), status)}


class GapIn(BaseModel):
    document_id: int | None = None
    dismiss: bool = False


@router.post("/gaps/{gap_id}/resolve")
def resolve_gap(gap_id: int, payload: GapIn, principal: Principal = Depends(require_role("manager")),
                db: Session = Depends(get_db)):
    return knowledge_hub.resolve_gap(db, active_org(principal), gap_id, document_id=payload.document_id,
                                     dismiss=payload.dismiss)


class CourseIn(BaseModel):
    title: str | None = Field(default=None, max_length=220)
    goal: str | None = Field(default=None, max_length=4000)
    document_ids: list[int] | None = None
    study_hour: int | None = None
    study_tz: str | None = None
    pass_score: int | None = None
    status: str | None = None
    agent_ids: list[int] = []
    department_ids: list[int] = []


@router.get("/courses")
def list_courses(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return {"items": courses.list_courses(db, active_org(principal))}


@router.post("/courses")
def create_course(payload: CourseIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return courses.create(db, principal, active_org(principal), payload.model_dump(exclude_unset=True))


@router.get("/courses/{course_id}")
def course_detail(course_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return courses.detail(db, active_org(principal), course_id)


@router.put("/courses/{course_id}")
def update_course(course_id: int, payload: CourseIn, principal: Principal = Depends(require_role("manager")),
                  db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    data.pop("agent_ids", None); data.pop("department_ids", None)
    return courses.update(db, active_org(principal), course_id, data)


class EnrollIn(BaseModel):
    agent_ids: list[int] = []
    department_ids: list[int] = []


@router.post("/courses/{course_id}/enroll")
def enroll(course_id: int, payload: EnrollIn, principal: Principal = Depends(require_role("manager")),
           db: Session = Depends(get_db)):
    return courses.enroll(db, active_org(principal), course_id, agent_ids=payload.agent_ids,
                          department_ids=payload.department_ids)


class QuizGenIn(BaseModel):
    author_agent_id: int | None = None
    questions: int = Field(default=6, ge=3, le=15)


@router.post("/courses/{course_id}/quiz/generate")
async def gen_quiz(course_id: int, payload: QuizGenIn, principal: Principal = Depends(require_role("manager")),
                   db: Session = Depends(get_db)):
    """Soạn đề trắc nghiệm một lần từ tài liệu của khoá (người quản lý xem/sửa được trước khi thi)."""
    return await courses.generate_quiz(db, active_org(principal), get_runtime(), course_id,
                                       author_agent_id=payload.author_agent_id, n=payload.questions)


class QuizIn(BaseModel):
    questions: list[dict]


@router.put("/courses/{course_id}/quiz")
def put_quiz(course_id: int, payload: QuizIn, principal: Principal = Depends(require_role("manager")),
             db: Session = Depends(get_db)):
    return courses.set_quiz(db, active_org(principal), course_id, payload.questions)


@router.post("/enrollments/{enrollment_id}/step")
async def step(enrollment_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """Chạy ngay một bước (học module tiếp theo hoặc thi) thay vì chờ giờ học."""
    return await courses.run_step(db, active_org(principal), get_runtime(), enrollment_id)


class RetakeIn(BaseModel):
    from_start: bool = False


@router.post("/enrollments/{enrollment_id}/retake")
def retake(enrollment_id: int, payload: RetakeIn, principal: Principal = Depends(require_role("manager")),
           db: Session = Depends(get_db)):
    return courses.retake(db, active_org(principal), enrollment_id, from_start=payload.from_start)


@router.get("/agents/{agent_id}")
def agent_learning(agent_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    """Khoá học, tiến độ, điểm và chứng chỉ của một agent."""
    from app.services import agent_hr
    agent_hr.seat(db, active_org(principal), agent_id)
    return courses.agent_learning(db, active_org(principal), agent_id)


# ------------------------------------------------------------------ M5b việc 10: Skill Studio

from app.services import skill_studio  # noqa: E402


@router.get("/skills")
def skills(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return {"items": skill_studio.list_skills(db, active_org(principal))}


@router.get("/skills/governance")
async def skills_governance(principal: Principal = Depends(require_human())):
    """Chế độ tự học kỹ năng của OpenClaw: 'auto' = agent tự sửa kỹ năng không cần duyệt."""
    return await skill_studio.governance(get_runtime())


@router.post("/skills/governance")
async def skills_enforce(principal: Principal = Depends(require_role("admin"))):
    """Chuyển Workshop sang 'propose' + 'pending': agent chỉ đề xuất, người duyệt mới áp (nạp nóng)."""
    return await skill_studio.enforce_governance(get_runtime())


@router.post("/skills/sync")
async def skills_sync(principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """Kéo đề xuất kỹ năng đang chờ của mọi agent về Hộp việc."""
    return await skill_studio.sync_workshop(db, active_org(principal), get_runtime())


class SkillDraftIn(BaseModel):
    slug: str = Field(max_length=64)
    title: str = Field(default="", max_length=220)
    description: str = Field(max_length=400)
    content: str = Field(max_length=60_000)
    eval_cases: list[dict] = []


@router.post("/skills")
def skill_create(payload: SkillDraftIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    """Soạn bản nháp (kỹ năng mới hoặc phiên bản mới của kỹ năng có sẵn cùng mã)."""
    return skill_studio.create_draft(db, principal, active_org(principal), payload.model_dump())


@router.get("/skills/{skill_id}")
def skill_detail(skill_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return skill_studio.detail(db, active_org(principal), skill_id)


class VersionPatchIn(BaseModel):
    content: str | None = Field(default=None, max_length=60_000)
    eval_cases: list[dict] | None = None


@router.put("/skill-versions/{version_id}")
def version_update(version_id: int, payload: VersionPatchIn, principal: Principal = Depends(require_role("manager")),
                   db: Session = Depends(get_db)):
    return skill_studio.update_draft(db, active_org(principal), version_id, payload.model_dump())


class EvalIn(BaseModel):
    agent_id: int


@router.post("/skill-versions/{version_id}/eval")
async def version_eval(version_id: int, payload: EvalIn, principal: Principal = Depends(require_role("manager")),
                       db: Session = Depends(get_db)):
    """Chạy các ca kiểm hai lần trên một agent: có kỹ năng và không có — chấm bằng luật."""
    return await skill_studio.run_eval(db, active_org(principal), get_runtime(), version_id, agent_id=payload.agent_id)


@router.post("/skill-versions/{version_id}/submit")
def version_submit(version_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return skill_studio.submit(db, active_org(principal), version_id, requester_member_id=principal.member_id)


class InstallIn(BaseModel):
    agent_ids: list[int]
    version_id: int | None = None


@router.post("/skills/{skill_id}/install")
async def skill_install(skill_id: int, payload: InstallIn, principal: Principal = Depends(require_role("manager")),
                        db: Session = Depends(get_db)):
    return await skill_studio.install(db, active_org(principal), get_runtime(), skill_id, agent_ids=payload.agent_ids,
                                      version_id=payload.version_id)


class RollbackIn(BaseModel):
    version_id: int


@router.post("/skills/{skill_id}/rollback")
async def skill_rollback(skill_id: int, payload: RollbackIn, principal: Principal = Depends(require_role("manager")),
                         db: Session = Depends(get_db)):
    """Quay về một phiên bản đã duyệt trước đó và cài lại cho mọi agent đang có kỹ năng này."""
    return await skill_studio.rollback(db, active_org(principal), get_runtime(), skill_id, version_id=payload.version_id)


# ------------------------------------------------------------------ M6 việc 11: đánh giá theo vai, scorecard, cấp tự chủ

from app.services import career  # noqa: E402


class SuiteIn(BaseModel):
    title: str | None = Field(default=None, max_length=220)
    role_keyword: str | None = Field(default=None, max_length=120)
    department_id: int | None = None
    cases: list[dict] | None = None
    k: int | None = None


@router.get("/eval-suites")
def eval_suites(principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    return {"items": career.suites_for(db, active_org(principal))}


@router.post("/eval-suites")
def eval_suite_create(payload: SuiteIn, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    return career.save_suite(db, active_org(principal), payload.model_dump(exclude_unset=True))


@router.put("/eval-suites/{suite_id}")
def eval_suite_update(suite_id: int, payload: SuiteIn, principal: Principal = Depends(require_role("manager")),
                      db: Session = Depends(get_db)):
    return career.save_suite(db, active_org(principal), payload.model_dump(exclude_unset=True), suite_id)


@router.get("/career/{agent_id}")
def career_overview(agent_id: int, days: int = 30, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    """Scorecard thật N ngày + gợi ý thăng/hạ + bộ đánh giá áp cho vai này + các lượt chạy gần đây."""
    return career.overview(db, active_org(principal), agent_id, days=max(1, min(days, 365)))


class RunSuiteIn(BaseModel):
    suite_id: int


@router.post("/career/{agent_id}/eval")
async def career_eval(agent_id: int, payload: RunSuiteIn, principal: Principal = Depends(require_role("manager")),
                      db: Session = Depends(get_db)):
    """Chạy bộ đánh giá: mỗi ca k lần trong phiên riêng; pass^k = tỉ lệ ca đúng cả k lần."""
    return await career.run_suite(db, active_org(principal), get_runtime(), agent_id, payload.suite_id)


@router.get("/eval-runs/{run_id}")
def eval_run(run_id: int, principal: Principal = Depends(require_human()), db: Session = Depends(get_db)):
    from fastapi import HTTPException
    from app.models.learning import EvalRun
    from app.services import agent_hr
    r = db.get(EvalRun, run_id)
    if r is None:
        raise HTTPException(404, "Không thấy lượt đánh giá")
    agent_hr.seat(db, active_org(principal), r.agent_id)
    return career.run_public(db, r)


class LevelIn(BaseModel):
    level: str
    reason: str = Field(default="", max_length=280)


@router.post("/career/{agent_id}/level")
async def career_level(agent_id: int, payload: LevelIn, principal: Principal = Depends(require_role("manager")),
                       db: Session = Depends(get_db)):
    """Thử việc / Chính thức / Tin cậy — đổi quyền theo hành động, lưu thành một phiên bản hồ sơ (khôi phục được)."""
    return await career.set_level(db, principal, active_org(principal), get_runtime(), agent_id,
                                  level=payload.level, reason=payload.reason)
