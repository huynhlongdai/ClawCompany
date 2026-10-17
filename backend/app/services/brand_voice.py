"""Giọng thương hiệu — văn bản có cấu trúc (phiên bản, duyệt để ban hành) + cưỡng chế tất định + giọng nói (TTS).

Văn bản (``brand_voices``): persona, cặp "là / không là", xưng hô (với khách theo nhóm, nội bộ), từ nên dùng, từ/cam kết
cấm, chính sách emoji & định dạng, ký tên/lời kết, biến thể theo kênh (Zalo, Facebook/Messenger, email, kịch bản gọi,
website/bài đăng, nội bộ), cặp ví dụ đúng/sai, từ điển phát âm. Vòng đời: draft → in_review → published (bản cũ →
archived) | rejected. Chỉ bản ``published`` vào AGENTS.md (``core_block``, ngắn, trong ngân sách phần cốt lõi) và dùng để
chấm; chi tiết từng kênh agent đọc bằng ``company_doc_get doc_code=VOICE channel=<kênh>``.

Cưỡng chế (``check_text``): tất định — từ cấm, cam kết cấm, xưng hô sai, emoji, độ dài theo kênh, markdown ở kênh chat,
thiếu ký tên email, từ nên thay. Điểm 0..1 (cao 0.4 / vừa 0.2 / thấp 0.08 mỗi lỗi). Chạy trên kết quả gửi khách của
``company_task_submit_output`` (trường văn bản gửi khách) theo cài đặt công ty: off / flag (ghi + thẻ Hộp việc) / rework
(trả làm lại như lỗi hợp đồng dữ liệu). Chấm bằng model chỉ khi bật cờ (cần quota) — chỉ để tham khảo, không quyết.

Cho thuê (R2): ghế thuê dùng giọng của BÊN THUÊ (công ty của ghế); từ/cam kết cấm của bên cho thuê luôn được chấm thêm
như "sàn" (nguồn provider_floor) và bên thuê không tắt được.

Giọng nói (``voice_profiles``): nhà cung cấp, giọng, ngôn ngữ, tốc độ, cao độ/phong cách, kịch bản chào/kết cuộc gọi; adapter
TTS không phụ thuộc nhà cung cấp (CometAPI ``/v1/audio/speech``; adapter giả chỉ khi ``tts_fake_enabled``). "Nghe thử" áp
từ điển phát âm rồi gọi TTS, lưu file; lỗi nhà cung cấp (hết quota…) trả lỗi thật, không giả thành công."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import struct
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Company, Member
from app.models.brand_voice import BrandVoice, BrandVoiceSettings, VoiceCheck, VoiceProfile, VoiceSample

CHANNELS = ("zalo", "facebook", "email", "phone", "website", "internal")
CHANNEL_VI = {"zalo": "Zalo", "facebook": "Facebook/Messenger", "email": "Email", "phone": "Kịch bản gọi điện",
              "website": "Website / bài đăng", "internal": "Nội bộ"}
CHANNEL_DEFAULTS = {
    "zalo": {"max_chars": 600, "no_markdown": True, "signature_required": False},
    "facebook": {"max_chars": 600, "no_markdown": True, "signature_required": False},
    "email": {"max_chars": 2500, "no_markdown": False, "signature_required": True},
    "phone": {"max_chars": 900, "no_markdown": True, "signature_required": False},
    "website": {"max_chars": 3000, "no_markdown": False, "signature_required": False},
    "internal": {"max_chars": 2000, "no_markdown": False, "signature_required": False},
}
EMOJI_POLICIES = ("none", "light", "free")
ENFORCEMENT = ("off", "flag", "rework")
STATUSES = ("draft", "in_review", "published", "archived", "rejected")
PENALTY = {"high": 0.4, "medium": 0.2, "low": 0.08}
DEFAULT_AVOID = ("tao", "mày", "tớ", "cậu", "bạn", "tôi")
INTERNAL_AVOID = ("tao", "mày")
CUSTOMER_FIELDS = ("customer_message", "reply", "reply_text", "message", "message_text", "caption", "post", "post_text",
                   "content", "body", "email_body", "script")
CORE_VOICE_BUDGET = 1600
VOICE_CODES = ("VOICE", "BRAND-VOICE", "GIONG")
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")
MD_RE = re.compile(r"(\*\*[^*]+\*\*|__[^_]+__|^#{1,6}\s|```|^\s*[-*]\s+\S.*\n\s*[-*]\s+\S)", re.M)
TTS_MODELS = ("gpt-4o-mini-tts", "tts-1", "tts-1-hd")
TTS_VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse")
PITCHES = {"low": "trầm", "medium": "vừa", "high": "cao, tươi"}
MAX_AUDIO = 4 * 1024 * 1024
MAX_PREVIEW_CHARS = 600


def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status, {"error": code, "message": message, **extra})


def _company(db: Session, org_id: int, company_id: int | None, *, write: bool = False) -> Company:
    from app.services.company_foundation import _company as c
    return c(db, org_id, company_id, write=write)


# ------------------------------------------------------------------ chuẩn hoá spec

def _s(v, limit: int) -> str:
    return str(v or "").strip()[:limit]


def _list(v, limit: int = 30, each: int = 160) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = [x for x in re.split(r"[\n;,]", v)]
    if not isinstance(v, list):
        raise _err(422, "invalid_list", "Cần một danh sách.")
    out = []
    for x in v:
        x = str(x or "").strip()[:each]
        if x and x.lower() not in [o.lower() for o in out]:
            out.append(x)
    return out[:limit]


def _words(s: str) -> list[str]:
    return [w.strip() for w in re.split(r"[/,;|]", s or "") if w.strip()]


def clean_spec(raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    traits = []
    for t in raw.get("traits") or []:
        if not isinstance(t, dict):
            continue
        a, b = _s(t.get("is"), 120), _s(t.get("is_not"), 120)
        if a or b:
            traits.append({"is": a, "is_not": b})
    addr = raw.get("address") if isinstance(raw.get("address"), dict) else {}
    cust = addr.get("customer") if isinstance(addr.get("customer"), dict) else {}
    internal = addr.get("internal") if isinstance(addr.get("internal"), dict) else {}
    segs = []
    for sg in addr.get("segments") or []:
        if not isinstance(sg, dict):
            continue
        key = re.sub(r"[^a-z0-9_]", "_", _s(sg.get("key") or sg.get("label"), 40).lower()) or f"seg{len(segs) + 1}"
        if not _s(sg.get("self"), 40) and not _s(sg.get("customer"), 60):
            continue
        segs.append({"key": key, "label": _s(sg.get("label"), 80) or key, "self": _s(sg.get("self"), 40),
                     "customer": _s(sg.get("customer"), 60)})
    preferred = []
    for p in raw.get("preferred_terms") or []:
        if isinstance(p, dict) and _s(p.get("use"), 80):
            preferred.append({"use": _s(p.get("use"), 80), "instead_of": _list(p.get("instead_of"), 8, 80)})
    emoji = raw.get("emoji") if isinstance(raw.get("emoji"), dict) else {}
    pol = emoji.get("policy") or "light"
    if pol not in EMOJI_POLICIES:
        raise _err(422, "invalid_emoji_policy", "Chính sách emoji phải là none | light | free.")
    try:
        emax = int(emoji.get("max") if emoji.get("max") not in (None, "") else 2)
    except (TypeError, ValueError):
        raise _err(422, "invalid_emoji_max", "Số emoji tối đa phải là số.")
    channels = {}
    for ch, val in (raw.get("channels") or {}).items():
        if ch not in CHANNELS or not isinstance(val, dict):
            continue
        c = {"tone": _s(val.get("tone"), 400), "greeting": _s(val.get("greeting"), 200), "closing": _s(val.get("closing"), 200)}
        if val.get("max_chars") not in (None, ""):
            try:
                c["max_chars"] = max(40, min(20000, int(val["max_chars"])))
            except (TypeError, ValueError):
                raise _err(422, "invalid_max_chars", f"Độ dài tối đa kênh {ch} phải là số.")
        if val.get("emoji") in EMOJI_POLICIES:
            c["emoji"] = val["emoji"]
        for flag in ("no_markdown", "signature_required"):
            if val.get(flag) is not None:
                c[flag] = bool(val[flag])
        channels[ch] = c
    examples = []
    for e in raw.get("examples") or []:
        if not isinstance(e, dict) or not (_s(e.get("good"), 10) or _s(e.get("bad"), 10)):
            continue
        ch = e.get("channel") if e.get("channel") in CHANNELS else "zalo"
        examples.append({"channel": ch, "situation": _s(e.get("situation"), 300), "good": _s(e.get("good"), 1200),
                         "bad": _s(e.get("bad"), 1200), "why": _s(e.get("why"), 300)})
    lexicon = []
    for x in raw.get("lexicon") or []:
        if isinstance(x, dict) and _s(x.get("term"), 80) and _s(x.get("say"), 160):
            lexicon.append({"term": _s(x.get("term"), 80), "say": _s(x.get("say"), 160)})
    spec = {
        "persona": _s(raw.get("persona"), 2000),
        "personality": _list(raw.get("personality"), 8, 60),
        "traits": traits[:10],
        "address": {"customer": {"self": _s(cust.get("self"), 40), "customer": _s(cust.get("customer"), 60)},
                    "segments": segs[:8],
                    "internal": {"self": _s(internal.get("self"), 40), "other": _s(internal.get("other"), 60)},
                    "avoid": _list(addr.get("avoid"), 12, 20) if addr.get("avoid") is not None else None},
        "preferred_terms": preferred[:30],
        "banned_words": _list(raw.get("banned_words"), 40, 80),
        "banned_claims": _list(raw.get("banned_claims"), 30, 160),
        "emoji": {"policy": pol, "max": max(0, min(10, emax))},
        "formatting": _s(raw.get("formatting"), 600),
        "signature": _s(raw.get("signature"), 300),
        "closing": _s(raw.get("closing"), 200),
        "channels": channels,
        "examples": examples[:24],
        "lexicon": lexicon[:60],
    }
    if raw.get("migrated_from_charter"):
        spec["migrated_from_charter"] = True
    # từ vừa "nên dùng" vừa "cấm" → mâu thuẫn, phải sửa trước khi lưu
    banned = {w.lower() for w in spec["banned_words"]}
    clash = [p["use"] for p in spec["preferred_terms"] if p["use"].lower() in banned]
    if clash:
        raise _err(422, "term_conflict", f"\"{clash[0]}\" vừa nằm trong từ nên dùng vừa trong từ cấm.", term=clash[0])
    return spec


def channel_rules(spec: dict, channel: str) -> dict:
    base = dict(CHANNEL_DEFAULTS.get(channel, CHANNEL_DEFAULTS["zalo"]))
    base["emoji"] = (spec.get("emoji") or {}).get("policy", "light")
    base.update({k: v for k, v in ((spec.get("channels") or {}).get(channel) or {}).items() if v not in (None, "")})
    return base


# ------------------------------------------------------------------ bộ chấm tất định

def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def _unaccent(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "").replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _find(term: str, text: str, *, loose: bool = False) -> int:
    """Số lần ``term`` xuất hiện như một cụm từ (không dính chữ khác), không phân biệt hoa thường. ``loose``: thêm so khớp
    không dấu cho cụm ≥ 2 tiếng (agent gõ không dấu) — một tiếng thì không, vì "bạn"→"ban" trùng "bán"."""
    term = _norm(term).strip()
    if not term:
        return 0
    pat = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)", re.I)
    n = len(pat.findall(_norm(text)))
    if not n and loose and len(term.split()) >= 2:
        pat2 = re.compile(r"(?<!\w)" + re.escape(_unaccent(term)) + r"(?!\w)", re.I)
        n = len(pat2.findall(_unaccent(text)))
    return n


def _v(code: str, severity: str, message: str, source: str = "voice", **params) -> dict:
    return {"code": code, "severity": severity, "source": source, "message": message, "params": params}


def address_for(spec: dict, channel: str, segment: str = "") -> dict:
    addr = spec.get("address") or {}
    if channel == "internal":
        it = addr.get("internal") or {}
        return {"self": it.get("self", ""), "customer": it.get("other", ""), "segment": "internal"}
    seg = next((s for s in addr.get("segments") or [] if segment and s["key"] == segment), None)
    c = seg or addr.get("customer") or {}
    return {"self": c.get("self", ""), "customer": c.get("customer", ""), "segment": seg["key"] if seg else ""}


def check_text(spec: dict, text: str, *, channel: str = "zalo", segment: str = "", floor: dict | None = None,
               min_score: float = 0.7) -> dict:
    """Chấm một đoạn văn bản theo giọng (tất định). ``floor`` = spec của bên cho thuê (chỉ từ/cam kết cấm được dùng)."""
    if channel not in CHANNELS:
        raise _err(422, "invalid_channel", f"Kênh phải là một trong: {', '.join(CHANNELS)}.")
    text = _norm(text or "")
    rules = channel_rules(spec, channel)
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(v: dict, key: str) -> None:
        if (v["code"], key.lower()) not in seen:
            seen.add((v["code"], key.lower()))
            out.append(v)

    for src, sp in (("provider_floor", floor or {}), ("voice", spec)):
        for w in sp.get("banned_words") or []:
            n = _find(w, text, loose=True)
            if n:
                add(_v("banned_word", "high", f"Dùng từ cấm \"{w}\"" + (" (sàn của bên cho thuê)" if src != "voice" else ""),
                       src, term=w, count=n), f"{src}:{w}")
        for c in sp.get("banned_claims") or []:
            n = _find(c, text, loose=True)
            if n:
                add(_v("banned_claim", "high", f"Cam kết/khẳng định bị cấm: \"{c}\"" + (" (sàn của bên cho thuê)" if src != "voice" else ""),
                       src, term=c, count=n), f"{src}:{c}")
    # xưng hô
    a = address_for(spec, channel, segment)
    allowed = {w.lower() for w in _words(a["self"]) + _words(a["customer"])}
    configured = bool(allowed)
    avoid_cfg = (spec.get("address") or {}).get("avoid")
    avoid = INTERNAL_AVOID if channel == "internal" else (tuple(avoid_cfg) if avoid_cfg is not None else DEFAULT_AVOID)
    if configured or avoid_cfg:
        for w in avoid:
            if w.lower() in allowed:
                continue
            n = _find(w, text)
            if n:
                add(_v("wrong_address", "high" if w in ("tao", "mày") else "medium",
                       f"Xưng hô \"{w}\" không đúng giọng (đúng: {a['self'] or '—'} / {a['customer'] or '—'})",
                       term=w, count=n, expected_self=a["self"], expected_customer=a["customer"]), w)
    if configured and channel != "internal" and len(text) >= 60 and a["customer"]:
        if not any(_find(w, text) for w in _words(a["customer"])):
            add(_v("missing_address", "low", f"Chưa gọi khách là \"{a['customer']}\"", expected_customer=a["customer"]), "x")
    # emoji
    emojis = [e for e in EMOJI_RE.findall(text) if e != "\uFE0F"]
    pol = rules.get("emoji", "light")
    emax = int((spec.get("emoji") or {}).get("max", 2))
    if pol == "none" and emojis:
        add(_v("emoji_not_allowed", "medium", f"Kênh {CHANNEL_VI[channel]} không dùng emoji ({len(emojis)} emoji)",
               count=len(emojis), channel=channel), "e")
    elif pol == "light" and len(emojis) > emax:
        add(_v("emoji_too_many", "low", f"Quá nhiều emoji: {len(emojis)} > {emax}", count=len(emojis), max=emax), "e")
    # độ dài
    mx = int(rules.get("max_chars") or 0)
    if mx and len(text) > mx:
        add(_v("too_long", "medium", f"Dài {len(text)} ký tự, kênh {CHANNEL_VI[channel]} tối đa {mx}",
               length=len(text), max=mx, channel=channel), "l")
    # định dạng
    if rules.get("no_markdown") and MD_RE.search(text):
        add(_v("markdown_in_chat", "low", f"Kênh {CHANNEL_VI[channel]} hiển thị chữ thô — bỏ ký hiệu markdown (**, #, gạch đầu dòng)",
               channel=channel), "m")
    if re.search(r"[!?]{3,}|!!", text):
        add(_v("excess_punctuation", "low", "Dấu chấm than/hỏi lặp (\"!!\") — nghe như quát"), "p")
    sig = (spec.get("signature") or "").strip()
    if rules.get("signature_required") and sig:
        first = sig.splitlines()[0].strip()
        if first and first.lower() not in text.lower():
            add(_v("missing_signature", "low", f"Thiếu ký tên \"{first}\"", signature=first), "s")
    for p in spec.get("preferred_terms") or []:
        for bad in p.get("instead_of") or []:
            if bad.lower() != p["use"].lower() and _find(bad, text):
                add(_v("preferred_term", "low", f"Dùng \"{p['use']}\" thay cho \"{bad}\"", use=p["use"], instead_of=bad), bad)
    score = 1.0
    for v in out:
        score -= PENALTY[v["severity"]]
    score = round(max(0.0, score), 3)
    high = any(v["severity"] == "high" for v in out)
    return {"score": score, "passed": (not high) and score >= min_score, "violations": out, "channel": channel,
            "segment": a["segment"], "length": len(text), "emoji_count": len(emojis), "min_score": min_score,
            "floor_applied": bool(floor and ((floor.get("banned_words") or floor.get("banned_claims"))))}


# ------------------------------------------------------------------ phiên bản

def published(db: Session, company_id: int | None) -> BrandVoice | None:
    if not company_id:
        return None
    return (db.query(BrandVoice).filter(BrandVoice.company_id == company_id, BrandVoice.status == "published")
            .order_by(BrandVoice.version_no.desc()).first())


def _draft(db: Session, company_id: int) -> BrandVoice | None:
    return (db.query(BrandVoice).filter(BrandVoice.company_id == company_id, BrandVoice.status.in_(("draft", "in_review")))
            .order_by(BrandVoice.version_no.desc()).first())


def settings_row(db: Session, org_id: int, company_id: int, *, create: bool = False) -> BrandVoiceSettings | None:
    s = db.query(BrandVoiceSettings).filter(BrandVoiceSettings.company_id == company_id).first()
    if s is None and create:
        s = BrandVoiceSettings(organization_id=org_id, company_id=company_id, enforcement="flag", min_score=0.7,
                               model_check=False)
        db.add(s); db.flush()
    return s


def settings_public(s: BrandVoiceSettings | None) -> dict:
    return {"enforcement": s.enforcement if s else "flag", "min_score": s.min_score if s else 0.7,
            "model_check": bool(s.model_check) if s else False, "eval_suite_id": s.eval_suite_id if s else None,
            "model_check_available": _api_configured()}


def ensure_legacy(db: Session, co: Company) -> BrandVoice | None:
    """Công ty có chữ "Giọng thương hiệu" cũ trong hiến chương mà chưa có phiên bản nào → v1 đã ban hành, persona = chữ cũ
    (cùng việc migration 0065 làm cho dữ liệu có sẵn; ở đây cho công ty sửa hiến chương sau migration)."""
    if db.query(BrandVoice.id).filter(BrandVoice.company_id == co.id).first():
        return None
    from app.services.company_foundation import profile_row
    p = profile_row(db, co.id)
    if p is None or not (p.brand_voice or "").strip():
        return None
    v = BrandVoice(organization_id=co.organization_id, company_id=co.id, version_no=1, status="published",
                   spec=clean_spec({"persona": p.brand_voice, "migrated_from_charter": True}),
                   change_note="Chuyển từ mục \"Giọng thương hiệu\" của hiến chương", published_at=datetime.utcnow())
    db.add(v); db.commit(); db.refresh(v)
    return v


def version_public(v: BrandVoice | None, *, full: bool = True) -> dict | None:
    if v is None:
        return None
    out = {"id": v.id, "version_no": v.version_no, "status": v.status, "is_demo": bool(v.is_demo),
           "change_note": v.change_note or "", "review_note": v.review_note or "",
           "submitted_by_user_id": v.submitted_by_user_id, "decided_by_user_id": v.decided_by_user_id,
           "submitted_at": v.submitted_at.isoformat() if v.submitted_at else None,
           "published_at": v.published_at.isoformat() if v.published_at else None,
           "created_at": v.created_at.isoformat() if v.created_at else None}
    if full:
        out["spec"] = clean_spec(v.spec or {})
    return out


def overview(db: Session, org_id: int, company_id: int | None) -> dict:
    co = _company(db, org_id, company_id)
    ensure_legacy(db, co)
    pub = published(db, co.id)
    dr = _draft(db, co.id)
    versions = (db.query(BrandVoice).filter(BrandVoice.company_id == co.id).order_by(BrandVoice.version_no.desc()).limit(20).all())
    core = core_block(db, co.id)
    return {"company_id": co.id, "company_name": co.name, "published": version_public(pub), "draft": version_public(dr),
            "versions": [version_public(v, full=False) for v in versions], "settings": settings_public(settings_row(db, org_id, co.id)),
            "channels": [{"key": c, **CHANNEL_DEFAULTS[c]} for c in CHANNELS], "core_preview": core, "core_chars": len(core),
            "core_budget": CORE_VOICE_BUDGET, "example_check": selftest(clean_spec(pub.spec)) if pub else None}


def save_draft(db: Session, org_id: int, principal, data: dict) -> dict:
    co = _company(db, org_id, data.get("company_id"), write=True)
    spec = clean_spec(data.get("spec"))
    dr = _draft(db, co.id)
    if dr is not None and dr.status == "in_review":
        raise _err(409, "in_review", "Bản v%d đang chờ duyệt — duyệt/từ chối xong mới sửa tiếp." % dr.version_no)
    if dr is None:
        last = db.query(BrandVoice).filter(BrandVoice.company_id == co.id).order_by(BrandVoice.version_no.desc()).first()
        dr = BrandVoice(organization_id=co.organization_id, company_id=co.id, version_no=(last.version_no + 1) if last else 1,
                        status="draft", created_by_user_id=getattr(principal, "user_id", None))
    dr.spec = spec
    if "change_note" in data:
        dr.change_note = _s(data.get("change_note"), 1000)
    if data.get("is_demo") is not None:
        dr.is_demo = bool(data["is_demo"])
    db.add(dr); db.commit(); db.refresh(dr)
    return version_public(dr)


def _version(db: Session, org_id: int, vid: int) -> BrandVoice:
    v = db.get(BrandVoice, vid)
    if v is None or v.organization_id != org_id:
        raise _err(404, "not_found", "Không thấy phiên bản giọng này.")
    from app.core import company_scope
    company_scope.check(v.company_id)
    return v


def get_version(db: Session, org_id: int, vid: int) -> dict:
    return version_public(_version(db, org_id, vid))


def submit(db: Session, org_id: int, principal, vid: int, note: str = "") -> dict:
    v = _version(db, org_id, vid)
    if v.status != "draft":
        raise _err(409, "not_draft", "Chỉ bản nháp mới gửi duyệt được.")
    spec = clean_spec(v.spec)
    if not (spec["persona"] or spec["traits"] or spec["banned_words"]):
        raise _err(422, "empty_voice", "Giọng còn trống — ghi ít nhất tính cách, một cặp là/không là hoặc từ cấm.")
    v.status, v.submitted_by_user_id, v.submitted_at = "in_review", getattr(principal, "user_id", None), datetime.utcnow()
    if note:
        v.change_note = _s(note, 1000)
    db.add(v); db.commit(); db.refresh(v)
    return version_public(v)


def discard(db: Session, org_id: int, vid: int) -> dict:
    v = _version(db, org_id, vid)
    if v.status not in ("draft", "in_review"):
        raise _err(409, "not_draft", "Chỉ bỏ được bản nháp / đang chờ duyệt.")
    v.status = "rejected"; v.review_note = v.review_note or "Bỏ bản nháp"
    db.add(v); db.commit()
    return version_public(v)


def _is_owner(db: Session, principal, company_id: int) -> bool:
    from app.core import company_scope
    if company_scope.restricted(principal):
        return company_scope.role_in(company_id, principal) == "owner"
    return getattr(principal, "role", "") == "owner"


def decide(db: Session, org_id: int, principal, vid: int, decision: str, note: str = "") -> tuple[dict, bool]:
    """Duyệt (ban hành) hoặc từ chối. Trả (phiên bản, có ban hành không) — ban hành thì nơi gọi đồng bộ lại AGENTS.md."""
    from app.core import company_scope
    v = _version(db, org_id, vid)
    company_scope.check(v.company_id, min_role="admin")
    if decision not in ("approve", "reject"):
        raise _err(422, "invalid_decision", "decision phải là approve hoặc reject.")
    if v.status != "in_review":
        raise _err(409, "not_in_review", "Bản này không ở trạng thái chờ duyệt.")
    uid = getattr(principal, "user_id", None)
    if decision == "approve" and uid and uid == v.submitted_by_user_id and not _is_owner(db, principal, v.company_id):
        raise _err(403, "self_approval", "Người gửi không tự duyệt được — cần chủ công ty hoặc quản trị khác duyệt.")
    v.decided_by_user_id, v.review_note = uid, _s(note, 1000)
    if decision == "reject":
        v.status = "rejected"
        db.add(v); db.commit()
        return version_public(v), False
    for old in db.query(BrandVoice).filter(BrandVoice.company_id == v.company_id, BrandVoice.status == "published").all():
        old.status = "archived"; db.add(old)
    v.status, v.published_at = "published", datetime.utcnow()
    db.add(v); db.commit(); db.refresh(v)
    try:
        from app.services import audit
        audit.log_event(db, org_id, "brand_voice.published", "brand_voice", str(v.id),
                        actor_name=f"user:{uid}", payload={"company_id": v.company_id, "version_no": v.version_no})
    except Exception:  # noqa: BLE001 — sổ kiểm toán không chặn ban hành
        db.rollback()
    return version_public(v), True


def save_settings(db: Session, org_id: int, principal, data: dict) -> dict:
    from app.core import company_scope
    co = _company(db, org_id, data.get("company_id"), write=True)
    company_scope.check(co.id, min_role="admin")
    s = settings_row(db, org_id, co.id, create=True)
    if data.get("enforcement") is not None:
        if data["enforcement"] not in ENFORCEMENT:
            raise _err(422, "invalid_enforcement", "Cưỡng chế phải là off | flag | rework.")
        s.enforcement = data["enforcement"]
    if data.get("min_score") is not None:
        try:
            ms = float(data["min_score"])
        except (TypeError, ValueError):
            raise _err(422, "invalid_min_score", "Điểm tối thiểu phải là số 0..1.")
        if not 0 <= ms <= 1:
            raise _err(422, "invalid_min_score", "Điểm tối thiểu phải từ 0 đến 1.")
        s.min_score = ms
    if data.get("model_check") is not None:
        s.model_check = bool(data["model_check"])
    s.updated_by_user_id = getattr(principal, "user_id", None)
    db.add(s); db.commit(); db.refresh(s)
    return settings_public(s)


# ------------------------------------------------------------------ biên dịch vào AGENTS.md + tool

def _pairs(spec: dict, n: int = 5) -> str:
    return "; ".join(f"{t['is'] or '—'} — không {t['is_not'] or '—'}" for t in (spec.get("traits") or [])[:n])


def core_block(db: Session, company_id: int | None) -> str:
    """Phần giọng ngắn trong "Kiến thức cốt lõi" (≤ CORE_VOICE_BUDGET). Rỗng khi chưa có bản ban hành."""
    v = published(db, company_id)
    if v is None:
        return ""
    sp = clean_spec(v.spec)
    co = db.get(Company, company_id)
    lines = [f"### Giọng thương hiệu {co.name if co else ''} (v{v.version_no}{' · bản demo' if v.is_demo else ''}; "
             "áp dụng khi viết cho khách và nội bộ)"]
    if sp["persona"]:
        lines.append(f"**Tính cách:** {sp['persona'][:320]}")
    if sp["personality"]:
        lines.append("**Nét chính:** " + ", ".join(sp["personality"]))
    if sp["traits"]:
        lines.append(f"**Là / không là:** {_pairs(sp)}")
    a = sp["address"]
    if a["customer"]["self"] or a["customer"]["customer"]:
        segs = "; ".join(f"{s['label']}: {s['self']} – {s['customer']}" for s in a["segments"][:4])
        lines.append(f"**Xưng hô với khách:** xưng \"{a['customer']['self']}\", gọi \"{a['customer']['customer']}\""
                     + (f" (theo nhóm — {segs})" if segs else ""))
    if a["internal"]["self"] or a["internal"]["other"]:
        lines.append(f"**Nội bộ:** xưng \"{a['internal']['self']}\", gọi \"{a['internal']['other']}\"")
    if sp["preferred_terms"]:
        lines.append("**Nên dùng:** " + "; ".join(
            p["use"] + (f" (thay {', '.join(p['instead_of'][:2])})" if p["instead_of"] else "") for p in sp["preferred_terms"][:8]))
    if sp["banned_words"]:
        lines.append("**Không bao giờ dùng:** " + ", ".join(sp["banned_words"][:15]))
    if sp["banned_claims"]:
        lines.append("**Không khẳng định/cam kết:** " + "; ".join(sp["banned_claims"][:8]))
    em = {"none": "không dùng", "light": f"tối đa {sp['emoji']['max']}", "free": "thoải mái vừa phải"}[sp["emoji"]["policy"]]
    tail = [f"Emoji: {em}"]
    if sp["signature"]:
        tail.append(f"ký tên email: {sp['signature'].splitlines()[0]}")
    if sp["closing"]:
        tail.append(f"lời kết: {sp['closing']}")
    lines.append("**Định dạng:** " + "; ".join(tail).rstrip(".") + (f". {sp['formatting'][:200]}" if sp["formatting"] else ""))
    lens = ", ".join(f"{CHANNEL_VI[c]} ≤{channel_rules(sp, c)['max_chars']}" for c in CHANNELS)
    lines.append(f"**Theo kênh (ký tự):** {lens}. Chi tiết, lời chào và ví dụ từng kênh: company_doc_get doc_code=VOICE "
                 "channel=<zalo|facebook|email|phone|website|internal>. Văn bản gửi khách được hệ thống chấm giọng.")
    out = ""
    for ln in lines:   # không cắt giữa dòng — dòng không vừa thì bỏ (dòng kênh/tool luôn giữ ở cuối)
        if len(out) + len(ln) + 1 > CORE_VOICE_BUDGET - (len(lines[-1]) + 2 if ln is not lines[-1] else 0):
            continue
        out += ("\n" if out else "") + ln
    return out


def effective_for_member(db: Session, member: Member | None) -> tuple[dict | None, dict | None, int | None, BrandVoice | None]:
    """(spec giọng áp dụng, spec sàn bên cho thuê, lease_id, bản giọng). Ghế thuê → giọng bên thuê + sàn bên cho thuê."""
    if member is None:
        return None, None, None, None
    v = published(db, member.company_id)
    floor, lease_id = None, None
    from app.services import seat_leases
    ls = seat_leases.lease_of_member(db, member.id, live_only=True)
    if ls is not None:
        lease_id = ls.id
        pv = published(db, ls.provider_company_id)
        if pv is not None:
            ps = clean_spec(pv.spec)
            floor = {"banned_words": ps["banned_words"], "banned_claims": ps["banned_claims"]}
    return (clean_spec(v.spec) if v else None), floor, lease_id, v


def floor_lines(db: Session, provider_company_id: int) -> str:
    """Mục giọng trong "Sàn của bên cho thuê": chỉ từ/cam kết cấm (bên thuê không nới được)."""
    v = published(db, provider_company_id)
    if v is None:
        return ""
    sp = clean_spec(v.spec)
    if not (sp["banned_words"] or sp["banned_claims"]):
        return ""
    parts = ["### Từ và cam kết cấm của bên cho thuê (giọng — luôn áp dụng)"]
    if sp["banned_words"]:
        parts.append("- Không dùng: " + ", ".join(sp["banned_words"][:15]))
    if sp["banned_claims"]:
        parts.append("- Không khẳng định/cam kết: " + "; ".join(sp["banned_claims"][:8]))
    parts.append("- Giọng, xưng hô, độ dài theo kênh: theo giọng của bên thuê.")
    return "\n".join(parts)


def agent_view(db: Session, member: Member, channel: str = "") -> dict:
    """Kết quả tool (company_doc_get doc_code=VOICE): giọng áp dụng cho ghế này, chi tiết một kênh (hoặc mọi kênh)."""
    spec, floor, lease_id, v = effective_for_member(db, member)
    if spec is None:
        return {"doc_code": "VOICE", "found": False,
                "note": "Công ty chưa ban hành giọng thương hiệu — viết lịch sự, rõ ràng; đừng tự đặt ra quy tắc giọng."}
    if channel and channel not in CHANNELS:
        raise _err(422, "invalid_channel", f"channel phải là một trong {', '.join(CHANNELS)}")
    chans = [channel] if channel else list(CHANNELS)
    detail = {}
    for c in chans:
        r = channel_rules(spec, c)
        detail[c] = {"label": CHANNEL_VI[c], "max_chars": r["max_chars"], "emoji": r["emoji"], "no_markdown": r["no_markdown"],
                     "signature_required": r["signature_required"], "tone": r.get("tone", ""), "greeting": r.get("greeting", ""),
                     "closing": r.get("closing", ""), "address": address_for(spec, c),
                     "examples": [e for e in spec["examples"] if e["channel"] == c][:4]}
    return {"doc_code": "VOICE", "found": True, "version_no": v.version_no, "cite": f"[VOICE v{v.version_no}]",
            "persona": spec["persona"], "traits": spec["traits"], "address": spec["address"],
            "preferred_terms": spec["preferred_terms"], "banned_words": spec["banned_words"], "banned_claims": spec["banned_claims"],
            "emoji": spec["emoji"], "formatting": spec["formatting"], "signature": spec["signature"], "closing": spec["closing"],
            "channels": detail, "provider_floor": floor, "lease_id": lease_id,
            "note": "Viết theo giọng này. Văn bản gửi khách được chấm tự động (từ cấm, xưng hô, emoji, độ dài kênh)."}


# ------------------------------------------------------------------ chấm + cưỡng chế + ghi sổ

def record(db: Session, *, org_id: int, company_id: int, result: dict, text: str, source: str, member_id: int | None = None,
           task_id: int | None = None, task_output_id: int | None = None, voice: BrandVoice | None = None,
           lease_id: int | None = None, action: str = "none", model_result: dict | None = None, commit: bool = True) -> VoiceCheck:
    vc = VoiceCheck(organization_id=org_id, company_id=company_id, member_id=member_id, task_id=task_id,
                    task_output_id=task_output_id, source=source[:16], channel=result["channel"], segment=result.get("segment") or "",
                    voice_id=voice.id if voice else None, voice_version=voice.version_no if voice else None, lease_id=lease_id,
                    score=result["score"], passed=result["passed"], action=action, violations=result["violations"] or None,
                    model_result=model_result, text_excerpt=(text or "")[:500])
    db.add(vc)
    if commit:
        db.commit(); db.refresh(vc)
    else:
        db.flush()
    return vc


def check_public(vc: VoiceCheck) -> dict:
    return {"id": vc.id, "source": vc.source, "channel": vc.channel, "segment": vc.segment, "score": vc.score, "passed": vc.passed,
            "action": vc.action, "violations": vc.violations or [], "model_result": vc.model_result, "member_id": vc.member_id,
            "task_id": vc.task_id, "voice_version": vc.voice_version, "lease_id": vc.lease_id, "text_excerpt": vc.text_excerpt,
            "created_at": vc.created_at.isoformat() if vc.created_at else None}


def try_text(db: Session, org_id: int, data: dict) -> dict:
    """Ô "Thử văn bản": chấm theo bản ban hành (hoặc một phiên bản chỉ định, ví dụ bản nháp). Ghi sổ nguồn ``try`` (không tính
    vào điểm agent). ``agent_id`` → chấm như ghế đó (ghế thuê: giọng bên thuê + sàn bên cho thuê)."""
    co = _company(db, org_id, data.get("company_id"))
    text = str(data.get("text") or "")
    if not text.strip():
        raise _err(422, "empty_text", "Nhập văn bản cần kiểm.")
    if len(text) > 20000:
        raise _err(422, "text_too_long", "Tối đa 20.000 ký tự.")
    channel = data.get("channel") or "zalo"
    floor, lease_id, member = None, None, None
    if data.get("version_id"):
        v = _version(db, org_id, int(data["version_id"]))
        if v.company_id != co.id:
            raise _err(404, "not_found", "Phiên bản không thuộc công ty này.")
        spec = clean_spec(v.spec)
    elif data.get("agent_id"):
        from app.models import Agent
        ag = db.get(Agent, int(data["agent_id"]))
        member = db.get(Member, ag.member_id) if ag else None
        if member is None or member.organization_id != org_id or member.company_id != co.id:
            raise _err(404, "not_found", "Không thấy agent này trong công ty.")
        spec, floor, lease_id, v = effective_for_member(db, member)
        if spec is None:
            raise _err(409, "no_published_voice", "Công ty chưa ban hành giọng thương hiệu.")
    else:
        v = published(db, co.id)
        if v is None:
            raise _err(409, "no_published_voice", "Công ty chưa ban hành giọng thương hiệu — kiểm theo bản nháp bằng version_id.")
        spec = clean_spec(v.spec)
    s = settings_row(db, org_id, co.id)
    res = check_text(spec, text, channel=channel, segment=str(data.get("segment") or ""), floor=floor,
                     min_score=s.min_score if s else 0.7)
    model_result = None
    if data.get("use_model"):
        if not (s and s.model_check):
            model_result = {"status": "disabled", "message": "Chấm bằng model đang tắt trong cài đặt công ty."}
        else:
            model_result = model_tone_check(spec, text, channel)
    vc = record(db, org_id=org_id, company_id=co.id, result=res, text=text, source="try", voice=v, lease_id=lease_id,
                model_result=model_result)
    return {**res, "check_id": vc.id, "voice_version": v.version_no if v else None, "model_result": model_result}


def customer_texts(output) -> list[tuple[str, str]]:
    if not isinstance(output, dict):
        return []
    return [(k, output[k]) for k in CUSTOMER_FIELDS if isinstance(output.get(k), str) and output[k].strip()]


def check_output(db: Session, member: Member | None, output) -> dict | None:
    """Chấm các trường văn bản gửi khách của một kết quả nộp. None = không áp dụng (không có giọng ban hành / không có
    trường gửi khách / công ty tắt cưỡng chế)."""
    if member is None:
        return None
    texts = customer_texts(output)
    if not texts:
        return None
    spec, floor, lease_id, v = effective_for_member(db, member)
    if spec is None and not floor:
        return None
    s = settings_row(db, member.organization_id, member.company_id) if member.company_id else None
    enforcement = s.enforcement if s else "flag"
    if enforcement == "off" and not floor:
        return None
    channel = output.get("channel") if output.get("channel") in CHANNELS else "zalo"
    segment = str(output.get("segment") or "")
    text = "\n\n".join(t for _, t in texts)
    # bên thuê tắt cưỡng chế → chỉ còn sàn của bên cho thuê được chấm
    res = check_text((spec or {}) if enforcement != "off" else {}, text, channel=channel, segment=segment, floor=floor,
                     min_score=s.min_score if s else 0.7)
    # sàn bên cho thuê: vi phạm từ/cam kết cấm của bên cho thuê luôn trả làm lại, kể cả khi bên thuê để off/flag
    floor_hit = any(x["source"] == "provider_floor" for x in res["violations"])
    action = "none"
    if not res["passed"]:
        action = "rework" if (enforcement == "rework" or floor_hit) else ("flag" if enforcement == "flag" else "none")
    errors = [{"path": f"giọng.{x['code']}", "message": x["message"]} for x in res["violations"] if x["severity"] != "low"] \
        or [{"path": "giọng", "message": f"Điểm giọng {res['score']} < {res['min_score']}"}]
    return {"result": res, "action": action, "errors": errors if action == "rework" else [], "text": text,
            "voice": v, "lease_id": lease_id, "fields": [k for k, _ in texts]}


def after_submit(db: Session, task, member: Member | None, vres: dict | None, output_id: int | None) -> None:
    """Ghi điểm giọng của lần nộp + thẻ Hộp việc khi chỉ gắn cờ."""
    if not vres:
        return
    company_id = member.company_id if member and member.company_id else None
    if company_id is None:
        return
    vc = record(db, org_id=member.organization_id, company_id=company_id, result=vres["result"], text=vres["text"],
                source="submit_output", member_id=member.id, task_id=task.id, task_output_id=output_id, voice=vres["voice"],
                lease_id=vres["lease_id"], action=vres["action"])
    if vres["action"] == "flag":
        from app.services import authority, inbox
        target = member.manager_id or authority.owner_member(db, member.organization_id, company_id)
        top = "; ".join(x["message"] for x in vres["result"]["violations"][:3])
        inbox.notify(db, organization_id=member.organization_id, recipients=[target], kind="voice_flag", company_id=company_id,
                     title=f"{member.name}: văn bản gửi khách lệch giọng (điểm {vres['result']['score']}) — việc #{task.id}",
                     line=top[:300], task_id=task.id, related_type="voice_check", related_id=str(vc.id))


def review_note(db: Session, task_id: int) -> str:
    """Dòng cho người/agent duyệt: lần chấm giọng gần nhất của việc (nếu có)."""
    vc = (db.query(VoiceCheck).filter(VoiceCheck.task_id == task_id).order_by(VoiceCheck.id.desc()).first())
    if vc is None:
        return ""
    bad = "; ".join(x.get("message", "") for x in (vc.violations or [])[:5])
    return (f"- Kiểm giọng thương hiệu (tự động, kênh {CHANNEL_VI.get(vc.channel, vc.channel)}): điểm {vc.score}"
            + (" — đạt" if vc.passed else " — CHƯA ĐẠT") + (f"; lỗi: {bad}" if bad else ""))


def recent_checks(db: Session, org_id: int, company_id: int | None, limit: int = 30) -> dict:
    co = _company(db, org_id, company_id)
    rows = (db.query(VoiceCheck).filter(VoiceCheck.company_id == co.id).order_by(VoiceCheck.id.desc()).limit(min(limit, 100)).all())
    names = {m.id: m.name for m in db.query(Member).filter(Member.id.in_([r.member_id for r in rows if r.member_id] or [-1])).all()}
    return {"items": [{**check_public(r), "member_name": names.get(r.member_id)} for r in rows]}


def voice_metrics(db: Session, member_ids: list[int], *, days: int = 30, now: datetime | None = None) -> dict:
    """Điểm giọng của ghế (Agent HR): trung bình điểm các lần chấm từ việc thật / eval (không tính ô thử)."""
    since = (now or datetime.utcnow()) - timedelta(days=days)
    rows = (db.query(VoiceCheck).filter(VoiceCheck.member_id.in_(member_ids or [-1]), VoiceCheck.created_at >= since,
                                        VoiceCheck.source.in_(("submit_output", "review", "eval"))).all())
    if not rows:
        return {"score": None, "checks": 0, "pass_rate": None}
    return {"score": round(sum(r.score for r in rows) / len(rows), 4), "checks": len(rows),
            "pass_rate": round(sum(1 for r in rows if r.passed) / len(rows), 4)}


def selftest(spec: dict) -> dict:
    """Ví dụ đúng phải đạt, ví dụ sai phải bị bắt — kiểm bộ quy tắc trước khi ban hành."""
    rows = []
    for i, e in enumerate(spec.get("examples") or []):
        g = check_text(spec, e["good"], channel=e["channel"]) if e.get("good") else None
        b = check_text(spec, e["bad"], channel=e["channel"]) if e.get("bad") else None
        rows.append({"index": i, "channel": e["channel"], "situation": e["situation"],
                     "good_score": g["score"] if g else None, "good_ok": (g["passed"] if g else None),
                     "bad_score": b["score"] if b else None, "bad_caught": ((not b["passed"]) if b else None),
                     "good_violations": g["violations"] if g else [], "bad_violations": b["violations"] if b else []})
    ok = all((r["good_ok"] in (True, None)) and (r["bad_caught"] in (True, None)) for r in rows)
    return {"examples": rows, "all_ok": ok and bool(rows),
            "good_pass": sum(1 for r in rows if r["good_ok"]), "bad_caught": sum(1 for r in rows if r["bad_caught"]),
            "total": len(rows)}


def ensure_eval_suite(db: Session, org_id: int, company_id: int | None) -> dict:
    """Bộ eval giọng của công ty (chạy thật bằng đánh giá k lần ở Sự nghiệp agent): mỗi ví dụ → một ca, không được có từ/
    cam kết cấm và xưng hô bị tránh, phải gọi khách đúng."""
    from app.models.learning import EvalSuite
    from app.services import career
    co = _company(db, org_id, company_id, write=True)
    v = published(db, co.id)
    if v is None:
        raise _err(409, "no_published_voice", "Cần bản giọng đã ban hành trước khi tạo bộ eval.")
    sp = clean_spec(v.spec)
    cases = []
    for e in sp["examples"][:8]:
        a = address_for(sp, e["channel"])
        avoid = [w for w in ((sp["address"].get("avoid") or list(DEFAULT_AVOID)) if e["channel"] != "internal" else INTERNAL_AVOID)
                 if w.lower() not in {x.lower() for x in _words(a["self"]) + _words(a["customer"])}]
        must_not = (sp["banned_words"] + sp["banned_claims"] + [f" {w} " for w in avoid])[:10]
        must = [_words(a["customer"])[0]] if a["customer"] and e["channel"] != "internal" else []
        if not must and not must_not:
            continue
        prompt = (f"[Kênh {CHANNEL_VI[e['channel']]}] {e['situation'] or 'Khách nhắn hỏi'}. Viết đúng câu trả lời sẽ gửi, theo "
                  "giọng thương hiệu của công ty.")
        cases.append({"prompt": prompt, "must_include": must, "must_not_include": must_not})
    if not cases:
        raise _err(422, "no_examples", "Thêm ít nhất một ví dụ (tình huống + câu đúng) để tạo bộ eval.")
    s = settings_row(db, org_id, co.id, create=True)
    title = f"Giọng thương hiệu — {co.name} (v{v.version_no})"
    sid = s.eval_suite_id if s.eval_suite_id and db.get(EvalSuite, s.eval_suite_id) else None
    out = career.save_suite(db, org_id, {"title": title, "k": 2 if len(cases) * 2 <= 30 else 1, "cases": cases}, sid)
    s = settings_row(db, org_id, co.id)
    s.eval_suite_id = out["id"]; db.add(s); db.commit()
    return out


# ------------------------------------------------------------------ chấm bằng model (cờ, cần quota)

def _api_base() -> str:
    return (settings.tts_api_base or settings.embedding_api_base or os.environ.get("EMBEDDING_API_BASE", "")).rstrip("/")


def _api_key() -> str:
    f = settings.tts_api_key_file
    if f:
        try:
            with open(f, encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError:
            return ""
    from app.services import embeddings
    return embeddings._key()


def _api_configured() -> bool:
    return bool(_api_base() and _api_key())


def _http_error(exc: urllib.error.HTTPError) -> tuple[str, str]:
    try:
        body = exc.read().decode("utf-8", "replace")[:600]
    except Exception:  # noqa: BLE001
        body = ""
    low = body.lower()
    code = "provider_quota" if (exc.code in (402, 403, 429) and ("quota" in low or "insufficient" in low or "balance" in low)) \
        else ("provider_auth" if exc.code == 401 else "provider_error")
    return code, f"HTTP {exc.code}: {body or exc.reason}"


def model_tone_check(spec: dict, text: str, channel: str) -> dict:
    """Chấm giọng bằng model (OpenAI-compatible /chat/completions). Chỉ tham khảo; lỗi/hết quota → status error, nói thật."""
    if not _api_configured():
        return {"status": "error", "error": "not_configured", "message": "Chưa cấu hình API model (CometAPI)."}
    brief = core_like(spec)
    prompt = ("Bạn là người kiểm giọng thương hiệu. Giọng:\n" + brief + f"\n\nKênh: {CHANNEL_VI.get(channel, channel)}.\n"
              "Văn bản cần chấm:\n<<<\n" + text[:4000] + "\n>>>\nTrả về đúng một JSON: {\"score\": số 0..1, \"issues\": [chuỗi ngắn]}.")
    body = json.dumps({"model": settings.voice_check_model, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(_api_base() + "/chat/completions", data=body,
                                 headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:  # noqa: S310 — URL do quản trị cấu hình
            data = json.load(r)
        msg = data["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", msg, re.S)
        parsed = json.loads(m.group(0)) if m else {}
        sc = float(parsed.get("score"))
        return {"status": "ok", "model": settings.voice_check_model, "score": round(max(0.0, min(1.0, sc)), 3),
                "issues": [str(x)[:200] for x in (parsed.get("issues") or [])][:8]}
    except urllib.error.HTTPError as exc:
        code, msg = _http_error(exc)
        return {"status": "error", "error": code, "message": msg}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": "provider_error", "message": f"{type(exc).__name__}: {str(exc)[:200]}"}


def core_like(spec: dict) -> str:
    a = spec.get("address") or {}
    c = a.get("customer") or {}
    return "\n".join(x for x in (
        f"Tính cách: {spec.get('persona', '')[:400]}",
        f"Là / không là: {_pairs(spec)}" if spec.get("traits") else "",
        f"Xưng hô: xưng {c.get('self', '')}, gọi khách {c.get('customer', '')}" if c else "",
        "Từ cấm: " + ", ".join(spec.get("banned_words") or []) if spec.get("banned_words") else "",
    ) if x)


# ------------------------------------------------------------------ giọng nói (TTS)

class TTSError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class CometTTS:
    """OpenAI-compatible ``POST {base}/audio/speech`` (CometAPI)."""
    key = "cometapi"
    label = "CometAPI (OpenAI-compatible /v1/audio/speech)"

    def configured(self) -> bool:
        return _api_configured()

    def synthesize(self, text: str, *, model: str, voice: str, speed: float, instructions: str = "") -> tuple[bytes, str]:
        if not self.configured():
            raise TTSError("not_configured", "Chưa cấu hình CometAPI (base URL + key) cho máy chủ.")
        payload = {"model": model, "input": text, "voice": voice, "speed": speed, "response_format": "mp3"}
        if instructions and model == "gpt-4o-mini-tts":
            payload["instructions"] = instructions
        req = urllib.request.Request(_api_base() + "/audio/speech", data=json.dumps(payload).encode(),
                                     headers={"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 — URL do quản trị cấu hình
                ctype = r.headers.get("Content-Type", "")
                data = r.read(MAX_AUDIO + 1)
        except urllib.error.HTTPError as exc:
            code, msg = _http_error(exc)
            raise TTSError(code, msg) from None
        except Exception as exc:  # noqa: BLE001
            raise TTSError("provider_unreachable", f"{type(exc).__name__}: {str(exc)[:200]}") from None
        if "json" in ctype or "text" in ctype:
            raise TTSError("provider_error", "Nhà cung cấp trả JSON/chữ thay vì âm thanh: " + data[:300].decode("utf-8", "replace"))
        if len(data) > MAX_AUDIO:
            raise TTSError("audio_too_large", "File âm thanh quá 4 MB.")
        if len(data) < 64:
            raise TTSError("provider_error", "Nhà cung cấp trả file âm thanh rỗng.")
        return data, "audio/mpeg"


class FakeTTS:
    """Chỉ cho kiểm thử (``tts_fake_enabled``): WAV im lặng, độ dài theo số chữ. Không bao giờ bật ở môi trường thật."""
    key = "fake"
    label = "Giả lập (chỉ kiểm thử)"

    def configured(self) -> bool:
        return bool(settings.tts_fake_enabled)

    def synthesize(self, text: str, *, model: str, voice: str, speed: float, instructions: str = "") -> tuple[bytes, str]:
        if not self.configured():
            raise TTSError("not_configured", "Adapter giả chỉ dùng trong kiểm thử.")
        rate, n = 8000, max(800, min(8000 * 5, len(text) * 400))
        buf = io.BytesIO()
        buf.write(b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate, 1, 8)
                  + b"data" + struct.pack("<I", n) + bytes([128]) * n)
        return buf.getvalue(), "audio/wav"


ADAPTERS = {"cometapi": CometTTS(), "fake": FakeTTS()}


def providers() -> list[dict]:
    return [{"key": a.key, "label": a.label, "configured": a.configured()} for a in ADAPTERS.values()
            if a.key != "fake" or a.configured()]


def apply_lexicon(text: str, lexicon: list[dict]) -> str:
    out = _norm(text or "")
    for x in sorted(lexicon or [], key=lambda x: -len(x.get("term", ""))):
        t = _norm(x.get("term", "")).strip()
        if t:
            out = re.sub(r"(?<!\w)" + re.escape(t) + r"(?!\w)", x.get("say", ""), out, flags=re.I)
    return out


def _lexicon(db: Session, company_id: int) -> list[dict]:
    """Từ điển cho nghe thử: bản nháp đang soạn (nếu có) — để nghe ngay điều đang sửa — rồi mới tới bản ban hành."""
    v = _draft(db, company_id) or published(db, company_id)
    return clean_spec(v.spec)["lexicon"] if v else []


def profile_public(db: Session, co: Company, p: VoiceProfile | None) -> dict:
    lex = _lexicon(db, co.id)
    base = {"company_id": co.id, "exists": p is not None, "providers": providers(), "models": list(TTS_MODELS),
            "voices": list(TTS_VOICES), "pitches": list(PITCHES), "lexicon": lex}
    if p is None:
        return {**base, "provider": "cometapi", "model": "gpt-4o-mini-tts", "voice_name": "nova", "language": "vi-VN",
                "speed": 1.0, "pitch": "medium", "style": "", "greeting_script": "", "closing_script": "", "sample_text": "",
                "is_demo": False, "updated_at": None}
    return {**base, "provider": p.provider, "model": p.model, "voice_name": p.voice_name, "language": p.language,
            "speed": p.speed, "pitch": p.pitch, "style": p.style, "greeting_script": p.greeting_script,
            "closing_script": p.closing_script, "sample_text": p.sample_text, "is_demo": bool(p.is_demo),
            "updated_at": p.updated_at.isoformat() if p.updated_at else None}


def get_profile(db: Session, org_id: int, company_id: int | None) -> dict:
    co = _company(db, org_id, company_id)
    return profile_public(db, co, db.query(VoiceProfile).filter(VoiceProfile.company_id == co.id).first())


def save_profile(db: Session, org_id: int, principal, data: dict) -> dict:
    co = _company(db, org_id, data.get("company_id"), write=True)
    p = db.query(VoiceProfile).filter(VoiceProfile.company_id == co.id).first()
    if p is None:
        p = VoiceProfile(organization_id=co.organization_id, company_id=co.id)
    if data.get("provider") is not None:
        if data["provider"] not in ADAPTERS or (data["provider"] == "fake" and not ADAPTERS["fake"].configured()):
            raise _err(422, "invalid_provider", "Nhà cung cấp giọng nói không hợp lệ.")
        p.provider = data["provider"]
    if data.get("model") is not None:
        if data["model"] not in TTS_MODELS:
            raise _err(422, "invalid_model", f"Model TTS phải là một trong {', '.join(TTS_MODELS)}.")
        p.model = data["model"]
    if data.get("voice_name") is not None:
        vn = _s(data["voice_name"], 64)
        if not re.fullmatch(r"[A-Za-z0-9_.-]{2,64}", vn):
            raise _err(422, "invalid_voice", "Mã giọng chỉ gồm chữ, số, - _ .")
        p.voice_name = vn
    if data.get("language") is not None:
        lang = _s(data["language"], 16)
        if not re.fullmatch(r"[a-z]{2}(-[A-Z]{2})?", lang):
            raise _err(422, "invalid_language", "Ngôn ngữ dạng vi-VN.")
        p.language = lang
    if data.get("speed") is not None:
        try:
            sp = float(data["speed"])
        except (TypeError, ValueError):
            raise _err(422, "invalid_speed", "Tốc độ phải là số 0.5–2.0.")
        if not 0.5 <= sp <= 2.0:
            raise _err(422, "invalid_speed", "Tốc độ phải từ 0.5 đến 2.0.")
        p.speed = sp
    if data.get("pitch") is not None:
        if data["pitch"] not in PITCHES:
            raise _err(422, "invalid_pitch", "Cao độ: low | medium | high.")
        p.pitch = data["pitch"]
    for k, lim in (("style", 400), ("greeting_script", 1000), ("closing_script", 1000), ("sample_text", MAX_PREVIEW_CHARS)):
        if data.get(k) is not None:
            setattr(p, k, _s(data[k], lim))
    if data.get("is_demo") is not None:
        p.is_demo = bool(data["is_demo"])
    p.updated_by_user_id = getattr(principal, "user_id", None)
    db.add(p); db.commit(); db.refresh(p)
    return profile_public(db, co, p)


def sample_public(s: VoiceSample) -> dict:
    return {"id": s.id, "provider": s.provider, "model": s.model, "voice_name": s.voice_name, "settings": s.settings,
            "text_in": s.text_in, "text_spoken": s.text_spoken, "status": s.status, "error": s.error, "mime": s.mime,
            "size_bytes": s.size_bytes, "sha256": s.sha256, "created_at": s.created_at.isoformat() if s.created_at else None,
            "audio_path": f"/team/voice-samples/{s.id}/audio" if s.status == "ok" else None}


def preview(db: Session, org_id: int, principal, data: dict) -> dict:
    """Nghe thử: áp từ điển phát âm → TTS → lưu file. Lỗi nhà cung cấp → lưu lần thử lỗi + 424 với lỗi thật."""
    co = _company(db, org_id, data.get("company_id"), write=True)
    p = db.query(VoiceProfile).filter(VoiceProfile.company_id == co.id).first()
    if p is None:
        raise _err(409, "no_voice_profile", "Lưu cấu hình giọng nói trước khi nghe thử.")
    which = data.get("which") or "sample"
    text = str(data.get("text") or "").strip() or {"greeting": p.greeting_script, "closing": p.closing_script}.get(which) \
        or p.sample_text or p.greeting_script
    if not text.strip():
        raise _err(422, "empty_text", "Chưa có câu mẫu để đọc.")
    if len(text) > MAX_PREVIEW_CHARS:
        raise _err(422, "text_too_long", f"Câu nghe thử tối đa {MAX_PREVIEW_CHARS} ký tự.", max=MAX_PREVIEW_CHARS)
    spoken = apply_lexicon(text, _lexicon(db, co.id))
    adapter = ADAPTERS.get(p.provider)
    instr = f"Đọc bằng tiếng Việt ({p.language}), giọng {PITCHES.get(p.pitch, 'vừa')}" + (f", {p.style}" if p.style else "") + "."
    cfg = {"speed": p.speed, "pitch": p.pitch, "style": p.style, "language": p.language, "instructions": instr}
    s = VoiceSample(organization_id=co.organization_id, company_id=co.id, provider=p.provider, model=p.model,
                    voice_name=p.voice_name, settings=cfg, text_in=text, text_spoken=spoken,
                    created_by_user_id=getattr(principal, "user_id", None))
    try:
        if adapter is None:
            raise TTSError("invalid_provider", f"Không có adapter cho nhà cung cấp {p.provider}.")
        audio, mime = adapter.synthesize(spoken, model=p.model, voice=p.voice_name, speed=p.speed, instructions=instr)
    except TTSError as exc:
        s.status, s.error, s.audio = "error", f"{exc.code}: {exc.message}"[:1000], None
        db.add(s); db.commit(); db.refresh(s)
        raise _err(424, f"tts_{exc.code}", exc.message, sample_id=s.id, provider=p.provider)
    s.status, s.audio, s.mime, s.size_bytes, s.sha256 = "ok", audio, mime, len(audio), hashlib.sha256(audio).hexdigest()
    db.add(s); db.commit(); db.refresh(s)
    return sample_public(s)


def list_samples(db: Session, org_id: int, company_id: int | None) -> dict:
    co = _company(db, org_id, company_id)
    rows = db.query(VoiceSample).filter(VoiceSample.company_id == co.id).order_by(VoiceSample.id.desc()).limit(20).all()
    return {"items": [sample_public(s) for s in rows]}


def sample_audio(db: Session, org_id: int, sample_id: int) -> VoiceSample:
    s = db.get(VoiceSample, sample_id)
    if s is None or s.organization_id != org_id or s.status != "ok" or not s.audio:
        raise _err(404, "not_found", "Không thấy file nghe thử.")
    from app.core import company_scope
    company_scope.check(s.company_id)
    return s


# ------------------------------------------------------------------ demo

DEMO_SPEC = {
    "persona": ("Tiệm Gốm Mộc nói như người thợ gốm hiền, kỹ tính: ấm áp, mộc mạc, thật thà về sản phẩm thủ công (men loang, "
                "sai khác nhỏ là đặc trưng), luôn hướng dẫn khách dùng và giữ gốm bền. [BẢN DEMO — anh/chị sửa trước khi ban hành]"),
    "personality": ["Ấm áp", "Mộc mạc", "Tỉ mỉ", "Thật thà"],
    "traits": [{"is": "ấm áp, gần gũi", "is_not": "suồng sã, sến"},
               {"is": "mộc mạc, dễ hiểu", "is_not": "hoa mỹ, sáo rỗng"},
               {"is": "thật thà về hàng thủ công", "is_not": "phóng đại, hứa quá"},
               {"is": "chủ động hướng dẫn", "is_not": "đùn đẩy, trả lời cụt"}],
    "address": {"customer": {"self": "Mộc", "customer": "anh/chị"},
                "segments": [{"key": "khach_le", "label": "Khách lẻ", "self": "Mộc", "customer": "anh/chị"},
                             {"key": "khach_si", "label": "Khách sỉ / quán cà phê", "self": "Mộc", "customer": "anh/chị"},
                             {"key": "hoc_vien", "label": "Học viên lớp nặn", "self": "Mộc", "customer": "bạn"}],
                "internal": {"self": "mình", "other": "anh/chị/bạn"}, "avoid": ["tao", "mày", "tớ", "cậu", "bạn", "tôi"]},
    "preferred_terms": [{"use": "men loang tự nhiên", "instead_of": ["lỗi men"]},
                        {"use": "đổi trả", "instead_of": ["bồi thường"]},
                        {"use": "gốm thủ công", "instead_of": ["hàng chợ"]}],
    "banned_words": ["rẻ nhất", "hàng chợ", "đảm bảo 100%", "ok con dê", "vãi"],
    "banned_claims": ["không bao giờ vỡ", "an toàn tuyệt đối", "hoàn tiền ngay lập tức", "chịu nhiệt mọi nhiệt độ"],
    "emoji": {"policy": "light", "max": 2},
    "formatting": "Câu ngắn, mỗi ý một dòng; giá ghi dạng 185.000đ; không viết hoa cả câu.",
    "signature": "Tiệm Gốm Mộc — làm bằng tay, dùng bằng tim\nHotline 0900 000 000 (demo)",
    "closing": "Mộc cảm ơn anh/chị đã ghé tiệm ạ.",
    "channels": {
        "zalo": {"tone": "Thân mật, trả lời nhanh, 2–4 câu.", "greeting": "Dạ Mộc chào anh/chị ạ", "max_chars": 500},
        "facebook": {"tone": "Như Zalo; bình luận công khai thì mời nhắn riêng khi hỏi đơn/giá sỉ.",
                     "greeting": "Dạ Mộc chào anh/chị ạ", "max_chars": 500},
        "email": {"tone": "Lịch sự, đủ ý, có ký tên.", "greeting": "Kính gửi anh/chị", "emoji": "none", "max_chars": 2500},
        "phone": {"tone": "Chậm, rõ, nhắc lại số đơn và địa chỉ.", "greeting": "Dạ Tiệm Gốm Mộc xin nghe", "emoji": "none",
                  "max_chars": 700},
        "website": {"tone": "Kể chuyện làm gốm, có thông tin chất liệu, cách dùng.", "max_chars": 3000},
        "internal": {"tone": "Ngắn, rõ việc, có số liệu.", "emoji": "light"}},
    "examples": [
        {"channel": "zalo", "situation": "Khách hỏi bát bị loang màu có phải lỗi không",
         "good": "Dạ Mộc chào anh/chị ạ. Vệt loang là men loang tự nhiên khi nung, mỗi chiếc một khác nên không phải lỗi ạ. Anh/chị cần Mộc gửi thêm ảnh thật của chiếc bát không ạ?",
         "bad": "Lỗi men thôi bạn ơi, hàng chợ chỗ nào chả thế!!", "why": "Không gọi là lỗi, không chê hàng, không xưng 'bạn' với khách lẻ."},
        {"channel": "zalo", "situation": "Khách nhận hàng bị vỡ, đòi hoàn tiền",
         "good": "Dạ Mộc rất tiếc vì chiếc cốc bị vỡ khi giao ạ. Anh/chị gửi giúp Mộc ảnh kiện hàng và chiếc cốc, Mộc kiểm tra và đổi trả theo chính sách trong hôm nay ạ.",
         "bad": "Tôi hoàn tiền ngay lập tức cho bạn nhé, đảm bảo 100% không bao giờ vỡ nữa 😀😀😀",
         "why": "Không hứa hoàn tiền ngoài chính sách, không cam kết tuyệt đối."},
        {"channel": "email", "situation": "Quán cà phê hỏi giá sỉ 200 cốc",
         "good": "Kính gửi anh/chị,\nMộc gửi anh/chị báo giá sỉ 200 cốc men lam kèm thời gian làm 3–4 tuần. Anh/chị cần mẫu thử, Mộc gửi trước 2 chiếc ạ.\nTiệm Gốm Mộc — làm bằng tay, dùng bằng tim",
         "bad": "Giá rẻ nhất thị trường luôn nha 😍", "why": "Email cần ký tên, không khẳng định rẻ nhất, không emoji."}],
    "lexicon": [{"term": "Gốm Mộc", "say": "Gốm Mộc"}, {"term": "COD", "say": "xi ô đi"},
                {"term": "Zalo", "say": "Da lô"}, {"term": "ship", "say": "giao hàng"}],
}

DEMO_PROFILE = {"provider": "cometapi", "model": "gpt-4o-mini-tts", "voice_name": "nova", "language": "vi-VN", "speed": 1.0,
                "pitch": "medium", "style": "ấm, chậm rãi, mỉm cười khi nói",
                "greeting_script": "Dạ Tiệm Gốm Mộc xin nghe. Mộc có thể giúp gì cho anh chị ạ?",
                "closing_script": "Mộc cảm ơn anh chị đã gọi cho tiệm. Chúc anh chị một ngày thật vui ạ.",
                "sample_text": "Dạ Mộc chào anh chị. Đơn COD của anh chị sẽ được ship trong hôm nay, anh chị để ý điện thoại giúp Mộc nhé."}


def seed_demo(db: Session, org_id: int, company_id: int, principal=None) -> dict:
    """Bản nháp DEMO (không ban hành) + cấu hình giọng nói demo. Đã có bản nháp → không ghi đè."""
    co = db.get(Company, company_id)
    if co is None or co.organization_id != org_id:
        raise _err(404, "not_found", "Không thấy công ty.")
    ensure_legacy(db, co)
    dr = _draft(db, co.id)
    created = False
    if dr is None:
        out = save_draft(db, org_id, principal, {"company_id": co.id, "spec": DEMO_SPEC, "is_demo": True,
                                                 "change_note": "Bản DEMO do hệ thống soạn — sửa rồi gửi duyệt"})
        created, dr_id = True, out["id"]
    else:
        dr_id = dr.id
    p = db.query(VoiceProfile).filter(VoiceProfile.company_id == co.id).first()
    if p is None:
        save_profile(db, org_id, principal, {"company_id": co.id, **DEMO_PROFILE, "is_demo": True})
    return {"draft_id": dr_id, "created": created}
