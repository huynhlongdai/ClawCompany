"""D3.2 — chọn seat theo tải (WP-4.2, phần "theo tải").

``choose(need, seats)`` là hàm **thuần**: không đọc DB, không gọi gateway. Đầu
vào là ảnh chụp trạng thái các seat (``SeatState``), đầu ra là ``Decision``
gồm seat được chọn (hoặc ``None``), câu lý do đọc được cho người quản lý, và lý
do loại của từng seat. Lọc theo đúng thứ tự:

1. **phòng ban** — nếu việc thuộc một phòng, chỉ seat của phòng đó;
2. **kỹ năng** — seat phải có đủ mọi kỹ năng việc yêu cầu;
3. **active** — ``members.status`` và ``agents.lifecycle`` đều ``active``;
4. **tải** — số run đang mở (``task_runs`` queued/dispatched/running) phải
   dưới ``max_open_runs``;
5. **hạn mức còn lại** — phần còn lại nhỏ nhất trong các phong bì ngân sách áp
   dụng cho seat phải đủ cho số giữ chỗ ước tính (``budget_scope.estimate``).

Trong số seat qua cả 5 lớp: ít run mở nhất → nhiều hạn mức còn lại nhất → id
nhỏ nhất. Không ai qua thì ``seat=None`` và lý do nói rõ lớp nào loại hết ai —
không bao giờ chọn bừa.

Phần không thuần (``snapshot``, ``decide``, ``record``) nằm cuối file: đọc DB
để dựng ``SeatState`` và ghi quyết định vào ``company_events`` để trả lời
"vì sao việc này giao cho seat đó".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable, Sequence

STAGES = ("department", "skills", "active", "load", "budget")
STAGE_LABEL = {
    "department": "không thuộc phòng ban của việc",
    "skills": "thiếu kỹ năng",
    "active": "không hoạt động",
    "load": "đang đầy việc",
    "budget": "không đủ hạn mức",
}


@dataclass(frozen=True)
class Need:
    department_id: int | None = None
    skills: tuple[str, ...] = ()
    estimate_usd: float = 0.05
    max_open_runs: int = 2


@dataclass(frozen=True)
class SeatState:
    member_id: int
    name: str = ""
    department_id: int | None = None
    skills: tuple[str, ...] | None = ()   # None = chưa biết (không đọc được cấu hình seat)
    member_status: str = "active"
    lifecycle: str = "active"
    open_runs: int = 0
    budget_remaining_usd: float | None = None   # None = không phong bì nào áp dụng
    budget_block: str = ""                      # phong bì đã exhausted → lý do chặn
    estimate_usd: float | None = None           # số giữ chỗ riêng của seat (TB run gần đây)


@dataclass
class Decision:
    member_id: int | None
    reason: str
    stage: str = ""          # lớp loại hết ứng viên khi member_id None
    rejected: dict = field(default_factory=dict)   # member_id -> lý do
    considered: int = 0
    eligible: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _norm(skills: Iterable[str] | None) -> set[str]:
    return {str(s).strip().lower() for s in (skills or ()) if str(s).strip()}


def _reject(stage: str, seat: SeatState, need: Need) -> str:
    if stage == "department":
        if seat.department_id != need.department_id:
            return f"thuộc phòng {seat.department_id or '—'}, việc cần phòng {need.department_id}"
    elif stage == "skills":
        want = _norm(need.skills)
        if want:
            if seat.skills is None:
                return "chưa đọc được kỹ năng của seat"
            missing = sorted(want - _norm(seat.skills))
            if missing:
                return "thiếu kỹ năng: " + ", ".join(missing)
    elif stage == "active":
        if (seat.member_status or "") != "active":
            return f"seat đang {seat.member_status or 'không rõ'}"
        if (seat.lifecycle or "") != "active":
            return f"agent đang {seat.lifecycle or 'không rõ'}"
    elif stage == "load":
        if seat.open_runs >= need.max_open_runs:
            return f"đang mở {seat.open_runs}/{need.max_open_runs} run"
    elif stage == "budget":
        if seat.budget_block:
            return seat.budget_block
        need_usd = seat.estimate_usd if seat.estimate_usd is not None else need.estimate_usd
        if seat.budget_remaining_usd is not None and seat.budget_remaining_usd + 1e-9 < need_usd:
            return f"còn ${seat.budget_remaining_usd:.2f}, cần ${need_usd:.2f}"
    return ""


def choose(need: Need, seats: Sequence[SeatState]) -> Decision:
    pool = list(seats)
    rejected: dict[int, str] = {}
    if not pool:
        return Decision(None, "Không có seat agent nào để chọn.", stage="none", considered=0)
    for stage in STAGES:
        if stage == "department" and need.department_id is None:
            continue
        keep = []
        for seat in pool:
            why = _reject(stage, seat, need)
            if why:
                rejected[seat.member_id] = f"{STAGE_LABEL[stage]} — {why}"
            else:
                keep.append(seat)
        if not keep:
            return Decision(None, _nobody(stage, pool, rejected, need), stage=stage,
                            rejected=rejected, considered=len(seats))
        pool = keep
    pool.sort(key=lambda s: (s.open_runs, -(s.budget_remaining_usd if s.budget_remaining_usd is not None else float("inf")), s.member_id))
    best = pool[0]
    return Decision(best.member_id, _why(best, pool, need), rejected=rejected,
                    considered=len(seats), eligible=[s.member_id for s in pool])


def _nobody(stage: str, last: list[SeatState], rejected: dict, need: Need) -> str:
    names = ", ".join(f"{s.name or s.member_id} ({rejected[s.member_id].split(' — ', 1)[-1]})" for s in last)
    return f"Không seat nào đủ điều kiện: {len(last)} seat còn lại đều {STAGE_LABEL[stage]}: {names}."


def _why(best: SeatState, pool: list[SeatState], need: Need) -> str:
    parts = []
    if need.department_id is not None:
        parts.append(f"thuộc phòng {need.department_id}")
    if need.skills:
        parts.append("có đủ kỹ năng " + ", ".join(sorted(_norm(need.skills))))
    parts.append(f"đang mở {best.open_runs}/{need.max_open_runs} run")
    if best.budget_remaining_usd is not None:
        parts.append(f"còn ${best.budget_remaining_usd:.2f} hạn mức")
    tail = f"; ít tải nhất trong {len(pool)} seat đủ điều kiện" if len(pool) > 1 else "; là seat duy nhất đủ điều kiện"
    return f"Chọn {best.name or best.member_id}: " + ", ".join(parts) + tail + "."


# ------------------------------------------------------------- phần đọc/ghi DB


def snapshot(db, organization_id: int, *, task=None, company_id: int | None = None,
             skills_of: dict[int, Sequence[str]] | None = None) -> list[SeatState]:
    """Dựng ``SeatState`` cho mọi seat agent của tổ chức (lọc công ty nếu có).

    ``skills_of`` (member_id → kỹ năng) do tầng trên đọc từ cấu hình gateway
    (``seat_skills``); thiếu thì kỹ năng là ``None`` = chưa biết.
    """
    from sqlalchemy import func
    from app.models import BudgetEnvelope, TaskRun  # noqa: F401
    from app.models.entities import Agent, Member
    from app.models.work_graph import OPEN_RUN_STATUSES
    from app.services import budget as budget_svc
    from app.services import budget_scope as bs

    q = db.query(Member, Agent).join(Agent, Agent.member_id == Member.id).filter(
        Member.organization_id == organization_id, Member.member_type == "agent")
    if company_id is not None:
        q = q.filter(Member.company_id == company_id)
    rows = q.order_by(Member.id).all()
    ids = [m.id for m, _ in rows]
    open_by = dict(db.query(TaskRun.member_id, func.count(TaskRun.id)).filter(
        TaskRun.member_id.in_(ids or [-1]), TaskRun.status.in_(OPEN_RUN_STATUSES)).group_by(TaskRun.member_id).all())
    out = []
    for member, agent in rows:
        envs = bs.applicable(db, member, task)
        block, remaining = "", None
        for env in envs:
            if (env.threshold_state or "ok") == "exhausted" or env.status != "active":
                block = block or f"phong bì {env.name} đã {'hết hạn mức' if env.status == 'active' else env.status}"
            r = budget_svc.remaining(env)
            remaining = r if remaining is None else min(remaining, r)
        skills = None
        if skills_of is not None and member.id in skills_of:
            skills = tuple(skills_of[member.id] or ())
        out.append(SeatState(
            member_id=member.id, name=member.name, department_id=member.department_id, skills=skills,
            member_status=member.status or "", lifecycle=agent.lifecycle or "",
            open_runs=int(open_by.get(member.id, 0)), budget_remaining_usd=remaining, budget_block=block,
            estimate_usd=bs.estimate(db, member.id)))
    return out


async def seat_skills(registry, db, organization_id: int) -> dict[int, list[str]]:
    """Kỹ năng của từng seat theo cấu hình hiệu dụng trên gateway (nguồn sự thật)."""
    from app.models.entities import Agent, Member
    rows = db.query(Member.id, Agent.runtime_agent_id).join(Agent, Agent.member_id == Member.id).filter(
        Member.organization_id == organization_id).all()
    out: dict[int, list[str]] = {}
    for member_id, runtime_id in rows:
        try:
            entry = await registry.agent_entry(runtime_id)
        except Exception:
            continue
        skills = entry.get("effective", {}).get("skills")
        if isinstance(skills, list):
            out[member_id] = [str(s.get("name") if isinstance(s, dict) else s) for s in skills]
    return out


def decide(db, organization_id: int, *, task=None, department_id: int | None = None,
           skills: Sequence[str] = (), company_id: int | None = None,
           skills_of: dict[int, Sequence[str]] | None = None) -> Decision:
    from app.core.config import settings
    from app.services import budget_scope as bs
    seats = snapshot(db, organization_id, task=task, company_id=company_id, skills_of=skills_of)
    if department_id is None and task is not None:
        department_id = getattr(task, "assignee_department_id", None)
    need = Need(department_id=department_id, skills=tuple(skills or ()),
                estimate_usd=bs.estimate(db, None), max_open_runs=int(settings.dispatch_max_open_runs))
    return choose(need, seats)


def record(db, organization_id: int, decision: Decision, *, task=None, actor_member_id: int | None = None,
           company_id: int | None = None):
    """Ghi quyết định vào ``company_events`` (``task.dispatch_decided``)."""
    from app.services.company_event_bus import emit_event
    payload = decision.as_dict()
    payload["rejected"] = {str(k): v for k, v in decision.rejected.items()}
    if task is not None:
        payload["task_id"] = task.id
    return emit_event(db, organization_id=organization_id, company_id=company_id,
                      event_type="task.dispatch_decided", source="dispatch_policy",
                      aggregate_type="task" if task is not None else "", aggregate_id=str(task.id) if task is not None else "",
                      actor_member_id=actor_member_id, payload=payload)
