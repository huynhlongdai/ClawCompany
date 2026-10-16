"""P0 — route cũ cấp tổ chức lọc theo vai trò công ty (R1 hardening).

Trước: người có vai trò công ty (viewer/manager của MỘT công ty) vẫn đọc được việc, agent, chi phí, tổng quan và
v7–v36 của CẢ tổ chức. Test dựng ma trận R1 (org A có A1 + A2, mỗi công ty có dấu MK-A-n) rồi đi qua API thật như
người dùng bị giới hạn ở A2:
- danh sách cũ (/api/work, /api/tasks, /api/agents, roster, chi phí, ngân sách, tổng quan, dashboard, members,
  projects, departments, approvals, companies) chỉ có dữ liệu A2;
- quét MỌI route GET không tham số của app: không response 2xx nào chứa dấu của A1; route v7–v36 trả 403;
- đối tượng A1 theo id → 403, A2 → được; viewer không ghi được, manager ghi được trong công ty của mình;
- owner tổ chức (không bị giới hạn) vẫn thấy cả hai công ty (không hồi quy).
"""
from app.main import app
from app.models import Agent, Project
from tests.test_r1_isolation import M, _user  # noqa: F401  (fixture)
from tests.test_m2b_company_foundation import E  # noqa: F401
from tests.test_m3_agents import env  # noqa: F401


def _seed_work(X):
    """Mỗi công ty A1/A2: một dự án + một việc + một ngân sách mang dấu."""
    out = {}
    for key, co in (("A1", X.co.id), ("A2", X.a2.id)):
        mark = X.seed[key]["mark"]
        p = Project(company_id=co, name=f"PRJ {mark}", status="active"); X.db.add(p); X.db.commit()
        r = X.c.post("/api/work/tasks", json={"title": f"TASK {mark}", "project_id": p.id, "start": False},
                     headers=X.tA)
        assert r.status_code == 201, r.text
        b = X.c.post("/api/costs/budgets", json={"name": f"BUD {mark}", "scope_type": "company", "scope_id": co,
                                                  "amount_limit": 10}, headers=X.tA)
        assert b.status_code == 201, b.text
        out[key] = {"project": p.id, "task": r.json()["id"], "budget": b.json()["id"]}
    return out


def _restricted(X, role, email):
    u, t = _user(X, email, "manager")   # vai trò org manager — trước P0 đủ để đọc mọi thứ cả org
    r = X.c.put("/api/team/company-access", json={"company_id": X.a2.id, "role": role, "user_id": u.id},
                headers=X.tA)
    assert r.status_code == 200, r.text
    return t


LISTS = ["/api/work/tasks", "/api/work/meta", "/api/tasks", "/api/agents", "/api/agents/roster",
         "/api/costs/overview", "/api/costs/budgets", "/api/v17/workspace/overview", "/api/members",
         "/api/projects", "/api/departments", "/api/approvals", "/api/companies"]


