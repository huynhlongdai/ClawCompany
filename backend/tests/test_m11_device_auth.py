"""M1.1 — client backend ký ``connect.challenge`` bằng khoá thiết bị Ed25519.

Lỗi thật (VM persimmon, OpenClaw 2026.9.8, ``--bind lan --auth token``): không
gửi ``device`` → gateway xoá scope → ``missing scope: operator.read``. Sau sửa:
gateway tạo yêu cầu ghép đôi đúng role/scope; duyệt xong ``agents.list`` chạy.
Định dạng payload/ID/chữ ký đã được đối chiếu bằng chính hàm của OpenClaw
(``buildDeviceAuthPayloadV3``, ``deriveDeviceIdFromPublicKey``,
``verifyDeviceSignature``) — xem ``_reports/m1-openclaw-core.md``.
"""
import asyncio
import base64
import hashlib
import json
import os

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.core.config import settings
from app.runtime import openclaw_device as dev
from app.runtime.openclaw_native import NativeOpenClawRuntime, OpenClawProtocolError


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@pytest.fixture()
def ident_path(tmp_path, monkeypatch):
    p = tmp_path / "dev" / "openclaw-device.json"
    monkeypatch.setattr(settings, "openclaw_device_identity_path", str(p))
    monkeypatch.setattr(settings, "openclaw_device_auth", True)
    return p


def test_payload_v3_matches_upstream_layout():
    s = dev.build_payload_v3(device_id="d", client_id="gateway-client", client_mode="backend",
                             role="operator", scopes=["operator.read", "operator.write"],
                             signed_at_ms=1737264000000, token="tok", nonce="n1",
                             platform=" Linux ", device_family=None)
    assert s == "v3|d|gateway-client|backend|operator|operator.read,operator.write|1737264000000|tok|n1|linux|"


def test_payload_without_token_keeps_empty_slot():
    s = dev.build_payload_v3(device_id="d", client_id="c", client_mode="m", role="r", scopes=[],
                             signed_at_ms=1, token=None, nonce="n", platform="x", device_family="Server")
    assert s == "v3|d|c|m|r||1||n|x|server"


def test_normalize_meta_only_lowers_ascii_and_trims():
    assert dev.normalize_meta("  MacOS ") == "macos"
    assert dev.normalize_meta("ÄB") == "Äb"
    assert dev.normalize_meta(None) == ""


def test_device_id_is_sha256_of_raw_public_key_and_signature_verifies():
    ident = dev.DeviceIdentity.generate()
    raw = _unb64(ident.public_key)
    assert len(raw) == 32 and ident.device_id == hashlib.sha256(raw).hexdigest()
    block = ident.device_block(client_id="gateway-client", client_mode="backend", role="operator",
                               scopes=["operator.read"], token="t", nonce="abc", signed_at_ms=42,
                               platform="linux", device_family=None)
    assert set(block) == {"id", "publicKey", "signature", "signedAt", "nonce"}
    assert "=" not in block["publicKey"] and "=" not in block["signature"]
    payload = dev.build_payload_v3(device_id=ident.device_id, client_id="gateway-client",
                                   client_mode="backend", role="operator", scopes=["operator.read"],
                                   signed_at_ms=42, token="t", nonce="abc", platform="linux",
                                   device_family=None)
    Ed25519PublicKey.from_public_bytes(raw).verify(_unb64(block["signature"]), payload.encode())


def test_identity_is_persisted_once_and_private(ident_path):
    a = dev.load_or_create(ident_path)
    b = dev.load_or_create(ident_path)
    assert a.device_id == b.device_id
    assert oct(os.stat(ident_path).st_mode & 0o777) == "0o600"


