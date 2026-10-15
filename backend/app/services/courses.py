"""M5b việc 9 — khoá học cho agent: học từng module → đề xuất bài học (Hộp việc) → thi → chứng chỉ.

* Module = một tài liệu trong kho (thứ tự trong ``Course.document_ids``).
* Một buổi học chạy trong phiên riêng ``agent:<rid>:course-<id>-m<i>-<ts>`` (không lẫn phiên làm việc):
  agent đọc nội dung module, viết ghi chú và đề xuất tối đa 2 bài học → ``lessons.propose(source="course")``.
  Ký ức chỉ thay đổi khi người duyệt.
* Bài thi trắc nghiệm sinh MỘT lần từ tài liệu (người quản lý xem/sửa được), chấm bằng luật (đúng đáp án),
  không dùng model để chấm. Đạt ≥ ``pass_score`` → chứng chỉ trên hồ sơ; câu sai → lỗ hổng kiến thức.
* Lịch: Celery ``courses.tick`` mỗi giờ; tới ``study_hour`` (theo ``study_tz``) mỗi agent học tối đa 1 bước/ngày.
  Seat bị chặn chi (trần ngày/tháng) thì bỏ qua.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Agent, KnowledgeDocument, Member
from app.models.learning import Course, CourseEnrollment

MODULE_CHARS = 12_000
QUIZ_SOURCE_CHARS = 16_000
STATUS_VI = {"learning": "Đang học", "exam": "Chờ thi", "passed": "Đạt", "failed": "Chưa đạt", "stale": "Cần ôn"}


# ------------------------------------------------------------------ CRUD

def _course(db: Session, org_id: int, cid: int) -> Course:
    c = db.get(Course, cid)
    if c is None or c.organization_id != org_id:
        raise HTTPException(404, "Không thấy khoá học")
    return c


def _docs(db: Session, org_id: int, ids: list[int]) -> list[KnowledgeDocument]:
    out = []
    for i in ids:
        d = db.get(KnowledgeDocument, int(i))
        if d is None or d.organization_id != org_id:
            raise HTTPException(404, f"Không thấy tài liệu #{i}")
        out.append(d)
    return out


def _clean(db: Session, org_id: int, data: dict, course: Course | None = None) -> dict:
    out = {}
    if "title" in data or course is None:
        t = (data.get("title") or "").strip()
        if len(t) < 3:
            raise HTTPException(422, "Tên khoá học cần ít nhất 3 ký tự")
        out["title"] = t[:220]
    if "goal" in data:
        out["goal"] = (data.get("goal") or "")[:4000]
    if "document_ids" in data or course is None:
        ids = [int(x) for x in (data.get("document_ids") or [])]
        if not ids:
            raise HTTPException(422, "Khoá học cần ít nhất 1 tài liệu (module)")
        if len(set(ids)) != len(ids):
            raise HTTPException(422, "Một tài liệu chỉ xuất hiện một lần trong khoá")
        _docs(db, org_id, ids)
        out["document_ids"] = ids
    if "study_hour" in data:
        h = data.get("study_hour")
        if h is not None and not (0 <= int(h) <= 23):
            raise HTTPException(422, "Giờ học phải từ 0 đến 23")
        out["study_hour"] = None if h is None else int(h)
    if "study_tz" in data and data.get("study_tz"):
        try:
            ZoneInfo(data["study_tz"])
        except Exception:  # noqa: BLE001
            raise HTTPException(422, "Múi giờ không hợp lệ")
        out["study_tz"] = data["study_tz"]
    if "pass_score" in data and data.get("pass_score") is not None:
        p = int(data["pass_score"])
        if not (50 <= p <= 100):
            raise HTTPException(422, "Điểm đạt phải từ 50 đến 100")
        out["pass_score"] = p
    if "status" in data and data.get("status"):
        if data["status"] not in ("active", "archived"):
            raise HTTPException(422, "Trạng thái chỉ là active hoặc archived")
        out["status"] = data["status"]
    return out


def create(db: Session, principal, org_id: int, data: dict) -> dict:
    c = Course(organization_id=org_id, created_by_user_id=principal.user_id, **_clean(db, org_id, data))
    db.add(c); db.commit(); db.refresh(c)
    if data.get("agent_ids") or data.get("department_ids"):
        enroll(db, org_id, c.id, agent_ids=data.get("agent_ids") or [], department_ids=data.get("department_ids") or [])
    return detail(db, org_id, c.id)


def update(db: Session, org_id: int, cid: int, data: dict) -> dict:
    c = _course(db, org_id, cid)
    for k, v in _clean(db, org_id, data, c).items():
        setattr(c, k, v)
    c.updated_at = datetime.utcnow()
    db.add(c); db.commit()
    return detail(db, org_id, cid)


def enroll(db: Session, org_id: int, cid: int, *, agent_ids: list[int], department_ids: list[int]) -> dict:
    c = _course(db, org_id, cid)
    ids = set(int(a) for a in agent_ids)
    for dep in department_ids:
        for ag, m in (db.query(Agent, Member).join(Member, Member.id == Agent.member_id)
                      .filter(Member.organization_id == org_id, Member.department_id == int(dep)).all()):
            if ag.lifecycle != "retired":
                ids.add(ag.id)
    added = 0
    for aid in ids:
        ag = db.get(Agent, aid); m = db.get(Member, ag.member_id) if ag else None
        if m is None or m.organization_id != org_id:
            raise HTTPException(404, f"Không thấy agent #{aid}")
        if db.query(CourseEnrollment).filter(CourseEnrollment.course_id == c.id, CourseEnrollment.agent_id == aid).first():
            continue
        db.add(CourseEnrollment(course_id=c.id, agent_id=aid, log=[])); added += 1
    db.commit()
    return {"added": added, **detail(db, org_id, cid)}


def _enr_public(db: Session, e: CourseEnrollment, total: int) -> dict:
    ag = db.get(Agent, e.agent_id); m = db.get(Member, ag.member_id) if ag else None
    return {"id": e.id, "agent_id": e.agent_id, "agent_name": m.name if m else "?", "status": e.status,
            "status_vi": STATUS_VI.get(e.status, e.status), "module_index": e.module_index, "modules": total,
            "score": e.score, "attempts": e.attempts, "note": e.note or "",
            "certified_at": e.certified_at.isoformat() if e.certified_at else None,
            "last_session_at": e.last_session_at.isoformat() if e.last_session_at else None,
            "log": list(e.log or [])[-10:]}


def detail(db: Session, org_id: int, cid: int, *, with_answers: bool = True) -> dict:
    c = _course(db, org_id, cid)
    docs = {d.id: d for d in db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(list(c.document_ids or []) or [-1])).all()}
    total = len(c.document_ids or [])
    enr = db.query(CourseEnrollment).filter(CourseEnrollment.course_id == c.id).order_by(CourseEnrollment.id).all()
    quiz = [q if with_answers else {k: v for k, v in q.items() if k != "answer"} for q in (c.quiz or [])]
    return {"id": c.id, "title": c.title, "goal": c.goal, "status": c.status, "pass_score": c.pass_score,
            "study_hour": c.study_hour, "study_tz": c.study_tz,
            "modules": [{"index": i, "document_id": d, "title": docs[d].title if d in docs else "(đã xoá)"}
                        for i, d in enumerate(c.document_ids or [])],
            "quiz": quiz, "enrollments": [_enr_public(db, e, total) for e in enr]}


def list_courses(db: Session, org_id: int) -> list[dict]:
    out = []
    for c in db.query(Course).filter(Course.organization_id == org_id).order_by(Course.id.desc()).all():
        enr = db.query(CourseEnrollment).filter(CourseEnrollment.course_id == c.id).all()
        out.append({"id": c.id, "title": c.title, "status": c.status, "modules": len(c.document_ids or []),
                    "quiz_questions": len(c.quiz or []), "enrolled": len(enr),
                    "passed": sum(1 for e in enr if e.status == "passed"), "study_hour": c.study_hour})
    return out


def agent_learning(db: Session, org_id: int, agent_id: int) -> dict:
    rows = (db.query(CourseEnrollment, Course).join(Course, Course.id == CourseEnrollment.course_id)
            .filter(CourseEnrollment.agent_id == agent_id, Course.organization_id == org_id).all())
    return {"agent_id": agent_id, "items": [{**_enr_public(db, e, len(c.document_ids or [])), "course_id": c.id,
                                              "course_title": c.title} for e, c in rows]}


# ------------------------------------------------------------------ gọi agent

async def _ask(runtime: Any, rid: str, prompt: str, key: str, timeout: int = 150) -> str:
    text, err = "", ""
    try:
        async for ev in runtime.chat_stream(rid, prompt, session_key=key, timeout_seconds=timeout):
            if ev["kind"] == "delta":
                text = ev["text"]
            elif ev["kind"] == "final":
                text = ev.get("text") or text
                break
            elif ev["kind"] != "tool":
                err = str(ev.get("message") or "lỗi"); break
    except Exception as exc:  # noqa: BLE001
        err = f"gateway: {exc}"[:300]
    if err and not text:
        raise HTTPException(502, f"Agent không trả lời được: {err}")
    return text


def _json(text: str) -> Any:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None


def _seat(db: Session, agent_id: int) -> tuple[Agent, Member]:
    ag = db.get(Agent, agent_id); m = db.get(Member, ag.member_id) if ag else None
    if m is None:
        raise HTTPException(404, "Không thấy agent")
    return ag, m


def _need_gateway(runtime: Any) -> None:
    from app.services import agent_hr
    if not agent_hr._has_rpc(runtime) or not hasattr(runtime, "chat_stream"):
        raise HTTPException(409, "Cần gateway OpenClaw thật để agent học / thi")


QUIZ_PROMPT = """Em là người ra đề. Dựa CHỈ trên tài liệu dưới đây, soạn {n} câu hỏi trắc nghiệm tiếng Việt kiểm tra
những điểm quan trọng nhất mà nhân viên phải nhớ khi làm việc (quy định, con số, quy trình), không hỏi mẹo.
Mỗi câu có đúng 4 lựa chọn, chỉ 1 đáp án đúng. Trả lời CHỈ bằng JSON:
{{"questions": [{{"question": "...", "options": ["...", "...", "...", "..."], "answer": 0, "document_id": 12}}]}}
("answer" là chỉ số 0-3 của lựa chọn đúng; "document_id" là số trong tiêu đề TÀI LIỆU #...)

{docs}"""


def _valid_quiz(items: Any, doc_ids: list[int]) -> list[dict]:
    out = []
    for q in items or []:
        if not isinstance(q, dict):
            continue
        opts = q.get("options")
        try:
            ans = int(q.get("answer"))
        except Exception:  # noqa: BLE001
            continue
        if (isinstance(q.get("question"), str) and len(q["question"].strip()) >= 8 and isinstance(opts, list)
                and len(opts) == 4 and all(isinstance(o, str) and o.strip() for o in opts) and 0 <= ans <= 3):
            did = q.get("document_id")
            out.append({"question": q["question"].strip()[:500], "options": [o.strip()[:200] for o in opts],
                        "answer": ans, "document_id": int(did) if isinstance(did, int) and did in doc_ids else None})
    return out


async def generate_quiz(db: Session, org_id: int, runtime: Any, cid: int, *, author_agent_id: int | None = None,
                        n: int = 6) -> dict:
    _need_gateway(runtime)
    c = _course(db, org_id, cid)
    docs = _docs(db, org_id, list(c.document_ids or []))
    if author_agent_id is None:
        nina = (db.query(Agent).join(Member, Member.id == Agent.member_id)
                .filter(Member.organization_id == org_id, Agent.runtime_agent_id.like("%nina%")).first())
        first = db.query(CourseEnrollment).filter(CourseEnrollment.course_id == c.id).first()
        author_agent_id = (nina.id if nina else None) or (first.agent_id if first else None)
    if author_agent_id is None:
        raise HTTPException(409, "Chưa có agent nào để soạn đề — ghi danh học viên hoặc chọn người soạn")
    ag, _ = _seat(db, author_agent_id)
    per = max(2000, QUIZ_SOURCE_CHARS // max(1, len(docs)))
    body = "\n\n".join(f"### TÀI LIỆU #{d.id}: {d.title}\n{(d.content or '')[:per]}" for d in docs)
    text = await _ask(runtime, ag.runtime_agent_id, QUIZ_PROMPT.format(n=n, docs=body),
                      f"agent:{ag.runtime_agent_id}:course-{c.id}-quiz-{int(time.time())}", timeout=180)
    data = _json(text) or {}
    quiz = _valid_quiz(data.get("questions") if isinstance(data, dict) else None, [d.id for d in docs])
    if len(quiz) < 3:
        raise HTTPException(502, f"Đề sinh ra không hợp lệ (chỉ {len(quiz)} câu đúng định dạng) — thử lại")
    c.quiz = quiz; c.updated_at = datetime.utcnow()
    db.add(c); db.commit()
    return detail(db, org_id, cid)


def set_quiz(db: Session, org_id: int, cid: int, items: list) -> dict:
    c = _course(db, org_id, cid)
    quiz = _valid_quiz(items, list(c.document_ids or []))
    if len(quiz) != len(items or []):
        raise HTTPException(422, "Mỗi câu cần nội dung, đúng 4 lựa chọn và đáp án 0–3")
    c.quiz = quiz; c.updated_at = datetime.utcnow()
    db.add(c); db.commit()
    return detail(db, org_id, cid)


STUDY_PROMPT = """Em là {name}. Đây là buổi học module {i}/{n} của khoá "{course}"{goal}.
Đọc kỹ tài liệu dưới đây rồi trả lời CHỈ bằng JSON:
{{"notes": ["tối đa 5 ý chính em cần nhớ khi làm việc"], "lessons": ["tối đa 2 bài học áp dụng được ngay: khi nào, làm gì"]}}
Không bịa ngoài tài liệu.

### TÀI LIỆU #{doc_id}: {title}
{content}"""

EXAM_PROMPT = """Em là {name}. Đây là bài thi cuối khoá "{course}". Trả lời từng câu bằng chỉ số lựa chọn (0, 1, 2 hoặc 3),
chỉ dựa vào những gì em đã học. Trả lời CHỈ bằng JSON: {{"answers": [0, 2, ...]}} theo đúng thứ tự câu.

{questions}"""


async def run_step(db: Session, org_id: int, runtime: Any, enrollment_id: int) -> dict:
    """Một bước: học module tiếp theo, hoặc thi nếu đã học hết."""
    from app.services import lessons, seat_limits
    _need_gateway(runtime)
    e = db.get(CourseEnrollment, enrollment_id)
    c = _course(db, org_id, e.course_id) if e else None
    if e is None or c is None:
        raise HTTPException(404, "Không thấy lượt ghi danh")
    ag, m = _seat(db, e.agent_id)
    if ag.lifecycle in ("paused", "retired", "runtime_missing"):
        raise HTTPException(409, f"{m.name} đang ở trạng thái {ag.lifecycle}")
    blocked = seat_limits.check(db, m)
    if blocked:
        raise HTTPException(409, blocked)
    if e.status == "passed":
        return {"enrollment": _enr_public(db, e, len(c.document_ids or [])), "message": f"{m.name} đã đạt khoá này"}
    ids = list(c.document_ids or [])
    now = datetime.utcnow()
    if e.status in ("learning", "stale") and e.module_index < len(ids):
        doc = db.get(KnowledgeDocument, ids[e.module_index])
        text = await _ask(runtime, ag.runtime_agent_id, STUDY_PROMPT.format(
            name=m.name, i=e.module_index + 1, n=len(ids), course=c.title,
            goal=f" (mục tiêu: {c.goal[:300]})" if c.goal else "", doc_id=doc.id, title=doc.title,
            content=(doc.content or "")[:MODULE_CHARS]),
            f"agent:{ag.runtime_agent_id}:course-{c.id}-m{e.module_index + 1}-{int(time.time())}")
        data = _json(text) or {}
        notes = [str(x)[:300] for x in (data.get("notes") or [])][:5] if isinstance(data, dict) else []
        proposed = []
        for les in ([str(x) for x in (data.get("lessons") or [])][:2] if isinstance(data, dict) else []):
            try:
                r = lessons.propose(db, agent=ag, member=m, text=les, source="course",
                                    reason=f"Học module {e.module_index + 1} khoá \"{c.title}\" (tài liệu #{doc.id})")
                proposed.append(r["approval_id"])
            except lessons.LessonError:
                pass
        e.log = list(e.log or []) + [{"at": now.isoformat(), "kind": "study", "module": e.module_index + 1,
                                      "document_id": doc.id, "notes": notes, "lesson_approvals": proposed}]
        e.module_index += 1
        e.last_session_at = now
        if e.module_index >= len(ids):
            e.status, e.note = "exam", ""
        elif e.status == "stale":
            e.status = "learning"
        db.add(e); db.commit()
        msg = f"{m.name} đã học module {e.module_index}/{len(ids)}" + (f", đề xuất {len(proposed)} bài học chờ duyệt" if proposed else "")
        return {"enrollment": _enr_public(db, e, len(ids)), "message": msg}
    # thi
    if not c.quiz:
        raise HTTPException(409, "Khoá chưa có đề thi — bấm Soạn đề trước")
    qs = "\n\n".join(f"Câu {i + 1}: {q['question']}\n" + "\n".join(f"  {j}. {o}" for j, o in enumerate(q["options"]))
                     for i, q in enumerate(c.quiz))
    text = await _ask(runtime, ag.runtime_agent_id, EXAM_PROMPT.format(name=m.name, course=c.title, questions=qs),
                      f"agent:{ag.runtime_agent_id}:course-{c.id}-exam-{int(time.time())}")
    data = _json(text) or {}
    answers = data.get("answers") if isinstance(data, dict) else None
    answers = answers if isinstance(answers, list) else []
    result = grade(c.quiz, answers)
    e.attempts += 1
    e.score = result["score"]
    e.last_session_at = now
    if result["score"] >= c.pass_score:
        e.status, e.certified_at, e.note = "passed", now, ""
    else:
        e.status = "failed"
        e.note = f"Sai {len(result['wrong'])}/{len(c.quiz)} câu — cần học thêm rồi thi lại"
        from app.services import knowledge_hub
        for i in result["wrong"]:
            knowledge_hub.record_gap(db, org_id, m.id, c.quiz[i]["question"], source="exam")
    e.log = list(e.log or []) + [{"at": now.isoformat(), "kind": "exam", "score": result["score"],
                                  "wrong": [i + 1 for i in result["wrong"]], "answers": answers[:len(c.quiz)]}]
    db.add(e); db.commit()
    verdict = "ĐẠT — đã cấp chứng chỉ" if e.status == "passed" else "chưa đạt"
    return {"enrollment": _enr_public(db, e, len(ids)), "grade": result,
            "message": f"{m.name} thi được {result['score']:.0f}/100 — {verdict}"}


def grade(quiz: list[dict], answers: list) -> dict:
    wrong = []
    for i, q in enumerate(quiz):
        a = answers[i] if i < len(answers) else None
        try:
            ok = int(a) == int(q["answer"])
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            wrong.append(i)
    score = round(100 * (len(quiz) - len(wrong)) / len(quiz), 1) if quiz else 0.0
    return {"score": score, "wrong": wrong, "total": len(quiz)}


def retake(db: Session, org_id: int, enrollment_id: int, *, from_start: bool = False) -> dict:
    e = db.get(CourseEnrollment, enrollment_id)
    c = _course(db, org_id, e.course_id) if e else None
    if e is None or c is None:
        raise HTTPException(404, "Không thấy lượt ghi danh")
    if from_start:
        e.module_index, e.status = 0, "learning"
    else:
        e.status = "exam" if e.module_index >= len(c.document_ids or []) else "learning"
    e.note = ""
    db.add(e); db.commit()
    return _enr_public(db, e, len(c.document_ids or []))


async def tick(db: Session, runtime: Any, *, now: datetime | None = None) -> dict:
    """Tới giờ học → mỗi agent một bước/ngày. Lỗi một agent không chặn agent khác."""
    now = now or datetime.utcnow()
    done, errors = 0, []
    for c in db.query(Course).filter(Course.status == "active", Course.study_hour.isnot(None)).all():
        local = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(c.study_tz or "UTC"))
        if local.hour != c.study_hour:
            continue
        for e in db.query(CourseEnrollment).filter(CourseEnrollment.course_id == c.id,
                                                   CourseEnrollment.status.in_(("learning", "stale", "exam"))).all():
            if e.last_session_at is not None:
                last = e.last_session_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(c.study_tz or "UTC"))
                if last.date() == local.date():
                    continue
            if e.status == "exam" and not c.quiz:
                continue
            try:
                await run_step(db, c.organization_id, runtime, e.id); done += 1
            except HTTPException as exc:
                errors.append({"enrollment_id": e.id, "error": str(exc.detail)[:200]})
    return {"steps": done, "errors": errors}
