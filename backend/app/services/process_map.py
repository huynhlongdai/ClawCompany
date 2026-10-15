"""M2c D4 — Bản đồ quy trình: quy trình chuỗi giá trị theo nhóm APQC, có chức danh làm chủ,
các bước gắn chức danh + SOP + thời lượng kỳ vọng + loại việc của ma trận phân quyền.

Chạy được mà KHÔNG có động cơ thứ hai. Bắt đầu một lần chạy (``start``):

* mỗi bước → một ``tasks`` thường (``workspace_ops.create_task``) trong dự án "Quy trình · <tên>",
  giao cho seat đang ngồi chức danh của bước (ít việc mở nhất); chức danh trống → trưởng phòng
  của chức danh → chủ doanh nghiệp (ghi chú trên bước);
* bước sau bị chặn bởi bước trước bằng ``task_dependencies`` (D1.3) — ``wake_unblocked`` sẵn có
  đánh thức người nhận khi bước trước xong;
* bước có ``action_type`` → ``authority.decide`` (M2b) với số tiền của lần chạy; cần duyệt →
  task mang chặng ``approval`` của ``execution_policy`` (D2.2) với người duyệt theo luật, nên
  Hộp việc + duyệt đi đường cũ;
* bước đầu chuyển "Cần làm" và đánh thức seat (wakeup ``assigned``).

``task_lifecycle.transition`` gọi ``on_task_status`` → ghi ``started_at`` (Đang làm),
``finished_at`` + thời gian chu trình của bước (từ lúc tới lượt), mở bước sau, và khi bước cuối
xong thì ghi thời gian chu trình của cả lần chạy. Huỷ một bước → huỷ lần chạy và các bước chờ.
"""
from __future__ import annotations

import statistics
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import SOP, Company, Department, Member, Project, Task
from app.models.company_foundation import Position
from app.models.company_ops import Process, ProcessInstance, ProcessStep, ProcessStepRun
from app.models.work_graph import TaskDependency

SOURCE = "process_map"

# APQC Process Classification Framework (cross-industry) — 13 nhóm cấp 1.
CATEGORIES = [
    ("1", "Xây dựng tầm nhìn & chiến lược", "Develop vision and strategy"),
    ("2", "Phát triển sản phẩm & dịch vụ", "Develop and manage products and services"),
    ("3", "Marketing & bán hàng", "Market and sell products and services"),
    ("4", "Giao hàng hoá (kho vận)", "Deliver physical products"),
    ("5", "Cung cấp dịch vụ", "Deliver services"),
    ("6", "Chăm sóc khách hàng", "Manage customer service"),
    ("7", "Nhân sự", "Develop and manage human capital"),
    ("8", "Công nghệ thông tin", "Manage information technology"),
    ("9", "Tài chính", "Manage financial resources"),
    ("10", "Tài sản", "Acquire, construct, and manage assets"),
    ("11", "Rủi ro, tuân thủ & khắc phục", "Manage enterprise risk, compliance, remediation, and resiliency"),
    ("12", "Quan hệ bên ngoài", "Manage external relationships"),
    ("13", "Năng lực doanh nghiệp", "Develop and manage business capabilities"),
]
CATEGORY_KEYS = {c[0] for c in CATEGORIES}
MAX_STEPS = 20


def _err(status: int, msg: str) -> HTTPException:
    return HTTPException(status, msg)


def _company(db: Session, org_id: int, company_id: int | None) -> Company:
    from app.services.company_foundation import _company as c
    return c(db, org_id, company_id)


def _process(db: Session, org_id: int, pid: int) -> Process:
    p = db.get(Process, pid)
    if p is None or p.organization_id != org_id:
        raise _err(404, "Không thấy quy trình này. Tải lại tab Quy trình — có thể nó đã bị lưu trữ.")
    return p


def steps_of(db: Session, pid: int) -> list[ProcessStep]:
    return db.query(ProcessStep).filter(ProcessStep.process_id == pid).order_by(ProcessStep.seq, ProcessStep.id).all()


def _pos_title(db: Session, pid: int | None) -> str | None:
    p = db.get(Position, pid) if pid else None
    return p.title if p else None


# ------------------------------------------------------------------ thống kê chu trình

def _fmt_minutes(sec: float | None) -> float | None:
    return round(sec / 60, 1) if sec is not None else None


