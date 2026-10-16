"""R1 — ma trận cô lập 2 tổ chức × 2 công ty.

Mỗi công ty được gieo dữ liệu có "dấu" riêng (MK-<org>-<co>) qua API thật: chức danh, ma trận phân quyền,
quy trình + SOP, KPI, luật cứng, hợp đồng dữ liệu, SLA, tuân thủ, một agent, một thẻ hộp việc, một tài liệu.
Sau đó quét MỌI route GET của /api/team, /api/inbox, /api/learning: đọc công ty B không được thấy dấu của
công ty A (cùng tổ chức) và tổ chức khác thì 403/404/422. Mọi route có id trong path, gọi bằng người của tổ
chức kia → 4xx, không bao giờ 2xx hay 500. Tool MCP company_* của agent công ty A không trả dấu công ty B.
ORM thật trên SQLite, gateway giả."""
import re

import pytest

from app.main import app
from app.models import Agent, Company, Department, Member, Organization, User, UserOrganizationAccess
from app.core.security import create_access_token, hash_password
from app.services import company_mcp, inbox
from tests.test_m2b_company_foundation import E  # noqa: F401  (fixture)
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def _seed_company(X, tok, org_id, co, dept, mark):
    c = X.c
    h = tok
    out = {"mark": mark, "co": co.id}

    def ok(r, what):
        assert r.status_code == 200, (what, r.status_code, r.text[:300])
        return r.json()

    out["position"] = ok(c.post("/api/team/positions", json={"company_id": co.id, "title": f"POS {mark}",
                                                              "department_id": dept.id}, headers=h), "pos")["id"]
    ok(c.post("/api/team/authority/seed-defaults", json={"company_id": co.id}, headers=h), "auth")
    rules = ok(c.get(f"/api/team/authority?company_id={co.id}", headers=h), "auth-list")["rules"]
    out["arule"] = rules[0]["id"]
    ok(c.post("/api/team/processes/seed", json={"company_id": co.id, "template": "shop"}, headers=h), "proc-seed")
    p = ok(c.post("/api/team/processes", json={"company_id": co.id, "name": f"PROC {mark}",
                                               "steps": [{"name": f"STEP {mark}"}]}, headers=h), "proc")
    out["process"] = p.get("id")
    k = ok(c.post("/api/team/kpis", json={"company_id": co.id, "name": f"KPI {mark}", "level": "company",
                                          "metric": "manual"}, headers=h), "kpi")
    out["kpi"] = k.get("id")
    rr = ok(c.post("/api/team/rules", json={"company_id": co.id, "name": f"RULE {mark}", "kind": "regex",
                                            "pattern": "zzz", "action": "block", "message": f"RULE {mark}"},
                   headers=h), "rule")
    out["rule"] = rr.get("id") or rr.get("rule", {}).get("id")
    ct = ok(c.post("/api/team/contracts", json={"company_id": co.id, "template": "refund_request",
                                                "name": f"CT {mark}"}, headers=h), "contract")
    out["contract"] = ct.get("id") or ct.get("contract", {}).get("id")
    sl = ok(c.post("/api/team/sla-policies", json={"company_id": co.id, "name": f"SLA {mark}",
                                                   "position_id": out["position"], "first_response_minutes": 10},
                   headers=h), "sla")
    out["sla"] = sl.get("id") or sl.get("policy", {}).get("id")
    ok(c.put("/api/team/company-profile", json={"company_id": co.id, "mission": f"MISSION {mark}"}, headers=h), "prof")
    a = ok(c.post("/api/agents/hire", json={"name": f"AG {mark}", "role": "Nhân viên", "company_id": co.id,
                                            "department_id": dept.id, "personality": "than-thien",
                                            "monthly_budget": 5}, headers=h), "hire")
    out["agent"] = a["agent_id"]
    out["member"] = X.db.get(Agent, a["agent_id"]).member_id
    items = inbox.notify(X.db, organization_id=org_id, recipients=[out["member"]], kind="mention",
                         title=f"INBOX {mark}", company_id=co.id)
    out["item"] = items[0].id if items else None
    d = ok(c.post("/api/learning/docs", json={"title": f"DOC {mark}", "content": f"Noi dung {mark} gom su.",
                                              "scope": "company", "company_id": co.id}, headers=h), "doc")
    out["doc"] = d.get("id") or d.get("doc", {}).get("id")
    return out


