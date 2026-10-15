"""M2e.2 — luật cứng: luật của công ty / chức danh được CƯỠNG CHẾ lúc chạy, không chỉ là chữ trong AGENTS.md.

Hai nơi cưỡng chế, cùng một bộ luật biên dịch:

1. **Guard plugin trên gateway OpenClaw** (``openclaw-plugins/clawcompany-guard``): ``before_agent_finalize`` bắt viết
   lại (revise), ``message_sending`` che chữ (scrub) / huỷ gửi (block), ``before_tool_call`` chặn tool hoặc đòi người
   duyệt (requireApproval). Luật đến plugin qua ``config.patch`` một chuỗi JSON
   ``plugins.entries.clawcompany-guard.config.rulesJson`` (đổi ``plugins.entries.*`` chỉ nạp lại plugin, không khởi
   động lại gateway — docs gateway/configuration/hot-reload 2026.9.8). Vi phạm plugin báo về
   ``POST /api/guard/violations`` (token HMAC, mạng docker nội bộ).
2. **Cổng MCP của ClawCompany** (``api/mcp.py`` tools/call): luật ``tool`` / ``approval`` và luật chữ cho tool gửi
   ra ngoài (A2A) — đường tất định, kiểm được không cần model.

Điều cấm trong hiến chương là câu tự nhiên, không tự thành regex được: mỗi luật có thể ghi ``source=charter`` +
``source_ref`` = chỉ số điều cấm nó thực thi, và màn hình chỉ ra điều cấm nào CHƯA có luật cứng (chỉ là chữ)."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Agent, Member
from app.models.agent_native import CompanyRule, RuleViolation
from app.models.company_foundation import Position

KINDS = ("phrase", "regex", "tool", "approval", "pii")
ACTIONS = {"phrase": ("revise", "block", "scrub"), "regex": ("revise", "block", "scrub"),
           "tool": ("block",), "approval": ("approve",), "pii": ("scrub", "block", "revise")}
# Dữ liệu cá nhân — cùng một chuỗi regex cho Python và JS (plugin nhận nguồn regex trong JSON biên dịch).
PII = {
    "phone": r"(?<![0-9])(?:\+84|84|0)(?:[ .]?[0-9]){9}(?![0-9])",
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "cccd": r"(?<![0-9])[0-9]{12}(?![0-9])",
    "card": r"(?<![0-9])(?:[0-9][ -]?){15}[0-9](?![0-9])",
}
PII_VI = {"phone": "số điện thoại", "email": "email", "cccd": "số CCCD", "card": "số thẻ"}
EXTERNAL_TOOLS = {"company_delegate_external"}          # tool MCP gửi chữ ra ngoài công ty
REPLACEMENT = "[đã ẩn]"
TEMPLATES = {
    "pii_external": {"name": "Không đưa dữ liệu cá nhân ra ngoài", "kind": "pii", "pattern": "phone,email,cccd,card",
                     "action": "scrub", "external_only": True,
                     "message": "Không gửi số điện thoại, email, CCCD, số thẻ của khách ra kênh ngoài hoặc cho agent ngoài."},
    "no_refund_promise": {"name": "Không hứa hoàn tiền ngoài chính sách", "kind": "regex",
                          "pattern": r"(cam kết|hứa|chắc chắn)\s+(sẽ\s+)?hoàn\s+(tiền\s+)?(100|toàn bộ)",
                          "action": "revise",
                          "message": "Không hứa hoàn tiền toàn bộ/100%; chỉ nói theo chính sách đổi trả và việc cần người duyệt."},
    "no_external_agents": {"name": "Không giao việc cho agent ngoài", "kind": "tool", "pattern": "company_delegate_external",
                           "action": "block", "message": "Chức danh này không được gửi việc/dữ liệu cho agent bên ngoài công ty."},
}
KIND_VI = {"phrase": "Cụm từ cấm", "regex": "Mẫu chữ cấm", "tool": "Công cụ cấm", "approval": "Công cụ cần duyệt",
           "pii": "Dữ liệu cá nhân"}
ACTION_VI = {"revise": "bắt viết lại", "block": "chặn", "scrub": "che chữ", "approve": "chờ người duyệt"}


def _err(status: int, msg: str) -> HTTPException:
    return HTTPException(status, msg)


# ------------------------------------------------------------------ biên dịch / so khớp (thuần, test được)

def _esc(s: str) -> str:
    """Escape hợp lệ cho cả Python ``re`` và JS RegExp cờ ``u`` (re.escape sinh ``\\-``, ``\\#`` — JS u-mode báo lỗi)."""
    return re.sub(r"([.*+?^${}()|\[\]\\/])", r"\\\1", s)


def regex_of(r: CompanyRule | dict) -> list[tuple[str, str]]:
    """[(nhãn, nguồn regex)] của một luật chữ. phrase → regex an toàn (escape, khoảng trắng co giãn)."""
    kind = r["kind"] if isinstance(r, dict) else r.kind
    pat = (r["pattern"] if isinstance(r, dict) else r.pattern) or ""
    if kind == "phrase":
        out = []
        for ph in [x.strip() for x in re.split(r"[\n|]", pat) if x.strip()]:
            out.append((ph, r"\s+".join(_esc(w) for w in ph.split())))
        return out
    if kind == "regex":
        return [(pat, pat)] if pat else []
    if kind == "pii":
        return [(k, PII[k]) for k in [x.strip() for x in pat.split(",")] if k in PII]
    return []


def tools_of(r: CompanyRule | dict) -> list[str]:
    pat = (r["pattern"] if isinstance(r, dict) else r.pattern) or ""
    return [x.strip() for x in re.split(r"[\s,]+", pat) if x.strip()]


def tool_matches(name: str, wanted: str) -> bool:
    """Tên tool trên gateway có thể mang tiền tố server MCP (vd ``clawcompany__company_x``)."""
    n, w = (name or "").lower(), wanted.lower()
    return n == w or n.endswith("__" + w) or n.endswith("." + w) or n.endswith("/" + w)


def check_text(rules: list[dict], text: str, *, external: bool) -> list[dict]:
    hits = []
    for r in rules:
        if r["kind"] not in ("phrase", "regex", "pii") or (r.get("external_only") and not external):
            continue
        for label, src in regex_of(r):
            m = re.search(src, text or "", re.I)
            if m:
                hits.append({"rule_id": r["id"], "action": r["action"], "label": label, "match": m.group(0),
                             "message": r.get("message") or ""})
                break
    return hits


def scrub(rules: list[dict], text: str, *, external: bool) -> str:
    out = text or ""
    for r in rules:
        if r["action"] != "scrub" or (r.get("external_only") and not external):
            continue
        for _label, src in regex_of(r):
            out = re.sub(src, REPLACEMENT, out, flags=re.I)
    return out


def check_tool(rules: list[dict], name: str) -> dict | None:
    """Luật tool cho một lần gọi: block thắng approve."""
    found = None
    for r in rules:
        if r["kind"] in ("tool", "approval") and any(tool_matches(name, t) for t in tools_of(r)):
            if r["kind"] == "tool":
                return {"rule_id": r["id"], "action": "block", "message": r.get("message") or ""}
            found = found or {"rule_id": r["id"], "action": "approve", "message": r.get("message") or ""}
    return found


def redact(text: str, limit: int = 300) -> str:
    out = text or ""
    for src in PII.values():
        out = re.sub(src, REPLACEMENT, out)
    return out[:limit]


# ------------------------------------------------------------------ CRUD

def public_rule(db: Session, r: CompanyRule) -> dict:
    pos = db.get(Position, r.position_id) if r.position_id else None
    return {"id": r.id, "company_id": r.company_id, "position_id": r.position_id,
            "position": pos.title if pos else None, "name": r.name, "kind": r.kind, "kind_vi": KIND_VI.get(r.kind, r.kind),
            "pattern": r.pattern, "action": r.action, "action_vi": ACTION_VI.get(r.action, r.action),
            "message": r.message, "external_only": bool(r.external_only), "source": r.source,
            "source_ref": r.source_ref, "enabled": bool(r.enabled),
            "updated_at": r.updated_at.isoformat() if r.updated_at else None}


def as_dict(r: CompanyRule) -> dict:
    return {"id": r.id, "kind": r.kind, "pattern": r.pattern, "action": r.action, "message": r.message or "",
            "external_only": bool(r.external_only), "name": r.name}


def _rule(db: Session, org_id: int, rid: int) -> CompanyRule:
    r = db.get(CompanyRule, rid)
    if r is None or r.organization_id != org_id:
        raise _err(404, "Không thấy luật này. Tải lại tab Luật cứng.")
    return r


def _apply(db: Session, r: CompanyRule, data: dict, fields: set[str]) -> None:
    if "name" in fields:
        r.name = (data.get("name") or "").strip()[:200]
    if "kind" in fields:
        if data.get("kind") not in KINDS:
            raise _err(422, "Loại luật không hợp lệ — chọn: cụm từ, mẫu chữ (regex), công cụ cấm, công cụ cần duyệt, "
                            "dữ liệu cá nhân.")
        r.kind = data["kind"]
    if "pattern" in fields:
        r.pattern = (data.get("pattern") or "").strip()[:600]
    if "action" in fields and data.get("action"):
        r.action = data["action"]
    elif "kind" in fields and r.action not in ACTIONS[r.kind]:
        r.action = ACTIONS[r.kind][0]
    if r.action not in ACTIONS.get(r.kind, ()):
        raise _err(422, f"Luật loại {KIND_VI.get(r.kind, r.kind)} chỉ có cách xử lý: "
                        + ", ".join(ACTION_VI[a] for a in ACTIONS[r.kind]) + ".")
    if "message" in fields:
        r.message = (data.get("message") or "").strip()[:600]
    if "external_only" in fields:
        r.external_only = bool(data.get("external_only"))
    if "enabled" in fields:
        r.enabled = bool(data.get("enabled"))
    if "source_ref" in fields:
        ref = str(data.get("source_ref") or "").strip()[:64]
        r.source_ref = ref
        r.source = "charter" if ref else (r.source if r.source != "charter" else "manual")
    if "position_id" in fields:
        v = data.get("position_id")
        if v is not None:
            p = db.get(Position, v)
            if p is None or p.company_id != r.company_id:
                raise _err(422, f"Chức danh #{v} không thuộc công ty này.")
        r.position_id = v
    if not r.name:
        raise _err(422, "Luật cần có tên.")
    if not r.pattern:
        raise _err(422, "Luật cần nội dung: cụm từ / mẫu regex / tên công cụ / loại dữ liệu cá nhân.")
    if r.kind == "regex":
        try:
            re.compile(r.pattern)
        except re.error as exc:
            raise _err(422, f"Mẫu regex không hợp lệ: {exc}") from exc
        if re.search(r"\(\?[aiLmsux]", r.pattern) or "(?P" in r.pattern:
            raise _err(422, "Regex không được dùng cờ nội tuyến hoặc nhóm có tên kiểu Python (plugin chạy JavaScript).")
    if r.kind == "pii":
        bad = [x for x in [y.strip() for y in r.pattern.split(",")] if x and x not in PII]
        if bad:
            raise _err(422, "Dữ liệu cá nhân chỉ gồm: phone, email, cccd, card.")
    if r.kind in ("tool", "approval"):
        from app.services.tool_permissions import all_tools
        known = set(all_tools())
        unknown = [t for t in tools_of(r) if t not in known and not t.startswith(("exec", "browser", "web_", "message"))]
        if unknown:
            raise _err(422, "Không có công cụ: " + ", ".join(unknown) + ". Dùng tên công cụ công ty (company_…) hoặc "
                            "công cụ gateway (exec, browser, web_fetch, message).")


def list_rules(db: Session, org_id: int, company_id: int | None) -> dict:
    from app.services.company_foundation import _company, profile_row
    co = _company(db, org_id, company_id)
    rows = db.query(CompanyRule).filter(CompanyRule.company_id == co.id).order_by(CompanyRule.id).all()
    prof = profile_row(db, co.id)
    prohibitions = list((prof.prohibitions if prof else None) or [])
    covered = {r.source_ref for r in rows if r.source == "charter" and r.enabled}
    since = datetime.utcnow() - timedelta(days=30)
    viol = (db.query(RuleViolation).filter(RuleViolation.company_id == co.id).order_by(RuleViolation.id.desc())
            .limit(30).all())
    names = {m.id: m.name for m in db.query(Member).filter(Member.company_id == co.id).all()}
    return {"company_id": co.id, "company_name": co.name, "rules": [public_rule(db, r) for r in rows],
            "kinds": [{"key": k, "vi": KIND_VI[k], "actions": list(ACTIONS[k])} for k in KINDS],
            "templates": [{"key": k, **v} for k, v in TEMPLATES.items()],
            "prohibitions": [{"index": str(i), "text": t, "enforced": str(i) in covered} for i, t in enumerate(prohibitions)],
            "violations": [public_violation(v, names) for v in viol],
            "violations_30d": db.query(func.count(RuleViolation.id)).filter(
                RuleViolation.company_id == co.id, RuleViolation.created_at >= since).scalar() or 0,
            "seats": seat_compliance(db, co.id)}


def create_rule(db: Session, org_id: int, data: dict) -> CompanyRule:
    from app.services.company_foundation import _company
    co = _company(db, org_id, data.get("company_id"), write=True)
    tpl = TEMPLATES.get(data.get("template") or "")
    if data.get("template") and tpl is None:
        raise _err(422, "Không có mẫu luật này.")
    body = {**(tpl or {}), **{k: v for k, v in data.items() if v is not None and k not in ("company_id", "template")}}
    r = CompanyRule(organization_id=org_id, company_id=co.id, name="", kind=body.get("kind") or "phrase",
                    pattern="", action="", source="template" if tpl else "manual")
    _apply(db, r, body, set(body) | {"kind"})
    db.add(r); db.commit(); db.refresh(r)
    return r


def update_rule(db: Session, org_id: int, rid: int, data: dict) -> CompanyRule:
    r = _rule(db, org_id, rid)
    _apply(db, r, data, set(data))
    db.add(r); db.commit(); db.refresh(r)
    return r


def delete_rule(db: Session, org_id: int, rid: int) -> dict:
    r = _rule(db, org_id, rid)
    db.query(RuleViolation).filter(RuleViolation.rule_id == r.id).update({"rule_id": None})
    db.delete(r); db.commit()
    return {"deleted": rid}


# ------------------------------------------------------------------ luật của một ghế

def rules_for(db: Session, member: Member | None) -> list[dict]:
    if member is None or not member.company_id:
        return []
    q = db.query(CompanyRule).filter(CompanyRule.company_id == member.company_id, CompanyRule.enabled.is_(True))
    rows = [r for r in q.order_by(CompanyRule.id).all()
            if r.position_id is None or r.position_id == getattr(member, "position_id", None)]
    return [as_dict(r) for r in rows]


def agents_md_lines(db: Session, member: Member | None, position_id: int | None = None, company_id: int | None = None) -> list[str]:
    """Dòng "## Luật cứng" trong AGENTS.md (vẫn giữ chữ để model biết trước, plugin là lớp cưỡng chế)."""
    if member is not None:
        rules = rules_for(db, member)
    else:
        q = db.query(CompanyRule).filter(CompanyRule.company_id == company_id, CompanyRule.enabled.is_(True))
        rules = [as_dict(r) for r in q.all() if r.position_id in (None, position_id)]
    out = []
    for r in rules:
        what = {"tool": f"không dùng {r['pattern']}", "approval": f"{r['pattern']} phải có người duyệt",
                "pii": "không đưa " + ", ".join(PII_VI.get(x.strip(), x) for x in r["pattern"].split(",")) +
                       (" ra ngoài công ty" if r["external_only"] else "")}.get(r["kind"], r["message"] or r["name"])
        out.append(f"- {r['name']}: {what} (hệ thống {ACTION_VI.get(r['action'], r['action'])} nếu vi phạm)"[:240])
    return out[:20]


def compile_agent(db: Session, member: Member, agent: Agent) -> dict:
    from app.services.company_foundation import position_of
    pos = position_of(db, member)
    rules = rules_for(db, member)
    for r in rules:
        r["regex"] = [src for _l, src in regex_of(r)]
        r["tools"] = tools_of(r) if r["kind"] in ("tool", "approval") else []
    allowed = sorted(pos.allowed_tools or []) if pos is not None and pos.allowed_tools else None
    return {"seat": member.id, "company": member.company_id, "position": pos.id if pos else None,
            "rules": rules, "allowedCompanyTools": allowed}


def compile_all(db: Session, org_id: int | None = None) -> dict:
    q = db.query(Agent, Member).join(Member, Member.id == Agent.member_id).filter(
        Agent.lifecycle.notin_(("retired",)))
    if org_id is not None:
        q = q.filter(Member.organization_id == org_id)
    agents = {}
    for ag, m in q.all():
        c = compile_agent(db, m, ag)
        if c["rules"] or c["allowedCompanyTools"]:
            agents[ag.runtime_agent_id] = c
    return {"v": 1, "generated_at": datetime.utcnow().isoformat() + "Z", "replacement": REPLACEMENT, "agents": agents}


def report_token() -> str:
    from app.core.config import settings
    return hmac.new(settings.jwt_secret.encode(), b"clawcompany-guard-report", hashlib.sha256).hexdigest()[:40]


def report_url() -> str:
    from app.core.config import settings
    base = settings.clawcompany_mcp_url.rsplit("/api/", 1)[0]
    return f"{base}/api/guard/violations"


PLUGIN_CFG = ("plugins", "entries", "clawcompany-guard", "config")


async def push(db: Session, runtime: Any) -> dict:
    """Ghi bộ luật biên dịch lên gateway (một config.patch). Không có gateway thật → trả pushed False, không ném."""
    from app.services import agent_hr
    data = compile_all(db)   # một gateway dùng chung cho mọi tổ chức trên máy này
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if not agent_hr._has_rpc(runtime):
        return {"pushed": False, "reason": "no_gateway", "agents": len(data["agents"]), "bytes": len(raw)}
    from app.services.openclaw_config import ConfigRegistry
    reg = ConfigRegistry(runtime)
    snap = await reg.snapshot()
    await reg.patch({PLUGIN_CFG + ("rulesJson",): raw, PLUGIN_CFG + ("reportUrl",): report_url(),
                     PLUGIN_CFG + ("reportToken",): report_token()}, base_hash=snap.get("hash"),
                    note="ClawCompany: luật cứng cho guard plugin")
    return {"pushed": True, "agents": len(data["agents"]), "bytes": len(raw)}


# ------------------------------------------------------------------ vi phạm

def public_violation(v: RuleViolation, names: dict[int, str]) -> dict:
    return {"id": v.id, "member_id": v.member_id, "seat": names.get(v.member_id or -1), "rule_id": v.rule_id,
            "hook": v.hook, "action": v.action_taken, "action_vi": ACTION_VI.get(v.action_taken, v.action_taken),
            "excerpt": v.excerpt, "session_key": v.session_key,
            "created_at": v.created_at.isoformat() if v.created_at else None}


def record(db: Session, *, member: Member | None, agent_rid: str = "", rule_id: int | None, hook: str, action: str,
           excerpt: str = "", session_key: str = "", run_id: str = "") -> RuleViolation:
    from app.services import inbox
    rule = db.get(CompanyRule, rule_id) if rule_id else None
    if rule is not None and member is not None and rule.company_id != member.company_id:
        rule = None      # plugin cũ báo luật của công ty khác → không gán nhầm
    v = RuleViolation(organization_id=member.organization_id if member else (rule.organization_id if rule else 0),
                      company_id=member.company_id if member else (rule.company_id if rule else None),
                      member_id=member.id if member else None, rule_id=rule.id if rule else None,
                      agent_rid=agent_rid[:120], session_key=(session_key or "")[:240], run_id=(run_id or "")[:120],
                      hook=hook[:40], action_taken=action[:16], excerpt=redact(excerpt))
    db.add(v); db.commit(); db.refresh(v)
    if member is not None and member.manager_id:
        name = rule.name if rule else "luật cứng"
        inbox.notify(db, organization_id=v.organization_id, recipients=[member.manager_id], kind="rule_violation",
                     title=f"{member.name} vi phạm luật cứng: {name}"[:220], related_type="rule_violation_seat",
                     related_id=str(member.id), line=f"{name} — {ACTION_VI.get(action, action)} ({hook})",
                     source="guard", company_id=member.company_id)
    return v


def record_from_plugin(db: Session, payload: dict) -> dict:
    rid = str(payload.get("agentId") or "")[:160]
    ag = db.query(Agent).filter(Agent.runtime_agent_id == rid).first() if rid else None
    member = db.get(Member, ag.member_id) if ag else None
    if member is None:
        raise _err(404, "Không thấy seat của agent này.")
    rule_id = payload.get("ruleId")
    v = record(db, member=member, agent_rid=rid, rule_id=int(rule_id) if str(rule_id or "").isdigit() else None,
               hook=str(payload.get("hook") or ""), action=str(payload.get("action") or ""),
               excerpt=str(payload.get("excerpt") or ""), session_key=str(payload.get("sessionKey") or ""),
               run_id=str(payload.get("runId") or ""))
    return {"id": v.id}


def check_mcp_call(db: Session, member: Member, name: str, args: dict, *, session_key: str = "",
                   run_id: str = "") -> tuple[str, dict | None, dict]:
    """Cổng MCP: (``allow`` | ``block`` | ``approve``, luật, args có thể đã che chữ)."""
    rules = rules_for(db, member)
    if not rules:
        return "allow", None, args
    t = check_tool(rules, name)
    if t is not None:
        if t["action"] == "block":
            record(db, member=member, rule_id=t["rule_id"], hook="mcp", action="block", excerpt=name,
                   session_key=session_key, run_id=run_id)
        return t["action"], t, args
    if name in EXTERNAL_TOOLS:
        text = json.dumps(args, ensure_ascii=False, default=str)
        hits = check_text(rules, text, external=True)
        block = next((h for h in hits if h["action"] in ("block", "revise")), None)
        if block is not None:
            record(db, member=member, rule_id=block["rule_id"], hook="mcp", action="block", excerpt=text,
                   session_key=session_key, run_id=run_id)
            return "block", block, args
        if hits:
            clean = {k: (scrub(rules, v, external=True) if isinstance(v, str) else v) for k, v in args.items()}
            record(db, member=member, rule_id=hits[0]["rule_id"], hook="mcp", action="scrub", excerpt=text,
                   session_key=session_key, run_id=run_id)
            return "allow", hits[0], clean
    return "allow", None, args


# ------------------------------------------------------------------ tỷ lệ tuân thủ luật của ghế

def compliance(db: Session, member: Member, *, days: int = 30, now: datetime | None = None) -> dict:
    """Tỷ lệ lượt chạy không vi phạm = 1 − (lượt chạy có vi phạm / tổng lượt chạy) trong ``days`` ngày.
    Vi phạm không gắn được lượt chạy (chat, A2A) tính mỗi vi phạm là một lượt có vi phạm. Không có lượt chạy → None."""
    from app.models.work_graph import TaskRun
    since = (now or datetime.utcnow()) - timedelta(days=days)
    runs = db.query(func.count(TaskRun.id)).filter(TaskRun.member_id == member.id, TaskRun.created_at >= since).scalar() or 0
    vs = db.query(RuleViolation).filter(RuleViolation.member_id == member.id, RuleViolation.created_at >= since).all()
    with_run = {v.run_id for v in vs if v.run_id}
    without = sum(1 for v in vs if not v.run_id)
    bad = len(with_run) + without
    total = max(runs, bad)
    rate = None if total == 0 else round(1 - bad / total, 4)
    return {"runs": runs, "violations": len(vs), "violating_runs": bad, "rate": rate, "days": days}


def seat_compliance(db: Session, company_id: int) -> list[dict]:
    out = []
    for m in db.query(Member).filter(Member.company_id == company_id, Member.member_type == "agent",
                                     Member.status.notin_(("retired", "archived"))).order_by(Member.id).all():
        out.append({"member_id": m.id, "name": m.name, "rules": len(rules_for(db, m)), **compliance(db, m)})
    return out