def stats(db: Session, p: Process) -> dict:
    inst = db.query(ProcessInstance).filter(ProcessInstance.process_id == p.id).all()
    done = [i.cycle_seconds for i in inst if i.status == "done" and i.cycle_seconds is not None]
    by_step: dict[int, list[float]] = {}
    ids = [i.id for i in inst]
    runs = db.query(ProcessStepRun).filter(ProcessStepRun.instance_id.in_(ids)).all() if ids else []
    for r in runs:
        if r.status == "done" and r.cycle_seconds is not None and r.step_id:
            by_step.setdefault(r.step_id, []).append(r.cycle_seconds)
    now = datetime.utcnow()
    late = sum(1 for r in runs if r.status == "active" and r.expected_minutes and r.activated_at
               and (now - r.activated_at).total_seconds() > r.expected_minutes * 60)
    return {"instances": len(inst), "running": sum(1 for i in inst if i.status == "running"),
            "done": len(done), "cancelled": sum(1 for i in inst if i.status == "cancelled"),
            "avg_cycle_minutes": _fmt_minutes(statistics.mean(done)) if done else None,
            "median_cycle_minutes": _fmt_minutes(statistics.median(done)) if done else None,
            "late_steps": late,
            "step_avg_minutes": {sid: _fmt_minutes(statistics.mean(v)) for sid, v in by_step.items()}}


def public_step(db: Session, s: ProcessStep, avg: dict | None = None) -> dict:
    sop = db.get(SOP, s.sop_id) if s.sop_id else None
    return {"id": s.id, "seq": s.seq, "name": s.name, "instructions": s.instructions or "",
            "position_id": s.position_id, "position": _pos_title(db, s.position_id),
            "sop_id": s.sop_id, "sop": sop.title if sop else None, "expected_minutes": s.expected_minutes,
            "action_type": s.action_type or "", "risk": s.risk or "",
            "avg_minutes": (avg or {}).get(s.id)}


def public_process(db: Session, p: Process, *, with_stats: bool = True) -> dict:
    st = stats(db, p) if with_stats else None
    steps = steps_of(db, p.id)
    expected = sum(s.expected_minutes or 0 for s in steps) or None
    return {"id": p.id, "company_id": p.company_id, "category": p.category,
            "category_vi": next((c[1] for c in CATEGORIES if c[0] == p.category), p.category),
            "name": p.name, "description": p.description or "", "owner_position_id": p.owner_position_id,
            "owner_position": _pos_title(db, p.owner_position_id), "template_key": p.template_key or "",
            "status": p.status, "expected_minutes": expected,
            "steps": [public_step(db, s, (st or {}).get("step_avg_minutes")) for s in steps],
            "stats": {k: v for k, v in (st or {}).items() if k != "step_avg_minutes"} if st else None,
            "issues": issues(db, p, steps)}


def issues(db: Session, p: Process, steps: list[ProcessStep] | None = None) -> list[str]:
    """Điều làm quy trình chưa chạy tốt — chỉ cảnh báo, không chặn."""
    steps = steps_of(db, p.id) if steps is None else steps
    out = []
    if not p.owner_position_id:
        out.append("Chưa có chức danh làm chủ quy trình.")
    if not steps:
        out.append("Chưa có bước nào.")
    for s in steps:
        if not s.position_id:
            out.append(f"Bước {s.seq} \"{s.name}\" chưa gắn chức danh.")
        else:
            from app.services.company_foundation import seats_of
            if not seats_of(db, s.position_id):
                out.append(f"Bước {s.seq}: chức danh \"{_pos_title(db, s.position_id)}\" đang trống người — việc sẽ giao trưởng phòng.")
    return out


def list_processes(db: Session, org_id: int, company_id: int | None, *, include_archived: bool = False) -> dict:
    co = _company(db, org_id, company_id)
    q = db.query(Process).filter(Process.company_id == co.id)
    if not include_archived:
        q = q.filter(Process.status != "archived")
    rows = q.order_by(Process.category, Process.id).all()
    items = [public_process(db, p) for p in rows]
    used = sorted({p.category for p in rows}, key=lambda x: int(x) if x.isdigit() else 99)
    return {"company_id": co.id, "company_name": co.name,
            "categories": [{"key": k, "vi": vi, "en": en} for k, vi, en in CATEGORIES],
            "used_categories": used, "items": items,
            "templates": sorted(TEMPLATES),
            "positions": [{"id": x.id, "title": x.title} for x in db.query(Position).filter(
                Position.company_id == co.id, Position.status != "archived").order_by(Position.id).all()],
            "sops": [{"id": s.id, "title": s.title} for s in db.query(SOP).filter(
                SOP.organization_id == org_id).order_by(SOP.id.desc()).limit(200).all()]}