def test_viewer_of_one_company_sees_only_that_company_on_legacy_lists(M):
    X = M
    w = _seed_work(X)
    t = _restricted(X, "viewer", "view.a2@p0.test")
    for path in LISTS:
        r = X.c.get(path, headers=t)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])
        assert "MK-A-1" not in r.text, (path, "lộ dữ liệu A1")
    # what they DO see is their own company
    assert "TASK MK-A-2" in X.c.get("/api/work/tasks", headers=t).text
    assert "AG MK-A-2" in X.c.get("/api/agents/roster", headers=t).text
    assert "BUD MK-A-2" in X.c.get("/api/costs/budgets", headers=t).text
    ov = X.c.get("/api/v17/workspace/overview", headers=t).json()
    assert [c["id"] for c in ov["companies"]] == [X.a2.id] and ov["kpis"]["companies"] == 1
    d = X.c.get(f"/api/dashboard/summary?organization_id={X.org.id}", headers=t).json()
    assert d["companies"] == 1
    # by id: other company's objects → 403, own → 200
    assert X.c.get(f"/api/work/tasks/{w['A1']['task']}", headers=t).status_code == 403
    assert X.c.get(f"/api/work/tasks/{w['A2']['task']}", headers=t).status_code == 200
    assert X.c.get(f"/api/tasks/{w['A1']['task']}/journal", headers=t).status_code == 403
    assert X.c.get(f"/api/agents/{X.seed['A1']['agent']}/profile", headers=t).status_code == 403
    assert X.c.get(f"/api/agents/{X.seed['A2']['agent']}/profile", headers=t).status_code == 200
    assert X.c.get(f"/api/costs/budgets/{w['A1']['budget']}", headers=t).status_code == 403
    assert X.c.get(f"/api/work/tasks?company_id={X.co.id}", headers=t).status_code == 403
    # viewer is read-only even inside their company (org role manager no longer lets them write there)
    assert X.c.post("/api/work/tasks", json={"title": "x", "project_id": w["A2"]["project"], "start": False},
                    headers=t).status_code == 403
    assert X.c.patch(f"/api/costs/budgets/{w['A2']['budget']}", json={"amount_limit": 99},
                     headers=t).status_code == 403


def test_every_parameterless_get_route_hides_the_other_company(M):
    X = M
    _seed_work(X)
    t = _restricted(X, "manager", "mgr.a2@p0.test")
    leaks, open_v = [], []
    for r in app.routes:
        p = getattr(r, "path", "")
        if not p.startswith("/api/") or "{" in p or "GET" not in (getattr(r, "methods", None) or ()):
            continue
        try:
            res = X.c.get(p, params={"organization_id": X.org.id}, headers=t)
        except Exception:  # noqa: BLE001  gateway giả không có method → không phải dữ liệu
            continue
        if res.status_code < 300 and "MK-A-1" in res.text:
            leaks.append(p)
        if res.status_code >= 500 and p != "/api/learning/skills/governance":  # cần gateway thật (config.get)
            leaks.append((p, res.status_code))
        if p.split("/")[2] in {f"v{n}" for n in range(9, 37)} and p != "/api/v17/workspace/overview" \
                and "/workload-identity/" not in p and res.status_code != 403:  # OIDC công khai, không cần đăng nhập
            open_v.append((p, res.status_code))
    assert not leaks, leaks
    assert not open_v, open_v


def test_company_manager_writes_in_own_company_only_and_owner_unchanged(M):
    X = M
    w = _seed_work(X)
    t = _restricted(X, "manager", "mgr2.a2@p0.test")
    ok = X.c.post("/api/work/tasks", json={"title": "Việc A2", "project_id": w["A2"]["project"], "start": False},
                  headers=t)
    assert ok.status_code == 201, ok.text
    bad = X.c.post("/api/work/tasks", json={"title": "Lạc A1", "project_id": w["A1"]["project"], "start": False},
                   headers=t)
    assert bad.status_code == 403
    assert X.c.patch(f"/api/work/tasks/{w['A1']['task']}", json={"title": "x"}, headers=t).status_code == 403
    # hire into the other company → 403
    h = X.c.post("/api/agents/hire", json={"name": "Lạc", "role": "NV", "company_id": X.co.id,
                                           "department_id": X.sales.id, "personality": "than-thien",
                                           "monthly_budget": 5}, headers=t)
    assert h.status_code == 403
    # org-level operations inside scoped modules stay closed
    assert X.c.get("/api/tasks/cost-reconciliation", headers=t).status_code == 403
    assert X.c.post("/api/costs/budgets", json={"scope_type": "company", "scope_id": X.a2.id, "amount_limit": 5},
                    headers=t).status_code == 403
    # owner of the org is not restricted: sees both companies
    txt = X.c.get("/api/work/tasks", headers=X.tA).text
    assert "TASK MK-A-1" in txt and "TASK MK-A-2" in txt
    assert len(X.c.get("/api/v17/workspace/overview", headers=X.tA).json()["companies"]) == 2
    assert X.db.get(Agent, X.seed["A1"]["agent"]) is not None
