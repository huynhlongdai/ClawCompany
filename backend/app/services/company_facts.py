"""M3b — sự kiện công ty có nguồn + phát hiện mâu thuẫn v1 (số liệu). Spec: docs/company-knowledge-library-and-gaps.md §A6.

Trích XÁC ĐỊNH (regex trên chữ không dấu, không model) những số liệu hay lệch giữa các tài liệu: số ngày đổi trả, thời gian
hoàn tiền, tháng bảo hành, ngưỡng miễn phí vận chuyển, thời gian trả lời, giờ mở cửa, hotline. Mỗi sự kiện mang nguồn
(mã tài liệu + phiên bản + mục). Gửi duyệt một phiên bản → so với sự kiện ĐANG CÓ từ nguồn khác (tài liệu khác, nhập tay,
bảng có cấu trúc) → khác giá trị = mâu thuẫn: ghi vào phiên bản, Hộp việc cho hai chủ, duyệt cần xác nhận bỏ qua.

Giới hạn tự khai: chỉ bắt các mẫu câu thông dụng tiếng Việt kê trong PATTERNS; câu viết khác kiểu → không trích (không
báo sai, chỉ bỏ sót). Sự kiện nhập tay luôn thắng khi agent hỏi (company_fact_get trả mọi nguồn + cờ conflict)."""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import KnowledgeDocument
from app.models.documents import CompanyFact

KEYS = {
    "return_window_days": {"vi": "Số ngày đổi trả", "en": "Return window (days)", "unit": "ngày"},
    "refund_processing_hours": {"vi": "Thời gian hoàn tiền (giờ)", "en": "Refund processing (hours)", "unit": "giờ"},
    "warranty_months": {"vi": "Bảo hành (tháng)", "en": "Warranty (months)", "unit": "tháng"},
    "free_shipping_threshold_vnd": {"vi": "Ngưỡng miễn phí vận chuyển (VND)", "en": "Free-shipping threshold (VND)", "unit": "VND"},
    "response_minutes": {"vi": "Thời gian trả lời khách (phút)", "en": "Customer reply time (minutes)", "unit": "phút"},
    "opening_hours": {"vi": "Giờ mở cửa", "en": "Opening hours", "unit": ""},
    "hotline": {"vi": "Hotline", "en": "Hotline", "unit": ""},
}


def _u(text: str) -> str:
    from app.services.knowledge_hub import unaccent
    return unaccent((text or "").lower())


def _money(num: str, unit: str) -> float | None:
    n = num.replace(".", "").replace(",", "")
    try:
        v = float(n)
    except ValueError:
        return None
    unit = unit.strip()
    if unit in ("k", "nghin", "ngan"):
        v *= 1000
    elif unit == "trieu":
        v *= 1_000_000
    return v


def _hhmm(h: str, m: str | None) -> str:
    return f"{int(h):02d}:{int(m or 0):02d}"


# (khoá, regex trên chữ thường không dấu, hàm lấy (value, value_num))
PATTERNS = [
    ("return_window_days", re.compile(r"(?:doi tra|doi hang|tra hang|hoan tra)[^.\n]{0,60}?(\d{1,3})\s*ngay"),
     lambda m: (m.group(1), float(m.group(1)))),
    ("refund_processing_hours", re.compile(r"hoan tien[^.\n]{0,40}?(\d{1,3})\s*(?:gio|h)\b"),
     lambda m: (m.group(1), float(m.group(1)))),
    ("refund_processing_hours", re.compile(r"hoan tien[^.\n]{0,40}?(\d{1,2})\s*ngay"),
     lambda m: (str(int(m.group(1)) * 24), float(int(m.group(1)) * 24))),
    ("warranty_months", re.compile(r"bao hanh[^.\n]{0,40}?(\d{1,3})\s*thang"), lambda m: (m.group(1), float(m.group(1)))),
    ("free_shipping_threshold_vnd", re.compile(r"(?:mien phi|free)\s*(?:van chuyen|ship|giao hang)[^.\n]{0,50}?(\d[\d.,]*)\s*(k|nghin|ngan|trieu|d|vnd|dong)\b"),
     lambda m: (lambda v: (f"{int(v)}" if v is not None else m.group(1), v))(_money(m.group(1), m.group(2)))),
    ("response_minutes", re.compile(r"tra loi[^.\n]{0,40}?(\d{1,3})\s*phut"), lambda m: (m.group(1), float(m.group(1)))),
    ("opening_hours", re.compile(r"(?:mo cua|gio lam|lam viec|ho tro)[^.\n]{0,40}?(\d{1,2})[:h](\d{2})?\s*[–\-—]\s*(\d{1,2})[:h](\d{2})?"),
     lambda m: (f"{_hhmm(m.group(1), m.group(2))}–{_hhmm(m.group(3), m.group(4))}", None)),
    ("hotline", re.compile(r"(?:hotline|so dien thoai|dien thoai|goi)[^0-9\n]{0,20}((?:\+?84|0)\d[\d .]{7,12}\d)"),
     lambda m: (re.sub(r"\D", "", m.group(1)), None)),
]