# ------------------------------------------------------------------ ghi định nghĩa

def _check_position(db: Session, co: Company, pid: int | None, field: str) -> int | None:
    if pid is None:
        return None
    pos = db.get(Position, pid)
    if pos is None or pos.company_id != co.id or pos.status == "archived":
        raise _err(422, f"{field}: chức danh #{pid} không thuộc công ty {co.name}. Chọn lại chức danh trong danh sách "
                        f"(tab Chức danh).")
    return pid


def _apply(db: Session, co: Company, p: Process, data: dict, fields: set[str]) -> None:
    if "name" in fields:
        name = (data.get("name") or "").strip()
        if not name:
            raise _err(422, "Quy trình cần có tên, ví dụ \"Đơn hàng → giao hàng → hậu mãi\".")
        p.name = name[:200]
    if "category" in fields:
        cat = str(data.get("category") or "")
        if cat not in CATEGORY_KEYS:
            raise _err(422, "Nhóm quy trình phải là mã APQC từ 1 tới 13 (ví dụ 6 = Chăm sóc khách hàng).")
        p.category = cat
    if "description" in fields:
        p.description = (data.get("description") or "")[:4000]
    if "owner_position_id" in fields:
        p.owner_position_id = _check_position(db, co, data.get("owner_position_id"), "Chủ quy trình")


def save_steps(db: Session, org_id: int, p: Process, steps: list[dict]) -> None:
    from app.services import authority
    co = db.get(Company, p.company_id)
    if len(steps) > MAX_STEPS:
        raise _err(422, f"Tối đa {MAX_STEPS} bước. Gộp các bước nhỏ hoặc tách thành quy trình con.")
    if db.query(ProcessInstance).filter(ProcessInstance.process_id == p.id, ProcessInstance.status == "running").count():
        raise _err(409, "Quy trình đang có lần chạy dở. Chờ các lần chạy xong (hoặc huỷ chúng) rồi mới sửa các bước, "
                        "để thời gian chu trình không bị lẫn.")
    clean = []
    for i, s in enumerate(steps, start=1):
        name = (s.get("name") or "").strip()
        if not name:
            raise _err(422, f"Bước {i} chưa có tên.")
        at = s.get("action_type") or ""
        if at and authority.normalize_action(at) is None:
            raise _err(422, f"Bước {i}: loại việc \"{at}\" không có trong ma trận phân quyền. Chọn một loại trong danh "
                            f"sách hoặc để trống nếu bước không cần xét duyệt.")
        sop_id = s.get("sop_id")
        if sop_id:
            sop = db.get(SOP, sop_id)
            if sop is None or sop.organization_id != org_id:
                raise _err(422, f"Bước {i}: SOP #{sop_id} không thuộc tổ chức này.")
        em = s.get("expected_minutes")
        if em is not None and (not isinstance(em, int) or em <= 0 or em > 60 * 24 * 60):
            raise _err(422, f"Bước {i}: thời lượng kỳ vọng phải là số phút dương (tối đa 60 ngày).")
        risk = s.get("risk") or ""
        if risk and risk not in authority.RISKS:
            raise _err(422, f"Bước {i}: mức rủi ro phải là low, medium, high hoặc critical.")
        clean.append(dict(seq=i, name=name[:200], instructions=(s.get("instructions") or "")[:4000],
                          position_id=_check_position(db, co, s.get("position_id"), f"Bước {i}"),
                          sop_id=sop_id or None, expected_minutes=em,
                          action_type=authority.normalize_action(at) or "" if at else "", risk=risk))
    keep_ids = {s.get("id") for s in steps if s.get("id")}
    old = steps_of(db, p.id)
    by_id = {s.id: s for s in old}
    for s in old:
        if s.id not in keep_ids:
            db.delete(s)
    db.flush()
    for raw, c in zip(steps, clean):
        row = by_id.get(raw.get("id")) if raw.get("id") else None
        if row is None:
            row = ProcessStep(process_id=p.id, **c)
            db.add(row)
        else:
            for k, v in c.items():
                setattr(row, k, v)
    p.updated_at = datetime.utcnow()
    db.commit()