@pytest.fixture()
def M(E):
    """org A (E.org) có co A1 (=E.co) + A2; org B có B1 + B2. Mỗi org một owner."""
    X = E
    a2 = Company(organization_id=X.org.id, name="A2 Gốm", status="active"); X.db.add(a2); X.db.commit()
    da2 = Department(company_id=a2.id, name="CSKH A2", access_level="restricted"); X.db.add(da2); X.db.commit()
    orgb = Organization(name="Org B", slug="org-b-r1"); X.db.add(orgb); X.db.commit()
    b1 = Company(organization_id=orgb.id, name="B1", status="active")
    b2 = Company(organization_id=orgb.id, name="B2", status="active")
    X.db.add_all([b1, b2]); X.db.commit()
    db1 = Department(company_id=b1.id, name="D B1", access_level="restricted")
    db2 = Department(company_id=b2.id, name="D B2", access_level="restricted")
    X.db.add_all([db1, db2]); X.db.commit()
    ub = User(email="owner@orgb.test", password_hash=hash_password("Matkhau123")); X.db.add(ub); X.db.commit()
    X.db.add(UserOrganizationAccess(user_id=ub.id, organization_id=orgb.id, role="owner", is_default=True,
                                    status="active")); X.db.commit()
    bossb = Member(organization_id=orgb.id, company_id=b1.id, name="Chủ B", member_type="human", role="CEO")
    X.db.add(bossb); X.db.commit()
    tA = X.tok("owner")
    tB = {"Authorization": "Bearer " + create_access_token(ub.id, orgb.id, "owner")}
    X.seed = {
        "A1": _seed_company(X, tA, X.org.id, X.co, X.sales, "MK-A-1"),
        "A2": _seed_company(X, tA, X.org.id, a2, da2, "MK-A-2"),
        "B1": _seed_company(X, tB, orgb.id, b1, db1, "MK-B-1"),
        "B2": _seed_company(X, tB, orgb.id, b2, db2, "MK-B-2"),
    }
    X.tA, X.tB, X.orgb, X.a2, X.b1, X.b2 = tA, tB, orgb, a2, b1, b2
    return X


PREFIXES = ("/api/team", "/api/inbox", "/api/learning", "/api/agents", "/api/approvals", "/api/a2a/external",
            "/api/a2a/expose", "/api/leases")
# routes whose read is deliberately not company-scoped (org-level / me / static)
ORG_LEVEL = {"/api/team/me", "/api/team/templates", "/api/learning/embeddings", "/api/agents/model-tiers",
             "/api/agents/runtime/health", "/api/agents/hire/options", "/api/learning/skills/governance",
             "/api/team/invitations/lookup", "/api/team/compliance/holidays", "/api/agents/model-tiers/report"}


def _routes():
    for r in app.routes:
        p = getattr(r, "path", "")
        if p.startswith(PREFIXES):
            for m in sorted(getattr(r, "methods", []) or []):
                if m in ("GET", "POST", "PATCH", "PUT", "DELETE"):
                    yield m, p


def _marks(text, prefix):
    return sorted(set(re.findall(prefix + r"-\d", text)))


def test_list_reads_never_show_another_companys_data(M):
    X = M
    leaks = []
    for m, p in _routes():
        if m != "GET" or "{" in p or p in ORG_LEVEL:
            continue
        # same org, other company: reading A2 must not show A1's marks (and vice versa)
        for mine, other in (("A1", "A2"), ("A2", "A1")):
            r = X.c.get(p, params={"company_id": X.seed[mine]["co"]}, headers=X.tA)
            if r.status_code == 200 and X.seed[other]["mark"] in r.text:
                leaks.append(("same-org", p, mine, "sees", other))
            if r.status_code >= 500:
                leaks.append(("500", p, r.text[:120]))
        # other org asking for org A's company → never data
        r = X.c.get(p, params={"company_id": X.seed["A1"]["co"]}, headers=X.tB)
        if r.status_code == 200 and "MK-A-" in r.text:
            leaks.append(("cross-org", p, _marks(r.text, "MK-A")))
        # org B without company param → never org A's marks
        r = X.c.get(p, headers=X.tB)
        if r.status_code == 200 and "MK-A-" in r.text:
            leaks.append(("cross-org-noparam", p, _marks(r.text, "MK-A")))
    assert not leaks, "\n".join(map(str, leaks))


PARAM = {"position_id": "position", "process_id": "process", "kpi_id": "kpi", "contract_id": "contract",
         "policy_id": "sla", "agent_id": "agent", "member_id": "member", "item_id": "item", "doc_id": "doc"}


def _fill(p, s):
    def sub(mo):
        name = mo.group(1)
        if name == "rule_id":
            return str(s["arule"] if "/authority/" in p else s["rule"])
        key = PARAM.get(name)
        return str(s[key]) if key and s.get(key) else "999999"
    return re.sub(r"\{(\w+)\}", sub, p)


