from functools import lru_cache
import logging

from app.core.config import settings
from app.runtime.mock import MockOpenClawRuntime
from app.runtime.openclaw_native import NativeOpenClawRuntime

log = logging.getLogger("clawcompany.runtime")

# M1: chế độ "gateway" (adapter RPC kiểu cũ, viết theo hợp đồng đoán, chưa bao
# giờ chạy được với gateway thật) đã bị xoá. Giá trị cũ được hiểu là "native" —
# không âm thầm rơi về mock, vì như thế agent sẽ "làm việc" giả mà không ai biết.
LEGACY_ALIASES = {"gateway": "native", "openclaw": "native"}


def resolve_mode(mode: str) -> str:
    mode = (mode or "mock").strip().lower()
    if mode == "gateway":
        log.warning("OPENCLAW_MODE=gateway đã bị bỏ; dùng native (giao thức gateway OpenClaw thật).")
    return LEGACY_ALIASES.get(mode, mode)


@lru_cache(maxsize=4)
def _runtime_for(mode: str):
    if mode == "native":
        return NativeOpenClawRuntime()
    return MockOpenClawRuntime()


def get_runtime():
    # Keep one runtime instance per process. This matters for mock/dev sessions and
    # also avoids reconnect/config churn in long-running gateway processes.
    return _runtime_for(resolve_mode(settings.openclaw_mode))
