"""M3 — Nhân sự AI: tuyển, sửa hồ sơ 2 chiều, vòng đời, đối chiếu lệch.

Một nhân sự AI sống ở ba nơi (xem ``seat_profile``): Postgres, cấu hình agent
trên gateway, và 5 file workspace. Module này là chỗ duy nhất *ghi* cả ba cùng
lúc, theo các luật:

* **Tuyển** = tạo member + seat (``provision_agent``) → ``agents.create`` trên
  gateway → ghi đủ 5 file → lưu bản ClawCompany (``agent_file_snapshots``).
  Gateway từ chối thì nói thẳng (``needs_runtime``), không giả vờ đã có file.
* **Sửa hồ sơ** ghi DB và gateway (``agents.update``). File sinh lại
  (IDENTITY/SOUL/AGENTS/USER) chỉ ghi đè khi bản trên gateway còn khớp bản
  ClawCompany đã ghi; lệch thì dừng và báo, để người chọn chiều đồng bộ.
* **Lệch** = hash file trên gateway khác hash ClawCompany đã ghi, hoặc tên/model
  khác nhau. ``resync`` đẩy bản ClawCompany lên (push) hoặc nhận bản gateway
  (pull) — luôn là lựa chọn nói ra, không tự chọn hộ.
* **Nghỉ việc** dọn sạch phiên trên gateway, gỡ việc đang mở, bỏ chức trưởng
  phòng, chuyển người báo cáo lên trên, khoá API key; 5 file được lưu lại trước
  khi xoá agent khỏi gateway, nên hồ sơ vẫn đọc được.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.authz import Principal
from app.models import (Agent, AgentProvisioningJob, APIKey, BudgetEnvelope, Company, Department, Member,
                        Task)
from app.models.agent_hr import AgentFileSnapshot
from app.runtime import openclaw_protocol as ocp
from app.services import team as team_svc
from app.services import tool_permissions as perms
from app.services.audit import log_event
from app.services.provisioning import provision_agent

SEAT_FILES = ocp.AGENT_BOOTSTRAP_FILES
OPEN_STATUSES = ("backlog", "todo", "in_progress", "review", "blocked")
# Agent được phép tự ghi MEMORY.md (ký ức) — khác bản ClawCompany là chuyện bình
# thường, không tính là "lệch cần xử lý".
AGENT_OWNED_FILES = ("MEMORY.md",)
# Seat ở các trạng thái này không được nhận lượt chạy mới.
BLOCKED_LIFECYCLES = ("paused", "retired", "runtime_missing")
LIFECYCLE_VI = {"paused": "đang tạm dừng", "retired": "đã nghỉ việc",
                "runtime_missing": "chưa có agent trên gateway"}

PERSONALITIES: dict[str, dict[str, Any]] = {
    "tan-tuy": {"label": "Tận tuỵ, cẩn thận", "emoji": "🧭", "traits": [
        "Kiểm tra kỹ trước khi báo xong; nói rõ phần nào đã kiểm chứng, phần nào chưa.",
        "Báo rủi ro sớm, kể cả khi chưa chắc chắn.",
        "Không hứa quá khả năng; thiếu dữ liệu thì hỏi lại."]},
    "sang-tao": {"label": "Sáng tạo, dám thử", "emoji": "💡", "traits": [
        "Luôn đưa ít nhất hai phương án, kèm ưu/nhược điểm.",
        "Dám đề xuất cách làm mới, nhưng nêu rõ giả định đằng sau.",
        "Biến ý tưởng thành bước thử nhỏ, đo được."]},
    "ngan-gon": {"label": "Ngắn gọn, đi thẳng vấn đề", "emoji": "🎯", "traits": [
        "Kết luận trước, chi tiết sau; ưu tiên gạch đầu dòng.",
        "Số liệu đi kèm nguồn; bỏ câu chữ thừa.",
        "Một câu hỏi — một câu trả lời, không lan man."]},
    "than-thien": {"label": "Thân thiện, kiên nhẫn", "emoji": "🤝", "traits": [
        "Giọng ấm áp, lịch sự; giải thích dễ hiểu cho người không chuyên.",
        "Hỏi lại khi yêu cầu chưa rõ thay vì đoán.",
        "Ghi nhận công sức của đồng đội khi bàn giao."]},
    "phan-bien": {"label": "Phản biện, chất vấn giả định", "emoji": "🔍", "traits": [
        "Chỉ ra điểm yếu và giả định chưa kiểm chứng trong mọi kế hoạch.",
        "Đề xuất cách kiểm chứng trước khi làm lớn.",
        "Phản biện ý tưởng, tôn trọng con người."]},
}
DEFAULT_PERSONALITY = "tan-tuy"


def sha(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _has_rpc(runtime: Any) -> bool:
    return callable(getattr(runtime, "rpc", None))


def _rid_of(row: dict) -> str:
    return str(row.get("id") or row.get("agentId") or "")


# --------------------------------------------------------------------- render 5 file

def _ctx(db: Session, member: Member) -> dict:
    co = db.get(Company, member.company_id) if member.company_id else None
    dept = db.get(Department, member.department_id) if member.department_id else None
    mgr = db.get(Member, member.manager_id) if member.manager_id else None
    return {"company": co.name if co else "công ty", "department": dept.name if dept else "",
            "manager": mgr.name if mgr else ""}


def render_files(*, name: str, role: str, company: str, department: str, manager: str,
                 personality: str = DEFAULT_PERSONALITY, emoji: str = "", job_description: str = "",
                 manager_notes: str = "", monthly_budget: float | None = None,
                 hired_on: str | None = None) -> dict[str, str]:
    """5 file tiếng Việt từ hồ sơ. Vượt hạn mức ký tự → 422 (không cắt hộ)."""
    p = PERSONALITIES.get(personality) or PERSONALITIES[DEFAULT_PERSONALITY]
    emoji = emoji or p["emoji"]
    role = role or "Nhân sự AI"
    dept_line = f"Phòng {department}" if department else "Ban điều hành"
    boss = manager or "Ban điều hành"
    identity = (
        "# IDENTITY.md — Tôi là ai\n\n"
        f"- **Name:** {name}\n"
        f"- **Creature:** Nhân sự AI của {company}\n"
        f"- **Vibe:** {p['label']}\n"
        f"- **Emoji:** {emoji}\n\n"
        f"Chức danh: {role} · {dept_line} · {company}. Báo cáo cho: {boss}.\n")
    soul = (
        f"# SOUL.md — {name} là người thế nào\n\n"
        f"Bạn là **{name}**, {role} tại {company}. Tính cách: **{p['label']}**.\n\n"
        "## Cách làm việc\n" + "".join(f"- {t}\n" for t in p["traits"]) +
        "\n## Nguyên tắc chung\n"
        "- Trả lời bằng tiếng Việt, trừ khi được yêu cầu khác.\n"
        "- Không bịa số liệu; chưa chắc thì nói \"chưa xác minh\" và nêu cách kiểm chứng.\n"
        "- Việc vượt quyền, tốn tiền hoặc gửi ra ngoài công ty: hỏi người quản lý trước.\n"
        "- Giữ bí mật dữ liệu công ty.\n")
    duties = (job_description or "").strip()
    if duties and not duties.lstrip().startswith(("-", "*", "1.")):
        duties = "\n".join(f"- {line.strip()}" for line in duties.splitlines() if line.strip())
    duties = duties or (f"- Làm các việc được giao cho vị trí {role} trên bảng công việc.\n"
                        "- Chủ động đề xuất cải tiến trong phạm vi phòng ban.")
    budget_line = (f"Hạn mức chi phí: {monthly_budget:g} USD/tháng. Gần chạm hạn mức thì báo người quản lý."
                   if monthly_budget else "Chưa đặt hạn mức riêng; theo ngân sách phòng/công ty.")
    agents = (
        f"# AGENTS.md — Công việc của {name}\n\n"
        f"## Vai trò\n{role} · {dept_line} · {company}\nBáo cáo cho: {boss}\n\n"
        f"## Nhiệm vụ chính\n{duties}\n\n"
        "## Nhận và trả việc\n"
        "- Việc đến từ bảng công việc ClawCompany; mỗi việc là một phiên riêng.\n"
        "- Xong việc: tóm tắt kết quả, nêu cái đã kiểm chứng và cái chưa.\n"
        "- Bị chặn: báo ngay lý do và cần gì để đi tiếp.\n\n"
        f"## Ngân sách\n{budget_line}\n")
    notes = (manager_notes or "").strip() or ("- Báo cáo ngắn gọn, có số liệu và nguồn.\n"
                                              "- Hỏi lại khi yêu cầu chưa rõ.")
    user = f"# USER.md — Người quản lý muốn gì\n\nNgười quản lý: {boss}\n\n{notes}\n"
    memory = (
        "# MEMORY.md — Ký ức đã hợp nhất\n\n"
        f"- {hired_on or datetime.utcnow().date().isoformat()}: Được tuyển vào {company}"
        f"{' — ' + dept_line if department else ''} làm {role}.\n")
    files = {"IDENTITY.md": identity, "SOUL.md": soul, "AGENTS.md": agents, "USER.md": user,
             "MEMORY.md": memory}
    for fname, content in files.items():
        limit = ocp.USER_MD_MAX_CHARS if fname == "USER.md" else ocp.BOOTSTRAP_MAX_CHARS
        if len(content) > limit:
            raise HTTPException(422, f"{fname} dài {len(content)} ký tự, vượt hạn mức {limit}. Viết ngắn lại.")
    return files


# --------------------------------------------------------------------- tiện ích DB

def seat(db: Session, org_id: int, agent_id: int) -> tuple[Agent, Member]:
    agent = db.get(Agent, agent_id)
    member = db.get(Member, agent.member_id) if agent else None
    if not agent or not member or member.organization_id != org_id:
        raise HTTPException(404, "Không thấy nhân sự AI trong tổ chức")
    return agent, member


def _latest_job(db: Session, agent: Agent) -> AgentProvisioningJob | None:
    return (db.query(AgentProvisioningJob).filter(AgentProvisioningJob.agent_id == agent.id)
            .order_by(AgentProvisioningJob.id.desc()).first())


def hire_spec(db: Session, agent: Agent) -> dict:
    """Hồ sơ tuyển (tính cách, emoji, mô tả việc…) — lưu trong manifest của job tuyển."""
    job = _latest_job(db, agent)
    try:
        spec = json.loads(job.manifest_json or "{}") if job else {}
    except Exception:  # noqa: BLE001
        spec = {}
    return spec if isinstance(spec, dict) else {}


def _save_spec(db: Session, agent: Agent, spec: dict) -> None:
    job = _latest_job(db, agent)
    if job:
        job.manifest_json = json.dumps(spec, ensure_ascii=False); db.add(job)


def snapshots(db: Session, agent_id: int) -> dict[str, AgentFileSnapshot]:
    return {s.name: s for s in db.query(AgentFileSnapshot).filter(AgentFileSnapshot.agent_id == agent_id).all()}


def put_snapshot(db: Session, agent_id: int, name: str, content: str, *, source: str = "clawcompany",
                 user_id: int | None = None, hash_: str | None = None) -> AgentFileSnapshot:
    row = db.query(AgentFileSnapshot).filter_by(agent_id=agent_id, name=name).first()
    if row is None:
        row = AgentFileSnapshot(agent_id=agent_id, name=name)
    row.content = content; row.hash = hash_ or sha(content); row.source = source
    row.updated_by_user_id = user_id; row.updated_at = datetime.utcnow()
    db.add(row); db.commit()
    return row


def _unique_runtime_id(db: Session, name: str) -> str:
    base = team_svc.slug_ascii(name, 28)
    for _ in range(20):
        rid = f"{base}-{secrets.token_hex(2)}"
        if not db.query(Agent.id).filter(Agent.runtime_agent_id == rid).first():
            return rid
    raise HTTPException(500, "Không sinh được mã agent duy nhất")


async def _get_file(runtime: Any, rid: str, name: str) -> dict:
    payload = await runtime.rpc(ocp.M_AGENTS_FILES_GET, {"agentId": rid, "name": name})
    rec = payload.get("file") if isinstance(payload.get("file"), dict) else payload
    content = rec.get("content") or ""
    missing = bool(rec.get("missing"))
    return {"missing": missing, "content": content,
            "hash": "" if missing else (rec.get("hash") or sha(content))}


async def _set_file(runtime: Any, rid: str, name: str, content: str, expected_hash: str | None = None) -> str:
    params: dict[str, Any] = {"agentId": rid, "name": name, "content": content}
    if expected_hash:
        params["expectedHash"] = expected_hash
    payload = await runtime.rpc(ocp.M_AGENTS_FILES_SET, params)
    rec = payload.get("file") if isinstance(payload.get("file"), dict) else {}
    return rec.get("hash") or sha(content)


def record_file_write(db: Session, org_id: int, agent_id: int, name: str, content: str, hash_: str,
                      user_id: int | None) -> None:
    """Gọi sau PUT /agents/{id}/files/{name} thành công: bản ClawCompany = bản vừa ghi."""
    agent, _ = seat(db, org_id, agent_id)
    if name in SEAT_FILES:
        put_snapshot(db, agent.id, name, content, user_id=user_id, hash_=hash_ or sha(content))


async def _agents_update(db: Session, runtime: Any, agent: Agent, upd: dict, user_id: int | None) -> dict:
    """``agents.update`` + nhận phần IDENTITY.md do chính gateway viết lại.

    Đo trên 2026.9.8: ``agents.update {name|emoji|avatar}`` tự ghi lại IDENTITY.md
    (gộp dòng Name/Emoji vào file hiện có). Nếu không nhận bản đó làm bản
    ClawCompany, chính thao tác đổi tên của ta bị báo là "sửa tay trên gateway".
    Chỉ nhận khi trước lúc gọi, file trên gateway còn khớp bản ClawCompany.
    """
    absorb = bool({"name", "emoji", "avatar"} & set(upd))
    snap = snapshots(db, agent.id).get("IDENTITY.md") if absorb else None
    before = None
    if snap is not None:
        try:
            before = await _get_file(runtime, agent.runtime_agent_id, "IDENTITY.md")
        except Exception:  # noqa: BLE001
            before = None
    res = await runtime.rpc(ocp.M_AGENTS_UPDATE, upd)
    if snap is not None and before is not None and not before["missing"] and before["hash"] == snap.hash:
        after = await _get_file(runtime, agent.runtime_agent_id, "IDENTITY.md")
        if not after["missing"] and after["hash"] != snap.hash:
            spec = hire_spec(db, agent)
            gen = dict(spec.get("generated") or {})
            if gen.get("IDENTITY.md") == snap.hash:      # chưa chỉnh tay → vẫn là bản "sinh"
                gen["IDENTITY.md"] = after["hash"]; spec["generated"] = gen; _save_spec(db, agent, spec)
            put_snapshot(db, agent.id, "IDENTITY.md", after["content"], source=snap.source,
                         user_id=user_id, hash_=after["hash"])
    return res if isinstance(res, dict) else {}


# --------------------------------------------------------------------- tuỳ chọn & danh sách

async def hire_options(db: Session, org_id: int, runtime: Any) -> dict:
    companies = db.query(Company).filter(Company.organization_id == org_id).order_by(Company.id).all()
    cids = [c.id for c in companies]
    depts = (db.query(Department).filter(Department.company_id.in_(cids)).order_by(Department.id).all()
             if cids else [])
    members = (db.query(Member).filter(Member.organization_id == org_id,
                                       Member.status.notin_(("retired", "removed")))
               .order_by(Member.name).all())
    models, model_error = [], ""
    if _has_rpc(runtime):
        try:
            res = await runtime.rpc(ocp.M_MODELS_LIST, {})
            for m in res.get("models") or []:
                mid = str(m.get("id") or "")
                full = mid if ("/" in mid or not m.get("provider")) else f"{m['provider']}/{mid}"
                if mid:
                    models.append({"id": full, "name": m.get("name") or full,
                                   "default": "default" in (m.get("tags") or []),
                                   "available": m.get("available", True)})
        except Exception as exc:  # noqa: BLE001
            model_error = str(exc)
    return {
        "companies": [{"id": c.id, "name": c.name} for c in companies],
        "departments": [{"id": d.id, "company_id": d.company_id, "name": d.name,
                         "head_member_id": d.head_member_id} for d in depts],
        "managers": [{"id": m.id, "name": m.name, "member_type": m.member_type, "role": m.role,
                      "company_id": m.company_id, "department_id": m.department_id} for m in members],
        "models": models, "models_error": model_error,
        "personalities": [{"key": k, "label": v["label"], "emoji": v["emoji"], "traits": v["traits"]}
                          for k, v in PERSONALITIES.items()],
        "default_personality": DEFAULT_PERSONALITY,
        "limits": {"USER.md": ocp.USER_MD_MAX_CHARS, "other": ocp.BOOTSTRAP_MAX_CHARS},
    }


async def roster(db: Session, org_id: int, runtime: Any, company_id: int | None = None) -> dict:
    """Danh sách nhân sự AI (DB) đối chiếu với roster gateway."""
    q = (db.query(Agent, Member).join(Member, Member.id == Agent.member_id)
         .filter(Member.organization_id == org_id))
    if company_id:
        q = q.filter(Member.company_id == company_id)
    rows = q.order_by(Member.company_id, Member.department_id, Member.name).all()
    gw: dict[str, dict] = {}
    gw_error = ""
    try:
        for a in await runtime.list_agents():
            gw[_rid_of(a)] = a
    except Exception as exc:  # noqa: BLE001
        gw_error = str(exc)
    cos = {c.id: c.name for c in db.query(Company).filter(Company.organization_id == org_id).all()}
    depts = {d.id: d for d in db.query(Department).filter(Department.company_id.in_(list(cos) or [0])).all()}
    names = {m.id: m.name for m in db.query(Member).filter(Member.organization_id == org_id).all()}
    items = []
    for agent, m in rows:
        g = gw.get(agent.runtime_agent_id)
        d = depts.get(m.department_id)
        items.append({
            "agent_id": agent.id, "member_id": m.id, "name": m.name, "role": m.role,
            "company_id": m.company_id, "company": cos.get(m.company_id, ""),
            "department_id": m.department_id, "department": d.name if d else "",
            "is_head": bool(d and d.head_member_id == m.id),
            "manager_id": m.manager_id, "manager": names.get(m.manager_id, "") if m.manager_id else "",
            "lifecycle": agent.lifecycle, "status": m.status, "model": agent.model,
            "runtime_agent_id": agent.runtime_agent_id,
            "on_gateway": (g is not None) if not gw_error else None,
            "gateway_model": (g or {}).get("model"), "sessions": (g or {}).get("sessions", 0),
            "running": bool((g or {}).get("active")),
        })
    counts: dict[str, int] = {}
    for it in items:
        counts[it["lifecycle"]] = counts.get(it["lifecycle"], 0) + 1
    # Agent trên gateway mà không seat nào (của bất kỳ tổ chức nào) gắn vào: chỉ
    # báo số lượng, không lộ id của tổ chức khác.
    bound = {r for (r,) in db.query(Agent.runtime_agent_id).all()}
    unbound = sum(1 for k in gw if k not in bound and k != "main") if not gw_error else None
    return {"items": items, "counts": counts, "gateway_error": gw_error, "unbound_on_gateway": unbound}


# --------------------------------------------------------------------- tuyển

async def hire(db: Session, principal: Principal, org_id: int, runtime: Any, data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "Cần tên nhân sự AI")
    role = (data.get("role") or "").strip() or "Nhân sự AI"
    personality = data.get("personality") or DEFAULT_PERSONALITY
    if personality not in PERSONALITIES:
        raise HTTPException(422, f"Tính cách phải là một trong: {', '.join(PERSONALITIES)}")
    company_id, department_id, manager_id = team_svc._check_placement(
        db, org_id, data.get("company_id"), data.get("department_id"), data.get("manager_member_id"))
    if not company_id:
        raise HTTPException(422, "Cần chọn công ty cho nhân sự AI")
    dept = db.get(Department, department_id) if department_id else None
    if manager_id is None and dept is not None and dept.head_member_id:
        manager_id = dept.head_member_id            # mặc định báo cáo trưởng phòng
    budget = data.get("monthly_budget")
    budget = float(budget) if budget not in (None, "") else None
    if budget is not None and budget < 0:
        raise HTTPException(422, "Ngân sách không được âm")
    tools = data.get("tools") or {}
    from app.services.company_mcp import TOOLS
    for tool, level in tools.items():
        if tool not in TOOLS:
            raise HTTPException(422, f"Không có tool {tool}")
        if level not in perms.TOOL_LEVELS:
            raise HTTPException(422, f"Mức quyền {level} không hợp lệ cho {tool}")
    model = (data.get("model") or "").strip()
    co = db.get(Company, company_id)
    mgr = db.get(Member, manager_id) if manager_id else None
    emoji = (data.get("emoji") or "").strip() or PERSONALITIES[personality]["emoji"]
    # Render trước khi tạo gì: file quá dài thì từ chối sớm, không để lại seat dở.
    files = render_files(name=name, role=role, company=co.name, department=dept.name if dept else "",
                         manager=mgr.name if mgr else "", personality=personality, emoji=emoji,
                         job_description=data.get("job_description") or "",
                         manager_notes=data.get("manager_notes") or "", monthly_budget=budget)
    rid = _unique_runtime_id(db, name)
    spec = {"personality": personality, "emoji": emoji,
            "job_description": data.get("job_description") or "",
            "manager_notes": data.get("manager_notes") or "", "monthly_budget": budget,
            "hired_via": "m3_wizard"}
    job = await provision_agent(db, organization_id=org_id, company_id=company_id, department_id=department_id,
                                name=name, role=role, model=model, runtime_agent_id=rid,
                                manager_member_id=manager_id, manifest=spec,
                                requested_by_user_id=principal.user_id)
    out: dict[str, Any] = {"job_id": job.id, "status": job.status, "agent_id": job.agent_id,
                           "member_id": job.member_id, "runtime_agent_id": rid, "manager_member_id": manager_id,
                           "files": [], "warnings": []}
    if job.status == "failed":
        raise HTTPException(502, {"message": f"Gateway lỗi khi tạo agent: {job.error}", **out})
    agent = db.get(Agent, job.agent_id)
    member = db.get(Member, job.member_id)
    if budget:
        env = BudgetEnvelope(organization_id=org_id, company_id=company_id, name=f"Hạn mức · {name}",
                             amount_limit=budget, scope_type="member", scope_id=member.id,
                             period="monthly", warn_pct=80)
        db.add(env); db.commit(); out["budget_envelope_id"] = env.id
    for tool, level in tools.items():
        perms.set_level(db, org_id, tool, level, member_id=member.id)
    db.commit()
    if job.status != "ready" or not _has_rpc(runtime):
        out["warnings"].append(
            (f"Gateway chưa tạo agent ({job.error}). " if job.status != "ready" else
             "Runtime hiện tại không ghi được file. ") +
            "Hồ sơ đã lưu; 5 file sẽ lên gateway khi gắn được runtime — dùng \"Đồng bộ lại → Đẩy lên\".")
        for fname, content in files.items():   # giữ bản ClawCompany để đẩy lên sau
            put_snapshot(db, agent.id, fname, content, user_id=principal.user_id)
            out["files"].append({"name": fname, "written": False})
        spec["generated"] = {f: sha(c) for f, c in files.items()}
        _save_spec(db, agent, spec); db.commit()
        return out
    upd: dict[str, Any] = {"agentId": rid, "name": name, "emoji": emoji}
    try:
        await runtime.rpc(ocp.M_AGENTS_UPDATE, upd)
    except Exception as exc:  # noqa: BLE001
        out["warnings"].append(f"agents.update (tên/emoji) lỗi: {exc}")
    if not model:
        # Không chọn model → gateway dùng agents.defaults. Ghi lại model thật đang
        # chạy, để cột agents.model không trống (và không lệch) ngay từ đầu.
        try:
            entry = next((a for a in await runtime.list_agents() if _rid_of(a) == rid), None)
            live = str((entry or {}).get("model") or "")
            if live:
                agent.model = live; db.add(agent); db.commit(); out["model"] = live
        except Exception:  # noqa: BLE001
            pass
    for fname, content in files.items():
        try:
            h = await _set_file(runtime, rid, fname, content)
            put_snapshot(db, agent.id, fname, content, user_id=principal.user_id, hash_=h)
            out["files"].append({"name": fname, "written": True, "hash": h, "chars": len(content)})
        except Exception as exc:  # noqa: BLE001
            put_snapshot(db, agent.id, fname, content, user_id=principal.user_id)
            out["files"].append({"name": fname, "written": False, "error": str(exc)})
            out["warnings"].append(f"Ghi {fname} lỗi: {exc}")
    spec["generated"] = {f["name"]: f["hash"] for f in out["files"] if f.get("written")}
    _save_spec(db, agent, spec); db.commit()
    log_event(db, org_id, "agent.hr.hire", "agents", agent.id, actor_name=f"user:{principal.user_id}",
              payload={"runtime_agent_id": rid, "files": [f["name"] for f in out["files"] if f.get("written")],
                       "personality": personality, "budget": budget})
    out["status"] = agent.lifecycle
    return out


# --------------------------------------------------------------------- sửa hồ sơ (2 chiều)

async def _regen(db: Session, runtime: Any, agent: Agent, member: Member, names: tuple[str, ...],
                 user_id: int | None, force: tuple[str, ...] = ()) -> dict[str, dict]:
    """Sinh lại file từ hồ sơ. Hai chốt, theo thứ tự:

    * file đã được chỉnh tay trên UI sau lần sinh gần nhất (hash bản ClawCompany
      ≠ hash bản đã sinh) → giữ nguyên, trừ khi người dùng chọn sinh lại (``force``);
    * gateway đã bị sửa ngoài ClawCompany → không ghi đè, báo lệch.
    """
    spec = hire_spec(db, agent)
    generated = dict(spec.get("generated") or {})
    files = render_files(name=member.name, role=member.role,
                         personality=spec.get("personality") or DEFAULT_PERSONALITY,
                         emoji=spec.get("emoji") or "", job_description=spec.get("job_description") or "",
                         manager_notes=spec.get("manager_notes") or "",
                         monthly_budget=spec.get("monthly_budget"), **_ctx(db, member))
    snaps = snapshots(db, agent.id)
    result: dict[str, dict] = {}
    for fname in names:
        content = files[fname]
        snap = snaps.get(fname)
        if (snap is not None and fname not in force and generated.get(fname)
                and snap.hash != generated[fname]):
            result[fname] = {"written": False, "reason": "customized",
                             "message": f"{fname} đã được chỉnh tay sau lần sinh trước — giữ nguyên. "
                                        "Chọn \"Sinh lại từ hồ sơ\" nếu muốn thay."}
            continue
        if not _has_rpc(runtime) or agent.lifecycle == "runtime_missing":
            put_snapshot(db, agent.id, fname, content, user_id=user_id)
            generated[fname] = sha(content)
            result[fname] = {"written": False, "reason": "saved_only",
                             "message": "Chỉ lưu bản ClawCompany (agent chưa có trên gateway)."}
            continue
        try:
            cur = await _get_file(runtime, agent.runtime_agent_id, fname)
        except Exception as exc:  # noqa: BLE001
            result[fname] = {"written": False, "reason": "read_failed", "message": f"Không đọc được gateway: {exc}"}
            continue
        if snap is not None and not cur["missing"] and cur["hash"] != snap.hash:
            result[fname] = {"written": False, "reason": "edited_on_gateway",
                             "message": f"{fname} đã bị sửa trên gateway — không ghi đè. "
                                        "Mở mục Lệch để chọn chiều đồng bộ."}
            continue
        if not cur["missing"] and cur["hash"] == sha(content):
            put_snapshot(db, agent.id, fname, content, user_id=user_id, hash_=cur["hash"])
            generated[fname] = cur["hash"]
            result[fname] = {"written": False, "reason": "unchanged"}
            continue
        try:
            h = await _set_file(runtime, agent.runtime_agent_id, fname, content,
                                expected_hash=None if cur["missing"] else cur["hash"])
        except Exception as exc:  # noqa: BLE001
            result[fname] = {"written": False, "reason": "write_failed", "message": f"Ghi {fname} lỗi: {exc}"}
            continue
        put_snapshot(db, agent.id, fname, content, user_id=user_id, hash_=h)
        generated[fname] = h
        result[fname] = {"written": True, "hash": h}
    spec["generated"] = generated
    _save_spec(db, agent, spec); db.commit()
    return result


async def update_hr(db: Session, principal: Principal, org_id: int, runtime: Any, agent_id: int,
                    data: dict, fields_set: set[str]) -> dict:
    force = tuple(data.get("regenerate_files") or ())
    bad = [f for f in force if f not in SEAT_FILES or f == "MEMORY.md"]
    if bad:
        raise HTTPException(422, f"Không sinh lại được: {', '.join(bad)} (MEMORY.md là ký ức của agent)")
    agent, member = seat(db, org_id, agent_id)
    if agent.lifecycle == "retired":
        raise HTTPException(409, "Nhân sự đã nghỉ việc — không sửa hồ sơ được")
    actor = f"user:{principal.user_id}"
    changed: list[str] = []
    warnings: list[str] = []
    spec = hire_spec(db, agent)
    fields_set = set(fields_set)
    if "name" in fields_set and (data.get("name") or "").strip() and data["name"].strip() != member.name:
        member.name = data["name"].strip(); changed.append("name")
    if "role" in fields_set and (data.get("role") or "").strip() and data["role"].strip() != (member.role or ""):
        member.role = data["role"].strip(); changed.append("role")
    if "department_id" in fields_set and data.get("department_id") != member.department_id:
        dep_id = data.get("department_id")
        new_dept = db.get(Department, dep_id) if dep_id else None
        if dep_id and (not new_dept or new_dept.company_id != member.company_id):
            raise HTTPException(422, "Phòng ban phải thuộc cùng công ty")
        old_dept = db.get(Department, member.department_id) if member.department_id else None
        if old_dept and old_dept.head_member_id == member.id:
            old_dept.head_member_id = None; db.add(old_dept)
        member.department_id = dep_id; changed.append("department")
        if ("manager_member_id" not in fields_set and new_dept and new_dept.head_member_id
                and new_dept.head_member_id != member.id):
            data["manager_member_id"] = new_dept.head_member_id; fields_set.add("manager_member_id")
    for key in ("personality", "emoji", "job_description", "manager_notes"):
        if key in fields_set and data.get(key) is not None and data.get(key) != spec.get(key):
            if key == "personality" and data[key] not in PERSONALITIES:
                raise HTTPException(422, f"Tính cách phải là một trong: {', '.join(PERSONALITIES)}")
            spec[key] = data[key]; changed.append(key)
    team_svc._bump(member); db.add(member); _save_spec(db, agent, spec); db.commit()
    if "manager_member_id" in fields_set and data.get("manager_member_id") != member.manager_id:
        team_svc.set_manager(db, org_id, member, data.get("manager_member_id"), actor=actor)
        changed.append("manager")
    gateway: dict[str, Any] = {}
    new_model = (data.get("model") or "").strip() if "model" in fields_set else ""
    model_changed = bool(new_model) and new_model != (agent.model or "")
    on_gateway = _has_rpc(runtime) and agent.lifecycle != "runtime_missing"
    if on_gateway and ({"name", "emoji"} & set(changed) or model_changed):
        upd: dict[str, Any] = {"agentId": agent.runtime_agent_id}
        if "name" in changed:
            upd["name"] = member.name
        if "emoji" in changed and spec.get("emoji"):
            upd["emoji"] = spec["emoji"]
        if model_changed:
            upd["model"] = new_model
        try:
            gateway["agents.update"] = await _agents_update(db, runtime, agent, upd, principal.user_id)
            gateway["sent"] = sorted(k for k in upd if k != "agentId")
            if model_changed:
                agent.model = new_model; changed.append("model")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Gateway từ chối agents.update: {exc}")
            gateway["error"] = str(exc)
    elif model_changed:
        agent.model = new_model; changed.append("model")
        warnings.append("Chỉ đổi model trong ClawCompany — agent chưa có trên gateway.")
    db.add(agent); db.commit()
    touched = set(changed)
    regen: tuple[str, ...] = ()
    if touched & {"name", "role", "department", "manager", "emoji", "personality"}:
        regen += ("IDENTITY.md",)
    if touched & {"name", "role", "personality"}:
        regen += ("SOUL.md",)
    if touched & {"name", "role", "department", "manager", "job_description"}:
        regen += ("AGENTS.md",)
    if touched & {"manager", "manager_notes"}:
        regen += ("USER.md",)
    regen += tuple(f for f in force if f not in regen)
    files = await _regen(db, runtime, agent, member, regen, principal.user_id, force=force) if regen else {}
    warnings += [r["message"] for r in files.values()
                 if r.get("reason") in ("edited_on_gateway", "customized", "write_failed")]
    if changed or force:
        log_event(db, org_id, "agent.hr.update", "agents", agent.id, actor_name=actor,
                  payload={"changed": changed, "files": {k: v.get("written") for k, v in files.items()}})
    return {"agent_id": agent.id, "changed": changed, "gateway": gateway, "files": files, "warnings": warnings}


# --------------------------------------------------------------------- lệch & đồng bộ

async def drift(db: Session, org_id: int, runtime: Any, agent_id: int) -> dict:
    agent, member = seat(db, org_id, agent_id)
    rid = agent.runtime_agent_id
    out: dict[str, Any] = {"agent_id": agent.id, "runtime_agent_id": rid, "lifecycle": agent.lifecycle,
                           "checked_at": datetime.utcnow().isoformat() + "Z", "fields": [], "files": [],
                           "warnings": [], "drift_count": 0}
    snaps = snapshots(db, agent.id)
    if not _has_rpc(runtime):
        out.update(roster_match=None, in_sync=None)
        out["warnings"].append("Runtime hiện tại không đọc được gateway.")
        return out
    try:
        entry = next((a for a in await runtime.list_agents() if _rid_of(a) == rid), None)
    except Exception as exc:  # noqa: BLE001
        out.update(roster_match=None, in_sync=None)
        out["warnings"].append(f"Không đọc được roster: {exc}")
        return out
    out["roster_match"] = entry is not None
    if entry is None:
        out["in_sync"] = agent.lifecycle == "retired"
        out["files"] = [{"name": n, "status": "no_agent", "has_snapshot": n in snaps,
                         "counts_as_drift": False} for n in SEAT_FILES]
        if agent.lifecycle != "retired":
            out["drift_count"] = 1
            out["warnings"].append(f"Gateway không có agent `{rid}` — dùng \"Đẩy lên\" sau khi gắn runtime.")
        return out
    try:
        ident = await runtime.rpc(ocp.M_AGENT_IDENTITY_GET, {"agentId": rid})
    except Exception:  # noqa: BLE001
        ident = {}
    gw_name = str((ident or {}).get("name") or entry.get("name") or "")
    gw_model = str(entry.get("model") or "")
    out["fields"] = [
        {"field": "name", "label": "Tên", "clawcompany": member.name, "gateway": gw_name,
         "match": (not gw_name) or gw_name == member.name},
        {"field": "model", "label": "Model", "clawcompany": agent.model or "", "gateway": gw_model,
         "match": (not agent.model) or (not gw_model) or agent.model == gw_model},
    ]
    drifted = [f for f in out["fields"] if not f["match"]]
    for name in SEAT_FILES:
        snap = snaps.get(name)
        try:
            cur = await _get_file(runtime, rid, name)
        except Exception as exc:  # noqa: BLE001
            out["files"].append({"name": name, "status": "error", "error": str(exc), "counts_as_drift": False})
            continue
        if snap is None:
            status = "absent" if cur["missing"] else "untracked"
        elif cur["missing"]:
            status = "missing_on_gateway"
        elif cur["hash"] == snap.hash:
            status = "in_sync"
        else:
            status = "edited_on_gateway"
        counts = status in ("missing_on_gateway", "edited_on_gateway") and name not in AGENT_OWNED_FILES
        rec = {"name": name, "status": status, "counts_as_drift": counts, "agent_owned": name in AGENT_OWNED_FILES,
               "gateway_hash": cur["hash"], "clawcompany_hash": snap.hash if snap else "",
               "clawcompany_updated_at": (snap.updated_at.isoformat() + "Z") if snap and snap.updated_at else None,
               "clawcompany_source": snap.source if snap else None}
        if status == "edited_on_gateway":
            rec["gateway_content"] = cur["content"]
            rec["clawcompany_content"] = snap.content
        out["files"].append(rec)
        if counts:
            drifted.append(rec)
    out["in_sync"] = not drifted
    out["drift_count"] = len(drifted)
    return out


async def resync(db: Session, principal: Principal, org_id: int, runtime: Any, agent_id: int, *,
                 direction: str, files: list[str] | None = None, fields: list[str] | None = None) -> dict:
    if direction not in ("push", "pull"):
        raise HTTPException(422, "direction phải là push (đẩy bản ClawCompany lên) hoặc pull (nhận bản gateway)")
    agent, member = seat(db, org_id, agent_id)
    if agent.lifecycle == "retired":
        raise HTTPException(409, "Nhân sự đã nghỉ việc — không đồng bộ")
    bad = [f for f in (files or []) if f not in SEAT_FILES]
    if bad:
        raise HTTPException(422, f"File không hợp lệ: {', '.join(bad)}")
    before = await drift(db, org_id, runtime, agent_id)
    if not before.get("roster_match"):
        raise HTTPException(409, {"message": "Gateway không có agent này — chưa đồng bộ được", "drift": before})
    by_name = {f["name"]: f for f in before["files"]}
    if files is None:
        want = (("edited_on_gateway", "missing_on_gateway") if direction == "push"
                else ("edited_on_gateway", "untracked"))
        files = [n for n, f in by_name.items() if f["status"] in want]
    if fields is None:
        fields = [f["field"] for f in before["fields"] if not f["match"]]
    done: list[dict] = []
    snaps = snapshots(db, agent.id)
    for name in files:
        st = by_name.get(name, {})
        if direction == "push":
            snap = snaps.get(name)
            if not snap:
                done.append({"file": name, "ok": False, "reason": "ClawCompany chưa có bản của file này"}); continue
            try:
                h = await _set_file(runtime, agent.runtime_agent_id, name, snap.content,
                                    expected_hash=st.get("gateway_hash") or None)
                put_snapshot(db, agent.id, name, snap.content, user_id=principal.user_id, hash_=h)
                done.append({"file": name, "ok": True, "direction": "push"})
            except Exception as exc:  # noqa: BLE001
                done.append({"file": name, "ok": False, "reason": str(exc)})
        else:
            cur = await _get_file(runtime, agent.runtime_agent_id, name)
            if cur["missing"]:
                done.append({"file": name, "ok": False, "reason": "gateway không có file này"}); continue
            put_snapshot(db, agent.id, name, cur["content"], source="gateway_accepted",
                         user_id=principal.user_id, hash_=cur["hash"])
            done.append({"file": name, "ok": True, "direction": "pull"})
    fmap = {f["field"]: f for f in before["fields"]}
    for field in fields:
        f = fmap.get(field)
        if not f or field not in ("name", "model"):
            continue
        if direction == "pull":
            if field == "name" and f["gateway"]:
                member.name = f["gateway"]; team_svc._bump(member); db.add(member)
            if field == "model" and f["gateway"]:
                agent.model = f["gateway"]; db.add(agent)
            db.commit(); done.append({"field": field, "ok": True, "direction": "pull"})
            continue
        upd: dict[str, Any] = {"agentId": agent.runtime_agent_id}
        if field == "name":
            upd["name"] = member.name
        elif agent.model:
            upd["model"] = agent.model
        try:
            await _agents_update(db, runtime, agent, upd, principal.user_id)
            if field == "name" and "IDENTITY.md" not in files:
                await _regen(db, runtime, agent, member, ("IDENTITY.md",), principal.user_id)
            done.append({"field": field, "ok": True, "direction": "push"})
        except Exception as exc:  # noqa: BLE001
            done.append({"field": field, "ok": False, "reason": str(exc)})
    log_event(db, org_id, "agent.hr.resync", "agents", agent.id, actor_name=f"user:{principal.user_id}",
              payload={"direction": direction, "done": done})
    return {"direction": direction, "done": done, "drift": await drift(db, org_id, runtime, agent_id)}


# --------------------------------------------------------------------- vòng đời

def _is_main(row: dict) -> bool:
    return bool(row.get("isMain")) or str(row.get("key") or "").endswith(":main")


async def agent_sessions(runtime: Any, rid: str) -> list[dict]:
    res = await runtime.rpc(ocp.M_SESSIONS_LIST, {"limit": 500})
    rows = res.get("sessions") or res.get("items") or []
    return [r for r in rows if isinstance(r, dict) and
            str(r.get("agentId") or ocp.agent_id_from_session_key(str(r.get("key") or "")) or "") == rid]


async def lifecycle(db: Session, principal: Principal, org_id: int, runtime: Any, agent_id: int, *,
                    action: str, reassign_to_member_id: int | None = None,
                    remove_from_gateway: bool = True, reason: str = "") -> dict:
    agent, member = seat(db, org_id, agent_id)
    out: dict[str, Any] = {"agent_id": agent.id, "action": action, "previous": agent.lifecycle, "warnings": []}
    if action == "pause":
        if agent.lifecycle == "retired":
            raise HTTPException(409, "Nhân sự đã nghỉ việc")
        if agent.lifecycle == "paused":
            return {**out, "lifecycle": "paused", "noop": True}
        out["aborted"] = await _abort_active(db, runtime, agent, member, out["warnings"])
        agent.lifecycle = "paused"; member.status = "paused"
    elif action == "resume":
        if agent.lifecycle != "paused":
            raise HTTPException(409, f"Chỉ tiếp tục được nhân sự đang tạm dừng (hiện: {agent.lifecycle})")
        on_gw = None
        try:
            on_gw = any(_rid_of(a) == agent.runtime_agent_id for a in await runtime.list_agents())
        except Exception as exc:  # noqa: BLE001
            out["warnings"].append(f"Không kiểm được roster: {exc}")
        agent.lifecycle = "runtime_missing" if on_gw is False else "active"
        member.status = "pending_runtime" if on_gw is False else "active"
        if on_gw is False:
            out["warnings"].append("Gateway không còn agent này — để ở trạng thái chờ gắn runtime.")
    elif action == "retire":
        if agent.lifecycle == "retired":
            return {**out, "lifecycle": "retired", "noop": True}
        out.update(await _retire(db, principal, org_id, runtime, agent, member,
                                 reassign_to_member_id=reassign_to_member_id,
                                 remove_from_gateway=remove_from_gateway, warnings=out["warnings"]))
        agent.lifecycle = "retired"; member.status = "retired"
    else:
        raise HTTPException(422, "action phải là pause, resume hoặc retire")
    team_svc._bump(member); db.add_all([agent, member]); db.commit()
    payload = {k: v for k, v in out.items() if k != "warnings"}
    payload["reason"] = reason
    log_event(db, org_id, f"agent.hr.{action}", "agents", agent.id, actor_name=f"user:{principal.user_id}",
              payload=payload)
    out["lifecycle"] = agent.lifecycle
    return out


async def _abort_active(db: Session, runtime: Any, agent: Agent, member: Member, warnings: list) -> dict:
    """Dừng lượt đang chạy (task về 'todo') + abort phiên đang chạy trên gateway."""
    from app.services import agent_dispatch
    aborted_tasks = []
    for t in db.query(Task).filter(Task.assignee_member_id == member.id, Task.status == "in_progress").all():
        try:
            await agent_dispatch.abort_task(db, t, back_to="todo")
            aborted_tasks.append(t.id)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Task #{t.id}: {exc}")
    aborted_sessions = 0
    if _has_rpc(runtime) and agent.lifecycle != "runtime_missing":
        try:
            for s in await agent_sessions(runtime, agent.runtime_agent_id):
                if s.get("hasActiveRun"):
                    await runtime.rpc(ocp.M_SESSIONS_ABORT, {"key": s["key"], "agentId": agent.runtime_agent_id})
                    aborted_sessions += 1
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Abort phiên trên gateway lỗi: {exc}")
    return {"tasks": aborted_tasks, "sessions": aborted_sessions}


async def _retire(db: Session, principal: Principal, org_id: int, runtime: Any, agent: Agent, member: Member, *,
                  reassign_to_member_id: int | None, remove_from_gateway: bool, warnings: list) -> dict:
    target = None
    if reassign_to_member_id:
        target = db.get(Member, reassign_to_member_id)
        tgt_agent = db.query(Agent).filter(Agent.member_id == target.id).first() if target else None
        if (not target or target.organization_id != org_id or target.id == member.id
                or target.company_id != member.company_id or target.status in ("retired", "removed")
                or (tgt_agent is not None and tgt_agent.lifecycle in BLOCKED_LIFECYCLES)):
            raise HTTPException(422, "Người nhận việc phải đang làm, cùng công ty và không phải chính nhân sự này")
    result: dict[str, Any] = {"aborted": await _abort_active(db, runtime, agent, member, warnings)}
    # 1) việc đang mở → người nhận, hoặc trả về phòng ban để trưởng phòng giao lại
    moved = []
    for t in db.query(Task).filter(Task.assignee_member_id == member.id, Task.status.in_(OPEN_STATUSES)).all():
        t.assignee_member_id = target.id if target else None
        if not target and not t.assignee_department_id and member.department_id:
            t.assignee_department_id = member.department_id
        team_svc._bump(t); db.add(t); moved.append(t.id)
    result["tasks_reassigned"] = {"count": len(moved), "task_ids": moved,
                                  "to": target.name if target else "phòng ban (chờ giao lại)"}
    # 2) chức trưởng phòng, người báo cáo, API key, hạn mức riêng
    heads = db.query(Department).filter(Department.head_member_id == member.id).all()
    for d in heads:
        d.head_member_id = None; db.add(d)
    reports = db.query(Member).filter(Member.manager_id == member.id).all()
    for r in reports:
        r.manager_id = member.manager_id; team_svc._bump(r); db.add(r)
    keys = db.query(APIKey).filter(APIKey.member_id == member.id, APIKey.is_active.is_(True)).all()
    for k in keys:
        k.is_active = False; db.add(k)
    envs = db.query(BudgetEnvelope).filter(BudgetEnvelope.scope_type == "member",
                                           BudgetEnvelope.scope_id == member.id,
                                           BudgetEnvelope.status == "active").all()
    for e in envs:
        e.status = "closed"; db.add(e)
    db.commit()
    result.update(departments_unheaded=[d.id for d in heads], reports_moved=len(reports),
                  api_keys_disabled=len(keys), budgets_closed=len(envs))
    # 3) gateway: lưu 5 file → dọn phiên → (mặc định) xoá agent, rồi đếm lại
    gw: dict[str, Any] = {"sessions_before": None, "sessions_after": None, "agent_removed": False,
                          "files_archived": []}
    if _has_rpc(runtime) and agent.lifecycle != "runtime_missing":
        rid = agent.runtime_agent_id
        for name in SEAT_FILES:
            try:
                cur = await _get_file(runtime, rid, name)
                if not cur["missing"]:
                    put_snapshot(db, agent.id, name, cur["content"], source="archived_on_retire",
                                 user_id=principal.user_id, hash_=cur["hash"])
                    gw["files_archived"].append(name)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Lưu {name} lỗi: {exc}")
        try:
            sessions = await agent_sessions(runtime, rid)
            gw["sessions_before"] = len(sessions)
            deleted = reset = 0
            for s in sessions:
                if _is_main(s):
                    continue
                await runtime.rpc("sessions.delete", {"key": s["key"], "agentId": rid, "deleteTranscript": True})
                deleted += 1
            if remove_from_gateway:
                # Phiên main không xoá riêng được ("Cannot delete the main session");
                # agents.delete dọn workspace + phiên + transcript vào thùng rác của gateway.
                await runtime.rpc(ocp.M_AGENTS_DELETE, {"agentId": rid, "deleteFiles": True})
                gw["agent_removed"] = True
            else:
                for s in sessions:
                    if _is_main(s):
                        await runtime.rpc("sessions.reset", {"key": s["key"], "agentId": rid, "reason": "reset"})
                        reset += 1
            gw.update(sessions_deleted=deleted, main_reset=reset)
            remaining = await agent_sessions(runtime, rid)
            if not remove_from_gateway:   # main vừa reset = phiên rỗng mới, không tính là còn sót
                remaining = [s for s in remaining if not _is_main(s)]
            gw["sessions_after"] = len(remaining)
            if remaining:
                warnings.append(f"Còn {len(remaining)} phiên trên gateway chưa dọn được")
            if remove_from_gateway:
                gw["still_on_roster"] = any(_rid_of(a) == rid for a in await runtime.list_agents())
        except Exception as exc:  # noqa: BLE001
            gw["error"] = str(exc)
            warnings.append(f"Dọn gateway lỗi: {exc}")
    result["gateway"] = gw
    return result


# --------------------------------------------------------------------- quyền tool theo seat

def seat_tools(db: Session, org_id: int, agent_id: int) -> dict:
    from app.services.company_mcp import TOOLS
    agent, member = seat(db, org_id, agent_id)
    tier = perms.seat_tier(db, member)
    items = []
    for name, t in TOOLS.items():
        level, source = perms.resolve(db, member, name)
        items.append({"name": name, "group": t.group, "writes": t.writes, "description": t.description,
                      "level": level, "source": source})
    return {"agent_id": agent.id, "member_id": member.id, "tier": tier,
            "tier_label": "Trưởng/điều hành" if tier == "lead" else "Thừa hành",
            "levels": list(perms.TOOL_LEVELS), "tools": items}