def test_id_routes_refuse_the_other_org(M):
    X = M
    bad = []
    for m, p in _routes():
        if "{" not in p:
            continue
        names = re.findall(r"\{(\w+)\}", p)
        if not all(n in PARAM or n == "rule_id" for n in names):
            continue
        url = _fill(p, X.seed["A1"])
        r = X.c.request(m, url, json={}, headers=X.tB)
        if r.status_code < 400 or r.status_code >= 500 or (r.status_code == 200 and "MK-A-" in r.text):
            bad.append((m, url, r.status_code, r.text[:160]))
    assert not bad, "\n".join(map(str, bad))


def test_mcp_company_tools_stay_inside_the_agents_company(M):
    X = M
    ag = X.db.get(Agent, X.seed["A1"]["agent"]); mem = X.db.get(Member, ag.member_id)
    ctx = company_mcp.ToolContext(db=X.db, member=mem, agent=ag, scopes=["*"])
    leaks = []
    for name, tool in company_mcp.TOOLS.items():
        for args in ({}, {"query": "MK gom su Noi dung"}):
            try:
                out = tool.handler(ctx, dict(args))
            except Exception:
                continue
            txt = str(out)
            for other in ("MK-A-2", "MK-B-1", "MK-B-2"):
                if other in txt:
                    leaks.append((name, other))
    assert not leaks, leaks


# ------------------------------------------------------------------ vai trò theo công ty + nhiều ghế

def _user(X, email, org_role="member"):
    u = User(email=email, password_hash=hash_password("Matkhau123"), display_name=email.split("@")[0])
    X.db.add(u); X.db.commit()
    X.db.add(UserOrganizationAccess(user_id=u.id, organization_id=X.org.id, role=org_role, is_default=True,
                                    status="active")); X.db.commit()
    return u, {"Authorization": "Bearer " + create_access_token(u.id, X.org.id, org_role)}


def test_company_manager_is_confined_to_their_company(M):
    X = M
    u, t = _user(X, "mgr.a2@r1.test", "member")
    r = X.c.put("/api/team/company-access", json={"company_id": X.a2.id, "role": "manager", "user_id": u.id},
                headers=X.tA)
    assert r.status_code == 200, r.text
    a1, a2 = X.seed["A1"]["co"], X.seed["A2"]["co"]
    # write in own company OK (org role is only member), other company 403
    assert X.c.post("/api/team/positions", json={"company_id": a2, "title": "Mới A2"}, headers=t).status_code == 200
    assert X.c.post("/api/team/positions", json={"company_id": a1, "title": "Lạc A1"}, headers=t).status_code == 403
    assert X.c.get(f"/api/team/positions?company_id={a1}", headers=t).status_code == 403
    # no company_id → their single company, not 422
    got = X.c.get("/api/team/positions", headers=t)
    assert got.status_code == 200 and "POS MK-A-2" in got.text and "MK-A-1" not in got.text
    # by-id write on the other company's objects → 403
    assert X.c.patch(f"/api/team/positions/{X.seed['A1']['position']}", json={"title": "x"}, headers=t).status_code == 403
    assert X.c.patch(f"/api/team/kpis/{X.seed['A1']['kpi']}", json={"name": "x"}, headers=t).status_code == 403
    assert X.c.patch(f"/api/team/kpis/{X.seed['A2']['kpi']}", json={"name": "KPI MK-A-2 sửa"}, headers=t).status_code == 200
    # org-wide lists are filtered to their company
    for path in ("/api/learning/docs", "/api/team/rules/compiled", "/api/inbox"):
        r = X.c.get(path, headers=t)
        assert r.status_code in (200, 403), (path, r.status_code)
        assert "MK-A-1" not in r.text, path
    mc = X.c.get("/api/team/my-companies", headers=t).json()
    assert mc["restricted"] and [c["id"] for c in mc["items"]] == [a2] and mc["items"][0]["role"] == "manager"
    # cannot grant themselves more: only org admin/owner or the company owner manages company roles
    assert X.c.put("/api/team/company-access", json={"company_id": a2, "role": "owner", "user_id": u.id},
                   headers=t).status_code == 403
    # org-level admin pages stay closed
    assert X.c.post("/api/team/authority/seed-defaults", json={"company_id": a2}, headers=t).status_code == 403


def test_company_viewer_reads_but_cannot_write(M):
    X = M
    u, t = _user(X, "view.a1@r1.test", "manager")      # org manager, but confined as viewer of A1
    X.c.put("/api/team/company-access", json={"company_id": X.co.id, "role": "viewer", "user_id": u.id}, headers=X.tA)
    a1 = X.co.id
    assert X.c.get(f"/api/team/kpis?company_id={a1}", headers=t).status_code == 200
    assert X.c.post("/api/team/kpis", json={"company_id": a1, "name": "k", "level": "company", "metric": "manual"},
                    headers=t).status_code == 403
    assert X.c.get(f"/api/team/kpis?company_id={X.a2.id}", headers=t).status_code == 403


