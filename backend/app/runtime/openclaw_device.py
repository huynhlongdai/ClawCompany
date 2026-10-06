"""M1.1 — định danh thiết bị (device identity) cho client backend OpenClaw.

Đo trên gateway 2026.9.8 chạy ``--bind lan --auth token`` (VM persimmon,
06/10/2026): ClawCompany kết nối bằng token chung nhưng KHÔNG gửi ``device``,
nên gateway xoá hết scope tự khai và mọi lời gọi đọc nhận
``FORBIDDEN missing scope: operator.read``. Theo docs/gateway/protocol/auth.md,
chỉ hai đường "device-less" được giữ scope (Control UI trusted-proxy và helper
loopback nội bộ); client backend chạy ở container khác phải:

1. chờ event ``connect.challenge`` (``payload.nonce``, ``payload.ts``);
2. ký payload v3 (``buildDeviceAuthPayloadV3`` trong
   ``packages/gateway-client/src/device-auth.ts``)::

       v3|deviceId|clientId|clientMode|role|scope1,scope2|signedAtMs|token|nonce|platform|deviceFamily

   với ``platform``/``deviceFamily`` đã trim và hạ chữ hoa A–Z;
3. gửi ``connect.params.device = {id, publicKey, signature, signedAt, nonce}``
   trong đó ``id = sha256(raw public key).hex`` và ``publicKey``/``signature``
   là base64url không padding (Ed25519).

Lần đầu thiết bị mới sẽ nhận ``PAIRING_REQUIRED``; người vận hành duyệt một lần
bằng ``openclaw devices approve`` trên gateway. Khoá được lưu trong một file
dùng chung cho api/worker/beat để cả ba là CÙNG một thiết bị (duyệt một lần).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def normalize_meta(value) -> str:
    """Giống ``normalizeDeviceMetadataForAuth``: trim, chỉ hạ chữ A–Z."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[A-Z]", lambda m: m.group(0).lower(), value.strip())


def build_payload_v3(*, device_id: str, client_id: str, client_mode: str, role: str,
                     scopes: list[str], signed_at_ms: int, token: str | None, nonce: str,
                     platform: str | None, device_family: str | None) -> str:
    return "|".join([
        "v3", device_id, client_id, client_mode, role, ",".join(scopes),
        str(int(signed_at_ms)), token or "", nonce,
        normalize_meta(platform), normalize_meta(device_family),
    ])


class DeviceIdentity:
    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._key = private_key
        raw = private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.public_key = b64url(raw)
        self.device_id = hashlib.sha256(raw).hexdigest()

    @classmethod
    def generate(cls) -> "DeviceIdentity":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_pem(cls, pem: str) -> "DeviceIdentity":
        key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("OpenClaw device key phải là Ed25519")
        return cls(key)

    def private_pem(self) -> str:
        return self._key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()).decode("ascii")

    def sign(self, payload: str) -> str:
        return b64url(self._key.sign(payload.encode("utf-8")))

    def device_block(self, *, client_id: str, client_mode: str, role: str, scopes: list[str],
                     token: str | None, nonce: str, signed_at_ms: int,
                     platform: str | None, device_family: str | None) -> dict:
        payload = build_payload_v3(
            device_id=self.device_id, client_id=client_id, client_mode=client_mode, role=role,
            scopes=scopes, signed_at_ms=signed_at_ms, token=token, nonce=nonce,
            platform=platform, device_family=device_family)
        return {"id": self.device_id, "publicKey": self.public_key,
                "signature": self.sign(payload), "signedAt": int(signed_at_ms), "nonce": nonce}


def default_path() -> Path:
    return Path.home() / ".clawcompany" / "openclaw-device.json"


def load_or_create(path: str | os.PathLike | None = None) -> DeviceIdentity:
    """Đọc khoá; chưa có thì tạo bằng O_EXCL để api/worker/beat khởi động cùng
    lúc vẫn ra đúng MỘT thiết bị (tiến trình thua cuộc đọc lại file)."""
    p = Path(path) if path else default_path()
    if p.exists():
        return DeviceIdentity.from_pem(json.loads(p.read_text())["privateKeyPem"])
    p.parent.mkdir(parents=True, exist_ok=True)
    ident = DeviceIdentity.generate()
    body = json.dumps({"version": 1, "deviceId": ident.device_id,
                       "publicKey": ident.public_key, "privateKeyPem": ident.private_pem()})
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return DeviceIdentity.from_pem(json.loads(p.read_text())["privateKeyPem"])
    with os.fdopen(fd, "w") as fh:
        fh.write(body)
    return ident