def create_process(db: Session, org_id: int, data: dict) -> Process:
    co = _company(db, org_id, data.get("company_id"))
    p = Process(organization_id=org_id, company_id=co.id, name="", category="6")
    fields = (set(data) & {"description", "owner_position_id"}) | {"name", "category"}
    _apply(db, co, p, {"category": "6", **data}, fields)
    db.add(p); db.commit(); db.refresh(p)
    if data.get("steps") is not None:
        save_steps(db, org_id, p, data["steps"])
    return p


def update_process(db: Session, org_id: int, pid: int, data: dict, fields: set[str]) -> Process:
    p = _process(db, org_id, pid)
    co = db.get(Company, p.company_id)
    _apply(db, co, p, data, fields & {"name", "category", "description", "owner_position_id"})
    db.commit()
    if "steps" in fields and data.get("steps") is not None:
        save_steps(db, org_id, p, data["steps"])
    db.refresh(p)
    return p


def archive_process(db: Session, org_id: int, pid: int) -> dict:
    p = _process(db, org_id, pid)
    p.status = "archived"
    db.commit()
    return {"id": p.id, "status": p.status}


# ------------------------------------------------------------------ chạy

def _project(db: Session, p: Process) -> Project:
    name = f"Quy trình · {p.name}"[:200]
    pr = db.query(Project).filter(Project.company_id == p.company_id, Project.name == name).first()
    if pr is None:
        pr = Project(company_id=p.company_id, name=name, status="active",
                     description=f"Việc sinh ra từ quy trình #{p.id} (bản đồ quy trình, M2c)")
        db.add(pr); db.commit(); db.refresh(pr)
    return pr


def _open_load(db: Session, member_id: int) -> int:
    return db.query(Task).filter(Task.assignee_member_id == member_id,
                                 Task.status.in_(("backlog", "todo", "in_progress", "review", "blocked"))).count()


def pick_assignee(db: Session, org_id: int, company_id: int, position_id: int | None) -> tuple[int | None, str]:
    from app.services import authority
    from app.services.company_foundation import seats_of
    if position_id:
        seats = [m for m in seats_of(db, position_id) if m.status in ("active", "onboarding")]
        if seats:
            best = min(seats, key=lambda m: (_open_load(db, m.id), m.id))
            return best.id, ""
        pos = db.get(Position, position_id)
        dept = db.get(Department, pos.department_id) if pos and pos.department_id else None
        if dept and dept.head_member_id:
            return dept.head_member_id, f"Chức danh \"{pos.title}\" đang trống → giao trưởng phòng {dept.name}."
        owner = authority.owner_member(db, org_id, company_id)
        return owner, f"Chức danh \"{pos.title if pos else position_id}\" đang trống, phòng chưa có trưởng → giao chủ doanh nghiệp."
    owner = authority.owner_member(db, org_id, company_id)
    return owner, "Bước chưa gắn chức danh → giao chủ doanh nghiệp."


def _brief(db: Session, p: Process, inst: ProcessInstance, s: ProcessStep, steps: list[ProcessStep]) -> str:
    lines = [f"**Quy trình:** {p.name} — lần chạy #{inst.id}: {inst.title}",
             f"**Bước {s.seq}/{len(steps)}:** {s.name}"]
    if p.owner_position_id:
        lines.append(f"**Chủ quy trình:** {_pos_title(db, p.owner_position_id)}")
    if s.expected_minutes:
        lines.append(f"**Thời lượng kỳ vọng:** {s.expected_minutes} phút")
    nxt = next((x for x in steps if x.seq == s.seq + 1), None)
    if nxt:
        lines.append(f"**Bước sau:** {nxt.name} ({_pos_title(db, nxt.position_id) or 'chưa gắn chức danh'})")
    if s.instructions:
        lines += ["", "## Việc cần làm", s.instructions]
    if s.sop_id:
        sop = db.get(SOP, s.sop_id)
        if sop:
            lines += ["", f"## SOP: {sop.title} ({sop.version})", (sop.content or "")[:3000]]
    if inst.amount_usd is not None:
        lines.append(f"\n**Số tiền của lần chạy:** ${inst.amount_usd:,.2f}")
    if inst.input_json:
        import json
        lines += ["", "## Dữ liệu đầu vào", "```json", json.dumps(inst.input_json, ensure_ascii=False, indent=1)[:3000], "```"]
    lines += ["", "Xong bước này thì chuyển việc sang review (bước sau tự mở khi việc này xong)."]
    return "\n".join(lines)


