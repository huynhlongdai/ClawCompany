"""Định tuyến model theo tầng — luật trước, model sau.

Đặc tả: ``docs/agent-knowledge-and-model-routing.md`` §B. Tóm tắt:

* Mỗi việc chạy ở **tầng rẻ nhất đủ điều kiện**. Không dùng LLM để phân loại
  mọi request: luật ở đây chạy trong vài micro-giây và giải thích được.
* Leo thang **có giới hạn**: việc đã bị làm lại / review trả về thì lượt sau
  lên một tầng, tối đa ``MAX_ESCALATION`` tầng so với mức cơ sở.
* Lỗi tạm thời (429/5xx/timeout) không phải việc của router: gateway đã có
  ``model.fallbacks`` cho chuyện đó. Lỗi 400/401 thì đổi model cũng vô ích.
* Mọi quyết định được ghi (``model.routed``) kèm lý do, để tuần sau đo
  **chi phí trên mỗi kết quả được chấp nhận** chứ không phải giá token.

Giá: CometAPI, đã nhân hệ số ``ratio=0.8``, đọc catalog ngày 2026-10-15. Đây là
số để ƯỚC TÍNH; chi phí thật lấy từ usage của gateway.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

PROVIDER = "custom"   # provider OpenAI-compatible trỏ vào CometAPI trên gateway


@dataclass(frozen=True)
class Tier:
    key: str
    label: str
    model_id: str              # id trong models.providers.custom.models
    usd_in_per_m: float
    usd_out_per_m: float
    reasoning: bool
    context_window: int
    use_for: str

    @property
    def ref(self) -> str:
        return f"{PROVIDER}/{self.model_id}"


TIERS: dict[str, Tier] = {t.key: t for t in (
    Tier("T1", "Rẻ nhất", "gpt-5-nano", 0.04, 0.32, True, 400_000,
         "phân loại, tóm tắt, heartbeat, chấm quiz"),
    Tier("T2", "Thường ngày", "gpt-5-mini", 0.20, 1.60, True, 400_000,
         "CSKH, soạn thảo, việc thường"),
    Tier("T3", "Cẩn thận", "gemini-3.8-flash", 0.60, 3.00, False, 1_048_576,
         "lập kế hoạch, review, việc rủi ro"),
    Tier("T4", "Quyết định lớn", "claude-sonnet-5", 1.60, 8.00, False, 200_000,
         "quyết định lớn, chính sách"),
)}
ORDER = ("T1", "T2", "T3", "T4")
MAX_ESCALATION = 1
# Fallback khi model chính lỗi tạm thời: model rẻ, nhanh, khác nhà cung cấp.
FALLBACK_MODEL = "claude-haiku-4-5-20251001"

# Từ khoá → loại việc. Tiếng Việt có và không dấu, vì tiêu đề task do người gõ.
_KINDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("decision", "T4", ("chiến lược", "chien luoc", "chính sách", "chinh sach", "quyết định",
                        "quyet dinh", "ngân sách năm", "tuyển dụng", "sa thải", "hợp đồng",
                        "hop dong", "pháp lý", "phap ly", "giá bán", "định giá")),
    ("planning", "T3", ("kế hoạch", "ke hoach", "lập kế hoạch", "review", "duyệt", "kiểm tra lại",
                        "phân tích", "phan tich", "đánh giá", "danh gia", "báo cáo tháng",
                        "rủi ro", "rui ro", "kiến trúc", "plan")),
    ("light", "T1", ("tóm tắt", "tom tat", "phân loại", "phan loai", "gắn nhãn", "dịch",
                     "heartbeat", "chấm", "nhắc", "kiểm tra nhanh", "liệt kê", "đếm")),
)
# Hành động có hậu quả ra ngoài: tối thiểu T3, dù tiêu đề nghe đơn giản.
_RISKY = ("gửi khách", "gửi email", "gui email", "đăng bài", "dang bai", "thanh toán",
          "thanh toan", "chuyển tiền", "xoá", "xóa", "hoàn tiền", "hoan tien", "publish",
          "production", "deploy", "mua ")
_RISKY_RE = re.compile(r"(gửi|gui|nhắn|nhan tin)\s.{0,30}(khách|khach|đối tác|doi tac|ra ngoài)", re.I)
_CUSTOMER = ("khách hàng", "khach hang", "cskh", "trả lời khách", "tra loi khach", "đơn hàng")
_LEAD_ROLE = re.compile(r"giám đốc|giam doc|trưởng|truong|chief|head|lead|manager|quản lý|ceo|cfo|cmo",
                        re.I)
_REWORK_OUTCOMES = ("failed", "rejected", "changes_requested", "rework", "returned")


@dataclass
class Decision:
    tier: str
    model: str
    base_tier: str
    reasons: list[str] = field(default_factory=list)
    escalated: bool = False
    est_usd: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        t = TIERS[self.tier]
        return {"tier": self.tier, "label": t.label, "model": self.model,
                "base_tier": self.base_tier, "escalated": self.escalated,
                "reasons": self.reasons, "est_usd": round(self.est_usd, 6)}


def _bump(tier: str, steps: int = 1) -> str:
    return ORDER[min(len(ORDER) - 1, ORDER.index(tier) + steps)]


def _max(a: str, b: str) -> str:
    return a if ORDER.index(a) >= ORDER.index(b) else b


def estimate_usd(tier: str, input_tokens: int, output_tokens: int) -> float:
    t = TIERS[tier]
    return input_tokens / 1e6 * t.usd_in_per_m + output_tokens / 1e6 * t.usd_out_per_m


def decide(*, title: str = "", description: str = "", priority: str = "medium",
           role: str = "", rework_count: int = 0, context_chars: int = 0,
           budget_state: str = "ok", pinned_tier: str | None = None) -> Decision:
    """Chọn tầng cho một lượt. Hàm thuần — mọi tín hiệu truyền vào, dễ test.

    ``budget_state``: ``ok`` | ``warned`` (đã chạm nấc cảnh báo) | ``critical_only``.
    ``pinned_tier``: người quản lý ghim tầng cho việc này (ưu tiên tuyệt đối).
    """
    reasons: list[str] = []
    if pinned_tier in TIERS:
        reasons.append(f"người quản lý ghim tầng {pinned_tier}")
        d = Decision(pinned_tier, TIERS[pinned_tier].ref, pinned_tier, reasons)
        d.est_usd = estimate_usd(pinned_tier, max(1, context_chars // 3) + 1500, 800)
        return d

    text = f"{title}\n{description}".lower()
    tier = "T2"
    reasons.append("mặc định T2 cho việc thường")
    for kind, kind_tier, words in _KINDS:
        hit = next((w for w in words if w in text), None)
        if hit:
            tier = kind_tier
            reasons[-1] = f"loại việc '{kind}' (khớp \"{hit}\") → {kind_tier}"
            break

    risky = next((w for w in _RISKY if w in text), None)
    if not risky:
        m = _RISKY_RE.search(text)
        risky = m.group(0) if m else None
    if risky:
        tier = _max(tier, "T3")
        reasons.append(f"có hành động ra ngoài (\"{risky.strip()}\") → tối thiểu T3")
    if tier == "T1" and any(w in text for w in _CUSTOMER):
        tier = "T2"
        reasons.append("khách hàng sẽ đọc kết quả → không dùng T1")
    if priority in ("critical", "urgent") and ORDER.index(tier) < ORDER.index("T3"):
        tier = "T3"
        reasons.append(f"ưu tiên {priority} → tối thiểu T3")
    if role and _LEAD_ROLE.search(role) and tier == "T1":
        tier = "T2"
        reasons.append("ghế quản lý → không dùng T1")
    if context_chars > 200_000 and ORDER.index(tier) < ORDER.index("T3"):
        tier = "T3"
        reasons.append("ngữ cảnh rất dài → model cửa sổ lớn (T3)")

    base = tier
    escalated = False
    if rework_count > 0:
        tier = _bump(tier, min(rework_count, MAX_ESCALATION))
        escalated = tier != base
        reasons.append(f"đã bị làm lại {rework_count} lần → leo tối đa {MAX_ESCALATION} tầng")

    if budget_state in ("warned", "critical_only") and tier == "T4":
        tier = "T3"
        reasons.append("ngân sách đã chạm nấc cảnh báo → hạ T4 xuống T3")

    d = Decision(tier, TIERS[tier].ref, base, reasons, escalated)
    d.est_usd = estimate_usd(tier, max(1, context_chars // 3) + 1500, 800)
    return d


# ------------------------------------------------------------------ đọc từ DB

def rework_count(db, task_id: int) -> int:
    from sqlalchemy import func, select
    from app.models.v37 import TaskJournalEntry
    try:
        return int(db.execute(select(func.count()).select_from(TaskJournalEntry).where(
            TaskJournalEntry.task_id == task_id,
            TaskJournalEntry.outcome.in_(_REWORK_OUTCOMES))).scalar() or 0)
    except Exception:  # noqa: BLE001 - router không được làm hỏng dispatch
        return 0


def budget_state(db, member, task) -> str:
    try:
        from app.services import budget_scope
        lines = " ".join(budget_scope.context_lines(db, member, task)).lower()
    except Exception:  # noqa: BLE001
        return "ok"
    if "chỉ làm việc critical" in lines:
        return "critical_only"
    if lines.strip():
        return "warned"
    return "ok"


def decide_for_task(db, task, member, *, context_chars: int = 0) -> Decision:
    policy = task.execution_policy if isinstance(getattr(task, "execution_policy", None), dict) else {}
    return decide(title=task.title or "", description=task.description or "",
                  priority=task.priority or "medium", role=(member.role if member else "") or "",
                  rework_count=rework_count(db, task.id), context_chars=context_chars,
                  budget_state=budget_state(db, member, task),
                  pinned_tier=(policy or {}).get("model_tier"))


def provider_models() -> list[dict]:
    """Mục ``models.providers.custom.models`` cho gateway (giá đã nhân ratio)."""
    out = []
    for t in TIERS.values():
        out.append({"id": t.model_id, "name": t.model_id, "api": "openai-completions",
                    "reasoning": t.reasoning, "input": ["text"],
                    "cost": {"input": t.usd_in_per_m, "output": t.usd_out_per_m,
                             "cacheRead": 0, "cacheWrite": 0},
                    "contextWindow": t.context_window, "maxTokens": 16384})
    out.append({"id": FALLBACK_MODEL, "name": FALLBACK_MODEL, "api": "openai-completions",
                "reasoning": False, "input": ["text"],
                "cost": {"input": 0.8, "output": 4.0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": 200_000, "maxTokens": 16384})
    return out


def seat_model_config(role: str) -> dict:
    """Cấu hình model mặc định cho một ghế: quản lý T3, thừa hành T2.

    ``utilityModel`` và ``heartbeat.model`` luôn T1 — việc vặt không cần
    model đắt. Router vẫn ghi đè theo từng việc qua ``sessions.patch``.
    """
    primary = TIERS["T3"] if role and _LEAD_ROLE.search(role) else TIERS["T2"]
    return {"model": {"primary": primary.ref, "fallbacks": [f"{PROVIDER}/{FALLBACK_MODEL}"]},
            "utilityModel": TIERS["T1"].ref,
            "heartbeat": {"model": TIERS["T1"].ref, "lightContext": True}}


def tiers_public() -> list[dict]:
    return [{"tier": t.key, "label": t.label, "model": t.ref, "use_for": t.use_for,
             "usd_in_per_m": t.usd_in_per_m, "usd_out_per_m": t.usd_out_per_m}
            for t in TIERS.values()]