def test_company_owner_is_the_final_approver_and_company_approver_kind(M):
    X = M
    from app.models.company_foundation import AuthorityRule
    from app.services import authority, company_roles
    from app.core.authz import Principal as P
    u, t = _user(X, "boss.a2@r1.test", "member")
    seat = Member(organization_id=X.org.id, company_id=X.a2.id, name="Giám đốc A2", member_type="human", role="GĐ")
    appr = Member(organization_id=X.org.id, company_id=X.a2.id, name="Kế toán duyệt A2", member_type="human", role="KT")
    X.db.add_all([seat, appr]); X.db.commit()
    owner_p = P(user_id=None, organization_id=X.org.id, role="owner", auth_type="jwt", scopes=[])
    company_roles.set_access(X.db, X.org.id, owner_p, company_id=X.a2.id, role="owner", user_id=u.id)
    company_roles.link_seat(X.db, X.org.id, owner_p, user_id=u.id, member_id=seat.id)
    u2, _ = _user(X, "duyet.a2@r1.test", "member")
    company_roles.set_access(X.db, X.org.id, owner_p, company_id=X.a2.id, role="approver", user_id=u2.id)
    company_roles.link_seat(X.db, X.org.id, owner_p, user_id=u2.id, member_id=appr.id)
    agent_a2 = X.db.get(Member, X.seed["A2"]["member"])
    assert authority.owner_member(X.db, X.org.id, X.a2.id) == seat.id          # not the org owner
    r = AuthorityRule(organization_id=X.org.id, company_id=X.a2.id, action_type="spend", approver_kind="company_approver",
                      enabled=True)
    X.db.add(r); X.db.commit()
    who, _ = authority.resolve_approver(X.db, r, agent_a2)
    assert who == appr.id
    r.approver_kind = "owner"; X.db.commit()
    assert authority.resolve_approver(X.db, r, agent_a2)[0] == seat.id
    # the company owner manages roles of THEIR company only
    assert X.c.put("/api/team/company-access", json={"company_id": X.a2.id, "role": "viewer", "email": "view2@r1.test"},
                   headers=t).status_code == 404     # unknown user, but authorised to try
    assert X.c.put("/api/team/company-access", json={"company_id": X.co.id, "role": "viewer", "user_id": u2.id},
                   headers=t).status_code == 403


def test_one_user_many_seats_inbox_and_approvals(M):
    X = M
    from app.models import Approval
    from app.services import company_roles
    from app.core.authz import Principal as P
    u, t = _user(X, "multi@r1.test", "manager")
    s1 = Member(organization_id=X.org.id, company_id=X.co.id, name="Lan @A1", member_type="human", role="QL")
    s2 = Member(organization_id=X.org.id, company_id=X.a2.id, name="Lan @A2", member_type="human", role="QL")
    s3 = Member(organization_id=X.org.id, company_id=X.a2.id, name="Lan @A2 thứ hai", member_type="human", role="QL")
    X.db.add_all([s1, s2, s3]); X.db.commit()
    owner_p = P(user_id=None, organization_id=X.org.id, role="owner", auth_type="jwt", scopes=[])
    company_roles.link_seat(X.db, X.org.id, owner_p, user_id=u.id, member_id=s1.id)
    company_roles.link_seat(X.db, X.org.id, owner_p, user_id=u.id, member_id=s2.id)
    with pytest.raises(Exception):   # one seat per company
        company_roles.link_seat(X.db, X.org.id, owner_p, user_id=u.id, member_id=s3.id)
    inbox.notify(X.db, organization_id=X.org.id, recipients=[s1.id], kind="mention", title="Việc ghế A1", company_id=X.co.id)
    inbox.notify(X.db, organization_id=X.org.id, recipients=[s2.id], kind="mention", title="Việc ghế A2", company_id=X.a2.id)
    f = X.c.get("/api/inbox/items", headers=t).json()
    titles = {c["title"] for g in f["groups"] for c in g["items"]}
    assert {"Việc ghế A1", "Việc ghế A2"} <= titles
    a = Approval(organization_id=X.org.id, company_id=X.a2.id, approver_member_id=s2.id, action="Chi $20",
                 policy_key="task_stage:1", status="pending")
    X.db.add(a); X.db.commit()
    r = X.c.post(f"/api/approvals/{a.id}/resolve", json={"status": "approved"}, headers=t)
    assert r.status_code == 200, r.text
    me = X.c.get("/api/team/me", headers=t).json()
    assert me["member_id"] in (s1.id, s2.id)
