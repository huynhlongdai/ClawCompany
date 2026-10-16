"""P0 (R1 hardening) — cổng phạm vi công ty cho các route CŨ cấp tổ chức.

Trước bản này người dùng bị giới hạn công ty (có dòng ``company_access``) chỉ bị lọc ở ``/api/team``, ``/api/inbox``,
``/api/learning``, ``/api/leases``; còn ``/api/work``, ``/api/tasks``, ``/api/agents``, chi phí, tổng quan và
v7–v36 vẫn trả dữ liệu của CẢ tổ chức (docs/r-rental-and-multi-company.md "Giới hạn còn lại").

Luật (chỉ áp cho người bị giới hạn; owner/admin org, người chưa có vai trò công ty, API key của agent, beat/worker
không đổi gì):

1. **Mặc định đóng.** Route thuộc module không nằm trong ``AWARE`` (đã tự lọc theo công ty) hay ``SCOPED`` (lọc ở
   bản này) → 403 ``org_level_route``. Đó là v7–v36, a2a, routines, strategy, shared-memory, knowledge, jobs,
   company-tools, organizations, realtime… — dữ liệu cấp tổ chức chưa có cột/luật công ty để lọc.
   Module mới thêm vào mà quên khai báo cũng đóng (không lộ im lặng).
2. **Route cấp tổ chức trong module đã lọc** (``ORG_ONLY``): đối soát chi phí cả org, hàng đợi wakeup, dây gateway,
   cấp phát tất cả agent… → 403.
3. **Đối tượng theo id** (``task_id``, ``agent_id``, ``member_id``, ``project_id``, ``company_id``, ``department_id``,
   ``approval_id``, ``budget_id``, …) và tham số ``?company_id=`` → tra công ty của đối tượng rồi
   ``company_scope.check``: GET cần ≥ viewer, ghi cần ≥ manager của ĐÚNG công ty đó.
4. **Danh sách** của module đã lọc đọc ``company_scope.allowed_company_ids()`` ở service (work_board, cost_board,
   agent_hr.roster, workspace_cockpit, các list ORM ở api/*) → chỉ các công ty của người đó.
"""
from __future__ import annotations

from fastapi import HTTPException

from app.core import company_scope

# module đã tự kiểm theo công ty từ R1/M2/M3 (require_company_role + company_scope.check ở service)
AWARE = {
    "app.api.team", "app.api.company_ops", "app.api.docs", "app.api.leases", "app.api.agent_native",
    "app.api.inbox", "app.api.learning", "app.api.auth", "app.api.health",
    "app.api.business",   # P1 (M3g–M3j): require_company_role + company_scope.check ở service
}
# module cũ được lọc ở bản này
SCOPED = {
    "app.api.work", "app.api.tasks", "app.api.agents", "app.api.companies", "app.api.members", "app.api.projects",
    "app.api.departments", "app.api.approvals", "app.api.dashboard",
}
# endpoint lẻ trong module cấp tổ chức được mở vì đã lọc (vỏ app gọi ngay khi đăng nhập)
SCOPED_ENDPOINTS = {
    ("app.api.v17", "overview"),            # /v17/workspace/overview — vỏ app: tên tổ chức + danh sách công ty
    ("app.api.extended", "list_inbox"),     # /inbox cũ — đã scope_filter từ R1
    ("app.api.extended", "mark_inbox_read"),
    # /api/costs (costs_router nằm trong module inbox): tổng quan + ngân sách theo công ty
    ("app.api.inbox", "costs_overview"), ("app.api.inbox", "budgets"), ("app.api.inbox", "budget_detail"),
    ("app.api.inbox", "patch_budget"), ("app.api.inbox", "override_budget"), ("app.api.inbox", "archive_budget"),
}
# endpoint cấp tổ chức trong module đã lọc → đóng với người bị giới hạn
ORG_ONLY = {
    ("app.api.tasks", "cost_reconciliation"), ("app.api.tasks", "list_wakeups"), ("app.api.tasks", "drain_wakeups"),
    ("app.api.agents", "wire_gateway"), ("app.api.agents", "gateway_isolation"), ("app.api.agents", "gateway_isolation_apply"), ("app.api.agents", "provision_all"), ("app.api.agents", "model_tier_report"),
    ("app.api.agents", "runtime_health"), ("app.api.companies", "create_company"),
    ("app.api.inbox", "create_budget"),
}

READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def _company_of(db, name: str, value) -> tuple[bool, int | None]:
    """(tìm thấy, company_id) của đối tượng theo tên tham số path. Không nhận ra tên → (False, None)."""
    from app.models import Agent, Approval, Company, Department, Member, Project, Task
    try:
        oid = int(value)
    except (TypeError, ValueError):
        return False, None
    if name in ("task_id", "blocked_by_task_id"):
        t = db.get(Task, oid)
        if t is None:
            return False, None
        p = db.get(Project, t.project_id) if t.project_id else None
        return True, (p.company_id if p else None)
    if name == "agent_id":
        a = db.get(Agent, oid)
        m = db.get(Member, a.member_id) if a and a.member_id else None
        return (a is not None), (m.company_id if m else None)
    if name == "member_id":
        m = db.get(Member, oid)
        return (m is not None), (m.company_id if m else None)
    if name == "project_id":
        p = db.get(Project, oid)
        return (p is not None), (p.company_id if p else None)
    if name == "company_id":
        c = db.get(Company, oid)
        return (c is not None), (c.id if c else None)
    if name == "department_id":
        d = db.get(Department, oid)
        return (d is not None), (d.company_id if d else None)
    if name == "approval_id":
        a = db.get(Approval, oid)
        return (a is not None), (a.company_id if a else None)
    if name == "budget_id":
        from app.models.v9 import BudgetEnvelope
        b = db.get(BudgetEnvelope, oid)
        return (b is not None), (b.company_id if b else None)
    return False, None


def enforce(request, principal, db) -> None:
    """Gọi từ ``get_principal`` cho người dùng JWT. Không làm gì nếu người gọi không bị giới hạn công ty."""
    if not company_scope.restricted(principal):
        return
    endpoint = request.scope.get("endpoint")
    if endpoint is None:
        return
    mod, fn = getattr(endpoint, "__module__", ""), getattr(endpoint, "__name__", "")
    if not mod.startswith("app.api."):
        return
    if (mod, fn) in ORG_ONLY:
        raise HTTPException(403, {"error": "org_level_route",
                                  "message": "Vai trò của anh chỉ ở cấp công ty; mục này là dữ liệu cả tổ chức."})
    if mod in AWARE and (mod, fn) not in SCOPED_ENDPOINTS:
        return
    if mod not in SCOPED and (mod, fn) not in SCOPED_ENDPOINTS:
        raise HTTPException(403, {"error": "org_level_route",
                                  "message": "Vai trò của anh chỉ ở cấp công ty; trang này chưa lọc theo công ty "
                                             "nên đang đóng với anh."})
    need = "member" if request.method in READ_METHODS else "manager"
    company_scope.remember(principal, need)
    for name, value in (request.path_params or {}).items():
        found, cid = _company_of(db, name, value)
        if found:
            company_scope.check(cid, min_role=need, principal=principal)
    qc = request.query_params.get("company_id")
    if qc:
        try:
            company_scope.check(int(qc), min_role=need, principal=principal)
        except ValueError:
            pass