def test_losing_the_create_race_reads_the_winner(ident_path, monkeypatch):
    winner = dev.DeviceIdentity.generate()
    ident_path.parent.mkdir(parents=True)
    real_exists = dev.Path.exists
    # Mô phỏng: lúc kiểm tra chưa có file, nhưng tới lúc O_EXCL thì tiến trình khác đã ghi.
    ident_path.write_text(json.dumps({"privateKeyPem": winner.private_pem()}))
    monkeypatch.setattr(dev.Path, "exists", lambda self: False if self == ident_path else real_exists(self))
    assert dev.load_or_create(ident_path).device_id == winner.device_id


def test_connect_params_sign_the_challenge(ident_path, monkeypatch):
    monkeypatch.setattr(settings, "openclaw_api_token", "shared")
    rt = NativeOpenClawRuntime()
    params = rt._connect_params({"nonce": "N-1", "ts": 1737264000123})
    d = params["device"]
    assert d["nonce"] == "N-1" and d["signedAt"] == 1737264000123
    ident = dev.load_or_create(ident_path)
    assert d["id"] == ident.device_id
    payload = dev.build_payload_v3(device_id=d["id"], client_id=params["client"]["id"],
                                   client_mode=params["client"]["mode"], role=params["role"],
                                   scopes=params["scopes"], signed_at_ms=d["signedAt"], token="shared",
                                   nonce="N-1", platform=params["client"]["platform"], device_family=None)
    Ed25519PublicKey.from_public_bytes(_unb64(d["publicKey"])).verify(_unb64(d["signature"]), payload.encode())


def test_no_challenge_or_disabled_means_no_device(ident_path, monkeypatch):
    rt = NativeOpenClawRuntime()
    assert "device" not in rt._connect_params()
    assert "device" not in rt._connect_params({"ts": 1})
    monkeypatch.setattr(settings, "openclaw_device_auth", False)
    assert "device" not in rt._connect_params({"nonce": "n", "ts": 1})


class _FakeWS:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))
        if self.sent[-1].get("method") == "connect" and self.incoming and callable(self.incoming[0]):
            self.incoming[0] = self.incoming[0](self.sent[-1]["id"])

    async def recv(self):
        if not self.incoming:
            await asyncio.sleep(10)
        item = self.incoming[0]
        if callable(item):
            await asyncio.sleep(10)
        return json.dumps(self.incoming.pop(0))


def test_handshake_waits_for_challenge_then_sends_signed_connect(ident_path):
    challenge = {"type": "event", "event": "connect.challenge", "payload": {"nonce": "zz", "ts": 7}}
    ws = _FakeWS([challenge, lambda rid: {"type": "res", "id": rid, "ok": True,
                                          "payload": {"type": "hello-ok"}}])
    hello = asyncio.run(NativeOpenClawRuntime()._handshake(ws))
    assert hello["ok"] is True
    connect = ws.sent[0]
    assert connect["method"] == "connect"
    assert connect["params"]["device"]["nonce"] == "zz" and connect["params"]["device"]["signedAt"] == 7


def test_pairing_required_is_explained_in_vietnamese(ident_path):
    challenge = {"type": "event", "event": "connect.challenge", "payload": {"nonce": "zz", "ts": 7}}
    err = {"code": "NOT_PAIRED", "message": "pairing required", "details": {"code": "PAIRING_REQUIRED"}}
    ws = _FakeWS([challenge, lambda rid: {"type": "res", "id": rid, "ok": False, "error": err}])
    with pytest.raises(OpenClawProtocolError) as exc:
        asyncio.run(NativeOpenClawRuntime()._handshake(ws))
    assert "openclaw devices approve" in str(exc.value)


def test_old_gateway_without_challenge_still_connects(ident_path, monkeypatch):
    monkeypatch.setattr(settings, "openclaw_challenge_timeout_seconds", 0.05)
    ws = _FakeWS([lambda rid: {"type": "res", "id": rid, "ok": True, "payload": {"type": "hello-ok"}}])
    asyncio.run(NativeOpenClawRuntime()._handshake(ws))
    assert "device" not in ws.sent[0]["params"]
