"""M5a — phiên bản hồ sơ nhân sự AI.

Hồ sơ = những gì người quản lý chỉnh được (chức danh, phòng, quản lý, tính cách,
emoji, mô tả việc, ghi chú quản lý, model). Mỗi lần đổi, ``update_hr`` gọi
``snapshot``; bản trùng hồ sơ với bản trước thì không tạo thêm.

Khôi phục KHÔNG chép đè file cũ: nó áp lại hồ sơ của bản đó qua ``update_hr``
(nên file được sinh lại theo công ty/quản lý hiện tại, gateway được cập nhật,
và chính việc khôi phục cũng thành một bản mới — lịch sử không bị viết lại).
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Agent, Member
from app.models.agent_hr import AgentFileSnapshot, AgentProfileVersion

PROFILE_FIELDS = ("name", "role", "department_id", "manager_member_id", "personality", "address_style", "emoji",
                  "job_description", "manager_notes", "model", "monthly_budget", "daily_cap_usd",
                  "model_policy")
FIELD_VI = {"name": "tên", "role": "chức danh", "department_id": "phòng ban", "manager_member_id": "quản lý",
            "personality": "tính cách", "address_style": "xưng hô", "emoji": "emoji", "job_description": "mô tả công việc",
            "manager_notes": "ghi chú quản lý", "model": "model", "monthly_budget": "hạn mức tháng",
            "daily_cap_usd": "trần chi ngày", "model_policy": "model theo loại việc"}


def current_profile(db: Session, agent: Agent, member: Member) -> dict:
    from app.services.agent_hr import DEFAULT_ADDRESS_STYLE, DEFAULT_PERSONALITY, hire_spec
    spec = hire_spec(db, agent)
    return {"name": member.name, "role": member.role or "", "department_id": member.department_id,
            "manager_member_id": member.manager_id,
            "personality": spec.get("personality") or DEFAULT_PERSONALITY,
            "address_style": spec.get("address_style") or DEFAULT_ADDRESS_STYLE, "emoji": spec.get("emoji") or "",
            "job_description": spec.get("job_description") or "", "manager_notes": spec.get("manager_notes") or "",
            "model": agent.model or "", "monthly_budget": spec.get("monthly_budget"),
            "daily_cap_usd": spec.get("daily_cap_usd"), "model_policy": spec.get("model_policy") or {}}


def _latest(db: Session, agent_id: int) -> AgentProfileVersion | None:
    return (db.query(AgentProfileVersion).filter(AgentProfileVersion.agent_id == agent_id)
            .order_by(AgentProfileVersion.version.desc()).first())


# Trường thêm sau: bản cũ không có khoá này nghĩa là đang dùng mặc định.
FIELD_DEFAULTS = {"address_style": "em-anh-chi", "monthly_budget": None, "daily_cap_usd": None,
                  "model_policy": {}}


def changed_fields(old: dict, new: dict) -> list[str]:
    def g(d, k):
        return (d or {}).get(k, FIELD_DEFAULTS.get(k))
    return [k for k in PROFILE_FIELDS if g(old, k) != g(new, k)]


def snapshot(db: Session, agent: Agent, member: Member, *, user_id: int | None = None,
             note: str = "") -> AgentProfileVersion | None:
    """Chụp hồ sơ hiện tại thành bản mới. Trùng bản trước → ``None``."""
    prof = current_profile(db, agent, member)
    last = _latest(db, agent.id)
    old = json.loads(last.profile_json) if last else {}
    changed = changed_fields(old, prof) if last else list(PROFILE_FIELDS)
    if last and not changed:
        return None
    files = {s.name: s.hash for s in db.query(AgentFileSnapshot).filter(AgentFileSnapshot.agent_id == agent.id)}
    row = AgentProfileVersion(
        organization_id=member.organization_id, agent_id=agent.id, version=(last.version + 1) if last else 1,
        profile_json=json.dumps(prof, ensure_ascii=False), files_json=json.dumps(files),
        changed_json=json.dumps(changed if last else [], ensure_ascii=False),
        note=(note or ("Bản đầu" if not last else ""))[:300], created_by_user_id=user_id)
    db.add(row); db.commit(); db.refresh(row)
    return row


def _out(row: AgentProfileVersion, current: dict) -> dict:
    prof = json.loads(row.profile_json or "{}")
    report = json.loads(row.persona_report_json) if row.persona_report_json else None
    return {"version": row.version, "created_at": row.created_at.isoformat(), "note": row.note,
            "changed": json.loads(row.changed_json or "[]"),
            "changed_vi": [FIELD_VI.get(f, f) for f in json.loads(row.changed_json or "[]")],
            "profile": prof, "is_current": not changed_fields(prof, current),
            "created_by_user_id": row.created_by_user_id,
            "persona_score": row.persona_score, "persona_report": report,
            "persona_checked_at": row.persona_checked_at.isoformat() if row.persona_checked_at else None}


def list_versions(db: Session, org_id: int, agent_id: int) -> dict:
    from app.services.agent_hr import seat
    agent, member = seat(db, org_id, agent_id)
    if _latest(db, agent.id) is None:          # seat có từ trước khi có phiên bản
        snapshot(db, agent, member, note="Bản đầu (chụp khi mở lịch sử)")
    current = current_profile(db, agent, member)
    rows = (db.query(AgentProfileVersion).filter(AgentProfileVersion.agent_id == agent.id)
            .order_by(AgentProfileVersion.version.desc()).all())
    return {"agent_id": agent.id, "versions": [_out(r, current) for r in rows]}


async def restore(db: Session, principal: Any, org_id: int, runtime: Any, agent_id: int, version: int) -> dict:
    from app.services import agent_hr
    agent, member = agent_hr.seat(db, org_id, agent_id)
    row = (db.query(AgentProfileVersion)
           .filter(AgentProfileVersion.agent_id == agent.id, AgentProfileVersion.version == version).first())
    if row is None:
        raise HTTPException(404, f"Không có phiên bản {version}")
    want = json.loads(row.profile_json or "{}")
    now = current_profile(db, agent, member)
    fields = set(changed_fields(now, want))
    if not fields:
        return {"agent_id": agent.id, "restored": version, "changed": [], "note": "Hồ sơ đã giống bản này"}
    data = {k: want.get(k, FIELD_DEFAULTS.get(k)) for k in fields}
    result = await agent_hr.update_hr(db, principal, org_id, runtime, agent.id, data, fields,
                                      version_note=f"Khôi phục từ bản {version}")
    return {**result, "restored": version}


def record_persona(db: Session, agent_id: int, report: dict) -> AgentProfileVersion | None:
    from datetime import datetime
    row = _latest(db, agent_id)
    if row is None:
        return None
    row.persona_score = report.get("score")
    row.persona_report_json = json.dumps(report, ensure_ascii=False)
    row.persona_checked_at = datetime.utcnow()
    db.add(row); db.commit()
    return row


def latest_version_number(db: Session, agent_id: int) -> int:
    return int(db.query(func.coalesce(func.max(AgentProfileVersion.version), 0))
               .filter(AgentProfileVersion.agent_id == agent_id).scalar() or 0)