def extract(text: str) -> list[dict]:
    """[{key, value, value_num, section, excerpt}] — mỗi khoá lấy lần xuất hiện đầu tiên trong mỗi mục."""
    from app.services.knowledge_hub import sections
    out, seen = [], set()
    for path, no, body in sections(text or ""):
        raw = body or ""
        low = _u(raw)
        for key, rx, get in PATTERNS:
            if key in seen:
                continue
            m = rx.search(low)
            if not m:
                continue
            value, num = get(m)
            seen.add(key)
            a, b = max(0, m.start() - 30), min(len(raw), m.end() + 30)
            out.append({"key": key, "value": str(value), "value_num": num, "section": path, "section_no": no,
                        "excerpt": raw[a:b].strip()[:300]})
    return out


def _norm(f) -> str:
    v = f["value"] if isinstance(f, dict) else f.value
    num = f.get("value_num") if isinstance(f, dict) else f.value_num
    return f"{num:g}" if num is not None else re.sub(r"\s+", "", str(v).lower())


def _src(db: Session, f: CompanyFact) -> str:
    if f.source_kind == "document" and f.source_doc_id:
        d = db.get(KnowledgeDocument, f.source_doc_id)
        if d is not None:
            return f"{d.doc_code} v{f.source_version_no}" + (f" §{f.source_section}" if f.source_section else "")
    return {"manual": "nhập tay", "structured": "bảng có cấu trúc"}.get(f.source_kind, f.source_kind)


def public(db: Session, f: CompanyFact) -> dict:
    k = KEYS.get(f.key, {})
    return {"id": f.id, "key": f.key, "label_vi": k.get("vi", f.key), "label_en": k.get("en", f.key), "value": f.value,
            "value_num": f.value_num, "unit": f.unit or k.get("unit", ""), "source_kind": f.source_kind,
            "source_doc_id": f.source_doc_id, "source_version_no": f.source_version_no, "source_section": f.source_section,
            "source": _src(db, f), "excerpt": f.excerpt, "status": f.status,
            "updated_at": f.updated_at.isoformat() if f.updated_at else None}


def active(db: Session, company_id: int | None, key: str | None = None) -> list[CompanyFact]:
    q = db.query(CompanyFact).filter(CompanyFact.company_id == company_id, CompanyFact.status == "active")
    if key:
        q = q.filter(CompanyFact.key == key)
    return q.order_by(CompanyFact.key, CompanyFact.id).all()


def conflicts_for(db: Session, doc: KnowledgeDocument, text: str) -> list[dict]:
    """Sự kiện trích từ ``text`` (phiên bản sắp ban hành) khác giá trị với sự kiện đang có từ NGUỒN KHÁC."""
    if not doc.company_id:
        return []
    out = []
    for f in extract(text):
        for o in active(db, doc.company_id, f["key"]):
            if o.source_kind == "document" and o.source_doc_id == doc.id:
                continue
            if _norm(o) != _norm(f):
                out.append({"key": f["key"], "label": KEYS.get(f["key"], {}).get("vi", f["key"]), "value": f["value"],
                            "section": f["section"], "other_value": o.value, "other_source": _src(db, o),
                            "other_doc_id": o.source_doc_id, "other_kind": o.source_kind, "fact_id": o.id})
    return out


def upsert_from_doc(db: Session, doc: KnowledgeDocument) -> int:
    """Bản vừa ban hành → sự kiện của tài liệu này (bản cũ của tài liệu → superseded)."""
    if not doc.company_id:
        return 0
    now = datetime.utcnow()
    for o in db.query(CompanyFact).filter(CompanyFact.source_doc_id == doc.id, CompanyFact.status == "active"):
        o.status, o.updated_at = "superseded", now
        db.add(o)
    if doc.agent_use == "none" or doc.status != "published":
        db.commit()
        return 0
    n = 0
    for f in extract(doc.content or ""):
        db.add(CompanyFact(organization_id=doc.organization_id, company_id=doc.company_id, key=f["key"], value=f["value"][:500],
                           value_num=f["value_num"], unit=KEYS.get(f["key"], {}).get("unit", ""), source_kind="document",
                           source_doc_id=doc.id, source_version_no=doc.version_no, source_section=(f["section"] or "")[:300],
                           excerpt=f["excerpt"][:500], status="active", created_at=now, updated_at=now))
        n += 1
    db.commit()
    return n


