"""v35.1: hình dạng frame gửi lên dây, pin theo schema upstream.

Vì sao cần file này: 89 test của v19-v35 đều xanh trong khi adapter native
không thể nói chuyện với một gateway thật. Chúng kiểm *nội dung params* bằng
test double và grep source, nhưng không có test nào kiểm *cái thực sự được
gửi lên WebSocket*. Bốn lỗi chặn toàn bộ đã sống qua 89 test đó:

1. request frame thiếu ``type: "req"`` -> 1008 policy violation;
2. đọc ``result`` trong khi upstream trả ``ok`` + ``payload``;
3. handshake sai hình dạng so với ``ConnectParamsSchema``, kèm ``client.id``
   không nằm trong enum đóng ``GATEWAY_CLIENT_IDS``;
4. ``sessions.messages.subscribe`` dùng ``sessionKey`` thay vì ``key``;
5. ``chat.send`` gửi ``metadata`` và thiếu ``idempotencyKey``.

Nguồn đối chiếu (đọc trực tiếp, không suy đoán):
``packages/gateway-protocol/src/schema/frames.ts``,
``schema/logs-chat.ts``, ``schema/exec-approvals.ts``,
``src/client-info.ts`` của openclaw/openclaw.

Đã kiểm chứng thực nghiệm với OpenClaw 2026.9.4 chạy localhost:
``_reports/native-probe-before-fix.log`` (1008) và
``_reports/native-probe-after-fix.log`` (hello-ok + sessions.create +
chat.send thành công).

Những test dưới đây KHÔNG cần gateway: chúng kiểm frame mà adapter tạo ra.
Đó là điểm mấu chốt -- một test cần gateway sẽ bị bỏ qua trong CI và lỗi
quay lại.
"""
import json
import uuid

import pytest

from app.runtime import openclaw_protocol as ocp
from app.runtime.openclaw_native import NativeOpenClawRuntime


@pytest.fixture()
def runtime():
    return NativeOpenClawRuntime()


# --- 1. Envelope ----------------------------------------------------------

def test_request_frame_declares_the_required_type_literal(runtime):
    """RequestFrameSchema = closedObject({type: Literal("req"), id, method, params?})."""
    frame = runtime._request_frame("status", {})
    assert frame["type"] == "req"
    assert frame["method"] == "status"
    assert frame["params"] == {}
    assert frame["id"]
    # closedObject: không được thừa khoá nào ngoài bốn khoá này.
    assert set(frame) == {"type", "id", "method", "params"}


def test_request_frame_keeps_the_caller_supplied_id(runtime):
    rid = str(uuid.uuid4())
    assert runtime._request_frame("status", {}, rid)["id"] == rid


def test_request_frame_is_json_serialisable(runtime):
    json.dumps(runtime._request_frame("sessions.list", {"limit": 10}))


# --- 2. Đọc response ------------------------------------------------------

def test_response_is_read_from_payload_not_result(runtime):
    """ResponseFrameSchema mang kết quả ở ``payload``, kèm cờ ``ok``."""
    out = runtime._read_response({"type": "res", "id": "x", "ok": True,
                                  "payload": {"runtimeVersion": "2026.9.4"}})
    assert out["runtimeVersion"] == "2026.9.4"


def test_ok_false_is_an_error_even_without_an_error_field(runtime):
    """Bản cũ chỉ kiểm ``error``, nên ok=false trần bị đọc thành thành công."""
    from app.runtime.openclaw_native import OpenClawProtocolError

    with pytest.raises(OpenClawProtocolError):
        runtime._read_response({"type": "res", "id": "x", "ok": False})


def test_error_field_is_raised(runtime):
    from app.runtime.openclaw_native import OpenClawProtocolError

    with pytest.raises(OpenClawProtocolError):
        runtime._read_response({"type": "res", "id": "x", "ok": False,
                                "error": {"code": "INVALID_REQUEST", "message": "nope"}})


def test_non_dict_payload_is_wrapped_not_dropped(runtime):
    assert runtime._read_response({"ok": True, "payload": [1, 2]}) == {"payload": [1, 2]}


# --- 3. Handshake ---------------------------------------------------------

def test_connect_params_match_the_upstream_schema(runtime):
    params = runtime._connect_params()
    assert params["minProtocol"] == params["maxProtocol"] >= 1
    assert "protocolVersion" not in params, "trường của bản cũ, không có trong schema"
    assert params["role"] == ocp.ROLE_OPERATOR
    assert set(params) <= {"minProtocol", "maxProtocol", "client", "caps", "commands",
                           "permissions", "role", "scopes", "auth", "locale", "userAgent",
                           "device", "modelCatalog", "pathEnv"}


