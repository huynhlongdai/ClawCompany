"""i18n cho thông điệp lỗi JSON: tiếng Việt mặc định, tiếng Anh khi client xin.

Thông điệp gốc trong code vẫn là tiếng Việt (nguồn sự thật). Khi request có
``Accept-Language`` ưu tiên ``en``, ``LocaleErrorMiddleware`` dịch trường
``detail`` (chuỗi) hoặc ``detail.message`` của phản hồi lỗi JSON (status ≥ 400)
theo bảng mẫu dưới đây. Câu chưa có trong bảng giữ nguyên tiếng Việt (fallback vi)
— không đoán, không dịch máy.

Mẫu: ``{}`` là chỗ giá trị động (khớp ``.+?``); bản tiếng Anh dùng ``{0}``, ``{1}``…
"""
from __future__ import annotations

import json
import re

SUPPORTED = ("vi", "en")
DEFAULT = "vi"


def pick_locale(accept_language: str | None) -> str:
    """Chọn vi/en theo Accept-Language (có trọng số q). Không nhận ra → vi."""
    if not accept_language:
        return DEFAULT
    best, best_q = DEFAULT, -1.0
    for i, part in enumerate(accept_language.split(",")):
        bits = part.strip().split(";")
        tag = bits[0].strip().lower()
        q = 1.0
        for b in bits[1:]:
            b = b.strip()
            if b.startswith("q="):
                try:
                    q = float(b[2:])
                except ValueError:
                    q = 0.0
        lang = tag.split("-")[0]
        if lang in SUPPORTED and (q > best_q):
            best, best_q = lang, q
    return best


# (mẫu tiếng Việt, bản tiếng Anh)
_PAIRS: list[tuple[str, str]] = [
    # errors.classify
    ("Gateway OpenClaw trả lỗi: {}", "The OpenClaw gateway returned an error: {0}"),
    ("Hết thời gian chờ dịch vụ phía sau (gateway hoặc cơ sở dữ liệu). Thử lại sau ít giây.", "A backend service (gateway or database) timed out. Try again in a few seconds."),
    ("Không kết nối được dịch vụ phía sau (gateway OpenClaw, Redis hoặc DB).", "Could not reach a backend service (OpenClaw gateway, Redis or the database)."),
    ("Lỗi máy chủ. Lỗi đã được ghi lại; gửi mã yêu cầu cho quản trị viên nếu lặp lại.", "Server error. It has been logged; send the request ID to your administrator if it happens again."),
    # auth / quyền
    ("Quyền truy cập tổ chức này đã bị thu hồi", "Your access to this organization has been revoked"),
    ("Tài khoản đã bị khoá", "This account is locked"),
    ("Mật khẩu cần ít nhất 8 ký tự", "Password must be at least 8 characters"),
    ("Email không hợp lệ", "Invalid email address"),
    ("Email này đã có tài khoản — nhập đúng mật khẩu của tài khoản đó", "This email already has an account — enter that account's password"),
    # team
    ("Không tự đổi hoặc thu quyền của chính mình", "You cannot change or revoke your own access"),
    ("Chỉ Chủ sở hữu mới đổi được quyền của Chủ sở hữu khác", "Only an Owner can change another Owner's role"),
    ("Không đổi được quyền của người cao quyền hơn mình", "You cannot change the role of someone above you"),
    ("Tổ chức phải còn ít nhất một Chủ sở hữu", "The organization must keep at least one Owner"),
    ("Vai không hợp lệ", "Invalid role"),
    ("Người này chưa có quyền trong tổ chức", "This person has no access to the organization yet"),
    ("Không thấy công ty trong tổ chức", "Company not found in this organization"),
    ("Phòng ban không thuộc công ty đã chọn", "The department does not belong to the selected company"),
    ("Không thấy phòng ban trong tổ chức", "Department not found in this organization"),
    ("Người quản lý không thuộc tổ chức", "The manager is not in this organization"),
    ("Người quản lý phải cùng công ty", "The manager must be in the same company"),
    ("Ghế được gắn phải là thành viên người trong tổ chức", "The linked seat must be a human member of the organization"),
    ("Ghế này đã gắn với một tài khoản", "This seat is already linked to an account"),
    ("Người này đã ở trong tổ chức — đổi vai ở mục Người & quyền", "This person is already in the organization — change their role under People & access"),
    ("Link mời không đúng", "Invalid invitation link"),
    ("Không thấy lời mời", "Invitation not found"),
    ("Lời mời không còn chờ", "This invitation is no longer pending"),
    ("Không thu hồi được lời mời có vai cao hơn quyền mình", "You cannot revoke an invitation for a role above yours"),
    ("Không thấy công ty", "Company not found"),
    ("Không thấy phòng ban", "Department not found"),
    ("Trưởng phòng phải là thành viên của cùng công ty", "The department head must be a member of the same company"),
    ("Trưởng phòng phải đang hoạt động", "The department head must be active"),
    ("Không thấy thành viên", "Member not found"),
    ("Không thể tự quản lý chính mình", "A member cannot manage themselves"),
    ("Tạo vòng quản lý: {}", "This would create a management loop: {0}"),
    ("Không có mẫu này", "Template not found"),
    ("Dựng công ty thất bại: {}", "Building the company failed: {0}"),
    ("File CSV rỗng", "The CSV file is empty"),
    ("Tối đa {} dòng mỗi lần nhập", "At most {0} rows per import"),
    ("Không sinh được mã agent duy nhất", "Could not generate a unique agent ID"),
    # agent HR
    ("Không thấy nhân sự AI trong tổ chức", "AI employee not found in this organization"),
    ("Cần tên nhân sự AI", "The AI employee needs a name"),
    ("Cần chọn công ty cho nhân sự AI", "Choose a company for the AI employee"),
    ("Ngân sách không được âm", "Budget cannot be negative"),
    ("Không có tool {}", "No such tool: {0}"),
    ("Mức quyền {} không hợp lệ cho {}", "Permission level {0} is not valid for {1}"),
    ("Gateway lỗi khi tạo agent: {}", "The gateway failed to create the agent: {0}"),
    ("Chỉ lưu bản ClawCompany (agent chưa có trên gateway).", "Saved the ClawCompany copy only (the agent is not on the gateway yet)."),
    ("Không đọc được gateway: {}", "Could not read from the gateway: {0}"),
    ("Ghi {} lỗi: {}", "Writing {0} failed: {1}"),
    ("Không sinh lại được: {}", "Could not regenerate: {0}"),
    ("Nhân sự đã nghỉ việc — không sửa hồ sơ được", "This employee has been retired — the profile can no longer be edited"),
    ("Phòng ban phải thuộc cùng công ty", "The department must belong to the same company"),
    ("Nhân sự đã nghỉ việc — không đồng bộ", "This employee has been retired — nothing to sync"),
    ("File không hợp lệ: {}", "Invalid file: {0}"),
    ("Gateway không có agent này — chưa đồng bộ được", "The gateway does not have this agent — cannot sync yet"),
    ("Nhân sự đã nghỉ việc", "This employee has been retired"),
    ("Chỉ tiếp tục được nhân sự đang tạm dừng (hiện: {})", "Only a paused employee can be resumed (currently: {0})"),
    ("action phải là pause, resume hoặc retire", "action must be pause, resume or retire"),
    ("Người nhận việc phải đang làm, cùng công ty và không phải chính nhân sự này", "The new assignee must be active, in the same company and not this employee"),
    # giao việc / vòng đời việc
    ("Việc chưa có người nhận — giao cho một agent trước", "This task has no assignee — assign it to an agent first"),
    ("Không thấy người nhận việc", "Assignee not found"),
    ("Người nhận là người, không phải agent — họ tự làm trên app", "The assignee is a person, not an agent — they work in the app themselves"),
    ("Ghế này chưa có hồ sơ agent — tuyển lại trong Đội ngũ", "This seat has no agent profile — hire it again under Team"),
    ("Task #{} đang được lượt chạy #{} giữ", "Task #{0} is held by run #{1}"),
    ("Trạng thái không hợp lệ", "Invalid status"),
    ("Giao việc cho một người hoặc agent trước rồi mới chuyển {}", "Assign the task to a person or agent before moving it {0}"),
    ("Thêm phụ thuộc này sẽ tạo vòng: {}", "Adding this dependency would create a cycle: {0}"),
    ("Đã gửi cho agent", "Sent to the agent"),
    # duyệt / kế hoạch / routine
    ("Kế hoạch đang {}", "The plan is {0}"),
    ("Yêu cầu này đã {} — không quyết lại được", "This request is already {0} — it cannot be decided again"),
    ("Không thấy routine", "Routine not found"),
    ("Routine đang dừng: {}", "The routine is paused: {0}"),
    ("Không thấy mục tiêu", "Goal not found"),
    ("Không thấy kế hoạch", "Plan not found"),
    ("Không phải hộp việc của anh", "This is not your inbox"),
    ("Cần OpenClaw native runtime", "Requires the native OpenClaw runtime"),
    ("Chọn một: assignee_member_id hoặc assignee_department_id", "Choose one: assignee_member_id or assignee_department_id"),
    ("cần amount_limit hoặc add_usd", "amount_limit or add_usd is required"),
    ("status phải là unread|read|done", "status must be unread|read|done"),
    # MCP
    ("MCP chỉ nhận API key của seat (X-API-Key)", "MCP only accepts a seat API key (X-API-Key)"),
    ("API key trỏ tới thành viên không còn tồn tại", "The API key points to a member that no longer exists"),
    ("X-ClawCompany-Seat không khớp seat của API key", "X-ClawCompany-Seat does not match the API key's seat"),
    ("API key không gắn seat: gửi X-ClawCompany-Seat", "The API key is not bound to a seat: send X-ClawCompany-Seat"),
    ("Không thấy seat", "Seat not found"),
    ("MCP dành cho seat agent", "MCP is for agent seats"),
    ("Seat đang ở trạng thái {}", "The seat is {0}"),
    ("API key thiếu scope {}", "The API key is missing scope {0}"),
    # câu chung từ HTTP status (frontend cũng có bản riêng)
    ("Không tìm thấy dữ liệu.", "Not found."),
]


