"""Embedding thật cho kho tri thức (API tương thích OpenAI ``POST /embeddings``).

Không cấu hình hoặc API lỗi → trả ``None`` và nơi gọi rơi về hash384 (tìm theo từ khoá như cũ),
không bao giờ chặn nạp tài liệu. Mỗi chunk ghi ``embedding_provider`` = ``api:<model>`` để biết vector
nào so được với vector câu hỏi (khác model → không so).
"""
from __future__ import annotations

import json
import math
import os
import urllib.request

from app.core.config import settings

BATCH = 64
TIMEOUT = 30


def _key() -> str:
    f = settings.embedding_api_key_file or os.environ.get("EMBEDDING_API_KEY_FILE", "")
    if f:
        try:
            with open(f, encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError:
            return ""
    return settings.embedding_api_key or os.environ.get("EMBEDDING_API_KEY", "")


def configured() -> bool:
    return bool((settings.embedding_api_base or "").strip() and _key())


def provider_name() -> str:
    return f"api:{settings.embedding_model}" if configured() else "hash384"


def _post(texts: list[str]) -> list[list[float]]:
    url = settings.embedding_api_base.rstrip("/") + "/embeddings"
    body = json.dumps({"model": settings.embedding_model, "input": texts}).encode()
    req = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {_key()}",
                                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 — URL do quản trị cấu hình
        data = json.load(r)["data"]
    out = [d["embedding"] for d in sorted(data, key=lambda d: d.get("index", 0))]
    return [_norm(v) for v in out]


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def embed(texts: list[str]) -> list[list[float]] | None:
    """Vector đã chuẩn hoá cho từng đoạn, hoặc ``None`` khi chưa cấu hình / API lỗi."""
    if not texts or not configured():
        return None
    try:
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH):
            out.extend(_post([t[:8000] or " " for t in texts[i:i + BATCH]]))
        return out if len(out) == len(texts) else None
    except Exception as exc:  # noqa: BLE001
        print(f"[embeddings] {type(exc).__name__}: {str(exc)[:200]}")
        return None


def semantic(cos: float) -> float:
    """Đưa cosine của embedding thật về 0..1 (text-embedding-3: câu cùng ý ~0.35–0.7, khác chủ đề ~0.1–0.28)."""
    return max(0.0, min(1.0, (cos - 0.15) / 0.45))