def retire_doc(db: Session, doc: KnowledgeDocument) -> None:
    for o in db.query(CompanyFact).filter(CompanyFact.source_doc_id == doc.id, CompanyFact.status == "active"):
        o.status = "superseded"; db.add(o)
    db.commit()


def listing(db: Session, org_id: int, company_id: int | None) -> dict:
    from app.services.doc_library import _company
    co = _company(db, org_id, company_id)
    rows = active(db, co.id)
    by: dict[str, list] = {}
    for f in rows:
        by.setdefault(f.key, []).append(public(db, f))
    items = []
    for key, fs in by.items():
        vals = {_norm({"value": y["value"], "value_num": y["value_num"]}) for y in fs}
        items.append({"key": key, "label_vi": KEYS.get(key, {}).get("vi", key), "label_en": KEYS.get(key, {}).get("en", key),
                      "conflict": len(vals) > 1, "sources": fs})
    return {"company_id": co.id, "items": items, "keys": [{"key": k, **v} for k, v in KEYS.items()],
            "conflicts": sum(1 for i in items if i["conflict"])}


def set_manual(db: Session, org_id: int, principal, data: dict) -> dict:
    from app.services.doc_library import _company, _seat
    co = _company(db, org_id, data.get("company_id"), write=True)
    key = re.sub(r"[^a-z0-9_]", "", (data.get("key") or "").lower())[:80]
    value = str(data.get("value") or "").strip()[:500]
    if not key or not value:
        raise HTTPException(422, "Cần key và value")
    num = data.get("value_num")
    if num is None:
        try:
            num = float(value.replace(",", ""))
        except ValueError:
            num = None
    now = datetime.utcnow()
    for o in db.query(CompanyFact).filter(CompanyFact.company_id == co.id, CompanyFact.key == key,
                                          CompanyFact.source_kind == "manual", CompanyFact.status == "active"):
        o.status, o.updated_at = "superseded", now; db.add(o)
    f = CompanyFact(organization_id=org_id, company_id=co.id, key=key, value=value, value_num=num,
                    unit=str(data.get("unit") or KEYS.get(key, {}).get("unit", ""))[:24], source_kind="manual",
                    updated_by_member_id=_seat(db, principal, co.id), status="active", created_at=now, updated_at=now)
    db.add(f); db.commit(); db.refresh(f)
    return public(db, f)


def remove_manual(db: Session, org_id: int, fact_id: int) -> dict:
    f = db.get(CompanyFact, fact_id)
    if f is None or f.organization_id != org_id:
        raise HTTPException(404, "Không thấy sự kiện")
    from app.core import company_scope
    company_scope.check(f.company_id)
    if f.source_kind != "manual":
        raise HTTPException(409, "Sự kiện lấy từ tài liệu — sửa tài liệu nguồn (phiên bản mới) thay vì xoá")
    f.status = "superseded"; db.add(f); db.commit()
    return {"id": f.id, "status": f.status}


def for_agent(db: Session, company_id: int | None, key: str = "", query: str = "") -> dict:
    """Tool company_fact_get: mọi nguồn đang hiệu lực + cờ conflict; khoá không có → gợi ý khoá gần nhất."""
    rows = active(db, company_id)
    if key:
        rows = [f for f in rows if f.key == key]
    elif query:
        q = _u(query)
        rows = [f for f in rows if any(w in _u(KEYS.get(f.key, {}).get("vi", f.key) + " " + f.key.replace("_", " "))
                                       for w in q.split() if len(w) > 2)]
    out: dict[str, list] = {}
    for f in rows:
        out.setdefault(f.key, []).append(f)
    facts = []
    for k, fs in out.items():
        vals = {_norm(f) for f in fs}
        manual = [f for f in fs if f.source_kind == "manual"]
        best = manual[0] if manual else fs[-1]
        facts.append({"key": k, "label": KEYS.get(k, {}).get("vi", k), "value": best.value, "unit": best.unit,
                      "source": _src(db, best), "conflict": len(vals) > 1,
                      "all_sources": [{"value": f.value, "source": _src(db, f)} for f in fs],
                      **({"note": "Các nguồn đang ghi khác nhau — báo người phụ trách (company_doc_flag reason=conflict), "
                                  "đừng tự chọn khi trả lời khách"} if len(vals) > 1 else {})})
    return {"facts": facts, "known_keys": list(KEYS) if not facts else None}
