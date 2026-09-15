from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints

# Email của một identity ĐÃ LƯU: chỉ kiểm hình dạng, không kiểm khả năng gửi
# thư. Lý do rất cụ thể: seed.py tạo ``admin@clawcompany.local`` và README
# quảng cáo đúng tài khoản đó, nhưng ``EmailStr`` từ chối TLD ``.local`` vì nó
# là special-use/reserved. Hệ quả đo được trên bản chạy thật:
#
#   POST /api/auth/login -> 422 "The part after the @-sign is a special-use or
#   reserved name that cannot be used with email"
#
# Tức không ai đăng nhập được vào một bản cài mới. Và vì ``UserOut.email``
# cũng là EmailStr, kể cả khi qua được login thì ``GET /api/auth/me`` sẽ 500
# lúc dựng response.
#
# Ranh giới: ĐĂNG KÝ vẫn dùng EmailStr -- lúc tạo mới một địa chỉ thì kiểm tra
# chặt là đúng. Còn lúc đối chiếu một địa chỉ đã tồn tại trong database thì
# không: dữ liệu đã ở đó rồi, từ chối nó chỉ là tự khoá cửa nhà mình.
StoredEmail = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=320,
                      pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
]

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10)
    display_name: str = ""

class LoginRequest(BaseModel):
    email: StoredEmail
    password: str
    organization_id: int | None = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    organization_id: int | None = None
    role: str = "member"

class UserOut(BaseModel):
    id: int
    email: StoredEmail
    display_name: str
    is_active: bool
    is_superuser: bool

class APIKeyCreate(BaseModel):
    organization_id: int
    name: str
    scopes: list[str] = []
    member_id: int | None = None

class APIKeyCreated(BaseModel):
    id: int
    name: str
    key: str
    key_prefix: str

class OrganizationAccessGrant(BaseModel):
    user_id: int
    organization_id: int
    role: str = Field(default="member", pattern="^(guest|member|manager|admin|owner)$")
    is_default: bool = False