def start(db: Session, org_id: int, pid: int, *, title: str = "", amount_usd: float | None = None,
          input_data: dict | None = None, actor_member_id: int | None = None) -> dict:
    from app.services import authority, execution_policy, wakeup
    from app.services import task_lifecycle as lifecycle
    from app.services import workspace_ops as ops
    from app.services.company_event_bus import emit_event
    p = _process(db, org_id, pid)
    if p.status == "archived":
        raise _err(409, "Quy trình đã lưu trữ. Khôi phục hoặc tạo quy trình mới trước khi chạy.")
    steps = steps_of(db, p.id)
    if not steps:
        raise _err(409, "Quy trình chưa có bước nào. Thêm ít nhất một bước (gắn chức danh) rồi bấm Chạy.")
    if amount_usd is not None and amount_usd < 0:
        raise _err(422, "Số tiền (USD) không được âm.")
    n = db.query(ProcessInstance).filter(ProcessInstance.process_id == p.id).count() + 1
    now = datetime.utcnow()
    inst = ProcessInstance(organization_id=org_id, company_id=p.company_id, process_id=p.id,
                           title=(title or f"Lần {n}")[:220], amount_usd=amount_usd, input_json=input_data or None,
                           started_by_member_id=actor_member_id, started_at=now, status="running")
    project = _project(db, p)
    inst.project_id = project.id
    db.add(inst); db.commit(); db.refresh(inst)
    prev_task: Task | None = None
    out_runs = []
    for s in steps:
        assignee, note = pick_assignee(db, org_id, p.company_id, s.position_id)
        task = ops.create_task(db, project, org_id, title=f"[{p.name} #{inst.id}] B{s.seq}: {s.name}"[:220],
                               description=_brief(db, p, inst, s, steps), assignee_member_id=assignee,
                               actor_member_id=actor_member_id)
        run = ProcessStepRun(instance_id=inst.id, step_id=s.id, seq=s.seq, name=s.name, task_id=task.id,
                             position_id=s.position_id, assignee_member_id=assignee,
                             expected_minutes=s.expected_minutes, note=note[:400], status="waiting")
        if s.action_type and assignee:
            d = authority.decide(db, db.get(Member, assignee), s.action_type, amount_usd=amount_usd,
                                 risk=s.risk or None, company_id=p.company_id)
            if d is not None:
                run.authority_rule_id = d.rule_id
                if d.requires_approval and d.approver_member_id:
                    run.approval_required, run.approver_member_id = True, d.approver_member_id
                    execution_policy.set_policy(db, task, {"stages": [{"type": "approval",
                                                                       "participants": [d.approver_member_id]}]})
        if prev_task is not None:
            db.add(TaskDependency(task_id=task.id, blocked_by_task_id=prev_task.id, created_by_member_id=actor_member_id))
        db.add(run); db.commit(); db.refresh(run)
        out_runs.append(run)
        prev_task = task
    first = out_runs[0]
    first.status, first.activated_at = "active", now
    db.commit()
    t0 = db.get(Task, first.task_id)
    lifecycle.transition(db, t0, "todo", reason=f"quy trình #{p.id} lần chạy #{inst.id}: bước 1 tới lượt",
                         via="process", system=True, organization_id=org_id, company_id=p.company_id)
    wakeup.enqueue_for_task(db, t0, "assigned", dedupe_key=f"process:i{inst.id}:s1",
                            payload={"process_id": p.id, "instance_id": inst.id, "step": 1})
    emit_event(db, organization_id=org_id, company_id=p.company_id, event_type="process.started", source=SOURCE,
               aggregate_type="process_instance", aggregate_id=str(inst.id), actor_member_id=actor_member_id,
               payload={"process_id": p.id, "instance_id": inst.id, "tasks": [r.task_id for r in out_runs]})
    return public_instance(db, inst)


def _close_instance(db: Session, inst: ProcessInstance, status: str, now: datetime) -> None:
    from app.services.company_event_bus import emit_event
    inst.status, inst.finished_at = status, now
    if status == "done":
        inst.cycle_seconds = (now - inst.started_at).total_seconds()
    db.commit()
    emit_event(db, organization_id=inst.organization_id, company_id=inst.company_id, event_type=f"process.{status}",
               source=SOURCE, aggregate_type="process_instance", aggregate_id=str(inst.id),
               payload={"process_id": inst.process_id, "instance_id": inst.id, "cycle_seconds": inst.cycle_seconds})


