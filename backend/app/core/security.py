from datetime import datetime, timedelta, timezone

import bcrypt
from jose import jwt, JWTError

from app.core.config import settings

# Trước đây dùng ``passlib.CryptContext(schemes=["bcrypt"])``. passlib 1.7.4
# (bản cuối, 2020) đọc ``bcrypt.__about__.__version__``, mà bcrypt 4.1 đã bỏ
# thuộc tính đó. Hệ quả: mỗi lần hash mật khẩu đều in ra
#
#   (trapped) error reading bcrypt version
#   AttributeError: module 'bcrypt' has no attribute '__about__'
#
# passlib bắt lỗi nên vẫn chạy, nhưng log bẩn ở mọi lần đăng nhập và mọi lần
# seed. Gọi thẳng ``bcrypt`` bỏ được một dependency không còn bảo trì mà không
# đổi định dạng hash: vẫn là bcrypt $2b$, nên hash cũ verify bình thường.
#
# bcrypt cắt input ở 72 byte. passlib cũng vậy, nên hành vi không đổi; chỉ là
# nay nó tường minh thay vì ẩn trong thư viện.
BCRYPT_MAX_BYTES = 72


def _prepare(secret: str) -> bytes:
    return secret.encode("utf-8")[:BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(_prepare(password), password_hash.encode("utf-8"))
    except ValueError:
        # Hash không đúng định dạng bcrypt: coi là không khớp, đừng để một
        # dòng dữ liệu hỏng làm sập cả đường đăng nhập.
        return False


class _PasswordHasher:
    """Giữ đúng bề mặt ``pwd_context.hash`` / ``.verify`` mà API key đang dùng.

    ``app/api/auth.py`` và ``app/core/authz.py`` băm/đối chiếu API key qua
    cùng một đối tượng này, nên giữ tên gọi để không phải sửa hai chỗ đó --
    và để hash API key đã phát hành trước đây vẫn verify được.
    """

    @staticmethod
    def hash(secret: str) -> str:
        return hash_password(secret)

    @staticmethod
    def verify(secret: str, hashed: str) -> bool:
        return verify_password(secret, hashed)


pwd_context = _PasswordHasher()

def create_access_token(user_id: int, organization_id: int | None, role: str, minutes: int | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "org_id": organization_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes or settings.access_token_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc
