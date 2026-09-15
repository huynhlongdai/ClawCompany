from functools import lru_cache
from app.core.config import settings
from app.runtime.mock import MockOpenClawRuntime
from app.runtime.gateway import OpenClawGatewayRuntime
from app.runtime.openclaw_native import NativeOpenClawRuntime

@lru_cache(maxsize=4)
def _runtime_for(mode: str):
    # "native" speaks the real upstream OpenClaw Gateway contract (v19).
    # "gateway" is the older configurable adapter kept for deployments pinned
    # to a custom RPC surface; it should be considered deprecated.
    if mode in ("native", "openclaw"):
        return NativeOpenClawRuntime()
    if mode == "gateway":
        return OpenClawGatewayRuntime()
    return MockOpenClawRuntime()

def get_runtime():
    # Keep one runtime instance per process. This matters for mock/dev sessions and
    # also avoids reconnect/config churn in long-running gateway processes.
    return _runtime_for(settings.openclaw_mode.lower())