def _compile(vi: str) -> re.Pattern:
    parts = vi.split("{}")
    return re.compile("^" + "(.+?)".join(re.escape(p) for p in parts) + "$", re.S)


CATALOG: list[tuple[re.Pattern, str]] = [(_compile(v), e) for v, e in _PAIRS]


def translate(message: str, locale: str) -> str:
    if locale != "en" or not isinstance(message, str):
        return message
    m = message.strip()
    for pat, en in CATALOG:
        hit = pat.match(m)
        if hit:
            return en.format(*hit.groups())
    return message


def translate_body(body: dict, locale: str) -> dict:
    """Dịch detail (chuỗi) hoặc detail.message (dict) của một body lỗi."""
    if locale != "en":
        return body
    d = body.get("detail")
    if isinstance(d, str):
        body["detail"] = translate(d, locale)
    elif isinstance(d, dict) and isinstance(d.get("message"), str):
        d["message"] = translate(d["message"], locale)
    return body


class LocaleErrorMiddleware:
    """ASGI: gắn ``Content-Language`` cho mọi phản hồi; với locale ``en`` dịch body lỗi JSON."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
        locale = pick_locale(headers.get("accept-language"))
        scope.setdefault("state", {})["locale"] = locale
        start: dict | None = None
        chunks: list[bytes] = []

        async def _send(message):
            nonlocal start
            if message["type"] == "http.response.start":
                hdrs = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"content-language"]
                hdrs.append((b"content-language", locale.encode()))
                message = {**message, "headers": hdrs}
                ctype = dict((k.lower(), v) for k, v in hdrs).get(b"content-type", b"")
                if locale == "en" and message["status"] >= 400 and b"json" in ctype:
                    start = message  # giữ lại tới khi đọc xong body
                    return
                return await send(message)
            if start is not None and message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                raw = b"".join(chunks)
                try:
                    raw = json.dumps(translate_body(json.loads(raw), locale), ensure_ascii=False).encode()
                except (ValueError, AttributeError):
                    pass
                hdrs = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"]
                hdrs.append((b"content-length", str(len(raw)).encode()))
                await send({**start, "headers": hdrs})
                return await send({"type": "http.response.body", "body": raw})
            return await send(message)

        await self.app(scope, receive, _send)
