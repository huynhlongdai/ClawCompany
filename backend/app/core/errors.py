"""M1: mọi lỗi chưa bắt đều thành JSON tiếng Việt, VÀ đi qua CORS.

Trước đây một exception chưa bắt rơi ra tới ``ServerErrorMiddleware`` của
Starlette — lớp NGOÀI CORSMiddleware — nên phản hồi 500 không có header
``Access-Control-Allow-Origin``. Trình duyệt chặn đọc phản hồi đó và báo "lỗi
CORS", nên mọi 500 trông như mất kết nối (đo được trên box: nút "Nối lại người
theo dõi" → 500 → console chỉ thấy CORS).

Middleware này phải được thêm TRƯỚC CORSMiddleware (Starlette: thêm sau = lớp
ngoài), để phản hồi lỗi nó dựng vẫn đi qua CORS.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from starlette.responses import JSONResponse

log = logging.getLogger("clawcompany.errors")


def classify(exc: BaseException) -> tuple[int, str, str]:
    """(status, code, câu tiếng Việt) cho một exception chưa bắt."""
    from app.runtime.openclaw_native import OpenClawProtocolError
    if isinstance(exc, OpenClawProtocolError):
        return 502, "openclaw_error", f"Gateway OpenClaw trả lỗi: {str(exc)[:300]}"
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return 504, "timeout", "Hết thời gian chờ dịch vụ phía sau (gateway hoặc cơ sở dữ liệu). Thử lại sau ít giây."
    if isinstance(exc, (ConnectionError, OSError)):
        return 503, "upstream_unreachable", "Không kết nối được dịch vụ phía sau (gateway OpenClaw, Redis hoặc DB)."
    return 500, "internal_error", "Lỗi máy chủ. Lỗi đã được ghi lại; gửi mã yêu cầu cho quản trị viên nếu lặp lại."


class JSONErrorMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def _send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception as exc:  # noqa: BLE001
            if started:  # đã gửi header thì không thể đổi phản hồi nữa
                raise
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
            request_id = headers.get("x-request-id") or f"req_{uuid.uuid4().hex[:16]}"
            status, code, message = classify(exc)
            log.exception("unhandled %s %s [%s]", scope.get("method"), scope.get("path"), request_id)
            response = JSONResponse(
                {"detail": message, "code": code, "request_id": request_id,
                 "error_type": type(exc).__name__},
                status_code=status, headers={"X-Request-ID": request_id},
            )
            await response(scope, receive, send)
