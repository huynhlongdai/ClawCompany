"""M6 việc 11 — sự nghiệp của agent: bộ đánh giá theo vai, scorecard thật, thử việc, thăng/hạ quyền.

* Bộ đánh giá (``EvalSuite``): ca kiểm như Skill Studio (câu hỏi + chữ phải có / không được có), mỗi ca chạy
  ``k`` lần trong phiên riêng. Agent gặp khách phải ĐÚNG CẢ k LẦN (pass^k), không phải đúng một lần:
  75%/lần → 3/3 lần chỉ ~42%. Mỗi lượt chạy gắn số phiên bản hồ sơ (AgentVersion) lúc chạy.
* Scorecard: tính từ dữ liệu thật trong N ngày — việc xong, tỉ lệ qua review ngay lần đầu, số vòng sửa,
  lượt chạy lỗi, chi phí/việc xong (USD), lần bị chặn quyền, lỗ hổng kiến thức, bài học được duyệt,
  điểm giữ vai, pass^k gần nhất. Không có số seed.
* Cấp tự chủ: ``probation`` (thử việc: gửi ra ngoài phải hỏi, không chi tiền, không xoá) → ``standard``
  (mặc định theo tầng) → ``trusted`` (tự gửi; chi tiền/xoá vẫn hỏi). Đổi cấp đi qua ``update_hr`` nên mỗi
  lần là một AgentVersion, khôi phục bản cũ = trả cả quyền về như cũ.
* Gợi ý thăng/hạ bằng luật rõ ràng; người quản lý bấm mới đổi.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Agent, Approval, Member, Task
from app.models.learning import EvalRun, EvalSuite, KnowledgeGap

LEVELS = ("probation", "standard", "trusted")
LEVEL_VI = {"probation": "Thử việc", "standard": "Chính thức", "trusted": "Tin cậy"}
LEVEL_ACTIONS = {
    "probation": {"action:send": "ask", "action:pay": "off", "action:delete": "off"},
    "standard": {"action:send": None, "action:pay": None, "action:delete": None},   # None = theo mặc định tầng
    "trusted": {"action:send": "allowed", "action:pay": "ask", "action:delete": "ask"},
}


def apply_level(db: Session, member: Member, level: str, *, actor_member_id: int | None = None) -> None:
    from app.services import tool_permissions as perms
    for tool, lvl in LEVEL_ACTIONS[level].items():
        perms.set_level(db, member.organization_id, tool, lvl, member_id=member.id, actor_member_id=actor_member_id)


# ------------------------------------------------------------------ bộ đánh giá

def _suite(db: Session, org_id: int, sid: int) -> EvalSuite:
    s = db.get(EvalSuite, sid)
    if s is None or s.organization_id != org_id:
        raise HTTPException(404, "Không thấy bộ đánh giá")
    return s


def suite_public(s: EvalSuite) -> dict:
    return {"id": s.id, "title": s.title, "role_keyword": s.role_keyword, "department_id": s.department_id,
            "cases": list(s.cases or []), "k": s.k}


def save_suite(db: Session, org_id: int, data: dict, sid: int | None = None) -> dict:
    from app.services.skill_studio import clean_cases
    s = _suite(db, org_id, sid) if sid else EvalSuite(organization_id=org_id)
    title = (data.get("title") if data.get("title") is not None else s.title or "").strip()
    if len(title) < 3:
        raise HTTPException(422, "Tên bộ đánh giá cần ít nhất 3 ký tự")
    k = int(data.get("k") or s.k or 3)
    if not 1 <= k <= 5:
        raise HTTPException(422, "Số lần chạy mỗi ca (k) từ 1 đến 5")
    cases = clean_cases(data["cases"]) if data.get("cases") is not None else list(s.cases or [])
    if not cases:
        raise HTTPException(422, "Bộ đánh giá cần ít nhất 1 ca")
    if len(cases) * k > 30:
        raise HTTPException(422, "Tối đa 30 lượt hỏi một lần chạy (số ca × k)")
    s.title, s.k, s.cases = title[:220], k, cases
    if "role_keyword" in data:
        s.role_keyword = (data.get("role_keyword") or "").strip()[:120]
    if "department_id" in data:
        s.department_id = data.get("department_id")
    db.add(s); db.commit(); db.refresh(s)
    return suite_public(s)


def suites_for(db: Session, org_id: int, member: Member | None = None) -> list[dict]:
    out = []
    for s in db.query(EvalSuite).filter(EvalSuite.organization_id == org_id).order_by(EvalSuite.id).all():
        if member is not None:
            kw = (s.role_keyword or "").lower()
            if kw and kw not in (member.role or "").lower():
                continue
            if s.department_id and s.department_id != member.department_id:
                continue
        out.append(suite_public(s))
    return out


async def run_suite(db: Session, org_id: int, runtime: Any, agent_id: int, suite_id: int, *, timeout: int = 120) -> dict:
    from app.services import agent_hr, agent_versions
    from app.services.skill_studio import score
    if not agent_hr._has_rpc(runtime) or not hasattr(runtime, "chat_stream"):
        raise HTTPException(409, "Cần gateway OpenClaw thật để chạy đánh giá")
    ag, m = agent_hr.seat(db, org_id, agent_id)
    if ag.lifecycle in ("paused", "retired", "runtime_missing"):
        raise HTTPException(409, f"{m.name} đang ở trạng thái {ag.lifecycle}")
    s = _suite(db, org_id, suite_id)
    stamp = int(time.time())
    sem = asyncio.Semaphore(4)

    async def ask(prompt: str, key: str) -> str:
        async with sem:
            text = ""
            try:
                async for ev in runtime.chat_stream(ag.runtime_agent_id, prompt, session_key=key, timeout_seconds=timeout):
                    if ev["kind"] == "delta":
                        text = ev["text"]
                    elif ev["kind"] == "final":
                        return ev.get("text") or text
                    elif ev["kind"] != "tool":
                        return text or f"[lỗi] {ev.get('message')}"
            except Exception as exc:  # noqa: BLE001
                return text or f"[lỗi gateway] {exc}"
            return text

    async def case(i: int, c: dict) -> dict:
        replies = await asyncio.gather(*(ask(c["prompt"], f"agent:{ag.runtime_agent_id}:eval-{s.id}-{i}-{j}-{stamp}")
                                         for j in range(s.k)))
        tries = [{**score(r, c), "reply": r[:800]} for r in replies]
        ok = sum(t["passed"] for t in tries)
        return {"prompt": c["prompt"], "passed": ok, "k": s.k, "all_passed": ok == s.k, "tries": tries}

    results = await asyncio.gather(*(case(i, c) for i, c in enumerate(s.cases or [])))
    n = len(results) or 1
    run = EvalRun(suite_id=s.id, agent_id=ag.id, profile_version=agent_versions.latest_version_number(db, ag.id) or None,
                  k=s.k, pass_at_1=round(sum(r["passed"] for r in results) / (n * s.k), 3),
                  pass_k=round(sum(r["all_passed"] for r in results) / n, 3), results=results)
    db.add(run); db.commit(); db.refresh(run)
    return run_public(db, run)


def run_public(db: Session, r: EvalRun, *, full: bool = True) -> dict:
    s = db.get(EvalSuite, r.suite_id)
    out = {"id": r.id, "suite_id": r.suite_id, "suite": s.title if s else "?", "profile_version": r.profile_version,
           "k": r.k, "pass_at_1": r.pass_at_1, "pass_k": r.pass_k, "created_at": r.created_at.isoformat()}
    if full:
        out["results"] = r.results
    return out


# ------------------------------------------------------------------ scorecard

def scorecard(db: Session, org_id: int, agent_id: int, *, days: int = 30) -> dict:
    from app.models.v10 import CompanyEvent
    from app.models.work_graph import TaskRun
    from app.services import agent_hr, agent_versions
    ag, m = agent_hr.seat(db, org_id, agent_id)
    since = datetime.utcnow() - timedelta(days=days)
    tasks = db.query(Task).filter(Task.assignee_member_id == m.id, Task.updated_at >= since).all()
    done = [t for t in tasks if t.status == "done"]
    reviewed = first_pass = revisions = 0
    for t in tasks:
        hist = [h for h in ((t.execution_state or {}).get("history") or []) if h.get("decision")]
        if not hist:
            continue
        reviewed += 1
        revisions += sum(1 for h in hist if h["decision"] == "revise")
        first_pass += hist[0]["decision"] == "approve"
    runs = db.query(TaskRun).filter(TaskRun.member_id == m.id, TaskRun.created_at >= since).all()
    failed = sum(1 for r in runs if (r.error_reason or "").strip() or r.status in ("failed", "error"))
    cost = round(sum(r.cost_usd or 0 for r in runs), 4)
    denied = (db.query(CompanyEvent).filter(CompanyEvent.event_type == "mcp.tool.denied",
                                            CompanyEvent.actor_member_id == m.id, CompanyEvent.occurred_at >= since).count())
    gaps = db.query(KnowledgeGap).filter(KnowledgeGap.member_id == m.id, KnowledgeGap.created_at >= since).count()
    lessons = (db.query(Approval).filter(Approval.organization_id == org_id, Approval.policy_key.like(f"lesson:a{ag.id}:%"),
                                         Approval.status == "approved").count())
    last = db.query(EvalRun).filter(EvalRun.agent_id == ag.id).order_by(EvalRun.id.desc()).first()
    v = agent_versions._latest(db, ag.id)
    spec = agent_hr.hire_spec(db, ag)
    from app.services import kpi_cascade   # M2c D5: KPI của seat (chia từ chức danh) vào scorecard
    kpis = kpi_cascade.seat_kpis(db, m.id)
    scored = [k["progress"] for k in kpis if k["progress"] is not None]
    from app.services import io_contracts, runtime_rules   # M2e.3 hợp đồng dữ liệu, M2e.2 luật cứng
    conf = io_contracts.conformance(db, member_ids=[m.id], days=days)
    rules = runtime_rules.compliance(db, m, days=days)
    return {"agent_id": ag.id, "name": m.name, "days": days,
            "output_conformance": conf, "output_conformance_rate": conf["rate"],
            "rule_compliance_rate": rules["rate"], "rule_violations": rules["violations"],
            "kpis": kpis, "kpi_attainment": round(sum(scored) / len(scored), 1) if scored else None,
            "level": spec.get("career_level") or "standard", "level_vi": LEVEL_VI[spec.get("career_level") or "standard"],
            "tasks_touched": len(tasks), "tasks_done": len(done),
            "reviewed": reviewed, "first_pass_rate": round(first_pass / reviewed, 3) if reviewed else None,
            "revisions": revisions, "runs": len(runs), "failed_runs": failed,
            "failure_rate": round(failed / len(runs), 3) if runs else None,
            "cost_usd": cost, "cost_per_done_usd": round(cost / len(done), 4) if done else None,
            "policy_denials": denied, "knowledge_gaps": gaps, "lessons_approved": lessons,
            "persona_score": v.persona_score if v else None,
            "eval": run_public(db, last, full=False) if last else None}


def recommend(card: dict) -> dict:
    """Luật thăng/hạ — rõ ràng để người quản lý thấy vì sao."""
    lvl, ev = card["level"], card.get("eval") or {}
    pk = ev.get("pass_k")
    fp = card.get("first_pass_rate")
    reasons: list[str] = []
    if card["policy_denials"] >= 3 or (pk is not None and pk < 0.6) or (card.get("failure_rate") or 0) > 0.3:
        if lvl != "probation":
            if card["policy_denials"] >= 3:
                reasons.append(f"{card['policy_denials']} lần gọi công cụ bị chặn")
            if pk is not None and pk < 0.6:
                reasons.append(f"chỉ {pk:.0%} ca đúng cả {ev.get('k')} lần")
            if (card.get("failure_rate") or 0) > 0.3:
                reasons.append(f"{card['failure_rate']:.0%} lượt chạy lỗi")
            return {"action": "demote", "to": LEVELS[LEVELS.index(lvl) - 1], "reasons": reasons}
    kpi = card.get("kpi_attainment")
    kpi_need = {"KPI của seat đạt ≥ 90%": kpi >= 90} if kpi is not None else {}   # M2c D5: chỉ xét khi seat có KPI có số
    if lvl == "probation":
        need = {**kpi_need, "đánh giá pass^k ≥ 80%": pk is not None and pk >= 0.8, "≥ 5 việc xong": card["tasks_done"] >= 5,
                "qua review lần đầu ≥ 70%": fp is None or fp >= 0.7, "không bị chặn quyền": card["policy_denials"] == 0}
        if all(need.values()):
            return {"action": "promote", "to": "standard", "reasons": list(need)}
        return {"action": "keep", "to": lvl, "reasons": [f"chưa đạt: {k}" for k, ok in need.items() if not ok]}
    if lvl == "standard":
        need = {**kpi_need, "đánh giá pass^k ≥ 90%": pk is not None and pk >= 0.9, "≥ 20 việc xong": card["tasks_done"] >= 20,
                "qua review lần đầu ≥ 85%": fp is not None and fp >= 0.85, "không bị chặn quyền": card["policy_denials"] == 0}
        if all(need.values()):
            return {"action": "promote", "to": "trusted", "reasons": list(need)}
        return {"action": "keep", "to": lvl, "reasons": [f"chưa đạt: {k}" for k, ok in need.items() if not ok]}
    return {"action": "keep", "to": lvl, "reasons": ["đang ở cấp cao nhất"]}


def overview(db: Session, org_id: int, agent_id: int, *, days: int = 30) -> dict:
    from app.services import agent_hr
    _, m = agent_hr.seat(db, org_id, agent_id)
    card = scorecard(db, org_id, agent_id, days=days)
    runs = db.query(EvalRun).filter(EvalRun.agent_id == agent_id).order_by(EvalRun.id.desc()).limit(10).all()
    return {"scorecard": card, "recommendation": recommend(card), "suites": suites_for(db, org_id, m),
            "runs": [run_public(db, r, full=False) for r in runs],
            "levels": [{"key": k, "label": LEVEL_VI[k], "actions": {a.split(":")[1]: (v or "mặc định") for a, v in LEVEL_ACTIONS[k].items()}}
                       for k in LEVELS]}


async def set_level(db: Session, principal, org_id: int, runtime: Any, agent_id: int, *, level: str, reason: str) -> dict:
    from app.services import agent_hr
    if level not in LEVELS:
        raise HTTPException(422, f"Cấp tự chủ phải là một trong: {', '.join(LEVELS)}")
    if len((reason or "").strip()) < 5:
        raise HTTPException(422, "Ghi lý do đổi cấp (ít nhất 5 ký tự) — lưu vào lịch sử phiên bản")
    out = await agent_hr.update_hr(db, principal, org_id, runtime, agent_id, {"career_level": level}, {"career_level"},
                                   version_note=f"Đổi cấp → {LEVEL_VI[level]}: {reason.strip()}"[:300])
    return {**out, "level": level, "level_vi": LEVEL_VI[level]}
