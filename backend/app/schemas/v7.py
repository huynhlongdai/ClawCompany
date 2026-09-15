from pydantic import BaseModel, EmailStr, Field

from app.schemas.auth import StoredEmail

class VectorSearchRequest(BaseModel):
    organization_id: int
    query: str
    company_id: int | None = None
    department_id: int | None = None
    project_id: int | None = None
    limit: int = Field(default=10, ge=1, le=50)

class PolicyCheckRequest(BaseModel):
    organization_id: int
    action: str
    actor_member_id: int | None = None
    company_id: int | None = None
    evidence: str = ""
    object_type: str = ""
    object_id: str = ""

class UsageEventCreate(BaseModel):
    organization_id: int
    customer_id: int | None = None
    agent_id: int | None = None
    task_id: int | None = None
    runtime_run_id: str = ""
    event_type: str
    quantity: float = 1
    unit: str = "event"
    unit_cost: float = 0
    metadata: dict = {}

class InvoiceCreate(BaseModel):
    customer_id: int
    period_start: str
    period_end: str
    currency: str = "USD"

class PortalRegister(BaseModel):
    customer_id: int
    email: EmailStr
    password: str
    display_name: str = ""

class PortalLogin(BaseModel):
    # Cùng lý do như LoginRequest: seed tạo client@acme.local, và đăng nhập
    # không được phép từ chối một identity đã lưu. Xem app/schemas/auth.py.
    email: StoredEmail
    password: str

class PortalToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    customer_id: int

class CustomerProjectAssign(BaseModel):
    customer_id: int
    project_id: int
    visibility: str = "customer"

class NinaCommandRequest(BaseModel):
    organization_id: int
    message: str

class RuntimeStreamRequest(BaseModel):
    runtime_agent_id: str
    input: str
    metadata: dict = {}