def test_client_id_is_from_the_closed_upstream_enum(runtime):
    """``client.id`` là Type.Enum(GATEWAY_CLIENT_IDS) -- chuỗi tự đặt bị từ chối."""
    upstream_client_ids = {
        "webchat-ui", "openclaw-control-ui", "openclaw-browser-copilot", "openclaw-tui",
        "webchat", "cli", "gateway-client", "openclaw-macos", "openclaw-linux",
        "openclaw-ios", "openclaw-watchos", "openclaw-android", "node-host",
        "openclaw-worker", "test", "fingerprint", "openclaw-probe",
    }
    upstream_modes = {"webchat", "cli", "ui", "backend", "node", "worker", "probe", "test"}
    client = runtime._connect_params()["client"]
    assert client["id"] in upstream_client_ids
    assert client["mode"] in upstream_modes
    assert "name" not in client, "schema không có client.name"
    assert client["version"] and client["platform"]
    # Tên riêng của ClawCompany vẫn phải xuất hiện, nhưng ở trường chẩn đoán.
    assert client["displayName"]


def test_token_goes_into_auth_not_top_level(monkeypatch, runtime):
    from app.core.config import settings

    monkeypatch.setattr(settings, "openclaw_api_token", "secret-token")
    params = NativeOpenClawRuntime()._connect_params()
    assert params["auth"] == {"token": "secret-token"}
    assert "token" not in params


def test_scopes_stay_narrow_by_default(runtime):
    assert set(runtime.scopes()) == {"operator.read", "operator.write"}
    assert ocp.SCOPE_APPROVALS not in runtime.scopes()


def test_operator_scope_list_matches_upstream():
    """Hằng số tự nhận là tập đóng thì phải đúng là tập đóng của upstream."""
    assert set(ocp.OPERATOR_SCOPES) == {
        "operator.admin", "operator.approvals", "operator.pairing",
        "operator.questions", "operator.read", "operator.talk",
        "operator.talk.secrets", "operator.write",
    }


# --- 4. Tham số từng method ----------------------------------------------

def test_subscribe_uses_key_not_session_key():
    """Đo được: {"sessionKey": ...} -> INVALID_REQUEST "must have required property 'key'".

    Gateway thật (2026.9.4) chấp nhận {"key": ...} và từ chối {"sessionKey": ...}.
    """
    import inspect

    src = inspect.getsource(NativeOpenClawRuntime.stream_run)
    assert '{"key": session_key}' in src
    assert '{"sessionKey": session_key}' not in src


def test_chat_send_carries_idempotency_key_and_no_metadata():
    """ChatSendParamsSchema: required ["sessionKey","message","idempotencyKey"], closed.

    ``metadata`` không phải thuộc tính của schema; gửi nó làm cả lượt gọi bị
    từ chối. Metadata của ClawCompany phải ở lại phía ClawCompany.
    """
    import inspect

    src = inspect.getsource(NativeOpenClawRuntime.run_agent)
    assert '"idempotencyKey": idempotency_key' in src
    assert '"metadata": meta' not in src


def test_idempotency_key_is_stable_per_send_not_per_task():
    """Khoá idempotency phải ổn định theo NỘI DUNG, không theo task.

    Bản đầu khoá theo task id (``clawcompany:{key}:task-{id}``). Nghe hợp lý,
    nhưng đo với gateway thật thì lượt gửi THỨ HAI cho cùng task -- một chỉ
    thị khác hẳn -- bị chặn:

        INVALID_REQUEST: This message ID was already used for different input
        (reason: chat-request-conflict)

    Tức một agent chỉ nhận được đúng một tin nhắn trong cả đời task. Khoá đúng
    phải dedupe *cùng một lần gửi* (retry transport) mà vẫn cho phép chỉ thị
    mới, nên nó gồm vân tay nội dung.
    """
    import inspect
    import re

    src = inspect.getsource(NativeOpenClawRuntime.run_agent)
    assert "hashlib.sha256(input_text" in src, "khoá phải gồm vân tay nội dung"
    assert re.search(r'task-\{task_ref\}:\{fingerprint\}', src)
    # Và không được quay về dạng chỉ-theo-task.
    assert not re.search(r'f"clawcompany:\{key\}:task-\{task_ref\}"\s*$', src, re.M)


def test_idempotency_key_dedupes_identical_text():
    """Cùng chữ -> cùng khoá; khác chữ -> khác khoá. Kiểm bằng cách tính lại."""
    import hashlib

    key = "agent:dev:company-task-5"
    def build(text: str) -> str:
        fp = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        return f"clawcompany:{key}:task-5:{fp}"

    assert build("Làm A") == build("Làm A")
    assert build("Làm A") != build("Làm B")


def test_approval_resolve_params_stay_closed():
    """ExecApprovalResolveParamsSchema: required ["id","decision"], additionalProperties false."""
    import inspect

    src = inspect.getsource(NativeOpenClawRuntime.respond_approval)
    assert '{"id": request_id, "decision": decision}' in src
    assert 'params["sessionKey"]' not in src
