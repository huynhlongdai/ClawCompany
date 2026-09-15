from pydantic import BaseModel, EmailStr, Field

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10)
    display_name: str = ""

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    organization_id: int | None = None

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    organization_id: int | None = None
    role: str = "member"

class UserOut(BaseModel):
    id: int
    email: EmailStr
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