def on_task_status(db: Session, task: Task, to: str) -> None:
    """Gọi từ ``task_lifecycle.transition`` sau khi task đổi trạng thái. Không bao giờ ném."""
    try:
        run = db.query(ProcessStepRun).filter(ProcessStepRun.task_id == task.id).first()
        if run is None:
            return
        _advance(db, run, to)
    except Exception as exc:  # noqa: BLE001 — đo chu trình không được làm hỏng việc chuyển trạng thái
        db.rollback()
        print(f"[m2c] process step for task #{task.id}: {exc}")


def _advance(db: Session, run: ProcessStepRun, to: str) -> None:
    from app.services import task_lifecycle as lifecycle
    now = datetime.utcnow()
    inst = db.get(ProcessInstance, run.instance_id)
    if inst is None or inst.status != "running":
        return
    if to == "in_progress":
        if run.started_at is None:
            run.started_at = now
        if run.status == "waiting":
            run.status, run.activated_at = "active", run.activated_at or now
        db.commit()
        return
    if to == "done" and run.status != "done":
        run.status, run.finished_at = "done", now
        run.cycle_seconds = (now - (run.activated_at or inst.started_at)).total_seconds()
        db.commit()
        nxt = (db.query(ProcessStepRun).filter(ProcessStepRun.instance_id == inst.id, ProcessStepRun.status == "waiting")
               .order_by(ProcessStepRun.seq).first())
        if nxt is None:
            _close_instance(db, inst, "done", now)
            return
        nxt.status, nxt.activated_at = "active", now
        db.commit()
        t = db.get(Task, nxt.task_id) if nxt.task_id else None
        if t is not None and t.status == "backlog":
            lifecycle.transition(db, t, "todo", reason=f"quy trình lần chạy #{inst.id}: bước {nxt.seq} tới lượt",
                                 via="process", system=True, organization_id=inst.organization_id,
                                 company_id=inst.company_id)
        return
    if to == "cancelled" and run.status not in ("done", "cancelled"):
        run.status, run.finished_at = "cancelled", now
        db.commit()
        cancel(db, inst.organization_id, inst.id, reason=f"bước {run.seq} bị huỷ", _from_task=True)


def cancel(db: Session, org_id: int, instance_id: int, *, reason: str = "huỷ tay", _from_task: bool = False) -> dict:
    from app.services import task_lifecycle as lifecycle
    inst = db.get(ProcessInstance, instance_id)
    if inst is None or inst.organization_id != org_id:
        raise _err(404, "Không thấy lần chạy này.")
    if inst.status != "running":
        raise _err(409, f"Lần chạy đã {inst.status}, không huỷ được nữa.")
    now = datetime.utcnow()
    _close_instance(db, inst, "cancelled", now)
    for r in db.query(ProcessStepRun).filter(ProcessStepRun.instance_id == inst.id,
                                              ProcessStepRun.status.in_(("waiting", "active"))).all():
        r.status, r.finished_at = "cancelled", now
        db.commit()
        t = db.get(Task, r.task_id) if r.task_id else None
        if t is not None and t.status not in ("done", "cancelled"):
            lifecycle.transition(db, t, "cancelled", reason=f"quy trình lần chạy #{inst.id} bị huỷ: {reason}",
                                 via="process", system=True, organization_id=org_id, company_id=inst.company_id)
    return public_instance(db, inst)


