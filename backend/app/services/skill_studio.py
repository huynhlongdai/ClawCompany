"""M5b việc 10 — Skill Studio: đề xuất → eval → duyệt → thư viện công ty → cài cho agent → rollback.

Dựng trên Skill Workshop có sẵn của OpenClaw (kiểm trên gateway thật 2026.9.8):
``skills.proposals.list/inspect/create/update/apply/reject`` + ``skills.workshop.read``.

* Quản trị: mặc định OpenClaw để ``skills.workshop.autonomous.mode = "auto"`` — agent tự sửa kỹ năng
  của mình không cần ai duyệt. Studio chuyển sang ``"propose"`` + ``approvalPolicy = "pending"``
  (cả hai nạp nóng, không khởi động lại gateway): agent chỉ được ĐỀ XUẤT.
* Đề xuất của agent (Workshop) được đồng bộ về thành một phiên bản ``source=workshop`` và tự gửi vào
  Hộp việc. Người quản lý cũng soạn được bản nháp (``source=manual``).
* Eval: mỗi ca kiểm là một câu hỏi + chữ BẮT BUỘC có / KHÔNG được có. Chạy cùng ca hai lần trên một agent
  — có hướng dẫn của kỹ năng và không có — để thấy kỹ năng có giúp thật không. Chấm bằng luật.
* Duyệt → bản đó thành bản hiện hành; đề xuất Workshop được ``apply`` trên agent gốc. Cài cho agent khác =
  ``proposals.create`` (hoặc ``update`` nếu agent đã có) rồi ``apply`` ngay vì công ty đã duyệt.
  Rollback = cài lại một bản đã duyệt trước đó cho mọi agent đang có kỹ năng.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Agent, Approval, Member
from app.models.learning import CompanySkill, CompanySkillInstall, CompanySkillVersion

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
STATUS_VI = {"draft": "Nháp", "in_review": "Chờ duyệt", "approved": "Đã duyệt", "rejected": "Bị từ chối",
             "superseded": "Bản cũ"}
GOVERNANCE = {("skills", "workshop", "autonomous", "mode"): "propose",
              ("skills", "workshop", "approvalPolicy"): "pending"}


def _has_rpc(runtime: Any) -> bool:
    from app.services import agent_hr
    return agent_hr._has_rpc(runtime)


def _need(runtime: Any) -> None:
    if not _has_rpc(runtime):
        raise HTTPException(409, "Cần gateway OpenClaw thật cho thao tác kỹ năng")


def body_of(content: str) -> str:
    """Bỏ frontmatter của SKILL.md / PROPOSAL.md — gateway tự sinh frontmatter khi tạo đề xuất."""
    m = re.match(r"^---\n.*?\n---\n?", content or "", re.S)
    return (content[m.end():] if m else content or "").strip() + "\n"


# ------------------------------------------------------------------ quản trị Workshop

async def governance(runtime: Any) -> dict:
    from app.services.openclaw_config import ConfigRegistry
    _need(runtime)
    snap = await ConfigRegistry(runtime).snapshot()
    ws = (((snap.get("config") or {}).get("skills") or {}).get("workshop") or {})
    mode = (ws.get("autonomous") or {}).get("mode") or "auto"
    policy = ws.get("approvalPolicy") or "auto"
    return {"autonomous_mode": mode, "approval_policy": policy, "governed": mode in ("propose", "off") and policy == "pending"}


async def enforce_governance(runtime: Any) -> dict:
    from app.services.openclaw_config import ConfigRegistry
    _need(runtime)
    reg = ConfigRegistry(runtime)
    snap = await reg.snapshot()
    await reg.patch(dict(GOVERNANCE), base_hash=snap.get("hash"),
                    note="ClawCompany Skill Studio: agent chỉ đề xuất kỹ năng, người duyệt mới áp")
    return await governance(runtime)


# ------------------------------------------------------------------ đọc / tạo

def _skill(db: Session, org_id: int, sid: int) -> CompanySkill:
    s = db.get(CompanySkill, sid)
    if s is None or s.organization_id != org_id:
        raise HTTPException(404, "Không thấy kỹ năng")
    return s


def _version(db: Session, org_id: int, vid: int) -> tuple[CompanySkill, CompanySkillVersion]:
    v = db.get(CompanySkillVersion, vid)
    s = db.get(CompanySkill, v.skill_id) if v else None
    if v is None or s is None or s.organization_id != org_id:
        raise HTTPException(404, "Không thấy phiên bản kỹ năng")
    return s, v


def _agent_name(db: Session, agent_id: int | None) -> str | None:
    if not agent_id:
        return None
    ag = db.get(Agent, agent_id); m = db.get(Member, ag.member_id) if ag else None
    return m.name if m else None


def clean_cases(cases: Any) -> list[dict]:
    out = []
    for c in cases or []:
        if not isinstance(c, dict) or not str(c.get("prompt") or "").strip():
            raise HTTPException(422, "Mỗi ca kiểm cần có câu hỏi (prompt)")
        inc = [str(x).strip() for x in (c.get("must_include") or []) if str(x).strip()]
        exc = [str(x).strip() for x in (c.get("must_not_include") or []) if str(x).strip()]
        if not inc and not exc:
            raise HTTPException(422, "Mỗi ca kiểm cần ít nhất một chữ bắt buộc có hoặc không được có")
        out.append({"prompt": str(c["prompt"]).strip()[:1500], "must_include": inc[:10], "must_not_include": exc[:10]})
    if len(out) > 12:
        raise HTTPException(422, "Tối đa 12 ca kiểm cho một phiên bản")
    return out


def v_public(db: Session, v: CompanySkillVersion, *, content: bool = True) -> dict:
    out = {"id": v.id, "version": v.version, "description": v.description, "source": v.source,
           "source_vi": "Agent đề xuất (Workshop)" if v.source == "workshop" else "Quản lý soạn",
           "origin_agent_id": v.origin_agent_id, "origin_agent": _agent_name(db, v.origin_agent_id),
           "status": v.status, "status_vi": STATUS_VI.get(v.status, v.status), "approval_id": v.approval_id,
           "eval_cases": list(v.eval_cases or []), "eval_report": v.eval_report, "scan": v.scan,
           "note": v.note or "", "created_at": v.created_at.isoformat() if v.created_at else None,
           "decided_at": v.decided_at.isoformat() if v.decided_at else None}
    if content:
        out["content"] = v.content
    return out


def detail(db: Session, org_id: int, sid: int) -> dict:
    s = _skill(db, org_id, sid)
    vs = db.query(CompanySkillVersion).filter(CompanySkillVersion.skill_id == s.id).order_by(CompanySkillVersion.version.desc()).all()
    inst = db.query(CompanySkillInstall).filter(CompanySkillInstall.skill_id == s.id).all()
    vmap = {v.id: v.version for v in vs}
    return {"id": s.id, "slug": s.slug, "title": s.title, "status": s.status,
            "current_version": vmap.get(s.current_version_id), "current_version_id": s.current_version_id,
            "versions": [v_public(db, v) for v in vs],
            "installs": [{"agent_id": i.agent_id, "agent": _agent_name(db, i.agent_id), "version": vmap.get(i.version_id),
                          "status": i.status, "error": i.error, "installed_at": i.installed_at.isoformat()} for i in inst]}


def list_skills(db: Session, org_id: int) -> list[dict]:
    out = []
    for s in db.query(CompanySkill).filter(CompanySkill.organization_id == org_id).order_by(CompanySkill.id.desc()).all():
        vs = db.query(CompanySkillVersion).filter(CompanySkillVersion.skill_id == s.id).all()
        cur = next((v for v in vs if v.id == s.current_version_id), None)
        out.append({"id": s.id, "slug": s.slug, "title": s.title, "status": s.status,
                    "current_version": cur.version if cur else None,
                    "pending": sum(1 for v in vs if v.status in ("draft", "in_review")),
                    "installed": db.query(CompanySkillInstall).filter(CompanySkillInstall.skill_id == s.id,
                                                                      CompanySkillInstall.status == "installed").count(),
                    "description": (cur or (max(vs, key=lambda v: v.version) if vs else None)).description if vs else ""})
    return out


def _next_version(db: Session, skill: CompanySkill) -> int:
    last = db.query(CompanySkillVersion).filter(CompanySkillVersion.skill_id == skill.id).order_by(CompanySkillVersion.version.desc()).first()
    return (last.version + 1) if last else 1


def _get_or_make_skill(db: Session, org_id: int, slug: str, title: str) -> CompanySkill:
    s = db.query(CompanySkill).filter(CompanySkill.organization_id == org_id, CompanySkill.slug == slug).first()
    if s is None:
        s = CompanySkill(organization_id=org_id, slug=slug, title=title[:220] or slug)
        db.add(s); db.commit(); db.refresh(s)
    return s


def create_draft(db: Session, principal, org_id: int, data: dict) -> dict:
    slug = (data.get("slug") or "").strip().lower()
    if not SLUG_RE.match(slug):
        raise HTTPException(422, "Mã kỹ năng chỉ gồm chữ thường không dấu, số và gạch ngang (2–63 ký tự)")
    content = (data.get("content") or "").strip()
    if len(content) < 40:
        raise HTTPException(422, "Nội dung kỹ năng quá ngắn — viết rõ khi nào dùng và các bước làm")
    if len(content.encode()) > 40_000:
        raise HTTPException(422, "Kỹ năng tối đa 40 KB")
    desc = (data.get("description") or "").strip()
    if not desc or len(desc.encode()) > 160:
        raise HTTPException(422, "Mô tả ngắn bắt buộc, tối đa 160 byte (agent đọc mô tả để biết khi nào dùng)")
    s = _get_or_make_skill(db, org_id, slug, data.get("title") or slug)
    v = CompanySkillVersion(skill_id=s.id, version=_next_version(db, s), description=desc, content=body_of(content),
                            source="manual", eval_cases=clean_cases(data.get("eval_cases")),
                            created_by_user_id=principal.user_id)
    db.add(v); db.commit()
    return detail(db, org_id, s.id)


def update_draft(db: Session, org_id: int, vid: int, data: dict) -> dict:
    s, v = _version(db, org_id, vid)
    if v.status not in ("draft", "rejected"):
        raise HTTPException(409, "Chỉ sửa được bản nháp hoặc bản bị từ chối — bản khác thì tạo phiên bản mới")
    if "content" in data and data["content"] is not None:
        if v.source == "workshop":
            raise HTTPException(409, "Nội dung đề xuất của agent không sửa tại đây — từ chối kèm lý do để agent sửa")
        v.content = body_of(data["content"])
    if data.get("eval_cases") is not None:
        v.eval_cases = clean_cases(data["eval_cases"])
        v.eval_report = None
    if v.status == "rejected":
        v.status = "draft"
    db.add(v); db.commit()
    return detail(db, org_id, s.id)


# ------------------------------------------------------------------ đồng bộ đề xuất từ Workshop

async def sync_workshop(db: Session, org_id: int, runtime: Any) -> dict:
    """Đề xuất đang chờ trên gateway → phiên bản ``workshop`` + yêu cầu duyệt trong Hộp việc."""
    _need(runtime)
    seats = (db.query(Agent, Member).join(Member, Member.id == Agent.member_id)
             .filter(Member.organization_id == org_id, Agent.lifecycle != "retired").all())
    imported, closed, errors = 0, 0, []
    for ag, m in seats:
        rid = (ag.runtime_agent_id or "").strip()
        if not rid:
            continue
        try:
            lst = await runtime.rpc("skills.proposals.list", {"agentId": rid})
        except Exception as exc:  # noqa: BLE001
            errors.append({"agent": m.name, "error": str(exc)[:200]}); continue
        for p in lst.get("proposals") or []:
            pid, status = p.get("id"), p.get("status")
            known = db.query(CompanySkillVersion).filter(CompanySkillVersion.workshop_proposal_id == pid).first()
            if known is not None:
                if status in ("applied", "rejected", "quarantined") and known.status == "in_review":
                    # Ai đó xử lý thẳng trên gateway — ghi nhận, không giả là đã duyệt ở đây.
                    known.status = "approved" if status == "applied" else "rejected"
                    known.note = f"Đã {status} trực tiếp trên gateway"
                    db.add(known); db.commit(); closed += 1
                continue
            if status != "pending":
                continue
            try:
                ins = await runtime.rpc("skills.proposals.inspect", {"agentId": rid, "proposalId": pid})
            except Exception as exc:  # noqa: BLE001
                errors.append({"agent": m.name, "error": str(exc)[:200]}); continue
            rec = ins.get("record") or {}
            name = ((rec.get("target") or {}).get("skillName") or p.get("skillName") or pid)[:64].lower()
            slug = re.sub(r"[^a-z0-9-]", "-", name).strip("-") or "skill"
            s = _get_or_make_skill(db, org_id, slug, rec.get("title") or name)
            v = CompanySkillVersion(skill_id=s.id, version=_next_version(db, s), description=(rec.get("description") or "")[:160],
                                    content=body_of(ins.get("content") or ""), source="workshop", origin_agent_id=ag.id,
                                    workshop_proposal_id=pid, workshop_revision_hash=ins.get("revisionHash") or "",
                                    scan=rec.get("scan"), eval_cases=[], note=(rec.get("goal") or "")[:2000])
            db.add(v); db.commit(); db.refresh(v)
            submit(db, org_id, v.id, requester_member_id=m.id)
            imported += 1
    return {"imported": imported, "closed": closed, "errors": errors}


# ------------------------------------------------------------------ eval

def score(text: str, case: dict) -> dict:
    low = (text or "").lower()
    miss = [w for w in case["must_include"] if w.lower() not in low]
    bad = [w for w in case["must_not_include"] if w.lower() in low]
    return {"passed": not miss and not bad, "missing": miss, "forbidden": bad}


SKILL_WRAP = """Bạn có kỹ năng "{slug}" dưới đây. Áp dụng nó nếu phù hợp với yêu cầu.

