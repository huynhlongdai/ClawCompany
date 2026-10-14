"""D2.3 — ngân sách ba nấc, chặn thật.

Một ``budget_envelopes`` có phạm vi ``scope_type`` ∈ company | department |
member | project | goal (+ ``scope_id``). Bản ghi cũ (trước 0023) có
``scope_type='company'``: ``company_id`` NULL nghĩa là cả tổ chức, ``goal_id``
có giá trị nghĩa là ngân sách của mục tiêu.

Vòng đời tiền của một lượt chạy (``task_runs``), dùng lại ``services/budget``:

1. **Giữ chỗ** khi drain wakeup, *trước* ``chat.send``: số giữ =
   ``estimate`` (max của số cấu hình và trung bình 10 run gần nhất của seat).
   Không giữ được ở bất kỳ phong bì nào → wakeup ``skipped`` lý do ``budget``,
   gateway không nhận gì.
2. **Quyết toán** khi run kết thúc bằng ``task_runs.cost_usd`` (cộng từ
   ``session.message``), rồi **đối chiếu** lại bằng ``sessions.usage`` của
   gateway — nguồn sự thật theo D1.2 (`_reports/cost-reconciliation.md`).
   Hàm quyết toán là luỹ đẳng: gọi lại với số mới chỉ ghi phần chênh.
3. Run lỗi → giải phóng phần còn giữ (vẫn tính phần đã tiêu thật).

Nấc: ≥ ``warn_pct`` → ``warned``: inbox cho người phụ trách + luật "chỉ làm
việc critical" ở khối 6. ≥ ``soft_stop_pct`` (M4b, tuỳ chọn) → ``soft_stopped``:
mỗi việc trong phạm vi muốn chạy lượt mới phải có phê duyệt
``budget_soft:e<phong bì>:t<việc>`` (cổng tự tạo phê duyệt, gửi quản lý người
của seat; duyệt → đánh thức lại, từ chối → việc không được chạy nữa ở nấc này).
≥ 100% → ``exhausted`` (dừng cứng): seat ``paused``, task mở của seat
``blocked`` lý do ``budget``. Mở lại chỉ qua ``override`` (có audit).
Rời nấc dừng mềm (nâng hạn mức / override) thì mọi phê duyệt chi tiếp của
phong bì hết hiệu lực (``expired``) — lần sau chạm lại nấc phải duyệt lại.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.runtime.factory import resolve_mode
from app.models import BudgetEnvelope, BudgetLedgerEntry, Member, Task, TaskRun
from app.services import budget as budget_svc

SCOPES = ("company", "department", "member", "team", "project", "goal")
GRANT_SCOPES = ("task", "seat", "department")   # M4b: một phê duyệt chi tiếp phủ một việc / cả seat / cả phòng
LEVELS = ("ok", "warned", "soft_stopped", "exhausted")
LEVEL_ORDER = {k: i for i, k in enumerate(LEVELS)}
LEVEL_VI = {"ok": "Trong hạn mức", "warned": "Cảnh báo", "soft_stopped": "Dừng mềm — cần duyệt để chi tiếp",
            "exhausted": "Dừng cứng — đã hết hạn mức"}
SOFT_PREFIX = "budget_soft:"
SRC = "task_run"            # giữ chỗ / quyết toán từ phần đã giữ / giải phóng
SRC_EXTRA = "task_run_extra"  # tiêu vượt phần giữ, hoặc điều chỉnh theo gateway
BLOCKABLE = ("todo", "in_progress")
EPS = 1e-9


# ------------------------------------------------------------------ phạm vi


def scope_of(env: BudgetEnvelope) -> tuple[str, int | None]:
    st = env.scope_type or "company"
    if st == "company" and env.goal_id is not None:
        return "goal", env.goal_id                       # phong bì mục tiêu cũ (v9)
    if st == "company":
        return "company", env.scope_id or env.company_id
    return st, env.scope_id


def team_ids(db: Session, member_id: int | None) -> set[int]:
    """Nhóm (agent_teams) đang có mặt thành viên này — để ngân sách theo nhóm phủ đúng seat."""
    if not member_id:
        return set()
    from app.models.v16 import AgentTeamMember
    return {t for (t,) in db.query(AgentTeamMember.team_id).filter(AgentTeamMember.member_id == member_id,
                                                                    AgentTeamMember.status == "active").all()}


def covers(env: BudgetEnvelope, member: Member | None, task, teams: set[int] | None = None) -> bool:
    st, sid = scope_of(env)
    if st == "team":
        return member is not None and sid is not None and sid in (teams or set())
    if st == "company":
        return member is not None and (sid is None or sid == member.company_id)
    if st == "department":
        return member is not None and sid is not None and member.department_id == sid
    if st == "member":
        return member is not None and sid == member.id
    if st == "project":
        return task is not None and sid is not None and task.project_id == sid
    if st == "goal":
        return task is not None and sid is not None and getattr(task, "goal_id", None) == sid
    return False


def applicable(db: Session, member: Member | None, task=None) -> list[BudgetEnvelope]:
    org = member.organization_id if member is not None else None
    if org is None:
        return []
    rows = (db.query(BudgetEnvelope)
            .filter(BudgetEnvelope.organization_id == org, BudgetEnvelope.status != "archived")
            .order_by(BudgetEnvelope.id).all())
    teams = team_ids(db, member.id) if any((e.scope_type or "") == "team" for e in rows) else set()
    return [e for e in rows if covers(e, member, task, teams)]


def estimate(db: Session, member_id: int | None) -> float:
    """Số giữ chỗ cho một run: không thấp hơn cấu hình, không thấp hơn thực tế gần đây."""
    base = float(settings.wakeup_run_estimate_usd)
    if not member_id:
        return base
    costs = [c for (c,) in db.query(TaskRun.cost_usd)
             .filter(TaskRun.member_id == member_id, TaskRun.cost_usd > 0)
             .order_by(TaskRun.id.desc()).limit(10).all()]
    avg = sum(costs) / len(costs) if costs else 0.0
    return round(max(base, avg), 6)


def pct(env: BudgetEnvelope) -> float:
    limit = float(env.amount_limit or 0)
    return 100.0 if limit <= 0 else round(100.0 * float(env.amount_spent or 0) / limit, 2)


# ------------------------------------------------------------------ cổng


def gate(db: Session, member: Member, task, amount: float | None = None) -> tuple[str, list, float]:
    """Trả (lý do chặn | "", phong bì áp dụng, số giữ)."""
    amount = estimate(db, member.id) if amount is None else amount
    envs = applicable(db, member, task)
    for env in envs:
        if (env.threshold_state or "ok") == "exhausted":
            return f"budget: {env.name}: đã hết hạn mức ({pct(env):.0f}%)", envs, amount
        ok, msg = budget_svc.can_reserve(env, amount)
        if not ok:
            return f"budget: {env.name}: {msg}", envs, amount
    for env in envs:   # M4b: dừng mềm — chỉ xét sau dừng cứng (lý do hết tiền quan trọng hơn)
        if (env.threshold_state or "ok") == "soft_stopped":
            why = soft_gate(db, env, member, task)
            if why:
                return why, envs, amount
    return "", envs, amount


# ------------------------------------------------------------------ M4b: dừng mềm


def soft_key(env_id: int, task_id: int) -> str:
    return f"{SOFT_PREFIX}e{env_id}:t{task_id}"


def parse_soft_key(key: str) -> tuple[int, int] | None:
    import re
    m = re.match(r"^budget_soft:e(\d+):t(\d+)$", key or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def soft_gate(db: Session, env: BudgetEnvelope, member: Member, task) -> str:
    """Phong bì ở nấc dừng mềm: cho chạy nếu việc đã có phê duyệt chi tiếp còn hiệu lực.

    Chưa có → tạo MỘT phê duyệt đang chờ (không tạo trùng mỗi lần drain) và chặn.
    Đã bị từ chối → chặn, không hỏi lại tới khi phong bì rời nấc này."""
    from app.models import Approval
    if not isinstance(task, Task):
        return f"budget_approval: {env.name}: đã chạm nấc dừng mềm ({pct(env):.0f}%) — cần duyệt chi tiếp"
    key = soft_key(env.id, task.id)
    if grant_for(db, env, member, task) is not None:
        return ""
    latest = (db.query(Approval).filter(Approval.organization_id == env.organization_id,
                                        Approval.policy_key == key)
              .order_by(Approval.id.desc()).first())
    if latest is not None and latest.status in ("rejected", "denied"):
        return (f"budget_rejected: {env.name}: chi tiếp cho việc #{task.id} đã bị từ chối "
                f"(phê duyệt #{latest.id})")
    if latest is None or latest.status != "pending":
        latest = _request_soft_approval(db, env, member, task, key)
    return (f"budget_approval: {env.name}: đã dùng {pct(env):.0f}% (nấc dừng mềm {env.soft_stop_pct}%) — "
            f"chờ duyệt chi tiếp (phê duyệt #{latest.id})")


def grant_scope_of(a) -> str:
    p = a.payload if isinstance(a.payload, dict) else {}
    return p.get("grant_scope") if p.get("grant_scope") in GRANT_SCOPES else "task"


def _evidence(a) -> dict:
    try:
        ev = json.loads(a.evidence or "{}")
        return ev if isinstance(ev, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def grant_covers(a, member: Member, task) -> bool:
    """Phê duyệt chi tiếp ``a`` (đã duyệt) có phủ (seat, việc) này không — theo phạm vi người duyệt chọn."""
    scope, ev = grant_scope_of(a), _evidence(a)
    if scope == "department":
        return ev.get("department_id") is not None and ev.get("department_id") == member.department_id
    if scope == "seat":
        return ev.get("member_id") == member.id
    parsed = parse_soft_key(a.policy_key or "")
    return parsed is not None and task is not None and parsed[1] == task.id


def grant_for(db: Session, env: BudgetEnvelope, member: Member, task):
    from app.models import Approval
    rows = (db.query(Approval).filter(Approval.organization_id == env.organization_id,
                                      Approval.policy_key.like(f"{SOFT_PREFIX}e{env.id}:t%"),
                                      Approval.status == "approved").order_by(Approval.id.desc()).all())
    return next((a for a in rows if grant_covers(a, member, task)), None)


def soft_approver(db: Session, env: BudgetEnvelope, member: Member) -> int | None:
    from app.services import inbox
    got = inbox.human_recipients(db, member.id)
    if got:
        return got[0]
    humans = _humans(db, env, [member])
    return humans[0] if humans else None


def _request_soft_approval(db: Session, env: BudgetEnvelope, member: Member, task: Task, key: str):
    from app.models import Approval
    a = Approval(organization_id=env.organization_id, company_id=member.company_id or env.company_id,
                 requester_member_id=member.id, approver_member_id=soft_approver(db, env, member),
                 action=f"Chi tiếp ngân sách '{env.name}' cho việc #{task.id}: {task.title}"[:220],
                 risk="high", policy_key=key, status="pending",
                 evidence=json.dumps({"task_id": task.id, "budget_id": env.id, "pct": pct(env),
                                      "soft_stop_pct": env.soft_stop_pct, "spent_usd": round(env.amount_spent or 0, 6),
                                      "limit_usd": env.amount_limit, "member_id": member.id,
                                      "department_id": member.department_id,
                                      "summary": f"{member.name} muốn chạy tiếp việc #{task.id} khi ngân sách "
                                                 f"'{env.name}' đã dùng {pct(env):.0f}% hạn mức"},
                                     ensure_ascii=False))
    db.add(a); db.commit(); db.refresh(a)
    return a


def expire_soft_grants(db: Session, env: BudgetEnvelope, why: str) -> list[int]:
    """Phê duyệt chi tiếp (đã duyệt hoặc đang chờ) của phong bì hết hiệu lực."""
    from app.models import Approval
    rows = (db.query(Approval).filter(Approval.organization_id == env.organization_id,
                                      Approval.policy_key.like(f"{SOFT_PREFIX}e{env.id}:t%"),
                                      Approval.status.in_(("approved", "pending"))).all())
    for a in rows:
        a.status = "expired"
        a.resolution_note = ((a.resolution_note or "") + f" [hết hiệu lực: {why}]").strip()
        db.add(a)
    if rows:
        db.commit()
    return [a.id for a in rows]


def on_soft_decision(db: Session, approval) -> dict:
    """Duyệt chi tiếp → đánh thức lại seat trên đúng việc đó.

    Phạm vi ``seat``/``department``: các yêu cầu chi tiếp đang chờ mà phê duyệt này phủ
    được duyệt theo (một quyết định gỡ cả hàng chờ của phòng), và seat trong phạm vi được đánh thức lại."""
    from app.models import Approval
    from app.services import wakeup
    parsed = parse_soft_key(approval.policy_key or "")
    if parsed is None or approval.status != "approved":
        return {"woken": None}
    scope = grant_scope_of(approval)
    covered: list[int] = []
    woken: list[int] = []
    if scope != "task":
        siblings = (db.query(Approval).filter(Approval.organization_id == approval.organization_id,
                                              Approval.policy_key.like(f"{SOFT_PREFIX}e{parsed[0]}:t%"),
                                              Approval.status == "pending", Approval.id != approval.id).all())
        for s in siblings:
            m = db.get(Member, s.requester_member_id) if s.requester_member_id else None
            sp = parse_soft_key(s.policy_key or "")
            if m is not None and sp is not None and grant_covers(approval, m, db.get(Task, sp[1])):
                s.status = "approved"
                s.payload = {**(s.payload or {}), "covered_by": approval.id}
                s.resolution_note = f"Được phủ bởi phê duyệt #{approval.id} ({scope})"
                db.add(s); covered.append(s.id)
        db.commit()
    for a in [approval] + [db.get(Approval, i) for i in covered]:
        sp = parse_soft_key(a.policy_key or "")
        task = db.get(Task, sp[1]) if sp else None
        if task is None:
            continue
        wk = wakeup.enqueue_for_task(db, task, "approval_resolved", member_id=a.requester_member_id,
                                     dedupe_key=f"budget_soft:a{a.id}",
                                     payload={"approval_id": a.id, "budget_id": parsed[0]})
        if wk is not None:
            woken.append(wk.id)
    return {"woken": woken[0] if woken else None, "woken_all": woken, "grant_scope": scope,
            "covered_approvals": covered}


def level_of(env: BudgetEnvelope, p: float | None = None) -> str:
    p = pct(env) if p is None else p
    if p >= 100 - EPS:
        return "exhausted"
    if env.soft_stop_pct and p >= float(env.soft_stop_pct) - EPS:
        return "soft_stopped"
    if p >= float(env.warn_pct or 80):
        return "warned"
    return "ok"


def hold(db: Session, envs: list, amount: float, key: str, memo: str) -> list[int]:
    return [budget_svc.reserve(db, env, amount, source_type=SRC, source_id=key, memo=memo).id for env in envs]


def rekey(db: Session, old: str, new: str) -> int:
    n = (db.query(BudgetLedgerEntry)
         .filter(BudgetLedgerEntry.source_type == SRC, BudgetLedgerEntry.source_id == old)
         .update({BudgetLedgerEntry.source_id: new}, synchronize_session=False))
    db.commit()
    return n


def release_key(db: Session, key: str, memo: str) -> None:
    for env_id in _env_ids(db, key):
        env = db.get(BudgetEnvelope, env_id)
        held, _ = _position(db, env_id, key)
        if env is not None and held > EPS:
            budget_svc.release_reserved(db, env, held, source_type=SRC, source_id=key, memo=memo)


def run_key(run: TaskRun | int) -> str:
    return f"run:{run if isinstance(run, int) else run.id}"


def _env_ids(db: Session, key: str) -> list[int]:
    return [i for (i,) in db.query(BudgetLedgerEntry.budget_id).filter(
        BudgetLedgerEntry.source_type.in_((SRC, SRC_EXTRA)), BudgetLedgerEntry.source_id == key).distinct()]


def _position(db: Session, env_id: int, key: str) -> tuple[float, float]:
    """(đang giữ, đã tiêu) của một khoá trên một phong bì."""
    rows = (db.query(BudgetLedgerEntry.entry_type, BudgetLedgerEntry.source_type, func.sum(BudgetLedgerEntry.amount))
            .filter(BudgetLedgerEntry.budget_id == env_id, BudgetLedgerEntry.source_id == key,
                    BudgetLedgerEntry.source_type.in_((SRC, SRC_EXTRA)))
            .group_by(BudgetLedgerEntry.entry_type, BudgetLedgerEntry.source_type).all())
    s = {(t, src): float(v or 0) for t, src, v in rows}
    held = s.get(("reserve", SRC), 0) - s.get(("release", SRC), 0) - s.get(("spend", SRC), 0)
    spent = s.get(("spend", SRC), 0) + s.get(("spend", SRC_EXTRA), 0) - s.get(("credit", SRC_EXTRA), 0)
    return max(0.0, held), spent


def _spend_direct(db: Session, env: BudgetEnvelope, amount: float, key: str, memo: str, entry_type="spend"):
    sign = 1 if entry_type == "spend" else -1
    env.amount_spent = max(0.0, float(env.amount_spent or 0) + sign * amount)
    db.add_all([env, BudgetLedgerEntry(organization_id=env.organization_id, budget_id=env.id,
                                       entry_type=entry_type, amount=amount, source_type=SRC_EXTRA,
                                       source_id=key, memo=memo)])
    db.commit()


def settle_key(db: Session, envs: list, key: str, actual: float, *, final: bool, memo: str) -> list[dict]:
    """Đưa số đã tiêu của ``key`` trên mỗi phong bì về đúng ``actual``. Luỹ đẳng."""
    ids = {e.id for e in envs} | set(_env_ids(db, key))
    out = []
    for env_id in sorted(ids):
        env = db.get(BudgetEnvelope, env_id)
        if env is None:
            continue
        held, spent = _position(db, env_id, key)
        delta = round(float(actual) - spent, 10)
        if delta > EPS:
            take = min(delta, held)
            if take > EPS:
                budget_svc.settle_reserved(db, env, take, source_type=SRC, source_id=key, memo=memo)
                held -= take
            if delta - take > EPS:
                _spend_direct(db, env, delta - take, key, memo + " (vượt phần giữ)")
        elif delta < -EPS:
            _spend_direct(db, env, -delta, key, memo + " (điều chỉnh giảm)", entry_type="credit")
        if final and held > EPS:
            budget_svc.release_reserved(db, env, held, source_type=SRC, source_id=key,
                                        memo=memo + " — trả phần giữ thừa")
        db.refresh(env)
        out.append({"budget_id": env.id, "delta": delta, **check_thresholds(db, env)})
    return out


def settle_run(db: Session, run: TaskRun, *, actual: float | None = None, final: bool = True,
               source: str = "task_runs.cost_usd") -> list[dict]:
    member = db.get(Member, run.member_id) if run.member_id else None
    task = db.get(Task, run.task_id) if run.task_id else None
    envs = applicable(db, member, task)
    value = float(run.cost_usd or 0) if actual is None else float(actual)
    return settle_key(db, envs, run_key(run), value, final=final,
                      memo=f"run #{run.id} task #{run.task_id} — {source}")


async def true_up_run(db: Session, run: TaskRun, runtime) -> dict:
    """Quyết toán theo ``sessions.usage`` của gateway (nguồn sự thật D1.2).

    Phiên của task có thể chứa nhiều run (làm lại sau SỬA). Phần của run này =
    tổng phiên − phần đã quyết toán cho các run TRƯỚC nó cùng phiên."""
    from app.services.cost_ledger import fetch_gateway_usage
    if not run.session_key:
        return {"status": "no_session"}
    got = await fetch_gateway_usage(runtime, run.session_key)
    usage = got.get("usage")
    if usage is None:
        return {"status": "no_usage", "cache": got.get("cache")}
    earlier = db.query(TaskRun).filter(TaskRun.session_key == run.session_key, TaskRun.id < run.id).all()
    before = sum(_spent_any(db, run_key(r)) for r in earlier)
    actual = max(0.0, round(float(usage["cost_usd"]) - before, 10))
    local = float(run.cost_usd or 0)
    res = settle_run(db, run, actual=actual, final=True, source=f"gateway sessions.usage ({got.get('cache')})")
    return {"status": "ok", "gateway_session_usd": usage["cost_usd"], "earlier_runs_usd": round(before, 10),
            "actual_usd": actual, "local_usd": local, "envelopes": res}


def schedule_true_up(run_id: int) -> bool:
    """Chạy ``true_up_run`` nền khi đang có event loop và runtime là gateway thật."""
    import asyncio
    if not settings.budget_true_up or resolve_mode(settings.openclaw_mode) != "native":
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    loop.create_task(_true_up_bg(run_id))
    return True


async def _true_up_bg(run_id: int) -> None:
    import asyncio
    from app.db.session import SessionLocal
    from app.runtime.factory import get_runtime
    await asyncio.sleep(settings.budget_true_up_delay_seconds)
    db = SessionLocal()
    try:
        run = db.get(TaskRun, run_id)
        if run is not None:
            out = await true_up_run(db, run, get_runtime())
            print(f"[D2.3] true-up run #{run_id}: {json.dumps(out, default=str)[:400]}")
    except Exception as exc:  # noqa: BLE001
        print(f"[D2.3] true-up run #{run_id} failed: {exc}")
    finally:
        db.close()


def _spent_any(db: Session, key: str) -> float:
    """Tiền đã quyết toán của một khoá (lấy ở phong bì đầu tiên có ghi)."""
    ids = _env_ids(db, key)
    return _position(db, ids[0], key)[1] if ids else 0.0


# ------------------------------------------------------------------ nấc


def check_thresholds(db: Session, env: BudgetEnvelope) -> dict:
    p = pct(env)
    state = env.threshold_state or "ok"
    new = level_of(env, p)
    if new == state:
        return {"state": state, "pct": p, "changed": False}
    env.threshold_state = new
    db.add(env); db.commit()
    acted: dict = {}
    if state == "soft_stopped" and LEVEL_ORDER[new] < LEVEL_ORDER[state]:
        acted["expired_approvals"] = expire_soft_grants(db, env, "phong bì rời nấc dừng mềm")
    if new == "warned" and state == "ok":
        acted = {**acted, **_on_warned(db, env, p)}
    elif new == "soft_stopped" and LEVEL_ORDER[state] < LEVEL_ORDER[new]:
        acted = {**acted, **_on_soft_stopped(db, env, p)}
    elif new == "exhausted":
        acted = {**acted, **_on_exhausted(db, env, p)}
    return {"state": new, "pct": p, "changed": True, **acted}


def _scope_members(db: Session, env: BudgetEnvelope) -> list[Member]:
    st, sid = scope_of(env)
    q = db.query(Member).filter(Member.organization_id == env.organization_id, Member.member_type == "agent")
    if st == "member":
        q = q.filter(Member.id == sid)
    elif st == "department":
        q = q.filter(Member.department_id == sid)
    elif st == "company":
        if sid is not None:
            q = q.filter(Member.company_id == sid)
    elif st == "team":
        from app.models.v16 import AgentTeamMember
        ids = [m for (m,) in db.query(AgentTeamMember.member_id).filter(AgentTeamMember.team_id == sid,
                                                                        AgentTeamMember.status == "active").all()]
        q = q.filter(Member.id.in_(ids or [-1]))
    else:
        return []          # project/goal: chỉ chặn task trong phạm vi, không dừng seat
    return q.all()


def _scope_tasks(db: Session, env: BudgetEnvelope, members: list[Member]) -> list[Task]:
    st, sid = scope_of(env)
    q = db.query(Task).filter(Task.status.in_(BLOCKABLE))
    if st == "project":
        q = q.filter(Task.project_id == sid)
    elif st == "goal":
        q = q.filter(Task.goal_id == sid)
    else:
        if not members:
            return []
        q = q.filter(Task.assignee_member_id.in_([m.id for m in members]))
    return q.order_by(Task.id).all()


def _humans(db: Session, env: BudgetEnvelope, members: list[Member]) -> list[int]:
    ids = {m.manager_id for m in members if m.manager_id}
    if not ids:
        q = db.query(Member.id).filter(Member.organization_id == env.organization_id,
                                       Member.member_type == "human", Member.status == "active")
        if env.company_id:
            q = q.filter(Member.company_id == env.company_id)
        ids = {i for (i,) in q.limit(20).all()}
    return sorted(ids)


def _inbox(db: Session, env: BudgetEnvelope, recipients: list[int], title: str, priority: str,
           kind: str | None = None) -> list[int]:
    from app.services import inbox  # D3.5: gộp theo phong bì, chỉ người nhận
    kind = kind or ("budget_exhausted" if priority == "urgent" else "budget_warned")
    items = inbox.notify(db, organization_id=env.organization_id, recipients=recipients, kind=kind,
                         title=title, related_type="budget_envelope", related_id=str(env.id),
                         priority=priority, source="budget")
    return [i.id for i in items]


def _event(db: Session, env: BudgetEnvelope, event_type: str, payload: dict) -> None:
    from app.services.company_event_bus import emit_event
    try:
        emit_event(db, organization_id=env.organization_id, event_type=event_type, source="budget",
                   aggregate_type="budget_envelope", aggregate_id=str(env.id), company_id=env.company_id,
                   payload=payload)
    except Exception as exc:  # noqa: BLE001
        print(f"[D2.3] emit {event_type} failed: {exc}")


def _on_warned(db: Session, env: BudgetEnvelope, p: float) -> dict:
    members = _scope_members(db, env)
    title = f"Ngân sách '{env.name}' đã dùng {p:.0f}% — seat chỉ làm việc critical"
    inbox = _inbox(db, env, _humans(db, env, members), title, "high")
    _event(db, env, "budget.warned", {"pct": p, "inbox": inbox})
    return {"inbox": inbox}


def _on_soft_stopped(db: Session, env: BudgetEnvelope, p: float) -> dict:
    members = _scope_members(db, env)
    title = (f"Ngân sách '{env.name}' đã dùng {p:.0f}% — chạm nấc dừng mềm {env.soft_stop_pct}%: "
             "lượt chạy mới cần anh duyệt")
    inbox = _inbox(db, env, _humans(db, env, members), title, "high", kind="budget_soft_stopped")
    _event(db, env, "budget.soft_stopped", {"pct": p, "soft_stop_pct": env.soft_stop_pct, "inbox": inbox})
    return {"inbox": inbox}


def _on_exhausted(db: Session, env: BudgetEnvelope, p: float) -> dict:
    from app.services import task_lifecycle as lifecycle
    from app.services.audit import log_event
    members = _scope_members(db, env)
    paused = []
    for m in members:
        if m.status == "active":
            m.status = "paused"; db.add(m); paused.append(m.id)
    db.commit()
    blocked = []
    for t in _scope_tasks(db, env, members):
        st = dict(t.execution_state or {})
        st["budget_block"] = {"budget_id": env.id, "from": t.status, "at": datetime.utcnow().isoformat()}
        t.execution_state = st
        lifecycle.transition(db, t, "blocked", system=True, via="budget", reason="budget")
        blocked.append(t.id)
    title = f"Ngân sách '{env.name}' đã hết ({p:.0f}%) — {len(paused)} seat tạm dừng, {len(blocked)} task bị chặn"
    inbox = _inbox(db, env, _humans(db, env, members), title, "urgent")
    payload = {"pct": p, "paused_members": paused, "blocked_tasks": blocked, "inbox": inbox}
    log_event(db, env.organization_id, "budget.exhausted", object_type="budget_envelope", object_id=str(env.id),
              actor_name="system", result="success", risk="high", payload=payload)
    _event(db, env, "budget.exhausted", payload)
    return payload


def override(db: Session, env: BudgetEnvelope, *, actor_member_id: int | None, actor_name: str,
             reason: str, new_limit: float | None = None, add_usd: float | None = None) -> dict:
    """Đường duy nhất để mở lại một phong bì đã hết: đổi hạn mức + audit + khôi phục."""
    from app.models import AuditEvent
    from app.services import task_lifecycle as lifecycle
    from app.services import wakeup
    from app.services.audit import log_event
    if not reason or not reason.strip():
        raise ValueError("override cần lý do")
    before = {"amount_limit": env.amount_limit, "threshold_state": env.threshold_state, "pct": pct(env)}
    if new_limit is not None:
        env.amount_limit = float(new_limit)
    if add_usd:
        env.amount_limit = float(env.amount_limit or 0) + float(add_usd)
    if env.status == "exhausted":
        env.status = "active"
    p = pct(env)
    env.threshold_state = level_of(env, p)
    db.add(env); db.commit(); db.refresh(env)
    expired = expire_soft_grants(db, env, "override hạn mức")
    restored_members, restored_tasks, requeued = [], [], []
    if env.threshold_state != "exhausted":
        last = (db.query(AuditEvent).filter(AuditEvent.organization_id == env.organization_id,
                                            AuditEvent.action == "budget.exhausted",
                                            AuditEvent.object_type == "budget_envelope",
                                            AuditEvent.object_id == str(env.id))
                .order_by(AuditEvent.id.desc()).first())
        info = json.loads(last.payload_json or "{}") if last else {}
        for mid in info.get("paused_members", []):
            m = db.get(Member, mid)
            if m is not None and m.status == "paused" and not _still_exhausted(db, m, exclude=env.id):
                m.status = "active"; db.add(m); restored_members.append(mid)
        db.commit()
        for tid in info.get("blocked_tasks", []):
            t = db.get(Task, tid)
            st = dict(t.execution_state or {}) if t is not None else {}
            if t is None or t.status != "blocked" or (st.get("budget_block") or {}).get("budget_id") != env.id:
                continue
            st.pop("budget_block", None); t.execution_state = st
            lifecycle.transition(db, t, "todo", system=True, via="budget", reason="budget_override")
            restored_tasks.append(tid)
        stamp = int(datetime.utcnow().timestamp())
        for mid in sorted({*restored_members, *[m.id for m in _scope_members(db, env)]}):
            requeued += [w.id for w in wakeup._requeue(db, mid, "budget%", f"override-{env.id}-{stamp}")]
    payload = {"reason": reason, "before": before,
               "after": {"amount_limit": env.amount_limit, "threshold_state": env.threshold_state, "pct": pct(env)},
               "restored_members": restored_members, "restored_tasks": restored_tasks,
               "requeued_wakeups": requeued, "expired_approvals": expired}
    log_event(db, env.organization_id, "budget.override", object_type="budget_envelope", object_id=str(env.id),
              actor_member_id=actor_member_id, actor_name=actor_name, result="success", risk="high", payload=payload)
    _event(db, env, "budget.override", payload)
    return payload


def _still_exhausted(db: Session, member: Member, exclude: int) -> bool:
    return any(e.threshold_state == "exhausted" for e in applicable(db, member, None) if e.id != exclude)


# ------------------------------------------------------------------ khối 6


def context_lines(db: Session, member: Member | None, task) -> list[str]:
    if member is None:
        return []
    out = []
    for env in applicable(db, member, task):
        if (env.threshold_state or "ok") in ("warned", "soft_stopped", "exhausted"):
            out.append(f"- Ngân sách '{env.name}' đã dùng {pct(env):.0f}% hạn mức: CHỈ làm việc critical. "
                       "Việc không critical thì ghi comment xin hoãn rồi dừng.")
    return out[:2]


# ------------------------------------------------------------------ báo cáo chi tiêu


def spend_breakdown(db: Session, organization_id: int, budget_id: int | None = None) -> dict:
    """Chi tiêu thật theo seat, task, dự án — từ sổ cái, không từ ước lượng.

    Không truyền ``budget_id``: mỗi khoá chỉ đếm ở MỘT phong bì (phong bì lồng
    nhau ghi cùng một run nhiều lần)."""
    q = db.query(BudgetLedgerEntry).filter(BudgetLedgerEntry.organization_id == organization_id,
                                           BudgetLedgerEntry.source_type.in_((SRC, SRC_EXTRA)),
                                           BudgetLedgerEntry.entry_type.in_(("spend", "credit")))
    if budget_id is not None:
        return _aggregate(db, q.filter(BudgetLedgerEntry.budget_id == budget_id).all())
    rows = q.order_by(BudgetLedgerEntry.id).all()
    first: dict[str, int] = {}
    for e in rows:
        first.setdefault(e.source_id, e.budget_id)
    return _aggregate(db, [e for e in rows if first[e.source_id] == e.budget_id])


def _aggregate(db: Session, rows) -> dict:
    from app.models.entities import Project
    per_key: dict[str, float] = {}
    for e in rows:
        per_key[e.source_id] = per_key.get(e.source_id, 0.0) + (e.amount if e.entry_type == "spend" else -e.amount)
    seats: dict[str, float] = {}
    tasks: dict[str, float] = {}
    projects: dict[str, float] = {}
    runs = []
    for key, amt in per_key.items():
        if not key.startswith("run:"):
            seats["(phòng họp)"] = seats.get("(phòng họp)", 0.0) + amt
            continue
        run = db.get(TaskRun, int(key.split(":", 1)[1]))
        if run is None:
            continue
        task = db.get(Task, run.task_id)
        member = db.get(Member, run.member_id) if run.member_id else None
        project = db.get(Project, task.project_id) if task and task.project_id else None
        sk = member.name if member else "(không rõ)"
        seats[sk] = seats.get(sk, 0.0) + amt
        tk = f"#{run.task_id} {task.title if task else ''}".strip()
        tasks[tk] = tasks.get(tk, 0.0) + amt
        pk = project.name if project else "(không dự án)"
        projects[pk] = projects.get(pk, 0.0) + amt
        runs.append({"run_id": run.id, "task_id": run.task_id, "member": sk, "status": run.status,
                     "spent_usd": round(amt, 6), "run_cost_usd": round(float(run.cost_usd or 0), 6),
                     "session_key": run.session_key})

    def rows_of(d):
        return sorted(({"name": k, "spent_usd": round(v, 6)} for k, v in d.items()), key=lambda r: -r["spent_usd"])
    return {"by_seat": rows_of(seats), "by_task": rows_of(tasks), "by_project": rows_of(projects),
            "runs": sorted(runs, key=lambda r: -r["run_id"]), "total_usd": round(sum(per_key.values()), 6)}


def public(env: BudgetEnvelope) -> dict:
    st, sid = scope_of(env)
    return {"id": env.id, "name": env.name, "scope_type": st, "scope_id": sid, "company_id": env.company_id,
            "goal_id": env.goal_id, "amount_limit": env.amount_limit,
            "amount_reserved": round(env.amount_reserved or 0, 6), "amount_spent": round(env.amount_spent or 0, 6),
            "warn_pct": env.warn_pct, "soft_stop_pct": env.soft_stop_pct, "period": env.period,
            "threshold_state": env.threshold_state or "ok", "level_vi": LEVEL_VI.get(env.threshold_state or "ok", ""),
            "status": env.status, "pct": pct(env), "remaining": round(budget_svc.remaining(env), 6),
            "currency": env.currency}
