"""R2 — cho thuê agent (ghế). Spec: docs/r-rental-and-multi-company.md §R2.

Vòng đời: bên cho thuê tạo **chào thuê** (draft + mã ``offer_code``) từ một ghế agent của mình → bên thuê nhập mã,
chọn chức danh ở công ty mình → hệ thống tuyển một **ghế agent mới** trong công ty bên thuê (workspace, MEMORY.md,
phiên riêng; KHÔNG chép bộ nhớ nội bộ của bên cho thuê) → active. Hết hạn / kết thúc → retire ghế thuê (xoá
workspace + phiên trên gateway, xoá file/bộ nhớ/tài liệu riêng của ghế), giữ nguyên dòng đo đếm.

Chính sách xếp lớp (agent thuê tuân theo cả hai):
* **Sàn bên cho thuê** — điều cấm trong hiến chương bên cho thuê, luật cứng của công ty bên cho thuê (áp cho ghế
  nguồn), quy tắc xử lý dữ liệu, trần chi phí tháng, danh sách công cụ được phép. Biên dịch thành mục đầu tiên của
  "Kiến thức cốt lõi" trong AGENTS.md, đánh dấu KHÔNG GHI ĐÈ; luật cứng đi vào guard plugin + cổng MCP cùng luật
  bên thuê. Bên thuê không sửa/xoá được (khác tổ chức); sửa AGENTS.md mất mục sàn → 422.
* **Lớp bên thuê** — hiến chương, ma trận phân quyền, luật cứng, hợp đồng dữ liệu, tri thức của công ty bên thuê:
  có sẵn vì ghế thuê là một ghế của công ty bên thuê. Chỉ thêm/siết: công cụ = giao của (sàn) ∩ (chức danh bên
  thuê); trần chi = min(trần hợp đồng, hạn mức ghế bên thuê).

Đo đếm: mỗi lượt model thật của ghế thuê (``cost_ledger.record_message_usage``) → ``lease_usage`` kind=model, chi
phí thật × (1 + markup) ; việc xong → phí theo việc + phí theo giờ (thời lượng lượt chạy); phí tháng do tick ghi một
lần mỗi tháng. Chạm trần tháng → suspended + Hộp việc cả hai bên. A2A / cổng khách: kiểm hợp đồng trước khi gửi,
đo phiên sau khi trả lời (``meter_session``), ghi kênh + người gọi."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Agent, Company, KnowledgeDocument, Member, Organization
from app.models.leases import LEASE_STATUSES, LeaseUsage, SeatLease

FLOOR_HEADING = "## Sàn của bên cho thuê (KHÔNG ĐƯỢC GHI ĐÈ)"
FLOOR_BUDGET = 4_000
SCOPE_BUDGET = 3_000
APPROVAL_DEFAULTS = {"business": "renter", "policy": "provider", "payer": "renter"}
SUPPORTED = {"business": ("renter",), "policy": ("provider",), "payer": ("renter",)}
CHANGE_FIELDS = ("allowed_tools", "monthly_cost_cap_usd", "data_handling", "knowledge_doc_ids", "ends_at")


def _err(status: int, msg: str) -> HTTPException:
    return HTTPException(status, msg)


def period_of(dt: datetime | None = None) -> str:
    return (dt or datetime.utcnow()).strftime("%Y-%m")


# ------------------------------------------------------------------ tra cứu

def lease_of_member(db: Session, member_id: int | None, *, live_only: bool = False) -> SeatLease | None:
    if not member_id:
        return None
    q = db.query(SeatLease).filter(SeatLease.renter_member_id == member_id)
    q = q.filter(SeatLease.status.in_(("active", "suspended") if live_only else ("active", "suspended", "ended")))
    return q.order_by(SeatLease.id.desc()).first()


def lease_of_agent(db: Session, agent_id: int | None) -> SeatLease | None:
    if not agent_id:
        return None
    return (db.query(SeatLease).filter(SeatLease.renter_agent_id == agent_id,
                                       SeatLease.status.in_(("active", "suspended")))
            .order_by(SeatLease.id.desc()).first())


def _get(db: Session, lease_id: int) -> SeatLease:
    ls = db.get(SeatLease, lease_id)
    if ls is None:
        raise _err(404, "Không thấy hợp đồng thuê này.")
    return ls


def side_of(ls: SeatLease, org_id: int) -> str:
    if ls.provider_org_id == org_id:
        return "provider"
    if ls.renter_org_id == org_id:
        return "renter"
    raise _err(404, "Không thấy hợp đồng thuê này.")


def _policy(ls: SeatLease) -> dict:
    return {**APPROVAL_DEFAULTS, **(ls.approval_policy or {})}


def scope_doc_ids(ls: SeatLease | None) -> list[int]:
    return [int(x) for x in ((ls.knowledge_scope or {}).get("doc_ids") or [])] if ls else []


# ------------------------------------------------------------------ tiền

def _money(v, label: str, *, allow_none: bool = False) -> float | None:
    if v in (None, ""):
        if allow_none:
            return None
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise _err(422, f"{label} phải là số (USD).")
    if f < 0:
        raise _err(422, f"{label} không được âm.")
    return round(f, 6)


def billed_of(ls: SeatLease, cost_usd: float) -> float:
    return round(float(cost_usd or 0) * (1 + float(ls.markup_pct or 0) / 100.0), 8)


def month_totals(db: Session, ls: SeatLease, period: str | None = None) -> dict:
    period = period or period_of()
    rows = (db.query(LeaseUsage.kind, func.coalesce(func.sum(LeaseUsage.cost_usd), 0.0),
                     func.coalesce(func.sum(LeaseUsage.billed_usd), 0.0), func.count(LeaseUsage.id))
            .filter(LeaseUsage.lease_id == ls.id, LeaseUsage.period == period).group_by(LeaseUsage.kind).all())
    by = {k: {"cost_usd": round(float(c), 6), "billed_usd": round(float(b), 6), "count": int(n)} for k, c, b, n in rows}
    return {"period": period, "by_kind": by,
            "cost_usd": round(sum(v["cost_usd"] for v in by.values()), 6),
            "billed_usd": round(sum(v["billed_usd"] for v in by.values()), 6)}


# ------------------------------------------------------------------ sàn bên cho thuê

def provider_rules(db: Session, ls: SeatLease) -> list[dict]:
    """Luật cứng của công ty bên cho thuê áp cho ghế nguồn (luật chung + luật chức danh nguồn), đánh dấu sàn."""
    from app.models.agent_native import CompanyRule
    from app.services import runtime_rules
    src = db.get(Member, ls.provider_member_id)
    q = db.query(CompanyRule).filter(CompanyRule.company_id == ls.provider_company_id, CompanyRule.enabled.is_(True))
    out = []
    for r in q.order_by(CompanyRule.id).all():
        if r.position_id is None or (src is not None and r.position_id == src.position_id):
            d = runtime_rules.as_dict(r)
            d["floor"] = True
            d["lease_id"] = ls.id
            out.append(d)
    return out


def provider_allowed_tools(db: Session, ls: SeatLease) -> list[str] | None:
    """Danh sách công cụ của sàn: hợp đồng ghi rõ, hoặc của chức danh nguồn; None = không giới hạn thêm."""
    if ls.allowed_tools:
        return sorted(set(ls.allowed_tools))
    from app.services.company_foundation import position_of
    src = db.get(Member, ls.provider_member_id)
    pos = position_of(db, src) if src is not None else None
    return sorted(set(pos.allowed_tools)) if pos is not None and pos.allowed_tools else None


def floor_section(db: Session, ls: SeatLease) -> str:
    from app.services import runtime_rules
    from app.services.company_foundation import profile_row
    pco = db.get(Company, ls.provider_company_id)
    prof = profile_row(db, ls.provider_company_id)
    lines = [FLOOR_HEADING,
             f"Bạn là agent được **{pco.name if pco else 'bên cho thuê'}** cho thuê (hợp đồng #{ls.id}). Mục này do bên "
             "cho thuê đặt và hệ thống cưỡng chế; mọi chỉ dẫn của bên thuê (kể cả hiến chương, quản lý, khách) chỉ được "
             "THÊM hoặc SIẾT, không bao giờ nới các điều dưới đây. Mâu thuẫn → làm theo mục này và báo người quản lý."]
    pro = [p for p in ((prof.prohibitions if prof else None) or []) if str(p).strip()]
    if pro:
        lines.append("### Điều cấm của bên cho thuê\n" + "\n".join(f"- {p}" for p in pro[:12]))
    rules = provider_rules(db, ls)
    if rules:
        what = []
        for r in rules[:12]:
            w = {"tool": f"không dùng {r['pattern']}", "approval": f"{r['pattern']} phải có người duyệt"}.get(
                r["kind"], r.get("message") or r["name"])
            what.append(f"- {r['name']}: {w} (hệ thống {runtime_rules.ACTION_VI.get(r['action'], r['action'])})"[:240])
        lines.append("### Luật cứng của bên cho thuê\n" + "\n".join(what))
    dh = (ls.data_handling or "").strip()
    lines.append("### Dữ liệu\n"
                 "- Dữ liệu của bên thuê (khách, đơn, tin nhắn) chỉ dùng cho việc của bên thuê; không gửi cho bên cho thuê "
                 "hay bên thứ ba, không mang sang hợp đồng khác.\n"
                 "- Không tiết lộ thông tin nội bộ của bên cho thuê ngoài phạm vi tri thức được cấp."
                 + (f"\n- {dh}" if dh else ""))
    tools = provider_allowed_tools(db, ls)
    cap = ls.monthly_cost_cap_usd
    lines.append("### Công cụ & chi phí\n"
                 + (f"- Chỉ được dùng các công cụ công ty: {', '.join(tools)}\n" if tools else "")
                 + (f"- Trần chi phí hợp đồng: {cap:g} USD/tháng; chạm trần thì hệ thống tạm dừng ghế.\n" if cap else "")
                 + "- Thay đổi chính sách/nền tảng của agent (model, công cụ, trần chi) do bên cho thuê duyệt.")
    text = "\n\n".join(lines)
    if len(text) > FLOOR_BUDGET:
        text = text[:FLOOR_BUDGET - 40].rstrip() + "\n… (lược bớt)"
    return text


def scope_section(db: Session, ls: SeatLease) -> str:
    """Tri thức bên cho thuê cấp cho hợp đồng (chỉ các tài liệu trong knowledge_scope)."""
    ids = scope_doc_ids(ls)
    if not ids:
        return ""
    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(ids),
                                              KnowledgeDocument.organization_id == ls.provider_org_id).all()
    if not docs:
        return ""
    parts, used = ["### Tri thức bên cho thuê cấp cho hợp đồng"], 0
    for d in docs:
        body = (d.content or "").strip()
        room = SCOPE_BUDGET - used
        if room <= 200:
            break
        chunk = body[:room - 80]
        parts.append(f"**{d.title}** [KB#{d.id}]\n{chunk}" + ("…" if len(body) > len(chunk) else ""))
        used += len(chunk) + len(d.title) + 20
    return "\n\n".join(parts)


def layered_core(db: Session, member: Member, renter_core: str) -> str:
    """Phần "Kiến thức cốt lõi" của ghế thuê = lớp bên thuê (có nhãn). Sàn + phạm vi tri thức đặt ở ĐẦU AGENTS.md
    bằng ``place_floor`` (trước cả vai trò/nhiệm vụ do bên thuê đặt)."""
    ls = lease_of_member(db, member.id, live_only=True)
    renter = renter_core.strip()
    if ls is None or not renter:
        return renter_core
    return "## Lớp của bên thuê (chỉ thêm/siết)\n" + renter


def place_floor(db: Session, member: Member | None, agents_md: str) -> str:
    """AGENTS.md của ghế thuê: tiêu đề → sàn bên cho thuê → tri thức được cấp → phần còn lại (lớp bên thuê)."""
    ls = lease_of_member(db, member.id, live_only=True) if member is not None else None
    if ls is None:
        return agents_md
    head, _, rest = agents_md.partition("\n")
    block = "\n\n".join(x for x in (floor_section(db, ls), scope_section(db, ls)) if x)
    return f"{head}\n\n{block}\n\n{rest.lstrip()}"


def effective_tools(db: Session, member: Member | None, position_tools: list[str] | None) -> list[str] | None:
    """Công cụ hiệu lực của ghế thuê = sàn ∩ chức danh bên thuê (None = không giới hạn)."""
    ls = lease_of_member(db, member.id, live_only=True) if member is not None else None
    floor = provider_allowed_tools(db, ls) if ls is not None else None
    if not floor:
        return position_tools
    return sorted(set(floor) & set(position_tools)) if position_tools else sorted(floor)


def check_agents_md(db: Session, agent: Agent, content: str) -> None:
    """Bên thuê sửa AGENTS.md của ghế thuê: không được bỏ / sửa mục sàn."""
    ls = lease_of_agent(db, agent.id)
    if ls is None:
        return
    floor = floor_section(db, ls)
    if floor not in content:
        raise _err(422, "AGENTS.md của agent thuê phải giữ nguyên mục \"Sàn của bên cho thuê\" — bên thuê chỉ thêm/siết.")


# ------------------------------------------------------------------ cổng: công cụ, chi phí, trạng thái

def tool_gate(db: Session, member: Member, tool: str) -> tuple[str, str] | None:
    ls = lease_of_member(db, member.id, live_only=False)
    if ls is None:
        return None
    if ls.status != "active":
        return "off", f"lease:{ls.id}:{ls.status}"
    if not tool.startswith("company_"):
        return None
    from app.services.tool_permissions import ALWAYS_ALLOWED
    allowed = provider_allowed_tools(db, ls)
    if allowed and tool not in allowed and tool not in ALWAYS_ALLOWED:
        return "off", f"lease:{ls.id}"
    return None


def block_reason(db: Session, member: Member | None, now: datetime | None = None) -> str:
    """Lý do ghế thuê không được chạy (rỗng = chạy được)."""
    if member is None:
        return ""
    ls = lease_of_member(db, member.id)
    if ls is None:
        return ""
    now = now or datetime.utcnow()
    if ls.status == "ended":
        return f"Hợp đồng thuê #{ls.id} đã kết thúc."
    if ls.status == "suspended":
        return f"Hợp đồng thuê #{ls.id} đang tạm dừng: {ls.status_reason or 'chạm trần chi phí'}."
    if ls.ends_at and now >= ls.ends_at:
        return f"Hợp đồng thuê #{ls.id} đã hết hạn ({ls.ends_at:%Y-%m-%d %H:%M} UTC)."
    if ls.starts_at and now < ls.starts_at:
        return f"Hợp đồng thuê #{ls.id} chưa tới ngày bắt đầu."
    if ls.monthly_cost_cap_usd:
        t = month_totals(db, ls)
        if t["billed_usd"] >= ls.monthly_cost_cap_usd:
            return f"Hợp đồng thuê #{ls.id} đã chạm trần {ls.monthly_cost_cap_usd:g} USD tháng {t['period']}."
    return ""


# ------------------------------------------------------------------ đo đếm

def _add(db: Session, ls: SeatLease, **kw) -> LeaseUsage:
    row = LeaseUsage(lease_id=ls.id, period=kw.pop("period", None) or period_of(), **kw)
    db.add(row); db.flush()
    return row


def on_model_usage(db: Session, *, agent_id: int | None, usage_event, run=None, session_key: str = "",
                   channel: str = "task", caller: str = "", tokens_in: int = 0, tokens_out: int = 0) -> LeaseUsage | None:
    """Một lượt model thật của ghế thuê → dòng đo đếm (chi phí thật + số tiền tính cho bên thuê)."""
    ls = lease_of_agent(db, agent_id)
    if ls is None:
        return None
    cost = float(getattr(usage_event, "amount", 0) or 0)
    row = _add(db, ls, kind="model", usage_event_id=getattr(usage_event, "id", None),
               task_run_id=run.id if run is not None else None,
               task_id=getattr(usage_event, "task_id", None), session_key=session_key[:200], channel=channel,
               caller=caller[:200], cost_usd=cost, billed_usd=billed_of(ls, cost),
               tokens_in=tokens_in, tokens_out=tokens_out)
    if run is not None:
        run.lease_id = ls.id
        run.billed_usd = round((run.billed_usd or 0) + row.billed_usd, 8)
        db.add(run)
    db.commit()
    enforce_cap(db, ls)
    return row


def on_run_end(db: Session, run, *, commit: bool = True) -> list[LeaseUsage]:
    """Lượt chạy việc của ghế thuê kết thúc thành công → phí theo việc + phí theo giờ."""
    if run is None or run.member_id is None or run.status not in ("succeeded", "completed"):
        return []
    ls = lease_of_member(db, run.member_id, live_only=True)
    if ls is None:
        return []
    if db.query(LeaseUsage.id).filter(LeaseUsage.task_run_id == run.id,
                                      LeaseUsage.kind.in_(("task_fee", "hour_fee"))).first():
        return []
    out = []
    if ls.price_per_task_usd:
        out.append(_add(db, ls, kind="task_fee", task_run_id=run.id, task_id=run.task_id,
                        cost_usd=0.0, billed_usd=float(ls.price_per_task_usd)))
    if ls.price_per_hour_usd and run.started_at and run.ended_at:
        hours = max(0.0, (run.ended_at - run.started_at).total_seconds() / 3600.0)
        out.append(_add(db, ls, kind="hour_fee", task_run_id=run.id, task_id=run.task_id, quantity=round(hours, 6),
                        cost_usd=0.0, billed_usd=round(hours * float(ls.price_per_hour_usd), 8)))
    if out:
        run.lease_id = ls.id
        run.billed_usd = round((run.billed_usd or 0) + sum(x.billed_usd for x in out), 8)
        db.add(run)
    if commit:
        db.commit()
        enforce_cap(db, ls)
    else:
        db.flush()   # người gọi commit; trần được kiểm ở lượt model kế tiếp / tick
    return out


def month_fee(db: Session, ls: SeatLease, now: datetime | None = None) -> LeaseUsage | None:
    if not ls.price_per_month_usd or ls.status != "active":
        return None
    p = period_of(now)
    if db.query(LeaseUsage.id).filter(LeaseUsage.lease_id == ls.id, LeaseUsage.kind == "month_fee",
                                      LeaseUsage.period == p).first():
        return None
    row = _add(db, ls, kind="month_fee", period=p, cost_usd=0.0, billed_usd=float(ls.price_per_month_usd))
    db.commit()
    return row


async def meter_session(db: Session, runtime: Any, member: Member, agent: Agent, session_key: str, *,
                        channel: str, caller: str = "") -> LeaseUsage | None:
    """A2A / cổng khách: không có task_run → lấy usage của phiên từ gateway (sessions.usage), ghi phần chênh so với
    đã đo cho phiên này."""
    ls = lease_of_agent(db, agent.id)
    if ls is None:
        return None
    from app.services import cost_ledger
    try:
        gw = await cost_ledger.fetch_gateway_usage(runtime, session_key)
        u = gw.get("usage") or {}
    except Exception as exc:  # noqa: BLE001 — không đo được thì báo trong sự kiện, không chặn câu trả lời
        print(f"[lease] meter {session_key}: {exc}")
        return None
    total = float(u.get("cost_usd") or 0)
    seen = (db.query(func.coalesce(func.sum(LeaseUsage.cost_usd), 0.0))
            .filter(LeaseUsage.lease_id == ls.id, LeaseUsage.session_key == session_key[:200],
                    LeaseUsage.kind == "model").scalar() or 0.0)
    delta = round(total - float(seen), 10)
    if delta <= 0:
        return None
    from app.services.metering import record_usage
    ev = record_usage(db, organization_id=member.organization_id, agent_id=agent.id, task_id=None,
                      runtime_run_id="", event_type="model_usage", quantity=1, unit="model_call", unit_cost=delta,
                      metadata={"session_key": session_key, "source": f"lease.{channel}", "lease_id": ls.id,
                                "caller": caller})
    return on_model_usage(db, agent_id=agent.id, usage_event=ev, session_key=session_key, channel=channel,
                          caller=caller, tokens_in=int(u.get("input") or 0), tokens_out=int(u.get("output") or 0))


def enforce_cap(db: Session, ls: SeatLease) -> bool:
    if ls.status != "active" or not ls.monthly_cost_cap_usd:
        return False
    t = month_totals(db, ls)
    if t["billed_usd"] < ls.monthly_cost_cap_usd:
        return False
    ls.status = "suspended"
    ls.status_reason = f"Chạm trần {ls.monthly_cost_cap_usd:g} USD tháng {t['period']} (đã tính {t['billed_usd']:.4f} USD)."
    db.add(ls); db.commit()
    _notify_both(db, ls, "budget_exhausted", f"Agent thuê #{ls.id} tạm dừng: chạm trần chi phí tháng",
                 line=ls.status_reason)
    return True


# ------------------------------------------------------------------ Hộp việc hai bên

def _owner_seat(db: Session, org_id: int | None, company_id: int | None) -> int | None:
    if not org_id:
        return None
    from app.services import authority
    return authority.owner_member(db, org_id, company_id)


def _notify_both(db: Session, ls: SeatLease, kind: str, title: str, *, line: str = "") -> None:
    from app.services import inbox
    for org, co in ((ls.provider_org_id, ls.provider_company_id), (ls.renter_org_id, ls.renter_company_id)):
        who = _owner_seat(db, org, co)
        if org and who:
            try:
                inbox.notify(db, organization_id=org, recipients=[who], kind=kind, title=title, line=line[:300],
                             related_type="seat_lease", related_id=str(ls.id), source="seat_lease", company_id=co)
            except Exception as exc:  # noqa: BLE001
                print(f"[lease] notify {exc}")


# ------------------------------------------------------------------ vòng đời

def _clean_policy(data: dict | None) -> dict:
    p = {**APPROVAL_DEFAULTS, **{k: v for k, v in (data or {}).items() if v}}
    for k, allowed in SUPPORTED.items():
        if p[k] not in allowed:
            raise _err(422, f"approval_policy.{k}='{p[k]}' chưa hỗ trợ (chỉ {', '.join(allowed)}).")
    return {k: p[k] for k in SUPPORTED}


def _dt(v, label: str) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", ""))
    except ValueError:
        raise _err(422, f"{label} phải là ngày giờ ISO (UTC).")


def _apply_terms(db: Session, ls: SeatLease, data: dict) -> None:
    for f, label in (("price_per_task_usd", "Giá mỗi việc"), ("price_per_hour_usd", "Giá mỗi giờ"),
                     ("price_per_month_usd", "Giá mỗi tháng"), ("markup_pct", "Markup %")):
        if f in data:
            setattr(ls, f, _money(data[f], label))
    if "monthly_cost_cap_usd" in data:
        ls.monthly_cost_cap_usd = _money(data["monthly_cost_cap_usd"], "Trần chi phí tháng", allow_none=True)
    if "allowed_tools" in data:
        from app.services import company_mcp
        tools = [t for t in (data["allowed_tools"] or []) if t]
        bad = [t for t in tools if t not in company_mcp.TOOLS]
        if bad:
            raise _err(422, "Công cụ không có: " + ", ".join(bad))
        ls.allowed_tools = sorted(set(tools)) or None
    if "knowledge_doc_ids" in data:
        ids = sorted({int(x) for x in (data["knowledge_doc_ids"] or [])})
        if ids:
            n = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(ids),
                                                   KnowledgeDocument.organization_id == ls.provider_org_id).count()
            if n != len(ids):
                raise _err(422, "Tài liệu trong phạm vi tri thức phải thuộc tổ chức bên cho thuê.")
        ls.knowledge_scope = {"doc_ids": ids}
    if "data_handling" in data:
        ls.data_handling = str(data["data_handling"] or "")[:2000]
    for f in ("starts_at", "ends_at", "offer_expires_at"):
        if f in data:
            setattr(ls, f, _dt(data[f], f))
    if ls.starts_at and ls.ends_at and ls.ends_at <= ls.starts_at:
        raise _err(422, "Ngày kết thúc phải sau ngày bắt đầu.")
    if "approval_policy" in data:
        ls.approval_policy = _clean_policy(data["approval_policy"])
    if "name" in data and data["name"]:
        ls.name = str(data["name"])[:200]


def create_offer(db: Session, org_id: int, principal, data: dict) -> dict:
    from app.core import company_scope
    from app.services import agent_versions
    ag = db.get(Agent, int(data.get("provider_agent_id") or 0))
    m = db.get(Member, ag.member_id) if ag else None
    if ag is None or m is None or m.organization_id != org_id or m.member_type != "agent":
        raise _err(404, "Không thấy agent nguồn trong tổ chức của anh.")
    if lease_of_member(db, m.id) is not None:
        raise _err(422, "Agent này đang là agent đi thuê — không cho thuê lại.")
    company_scope.check(m.company_id, min_role="admin")
    ls = SeatLease(offer_code=secrets.token_urlsafe(9)[:12], status="draft", provider_org_id=org_id,
                   provider_company_id=m.company_id, provider_member_id=m.id, provider_agent_id=ag.id,
                   provider_version=agent_versions.latest_version_number(db, ag.id) or None,
                   name=f"{m.name} — cho thuê", created_by_user_id=getattr(principal, "user_id", None),
                   approval_policy=dict(APPROVAL_DEFAULTS))
    _apply_terms(db, ls, data)
    if not ls.offer_expires_at:
        ls.offer_expires_at = datetime.utcnow() + timedelta(days=14)
    db.add(ls); db.commit(); db.refresh(ls)
    return view(db, ls, org_id)


async def accept(db: Session, org_id: int, principal, runtime: Any, data: dict) -> dict:
    """Bên thuê nhận lời: tuyển ghế agent mới trong công ty bên thuê vào chức danh đã chọn."""
    from app.core import company_scope
    from app.services import agent_hr, runtime_rules
    code = str(data.get("offer_code") or "").strip()
    ls = db.query(SeatLease).filter(SeatLease.offer_code == code).first() if code else None
    if ls is None or ls.status != "draft":
        raise _err(404, "Mã chào thuê không đúng hoặc đã dùng.")
    if ls.offer_expires_at and datetime.utcnow() > ls.offer_expires_at:
        raise _err(410, "Chào thuê đã hết hạn — xin bên cho thuê mã mới.")
    if ls.provider_org_id == org_id:
        raise _err(422, "Không tự thuê agent của chính tổ chức mình — dùng điều chuyển nội bộ.")
    co = db.get(Company, int(data.get("company_id") or 0))
    if co is None or co.organization_id != org_id or co.status == "archived":
        raise _err(404, "Không thấy công ty bên thuê.")
    company_scope.check(co.id, min_role="admin")
    pos_id = data.get("position_id")
    if not pos_id:
        raise _err(422, "Cần chọn chức danh ở công ty bên thuê cho agent thuê.")
    src_ag, src = db.get(Agent, ls.provider_agent_id), db.get(Member, ls.provider_member_id)
    spec = agent_hr.hire_spec(db, src_ag) if src_ag else {}
    pco = db.get(Company, ls.provider_company_id)
    hire_data = {"name": str(data.get("name") or src.name)[:120], "company_id": co.id, "position_id": int(pos_id),
                 "department_id": data.get("department_id"), "personality": spec.get("personality") or "than-thien",
                 "emoji": spec.get("emoji") or "", "address_style": spec.get("address_style") or None,
                 "job_description": spec.get("job_description") or "",
                 "manager_notes": (spec.get("manager_notes") or "") + f"\n- Agent thuê từ {pco.name if pco else 'bên cho thuê'} (hợp đồng #{ls.id}).",
                 "monthly_budget": ls.monthly_cost_cap_usd, "model_policy": spec.get("model_policy")}
    hire_data = {k: v for k, v in hire_data.items() if v is not None}
    out = await agent_hr.hire(db, principal, org_id, runtime, hire_data)
    ls.renter_org_id, ls.renter_company_id, ls.renter_position_id = org_id, co.id, int(pos_id)
    ls.renter_member_id, ls.renter_agent_id = out["member_id"], out["agent_id"]
    ls.status, ls.activated_at = "active", datetime.utcnow()
    ls.starts_at = ls.starts_at or ls.activated_at
    ls.accepted_by_user_id = getattr(principal, "user_id", None)
    db.add(ls); db.commit()
    # AGENTS.md giờ mới biết hợp đồng → sinh lại để có sàn + phạm vi tri thức; luật sàn lên guard plugin
    ag, m = db.get(Agent, ls.renter_agent_id), db.get(Member, ls.renter_member_id)
    regen = await agent_hr._regen(db, runtime, ag, m, ("AGENTS.md",), getattr(principal, "user_id", None),
                                  force=("AGENTS.md",))
    try:
        pushed = await runtime_rules.push(db, runtime)
    except Exception as exc:  # noqa: BLE001
        pushed = {"pushed": False, "error": str(exc)}
    month_fee(db, ls)
    _notify_both(db, ls, "mention", f"Hợp đồng thuê #{ls.id} bắt đầu: {m.name}",
                 line=f"Bên thuê: {co.name}. Giá: {terms_line(ls)}")
    return {**view(db, ls, org_id), "hire": {k: out.get(k) for k in ("agent_id", "member_id", "runtime_agent_id",
                                                                        "warnings")},
            "agents_md": regen.get("AGENTS.md"), "rules_push": pushed}


def terms_line(ls: SeatLease) -> str:
    parts = []
    if ls.price_per_task_usd:
        parts.append(f"{ls.price_per_task_usd:g} USD/việc")
    if ls.price_per_hour_usd:
        parts.append(f"{ls.price_per_hour_usd:g} USD/giờ")
    if ls.price_per_month_usd:
        parts.append(f"{ls.price_per_month_usd:g} USD/tháng")
    parts.append(f"chi phí model thật + {ls.markup_pct or 0:g}%")
    if ls.monthly_cost_cap_usd:
        parts.append(f"trần {ls.monthly_cost_cap_usd:g} USD/tháng")
    return " · ".join(parts)


def update_terms(db: Session, org_id: int, lease_id: int, data: dict) -> dict:
    """Bên cho thuê sửa điều khoản (chính sách/nền tảng của agent). Bên thuê → change request."""
    ls = _get(db, lease_id)
    if side_of(ls, org_id) != "provider":
        raise _err(403, "Chỉ bên cho thuê sửa điều khoản; bên thuê gửi yêu cầu thay đổi.")
    from app.core import company_scope
    company_scope.check(ls.provider_company_id, min_role="admin")
    if ls.status == "ended":
        raise _err(409, "Hợp đồng đã kết thúc.")
    allowed = set(CHANGE_FIELDS) | {"price_per_task_usd", "price_per_hour_usd", "price_per_month_usd", "markup_pct",
                                    "name", "offer_expires_at", "starts_at", "approval_policy"}
    if ls.status != "draft":   # giá chỉ đổi khi còn là chào thuê
        allowed -= {"price_per_task_usd", "price_per_hour_usd", "price_per_month_usd", "markup_pct", "starts_at"}
    bad = sorted(set(data) - allowed)
    if bad:
        raise _err(422, "Không sửa được sau khi hợp đồng chạy: " + ", ".join(bad))
    _apply_terms(db, ls, data)
    db.add(ls); db.commit()
    if ls.status == "suspended" and not block_reason(db, db.get(Member, ls.renter_member_id)).startswith("Hợp đồng thuê"):
        pass
    _resync_later(ls)
    if ls.status != "draft":
        _notify_both(db, ls, "mention", f"Bên cho thuê đổi điều khoản hợp đồng #{ls.id}", line=", ".join(sorted(data)))
    return view(db, ls, org_id)


def request_change(db: Session, org_id: int, principal, lease_id: int, data: dict) -> dict:
    ls = _get(db, lease_id)
    if side_of(ls, org_id) != "renter":
        raise _err(403, "Chỉ bên thuê gửi yêu cầu thay đổi.")
    changes = {k: v for k, v in (data.get("changes") or {}).items() if k in CHANGE_FIELDS}
    if not changes:
        raise _err(422, "Yêu cầu không có thay đổi hợp lệ (" + ", ".join(CHANGE_FIELDS) + ").")
    reqs = list(ls.change_requests or [])
    cr = {"id": len(reqs) + 1, "changes": changes, "note": str(data.get("note") or "")[:500], "status": "pending",
          "by_user_id": getattr(principal, "user_id", None), "at": datetime.utcnow().isoformat() + "Z"}
    reqs.append(cr); ls.change_requests = reqs; db.add(ls); db.commit()
    from app.services import inbox
    who = _owner_seat(db, ls.provider_org_id, ls.provider_company_id)
    if who:
        inbox.notify(db, organization_id=ls.provider_org_id, recipients=[who], kind="approval_pending",
                     title=f"Bên thuê xin đổi hợp đồng #{ls.id}", line=", ".join(sorted(changes)),
                     related_type="seat_lease", related_id=str(ls.id), source="seat_lease",
                     company_id=ls.provider_company_id)
    return cr


def decide_change(db: Session, org_id: int, lease_id: int, cr_id: int, decision: str) -> dict:
    ls = _get(db, lease_id)
    if side_of(ls, org_id) != "provider":
        raise _err(403, "Chỉ bên cho thuê duyệt thay đổi chính sách của agent.")
    reqs = [dict(x) for x in (ls.change_requests or [])]
    cr = next((x for x in reqs if x["id"] == cr_id), None)
    if cr is None or cr["status"] != "pending":
        raise _err(404, "Không thấy yêu cầu đang chờ này.")
    if decision not in ("approved", "rejected"):
        raise _err(422, "decision là approved hoặc rejected.")
    if decision == "approved":
        _apply_terms(db, ls, cr["changes"])
    cr["status"] = decision; cr["decided_at"] = datetime.utcnow().isoformat() + "Z"
    ls.change_requests = reqs; db.add(ls); db.commit()
    _resync_later(ls)
    _notify_both(db, ls, "mention", f"Yêu cầu đổi hợp đồng #{ls.id}: {'đã duyệt' if decision == 'approved' else 'bị từ chối'}")
    return cr


def _resync_later(ls: SeatLease) -> None:
    """Sàn đổi → sinh lại AGENTS.md của ghế thuê + đẩy luật (nền, không chặn request)."""
    if not ls.renter_agent_id:
        return
    import threading

    def run(lease_id: int):
        import asyncio
        from app.db.session import SessionLocal
        from app.runtime.factory import get_runtime
        from app.services import agent_hr, runtime_rules
        db = SessionLocal()
        try:
            x = db.get(SeatLease, lease_id)
            ag, m = db.get(Agent, x.renter_agent_id), db.get(Member, x.renter_member_id)
            rt = get_runtime()

            async def go():
                await agent_hr._regen(db, rt, ag, m, ("AGENTS.md",), None, force=("AGENTS.md",))
                await runtime_rules.push(db, rt)
            asyncio.run(go())
        except Exception as exc:  # noqa: BLE001
            print(f"[lease] resync {lease_id}: {exc}")
        finally:
            db.close()
    threading.Thread(target=run, args=(ls.id,), daemon=True).start()


def set_status(db: Session, org_id: int, lease_id: int, action: str, reason: str = "") -> dict:
    ls = _get(db, lease_id)
    side = side_of(ls, org_id)
    if action == "suspend":
        if side != "provider" or ls.status != "active":
            raise _err(409, "Chỉ bên cho thuê tạm dừng một hợp đồng đang chạy.")
        ls.status, ls.status_reason = "suspended", reason or "Bên cho thuê tạm dừng."
    elif action == "resume":
        if side != "provider" or ls.status != "suspended":
            raise _err(409, "Chỉ bên cho thuê tiếp tục một hợp đồng đang tạm dừng.")
        if ls.monthly_cost_cap_usd and month_totals(db, ls)["billed_usd"] >= ls.monthly_cost_cap_usd:
            raise _err(409, "Vẫn đang chạm trần tháng này — nâng trần (sửa điều khoản) rồi tiếp tục.")
        ls.status, ls.status_reason = "active", ""
    else:
        raise _err(422, "action là suspend hoặc resume (kết thúc: POST /leases/{id}/end).")
    db.add(ls); db.commit()
    _notify_both(db, ls, "mention", f"Hợp đồng thuê #{ls.id}: {'tạm dừng' if action == 'suspend' else 'chạy lại'}",
                 line=ls.status_reason)
    return view(db, ls, org_id)


async def end(db: Session, ls: SeatLease, runtime: Any, *, reason: str, principal=None) -> dict:
    """Kết thúc: retire ghế thuê (xoá workspace + phiên trên gateway), xoá dữ liệu bên thuê trong ghế (file chụp,
    bộ nhớ, tài liệu riêng, khoá A2A), giữ nguyên lease_usage / usage_events / task_runs."""
    from app.core.authz import Principal
    from app.models.a2a import A2AExposure
    from app.models.agent_hr import AgentFileSnapshot
    from app.services import agent_hr
    if ls.status == "ended":
        return {"lease_id": ls.id, "noop": True}
    report: dict[str, Any] = {"reason": reason}
    if ls.status == "draft" or not ls.renter_agent_id:
        ls.status, ls.ended_at, ls.status_reason = "ended", datetime.utcnow(), reason
        db.add(ls); db.commit()
        return {"lease_id": ls.id, "status": "ended", "report": report}
    ag, m = db.get(Agent, ls.renter_agent_id), db.get(Member, ls.renter_member_id)
    sysp = principal or Principal(user_id=None, organization_id=ls.renter_org_id, role="owner", auth_type="jwt", scopes=[])
    ls.status = "ended"; db.add(ls); db.commit()   # chặn mọi lượt mới ngay
    try:
        if ag is not None and ag.lifecycle != "retired":
            r = await agent_hr.lifecycle(db, sysp, ls.renter_org_id, runtime, ag.id, action="retire",
                                         remove_from_gateway=True, reason=f"Kết thúc thuê #{ls.id}: {reason}")
            report["retire"] = {k: r.get(k) for k in ("gateway", "tasks_reassigned", "api_keys_disabled", "warnings")}
    except Exception as exc:  # noqa: BLE001
        report["retire_error"] = str(exc)[:300]
    if ag is not None:
        report["snapshots_deleted"] = db.query(AgentFileSnapshot).filter(AgentFileSnapshot.agent_id == ag.id).delete()
        report["a2a_exposures_deleted"] = db.query(A2AExposure).filter(A2AExposure.agent_id == ag.id).delete()
        report["agent_docs_deleted"] = db.query(KnowledgeDocument).filter(KnowledgeDocument.agent_id == ag.id).delete()
        try:
            from app.models import OrganizationMemory
            report["memories_deleted"] = db.query(OrganizationMemory).filter(
                getattr(OrganizationMemory, "agent_id") == ag.id).delete()
        except Exception:  # noqa: BLE001 — bảng không có cột agent_id → không có bộ nhớ riêng ở đó
            db.rollback()
    report["usage_rows_kept"] = db.query(LeaseUsage).filter(LeaseUsage.lease_id == ls.id).count()
    ls.ended_at = ls.wiped_at = datetime.utcnow()
    ls.status_reason = reason
    ls.wipe_report = report
    db.add(ls); db.commit()
    _notify_both(db, ls, "mention", f"Hợp đồng thuê #{ls.id} đã kết thúc — dữ liệu bên thuê trong ghế đã xoá",
                 line=reason)
    return {"lease_id": ls.id, "status": "ended", "report": report}


async def end_by(db: Session, org_id: int, principal, runtime: Any, lease_id: int, reason: str = "") -> dict:
    ls = _get(db, lease_id)
    side = side_of(ls, org_id)
    from app.core import company_scope
    company_scope.check(ls.provider_company_id if side == "provider" else ls.renter_company_id, min_role="admin")
    return await end(db, ls, runtime, reason=reason or f"Bên {'cho thuê' if side == 'provider' else 'thuê'} kết thúc")


async def tick(db: Session, runtime: Any, now: datetime | None = None) -> list[dict]:
    """Beat: hết hạn → kết thúc + dọn; phí tháng; chạm trần → tạm dừng; chào thuê quá hạn → ended."""
    now = now or datetime.utcnow()
    out = []
    for ls in db.query(SeatLease).filter(SeatLease.status.in_(("draft", "active", "suspended"))).all():
        try:
            if ls.status == "draft" and ls.offer_expires_at and now > ls.offer_expires_at:
                out.append(await end(db, ls, runtime, reason="Chào thuê hết hạn, chưa ai nhận"))
            elif ls.status != "draft" and ls.ends_at and now >= ls.ends_at:
                out.append(await end(db, ls, runtime, reason="Hết thời hạn thuê"))
            elif ls.status == "active":
                f = month_fee(db, ls, now)
                if f is not None:
                    out.append({"lease_id": ls.id, "month_fee": f.billed_usd})
                if enforce_cap(db, ls):
                    out.append({"lease_id": ls.id, "suspended": ls.status_reason})
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            out.append({"lease_id": ls.id, "error": str(exc)[:200]})
    return out


# ------------------------------------------------------------------ xem

def usage_summary(db: Session, ls: SeatLease) -> dict:
    tot = (db.query(func.coalesce(func.sum(LeaseUsage.cost_usd), 0.0), func.coalesce(func.sum(LeaseUsage.billed_usd), 0.0),
                    func.count(LeaseUsage.id)).filter(LeaseUsage.lease_id == ls.id).one())
    tasks = (db.query(func.count(func.distinct(LeaseUsage.task_run_id)))
             .filter(LeaseUsage.lease_id == ls.id, LeaseUsage.task_run_id.isnot(None)).scalar() or 0)
    by_channel = {c: {"calls": int(n), "billed_usd": round(float(b), 6)} for c, n, b in
                  db.query(LeaseUsage.channel, func.count(LeaseUsage.id), func.coalesce(func.sum(LeaseUsage.billed_usd), 0.0))
                  .filter(LeaseUsage.lease_id == ls.id).group_by(LeaseUsage.channel).all()}
    return {"cost_usd": round(float(tot[0]), 6), "billed_usd": round(float(tot[1]), 6),
            "margin_usd": round(float(tot[1]) - float(tot[0]), 6), "rows": int(tot[2]), "task_runs": int(tasks),
            "by_channel": by_channel, "month": month_totals(db, ls)}


def view(db: Session, ls: SeatLease, org_id: int) -> dict:
    side = side_of(ls, org_id)
    pco, rco = db.get(Company, ls.provider_company_id), db.get(Company, ls.renter_company_id) if ls.renter_company_id else None
    porg = db.get(Organization, ls.provider_org_id)
    rorg = db.get(Organization, ls.renter_org_id) if ls.renter_org_id else None
    src = db.get(Member, ls.provider_member_id)
    out = {"id": ls.id, "side": side, "name": ls.name, "status": ls.status, "status_reason": ls.status_reason,
           "provider": {"organization": porg.name if porg else "", "company": pco.name if pco else "",
                        "agent_name": src.name if src else "", "version": ls.provider_version},
           "renter": {"organization": rorg.name if rorg else "", "company": rco.name if rco else ""},
           "starts_at": ls.starts_at, "ends_at": ls.ends_at, "offer_expires_at": ls.offer_expires_at,
           "activated_at": ls.activated_at, "ended_at": ls.ended_at,
           "terms": {"price_per_task_usd": ls.price_per_task_usd, "price_per_hour_usd": ls.price_per_hour_usd,
                     "price_per_month_usd": ls.price_per_month_usd, "markup_pct": ls.markup_pct,
                     "monthly_cost_cap_usd": ls.monthly_cost_cap_usd, "line": terms_line(ls)},
           "floor": {"allowed_tools": provider_allowed_tools(db, ls), "knowledge_doc_ids": scope_doc_ids(ls),
                     "data_handling": ls.data_handling, "rules": len(provider_rules(db, ls))},
           "approval_policy": _policy(ls), "usage": usage_summary(db, ls),
           "change_requests": ls.change_requests or [], "wipe_report": ls.wipe_report}
    if side == "provider":
        # bên cho thuê chỉ thấy số đo đếm — không có ghế, việc, phiên hay dữ liệu của bên thuê
        out["offer_code"] = ls.offer_code if ls.status == "draft" else None
        out["provider"]["agent_id"] = ls.provider_agent_id
    else:
        out["renter"].update({"agent_id": ls.renter_agent_id, "member_id": ls.renter_member_id,
                              "position_id": ls.renter_position_id})
        out["block_reason"] = block_reason(db, db.get(Member, ls.renter_member_id)) if ls.renter_member_id else ""
    return out


def list_for(db: Session, org_id: int, side: str) -> dict:
    from app.core import company_scope
    if side == "provider":
        q = db.query(SeatLease).filter(SeatLease.provider_org_id == org_id)
        q = company_scope.scope_filter(q, SeatLease.provider_company_id, include_null=False)
    elif side == "renter":
        q = db.query(SeatLease).filter(SeatLease.renter_org_id == org_id)
        q = company_scope.scope_filter(q, SeatLease.renter_company_id, include_null=False)
    else:
        raise _err(422, "side là provider hoặc renter")
    rows = [view(db, x, org_id) for x in q.order_by(SeatLease.id.desc()).all()]
    totals = {"leases": len(rows), "active": sum(1 for r in rows if r["status"] == "active"),
              "billed_usd": round(sum(r["usage"]["billed_usd"] for r in rows), 6),
              "cost_usd": round(sum(r["usage"]["cost_usd"] for r in rows), 6),
              "month_billed_usd": round(sum(r["usage"]["month"]["billed_usd"] for r in rows), 6)}
    totals["margin_usd"] = round(totals["billed_usd"] - totals["cost_usd"], 6)
    return {"side": side, "items": rows, "totals": totals, "statuses": list(LEASE_STATUSES)}


def preview_offer(db: Session, code: str) -> dict:
    ls = db.query(SeatLease).filter(SeatLease.offer_code == code, SeatLease.status == "draft").first()
    if ls is None:
        raise _err(404, "Mã chào thuê không đúng hoặc đã dùng.")
    src = db.get(Member, ls.provider_member_id)
    pco = db.get(Company, ls.provider_company_id)
    return {"id": ls.id, "name": ls.name, "agent_name": src.name if src else "", "agent_role": src.role if src else "",
            "provider_company": pco.name if pco else "", "terms": terms_line(ls),
            "ends_at": ls.ends_at, "offer_expires_at": ls.offer_expires_at,
            "allowed_tools": provider_allowed_tools(db, ls), "approval_policy": _policy(ls)}


POLICY_FIELDS = ("model", "model_policy")


def guard_renter_edit(db: Session, agent_id: int, fields: set[str] | None = None, data: dict | None = None,
                      *, kind: str = "hr", tab: str = "") -> None:
    """Bên thuê sửa ghế thuê: thay đổi chính sách / nền tảng (model, cấu hình công cụ/quyền/hạn mức) → 403 kèm
    hướng dẫn gửi yêu cầu cho bên cho thuê; hạn mức ghế không được vượt trần hợp đồng."""
    ls = lease_of_agent(db, agent_id)
    if ls is None:
        return
    if kind == "config" and tab != "profile":   # tên/emoji hiển thị là của bên thuê; năng lực/quyền/hạn mức thì không
        raise _err(403, f"Cấu hình nền tảng của agent thuê do bên cho thuê duyệt (hợp đồng #{ls.id}). "
                        "Gửi yêu cầu thay đổi ở Đội ngũ → Agent đi thuê.")
    bad = sorted(set(fields or ()) & set(POLICY_FIELDS))
    if bad:
        raise _err(403, f"Đổi {', '.join(bad)} của agent thuê do bên cho thuê duyệt (hợp đồng #{ls.id}).")
    mb = (data or {}).get("monthly_budget")
    if mb is not None and ls.monthly_cost_cap_usd and float(mb) > ls.monthly_cost_cap_usd:
        raise _err(422, f"Hạn mức ghế không được vượt trần hợp đồng ({ls.monthly_cost_cap_usd:g} USD/tháng).")