<skill>
{body}
</skill>

Yêu cầu: {prompt}"""


async def run_eval(db: Session, org_id: int, runtime: Any, vid: int, *, agent_id: int, timeout: int = 120) -> dict:
    from app.services import agent_hr
    _need(runtime)
    s, v = _version(db, org_id, vid)
    if not v.eval_cases:
        raise HTTPException(409, "Phiên bản chưa có ca kiểm nào — thêm ca kiểm trước khi chạy eval")
    ag, m = agent_hr.seat(db, org_id, agent_id)
    if not hasattr(runtime, "chat_stream"):
        raise HTTPException(409, "Gateway không hỗ trợ chat để chạy eval")
    stamp = int(time.time())

    async def ask(prompt: str, key: str) -> str:
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

    async def one(i: int, c: dict) -> dict:
        base = f"agent:{ag.runtime_agent_id}:skill-eval-{v.id}-{i}-{stamp}"
        with_text, without_text = await asyncio.gather(
            ask(SKILL_WRAP.format(slug=s.slug, body=v.content[:20000], prompt=c["prompt"]), base + "-with"),
            ask(c["prompt"], base + "-base"))
        return {"prompt": c["prompt"], "with_skill": {**score(with_text, c), "reply": with_text[:1200]},
                "baseline": {**score(without_text, c), "reply": without_text[:1200]}}

    cases = await asyncio.gather(*(one(i, c) for i, c in enumerate(v.eval_cases)))
    w = sum(c["with_skill"]["passed"] for c in cases); b = sum(c["baseline"]["passed"] for c in cases)
    v.eval_report = {"agent_id": ag.id, "agent": m.name, "at": datetime.utcnow().isoformat(), "total": len(cases),
                     "with_skill": w, "baseline": b, "cases": cases}
    db.add(v); db.commit()
    return v_public(db, v)


# ------------------------------------------------------------------ duyệt

def submit(db: Session, org_id: int, vid: int, *, requester_member_id: int | None = None) -> dict:
    from app.services import inbox
    s, v = _version(db, org_id, vid)
    if v.status not in ("draft", "rejected"):
        raise HTTPException(409, f"Phiên bản đang ở trạng thái {STATUS_VI.get(v.status, v.status)}")
    if v.source == "manual" and v.eval_cases and not v.eval_report:
        raise HTTPException(409, "Chạy eval trước khi gửi duyệt (phiên bản đã có ca kiểm)")
    rep = v.eval_report or {}
    ev = {"skill": s.slug, "title": s.title, "version": v.version, "source_vi": v_public(db, v, content=False)["source_vi"],
          "description": v.description, "origin_agent": _agent_name(db, v.origin_agent_id),
          "eval": (f"Có kỹ năng đạt {rep['with_skill']}/{rep['total']} ca, không có kỹ năng đạt {rep['baseline']}/{rep['total']} "
                   f"(chạy trên {rep['agent']})") if rep else "Chưa chạy eval",
          "scan": (f"{(v.scan or {}).get('state')}: {(v.scan or {}).get('critical', 0)} nghiêm trọng, {(v.scan or {}).get('warn', 0)} cảnh báo"
                   if v.scan else None),
          "content": v.content[:6000], "goal": v.note or None}
    approver = None
    if v.origin_agent_id:
        ag = db.get(Agent, v.origin_agent_id); am = db.get(Member, ag.member_id) if ag else None
        if am is not None and am.manager_id:
            approver = (inbox.human_recipients(db, am.manager_id) or [None])[0]
    a = Approval(organization_id=org_id, requester_member_id=requester_member_id, approver_member_id=approver,
                 action=f"Kỹ năng {s.slug} v{v.version}: {v.description}"[:220],
                 risk="high" if (v.scan or {}).get("critical") else "medium", policy_key=f"skill:v{v.id}",
                 status="pending", evidence=json.dumps({k: x for k, x in ev.items() if x}, ensure_ascii=False),
                 payload={"skill_id": s.id, "version_id": v.id})
    db.add(a); db.commit(); db.refresh(a)
    v.status, v.approval_id = "in_review", a.id
    db.add(v); db.commit()
    return {"approval_id": a.id, **v_public(db, v, content=False)}


async def on_decided(db: Session, a: Approval, runtime: Any) -> dict:
    m = re.match(r"skill:v(\d+)$", a.policy_key or "")
    v = db.get(CompanySkillVersion, int(m.group(1))) if m else None
    if v is None:
        return {}
    s = db.get(CompanySkill, v.skill_id)
    v.decided_at = datetime.utcnow()
    ag = db.get(Agent, v.origin_agent_id) if v.origin_agent_id else None
    if a.status != "approved":
        v.status, v.note = "rejected", (a.resolution_note or v.note)
        db.add(v); db.commit()
        if v.source == "workshop" and ag and _has_rpc(runtime):
            try:
                await runtime.rpc("skills.proposals.reject", {"agentId": ag.runtime_agent_id, "proposalId": v.workshop_proposal_id,
                                                              "expectedRevisionHash": v.workshop_revision_hash,
                                                              "reason": (a.resolution_note or "")[:500]})
                return {"message": "đã báo agent đề xuất bị từ chối"}
            except Exception as exc:  # noqa: BLE001
                return {"message": f"chưa báo được gateway ({str(exc)[:150]})"}
        return {}
    for old in db.query(CompanySkillVersion).filter(CompanySkillVersion.skill_id == s.id, CompanySkillVersion.status == "approved").all():
        old.status = "superseded"; db.add(old)
    v.status = "approved"
    s.current_version_id = v.id
    db.add(v); db.add(s); db.commit()
    if v.source == "workshop" and ag and _has_rpc(runtime):
        try:
            await runtime.rpc("skills.proposals.apply", {"agentId": ag.runtime_agent_id, "proposalId": v.workshop_proposal_id,
                                                         "expectedRevisionHash": v.workshop_revision_hash,
                                                         "reason": "Đã duyệt trong ClawCompany"})
            _record_install(db, s, v, ag.id, "installed", "")
            return {"message": f"đã cài cho {_agent_name(db, ag.id)}; vào Skill Studio để cài cho agent khác"}
        except Exception as exc:  # noqa: BLE001
            _record_install(db, s, v, ag.id, "failed", str(exc)[:300])
            return {"message": f"đã duyệt nhưng CHƯA cài được lên gateway ({str(exc)[:150]})"}
    return {"message": "đã vào thư viện công ty — vào Skill Studio để cài cho agent"}


# ------------------------------------------------------------------ cài / rollback

def _record_install(db: Session, s: CompanySkill, v: CompanySkillVersion, agent_id: int, status: str, error: str) -> None:
    row = db.query(CompanySkillInstall).filter(CompanySkillInstall.skill_id == s.id, CompanySkillInstall.agent_id == agent_id).first()
    if row is None:
        row = CompanySkillInstall(skill_id=s.id, agent_id=agent_id, version_id=v.id)
    if status == "installed" or row.id is None:
        row.version_id = v.id
    row.status, row.error, row.installed_at = status, error, datetime.utcnow()
    db.add(row); db.commit()


async def _push(runtime: Any, rid: str, s: CompanySkill, v: CompanySkillVersion) -> None:
    """Có rồi → đề xuất cập nhật; chưa có → đề xuất tạo. Rồi apply ngay (công ty đã duyệt bản này)."""
    try:
        await runtime.rpc("skills.workshop.read", {"agentId": rid, "name": s.slug})
        exists = True
    except Exception:  # noqa: BLE001
        exists = False
    params = {"agentId": rid, "description": v.description or s.title, "content": v.content,
              "goal": f"ClawCompany: cài {s.slug} v{v.version} đã duyệt"}
    if exists:
        rec = await runtime.rpc("skills.proposals.update", {**params, "skillName": s.slug})
    else:
        rec = await runtime.rpc("skills.proposals.create", {**params, "name": s.slug})
    await runtime.rpc("skills.proposals.apply", {"agentId": rid, "proposalId": rec["record"]["id"],
                                                 "expectedRevisionHash": rec["revisionHash"],
                                                 "reason": f"ClawCompany: phiên bản v{v.version} đã duyệt"})


async def install(db: Session, org_id: int, runtime: Any, sid: int, *, agent_ids: list[int],
                  version_id: int | None = None) -> dict:
    from app.services import agent_hr
    _need(runtime)
    s = _skill(db, org_id, sid)
    vid = version_id or s.current_version_id
    if not vid:
        raise HTTPException(409, "Kỹ năng chưa có phiên bản nào được duyệt")
    _, v = _version(db, org_id, vid)
    if v.status not in ("approved", "superseded"):
        raise HTTPException(409, "Chỉ cài được phiên bản đã duyệt")
    rows = []
    for aid in agent_ids:
        ag, m = agent_hr.seat(db, org_id, int(aid))
        try:
            await _push(runtime, ag.runtime_agent_id, s, v)
            _record_install(db, s, v, ag.id, "installed", "")
            rows.append({"agent_id": ag.id, "agent": m.name, "status": "installed"})
        except Exception as exc:  # noqa: BLE001
            _record_install(db, s, v, ag.id, "failed", str(exc)[:300])
            rows.append({"agent_id": ag.id, "agent": m.name, "status": "failed", "error": str(exc)[:300]})
    return {"version": v.version, "results": rows, **detail(db, org_id, sid)}


async def rollback(db: Session, org_id: int, runtime: Any, sid: int, *, version_id: int) -> dict:
    s = _skill(db, org_id, sid)
    _, v = _version(db, org_id, version_id)
    if v.skill_id != s.id or v.status not in ("approved", "superseded"):
        raise HTTPException(409, "Chỉ quay về được một phiên bản đã từng được duyệt của kỹ năng này")
    for cur in db.query(CompanySkillVersion).filter(CompanySkillVersion.skill_id == s.id, CompanySkillVersion.status == "approved").all():
        cur.status = "superseded"; db.add(cur)
    v.status = "approved"
    s.current_version_id = v.id
    db.add(v); db.add(s); db.commit()
    agents = [i.agent_id for i in db.query(CompanySkillInstall).filter(CompanySkillInstall.skill_id == s.id).all()]
    if not agents:
        return {"version": v.version, "results": [], **detail(db, org_id, sid)}
    return await install(db, org_id, runtime, sid, agent_ids=agents, version_id=v.id)