def public_instance(db: Session, inst: ProcessInstance) -> dict:
    p = db.get(Process, inst.process_id)
    runs = (db.query(ProcessStepRun).filter(ProcessStepRun.instance_id == inst.id)
            .order_by(ProcessStepRun.seq).all())
    names = {m.id: m.name for m in db.query(Member).filter(
        Member.id.in_([r.assignee_member_id for r in runs if r.assignee_member_id]
                      + [r.approver_member_id for r in runs if r.approver_member_id])).all()} if runs else {}
    now = datetime.utcnow()
    elapsed = ((inst.finished_at or now) - inst.started_at).total_seconds()
    return {"id": inst.id, "process_id": inst.process_id, "process": p.name if p else None, "title": inst.title,
            "status": inst.status, "amount_usd": inst.amount_usd, "input": inst.input_json,
            "project_id": inst.project_id,
            "started_at": inst.started_at.isoformat() if inst.started_at else None,
            "finished_at": inst.finished_at.isoformat() if inst.finished_at else None,
            "cycle_minutes": _fmt_minutes(inst.cycle_seconds), "elapsed_minutes": _fmt_minutes(elapsed),
            "steps": [{"id": r.id, "seq": r.seq, "name": r.name, "task_id": r.task_id, "status": r.status,
                       "task_status": (db.get(Task, r.task_id).status if r.task_id and db.get(Task, r.task_id) else None),
                       "position": _pos_title(db, r.position_id), "assignee_member_id": r.assignee_member_id,
                       "assignee": names.get(r.assignee_member_id), "approval_required": r.approval_required,
                       "approver": names.get(r.approver_member_id), "authority_rule_id": r.authority_rule_id,
                       "expected_minutes": r.expected_minutes, "note": r.note,
                       "cycle_minutes": _fmt_minutes(r.cycle_seconds),
                       "late": bool(r.status == "active" and r.expected_minutes and r.activated_at
                                    and (now - r.activated_at).total_seconds() > r.expected_minutes * 60),
                       "activated_at": r.activated_at.isoformat() if r.activated_at else None,
                       "finished_at": r.finished_at.isoformat() if r.finished_at else None} for r in runs]}


def instances(db: Session, org_id: int, pid: int, *, limit: int = 30) -> dict:
    p = _process(db, org_id, pid)
    rows = (db.query(ProcessInstance).filter(ProcessInstance.process_id == p.id)
            .order_by(ProcessInstance.id.desc()).limit(limit).all())
    return {"process_id": p.id, "items": [public_instance(db, i) for i in rows]}


def get_instance(db: Session, org_id: int, instance_id: int) -> dict:
    inst = db.get(ProcessInstance, instance_id)
    if inst is None or inst.organization_id != org_id:
        raise _err(404, "Không thấy lần chạy này.")
    return public_instance(db, inst)


# ------------------------------------------------------------------ mẫu theo loại công ty

def _S(name, who, minutes, instructions="", action="", risk=""):
    return {"name": name, "who": who, "minutes": minutes, "instructions": instructions, "action": action, "risk": risk}


