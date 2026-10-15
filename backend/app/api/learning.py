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