TEMPLATES: dict[str, list[dict]] = {
    "shop": [
        {"key": "shop_order", "name": "Đơn hàng → giao hàng → hậu mãi", "category": "4", "owner": "bán hàng",
         "description": "Từ lúc khách chốt đơn tới khi nhận hàng và được hỏi thăm sau mua.",
         "steps": [_S("Xác nhận đơn với khách", "chăm sóc khách", 15, "Gọi/nhắn xác nhận sản phẩm, địa chỉ, hình thức thanh toán.", "external_message"),
                   _S("Đóng gói & xuất kho", "kho", 60, "Kiểm hàng, chèn chống sốc cho đồ gốm, in phiếu, trừ tồn."),
                   _S("Bàn giao vận chuyển & gửi mã vận đơn", "kho", 30, "Bàn giao đơn vị vận chuyển, gửi mã vận đơn cho khách."),
                   _S("Hỏi thăm sau giao hàng", "chăm sóc khách", 15, "Sau khi giao 2–3 ngày: hỏi tình trạng hàng, xin đánh giá.", "external_message")]},
        {"key": "shop_refund", "name": "Hoàn tiền / đổi trả", "category": "6", "owner": "bán hàng",
         "description": "Khách báo hàng lỗi/vỡ hoặc muốn đổi trả — theo chính sách đổi trả của cửa hàng.",
         "steps": [_S("Tiếp nhận yêu cầu & đối chiếu chính sách", "chăm sóc khách", 20, "Xin ảnh/video tình trạng hàng, đối chiếu chính sách đổi trả, ghi số tiền đề nghị hoàn."),
                   _S("Hoàn tiền cho khách", "chăm sóc khách", 30, "Hoàn đúng số tiền đã duyệt qua kênh khách đã thanh toán.", "refund"),
                   _S("Nhận hàng hoàn & kiểm kho", "kho", 60, "Nhận lại hàng (nếu có), kiểm và nhập kho/hủy."),
                   _S("Báo khách hoàn tất", "chăm sóc khách", 10, "Báo khách đã hoàn tiền/đổi xong, xin lỗi vì sự cố.", "external_message")]},
        {"key": "shop_post", "name": "Đăng sản phẩm mới", "category": "3", "owner": "marketing",
         "description": "Đưa một sản phẩm mới lên các kênh bán.",
         "steps": [_S("Viết mô tả & chuẩn bị ảnh", "nội dung", 90),
                   _S("Duyệt nội dung", "marketing", 30),
                   _S("Đăng lên kênh bán", "nội dung", 20, "", "external_message")]},
    ],
    "agency": [
        {"key": "agency_brief", "name": "Nhận brief → sản xuất → báo cáo khách", "category": "5", "owner": "account",
         "description": "Một yêu cầu sáng tạo của khách từ brief tới bàn giao.",
         "steps": [_S("Nhận & làm rõ brief", "account", 60), _S("Lên ý tưởng", "sáng tạo", 240),
                   _S("Thiết kế sản phẩm", "thiết kế", 480), _S("Gửi khách & nhận phản hồi", "account", 60, "", "external_message")]},
        {"key": "agency_ads", "name": "Chạy chiến dịch quảng cáo", "category": "3", "owner": "media",
         "description": "Lên kế hoạch, dựng và báo cáo một chiến dịch ads.",
         "steps": [_S("Lập kế hoạch media & ngân sách", "media", 120), _S("Dựng chiến dịch & nạp ngân sách", "ads", 120, "", "spend"),
                   _S("Báo cáo kết quả tuần đầu", "account", 60, "", "external_message")]},
    ],
    "ketoan": [
        {"key": "kt_tax", "name": "Khai thuế GTGT/TNCN kỳ", "category": "9", "owner": "thuế",
         "description": "Khai thuế theo tháng/quý cho một khách hàng.",
         "steps": [_S("Tập hợp & đối chiếu chứng từ", "kế toán viên", 240), _S("Lập tờ khai", "thuế", 120),
                   _S("Kiểm tra tờ khai", "kế toán trưởng", 60), _S("Nộp tờ khai & lưu biên nhận", "thuế", 30, "", "external_message")]},
        {"key": "kt_payroll", "name": "Tính lương & BHXH tháng", "category": "7", "owner": "lương",
         "description": "Bảng lương và hồ sơ bảo hiểm hằng tháng.",
         "steps": [_S("Chốt công & tính lương", "lương", 180), _S("Duyệt bảng lương", "giám đốc", 30),
                   _S("Nộp BHXH & gửi phiếu lương", "lương", 60, "", "spend")]},
    ],
}


def _find_position(positions: list[Position], hint: str) -> int | None:
    h = hint.lower()
    for p in positions:
        if h in (p.title or "").lower():
            return p.id
    return None


def seed_templates(db: Session, org_id: int, company_id: int, template: str, *, skip_existing: bool = True) -> dict:
    if template not in TEMPLATES:
        raise _err(422, f"Không có bộ quy trình mẫu \"{template}\". Chọn một trong: {', '.join(TEMPLATES)}.")
    co = _company(db, org_id, company_id)
    positions = db.query(Position).filter(Position.company_id == co.id, Position.status != "archived").order_by(Position.id).all()
    made, skipped = [], []
    for spec in TEMPLATES[template]:
        if skip_existing and db.query(Process).filter(Process.company_id == co.id, Process.template_key == spec["key"],
                                                       Process.status != "archived").first():
            skipped.append(spec["name"]); continue
        sop = SOP(organization_id=org_id, title=f"SOP: {spec['name']}", version="v1.0", status="published",
                  department_id=None,
                  content="\n".join([spec["description"], ""] + [f"{i}. {s['name']}" + (f" — {s['instructions']}" if s["instructions"] else "")
                                                                  for i, s in enumerate(spec["steps"], start=1)]))
        db.add(sop); db.commit(); db.refresh(sop)
        p = Process(organization_id=org_id, company_id=co.id, category=spec["category"], name=spec["name"],
                    description=spec["description"], owner_position_id=_find_position(positions, spec["owner"]),
                    template_key=spec["key"], status="active")
        db.add(p); db.commit(); db.refresh(p)
        for i, s in enumerate(spec["steps"], start=1):
            db.add(ProcessStep(process_id=p.id, seq=i, name=s["name"], instructions=s["instructions"],
                               position_id=_find_position(positions, s["who"]), sop_id=sop.id,
                               expected_minutes=s["minutes"], action_type=s["action"], risk=s["risk"]))
        db.commit()
        made.append(p.id)
    return {"company_id": co.id, "template": template, "created": made, "skipped": skipped}
