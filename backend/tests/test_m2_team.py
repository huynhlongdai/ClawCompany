"""M2 — Đội ngũ: quyền đọc từ DB, chặn leo quyền, lời mời, sơ đồ theo quản lý,
trưởng phòng, 3 mẫu công ty, nhập CSV. ORM thật (SQLite) + HTTP thật; runtime giả
chỉ ghi create_agent (có thể ép trả ``missing`` như gateway từ chối)."""
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
import app.models  # noqa: F401
from app.db.session import get_db
from app.main import app
from app.models import (Agent, AgentProvisioningJob, Company, Department, Invitation, Member, Organization,
                        User, UserOrganizationAccess)
from app.services import team as svc


class FakeRuntime:
    def __init__(self):
        self.created = []
        self.refuse = set()

    async def create_agent(self, runtime_agent_id, config):
        self.created.append(runtime_agent_id)
        if any(runtime_agent_id.endswith(x) for x in self.refuse):
            return {"id": runtime_agent_id, "status": "missing", "bound": False, "hint": "bật OPENCLAW_REQUEST_ADMIN_SCOPE"}
        return {"id": runtime_agent_id, "status": "created", "bound": True}


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Maker = sessionmaker(bind=engine, autoflush=False)
    db = Maker()

    def override():
        s = Maker()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    fake = FakeRuntime()
    monkeypatch.setattr("app.services.provisioning.get_runtime", lambda: fake)
    org = Organization(name="Nova M2", slug="nova-m2"); other = Organization(name="Khác", slug="khac-m2")
    db.add_all([org, other]); db.commit()
    co = Company(organization_id=org.id, name="Nova", status="active"); db.add(co); db.commit()
    co2 = Company(organization_id=org.id, name="Nova 2", status="active"); db.add(co2); db.commit()
    users = {}
    for role in ("owner", "admin", "manager", "member"):
        u = User(email=f"{role}@nova.test", password_hash=hash_password("Matkhau123"), display_name=role.title())
        db.add(u); db.commit()
        db.add(UserOrganizationAccess(user_id=u.id, organization_id=org.id, role=role, is_default=True, status="active"))
        db.commit(); users[role] = u
    su = User(email="root@nova.test", password_hash=hash_password("Matkhau123"), is_superuser=True); db.add(su); db.commit()
    users["root"] = su

    def tok(name, org_id=None, role=None):
        u = users[name]
        return {"Authorization": "Bearer " + create_access_token(u.id, org_id or org.id, role or ("owner" if name == "root" else name))}

    client = TestClient(app)
    yield type("E", (), dict(db=db, org=org, other=other, co=co, co2=co2, users=users, tok=staticmethod(tok),
                             c=client, fake=fake, Maker=Maker))
    app.dependency_overrides.pop(get_db, None)


def _acc(env, name):
    env.db.expire_all()
    return env.db.query(UserOrganizationAccess).filter_by(user_id=env.users[name].id, organization_id=env.org.id).one()


# ------------------------------------------------------------------ quyền sống từ DB

def test_role_is_read_from_db_not_jwt(env):
    h = env.tok("member")
    assert env.c.post("/api/team/invitations", json={"email": "a@x.vn"}, headers=h).status_code == 403
    acc = _acc(env, "member"); acc.role = "manager"; env.db.commit()
    r = env.c.post("/api/team/invitations", json={"email": "a@x.vn"}, headers=h)   # cùng token cũ
    assert r.status_code == 200, r.text
    acc = _acc(env, "member"); acc.status = "revoked"; env.db.commit()
    r = env.c.get("/api/team/me", headers=h)
    assert r.status_code == 401 and "thu hồi" in r.json()["detail"]


def test_jwt_role_kept_when_no_access_row(env):
    # token phát trực tiếp (test cũ, superuser) không có dòng access → giữ role JWT
    r = env.c.get("/api/team/me", headers=env.tok("root"))
    assert r.status_code == 200 and r.json()["role"] == "owner"
    assert r.json()["capabilities"]["create_company"] is True


def test_me_capabilities_per_role(env):
    caps = {n: env.c.get("/api/team/me", headers=env.tok(n)).json()["capabilities"] for n in ("owner", "manager", "member")}
    assert caps["owner"]["manage_roles"] and caps["owner"]["import_csv"]
    assert caps["manager"]["invite"] and not caps["manager"]["manage_roles"] and not caps["manager"]["create_company"]
    assert not caps["member"]["invite"] and not caps["member"]["edit_org_chart"] and caps["member"]["view_team"]


def test_login_skips_revoked_access(env):
    acc = _acc(env, "member"); acc.status = "revoked"; env.db.commit()
    r = env.c.post("/api/auth/login", json={"email": "member@nova.test", "password": "Matkhau123"})
    assert r.status_code == 200 and r.json()["organization_id"] is None


# ------------------------------------------------------------------ chặn leo quyền

def test_admin_cannot_grant_owner_anywhere(env):
    h = env.tok("admin"); mid = env.users["member"].id
    r = env.c.post("/api/auth/organization-access", json={"user_id": mid, "organization_id": env.org.id, "role": "owner"}, headers=h)
    assert r.status_code == 403
    assert env.c.patch(f"/api/team/access/{mid}", json={"role": "owner"}, headers=h).status_code == 403
    assert _acc(env, "member").role == "member"
    assert env.c.patch(f"/api/team/access/{mid}", json={"role": "admin"}, headers=h).status_code == 200


def test_cannot_touch_self_or_higher(env):
    h = env.tok("admin")
    assert env.c.patch(f"/api/team/access/{env.users['admin'].id}", json={"role": "member"}, headers=h).status_code == 403
    assert env.c.patch(f"/api/team/access/{env.users['owner'].id}", json={"role": "member"}, headers=h).status_code == 403
    assert env.c.delete(f"/api/team/access/{env.users['owner'].id}", headers=h).status_code == 403
    assert env.c.patch(f"/api/team/access/{env.users['member'].id}", json={"role": "manager"}, headers=env.tok("manager")).status_code == 403
    assert _acc(env, "owner").role == "owner"


def test_last_owner_is_protected(env):
    root = env.tok("root")
    r = env.c.patch(f"/api/team/access/{env.users['owner'].id}", json={"role": "admin"}, headers=root)
    assert r.status_code == 409 and "Chủ sở hữu" in r.json()["detail"]
    assert env.c.delete(f"/api/team/access/{env.users['owner'].id}", headers=root).status_code == 409
    # có owner thứ hai thì hạ được
    assert env.c.patch(f"/api/team/access/{env.users['admin'].id}", json={"role": "owner"}, headers=env.tok("owner")).status_code == 200
    assert env.c.patch(f"/api/team/access/{env.users['owner'].id}", json={"role": "admin"}, headers=root).status_code == 200


def test_revoke_takes_effect_immediately(env):
    hm = env.tok("member")
    assert env.c.get("/api/team/people", headers=hm).status_code == 200
    assert env.c.delete(f"/api/team/access/{env.users['member'].id}", headers=env.tok("admin")).status_code == 200
    assert env.c.get("/api/team/people", headers=hm).status_code == 401


def test_manager_invites_only_lower_roles(env):
    h = env.tok("manager")
    assert env.c.post("/api/team/invitations", json={"email": "x@x.vn", "role": "member"}, headers=h).status_code == 200
    assert env.c.post("/api/team/invitations", json={"email": "y@x.vn", "role": "manager"}, headers=h).status_code == 403
    assert env.c.post("/api/team/invitations", json={"email": "z@x.vn", "role": "owner"}, headers=env.tok("admin")).status_code == 403


# ------------------------------------------------------------------ lời mời

def _dept(env, name="Bán hàng", company=None):
    d = Department(company_id=(company or env.co).id, name=name); env.db.add(d); env.db.commit(); return d


def test_invite_accept_creates_user_member_and_role(env):
    d = _dept(env)
    boss = Member(organization_id=env.org.id, company_id=env.co.id, department_id=d.id, name="Long", member_type="human", status="active")
    env.db.add(boss); env.db.commit()
    r = env.c.post("/api/team/invitations", json={"email": "Lan@Shop.vn", "role": "manager", "job_title": "Trưởng ca",
                                                  "department_id": d.id, "manager_member_id": boss.id}, headers=env.tok("admin"))
    assert r.status_code == 200, r.text
    raw = r.json()["token"]
    assert r.json()["invite_path"] == f"/invite/{raw}" and r.json()["company"] == "Nova"
    inv = env.db.query(Invitation).one()
    assert inv.token_hash != raw and len(inv.token_hash) == 64 and inv.email == "lan@shop.vn"
    look = env.c.get("/api/team/invitations/lookup", params={"token": raw})
    assert look.status_code == 200 and look.json()["department"] == "Bán hàng" and look.json()["account_exists"] is False
    assert env.c.post("/api/team/invitations/accept", json={"token": raw, "password": "ngan"}).status_code == 422
    acc = env.c.post("/api/team/invitations/accept", json={"token": raw, "password": "Matkhau123", "display_name": "Lan"})
    assert acc.status_code == 200, acc.text
    body = acc.json()
    assert body["role"] == "manager" and body["organization_id"] == env.org.id
    env.db.expire_all()
    m = env.db.get(Member, body["member_id"])
    assert (m.member_type, m.department_id, m.manager_id, m.role, m.name) == ("human", d.id, boss.id, "Trưởng ca", "Lan")
    # đăng nhập thấy đúng quyền
    login = env.c.post("/api/auth/login", json={"email": "lan@shop.vn", "password": "Matkhau123"}).json()
    me = env.c.get("/api/team/me", headers={"Authorization": "Bearer " + login["access_token"]}).json()
    assert me["role"] == "manager" and me["capabilities"]["invite"] and not me["capabilities"]["manage_roles"]
    assert me["member_id"] == m.id
    # link dùng 1 lần
    assert env.c.post("/api/team/invitations/accept", json={"token": raw, "password": "Matkhau123"}).status_code == 410


def test_invite_without_manager_reports_to_department_head(env):
    d = _dept(env, "Kho")
    head = Member(organization_id=env.org.id, company_id=env.co.id, department_id=d.id, name="Trưởng kho", member_type="agent", status="active")
    env.db.add(head); env.db.commit(); d.head_member_id = head.id; env.db.commit()
    raw = env.c.post("/api/team/invitations", json={"email": "k@x.vn", "department_id": d.id}, headers=env.tok("admin")).json()["token"]
    body = env.c.post("/api/team/invitations/accept", json={"token": raw, "password": "Matkhau123"}).json()
    env.db.expire_all()
    assert env.db.get(Member, body["member_id"]).manager_id == head.id


def test_invite_expired_revoked_and_wrong_token(env):
    h = env.tok("admin")
    raw = env.c.post("/api/team/invitations", json={"email": "e@x.vn"}, headers=h).json()["token"]
    inv = env.db.query(Invitation).one(); inv.expires_at = datetime.utcnow() - timedelta(minutes=1); env.db.commit()
    assert env.c.get("/api/team/invitations/lookup", params={"token": raw}).status_code == 410
    raw2 = env.c.post("/api/team/invitations", json={"email": "f@x.vn"}, headers=h).json()
    assert env.c.delete(f"/api/team/invitations/{raw2['id']}", headers=h).status_code == 200
    assert env.c.post("/api/team/invitations/accept", json={"token": raw2["token"], "password": "Matkhau123"}).status_code == 410
    assert env.c.get("/api/team/invitations/lookup", params={"token": "inv_khongco"}).status_code == 404


def test_reinvite_revokes_old_link_and_existing_member_rejected(env):
    h = env.tok("admin")
    a = env.c.post("/api/team/invitations", json={"email": "g@x.vn"}, headers=h).json()["token"]
    b = env.c.post("/api/team/invitations", json={"email": "g@x.vn"}, headers=h).json()["token"]
    assert env.c.get("/api/team/invitations/lookup", params={"token": a}).status_code == 410
    assert env.c.get("/api/team/invitations/lookup", params={"token": b}).status_code == 200
    assert env.c.post("/api/team/invitations", json={"email": "member@nova.test"}, headers=h).status_code == 409


def test_existing_account_must_prove_password(env):
    u = User(email="cu@x.vn", password_hash=hash_password("CuMatKhau1")); env.db.add(u); env.db.commit()
    raw = env.c.post("/api/team/invitations", json={"email": "cu@x.vn", "role": "member"}, headers=env.tok("admin")).json()["token"]
    assert env.c.get("/api/team/invitations/lookup", params={"token": raw}).json()["account_exists"] is True
    assert env.c.post("/api/team/invitations/accept", json={"token": raw, "password": "sai-mat-khau"}).status_code == 401
    r = env.c.post("/api/team/invitations/accept", json={"token": raw, "password": "CuMatKhau1"})
    assert r.status_code == 200 and r.json()["user_id"] == u.id


def test_invite_into_foreign_company_rejected(env):
    foreign = Company(organization_id=env.other.id, name="Ngoài"); env.db.add(foreign); env.db.commit()
    r = env.c.post("/api/team/invitations", json={"email": "h@x.vn", "company_id": foreign.id}, headers=env.tok("admin"))
    assert r.status_code == 404


def test_people_lists_users_invites_and_editable_flags(env):
    env.c.post("/api/team/invitations", json={"email": "p@x.vn"}, headers=env.tok("admin"))
    body = env.c.get("/api/team/people", headers=env.tok("admin")).json()
    by = {u["email"]: u for u in body["users"]}
    assert by["owner@nova.test"]["editable"] is False and by["admin@nova.test"]["is_self"]
    assert by["member@nova.test"]["editable"] is True
    assert body["invitations"][0]["email"] == "p@x.vn" and body["invitations"][0]["status"] == "pending"
    assert "owner" not in body["assignable_roles"]
    assert all(not u["editable"] for u in env.c.get("/api/team/people", headers=env.tok("member")).json()["users"])


# ------------------------------------------------------------------ sơ đồ + trưởng phòng

def _m(env, name, dept=None, manager=None, typ="agent", company=None):
    m = Member(organization_id=env.org.id, company_id=(company or env.co).id, department_id=dept.id if dept else None,
               name=name, member_type=typ, status="active", manager_id=manager.id if manager else None)
    env.db.add(m); env.db.commit(); return m


def test_org_chart_tree_follows_manager(env):
    d = _dept(env)
    ceo = _m(env, "CEO", typ="human"); head = _m(env, "Trưởng", d, ceo); a = _m(env, "A", d, head); b = _m(env, "B", d)
    d.head_member_id = head.id; env.db.commit()
    chart = env.c.get("/api/team/org-chart", params={"company_id": env.co.id}, headers=env.tok("member")).json()
    roots = {n["name"]: n for n in chart["tree"]}
    assert set(roots) == {"CEO", "B"}
    t = roots["CEO"]["children"][0]
    assert t["name"] == "Trưởng" and t["is_head"] and [c["name"] for c in t["children"]] == ["A"]
    assert chart["departments"][0]["head_name"] == "Trưởng" and chart["stats"]["members"] == 4


def test_set_head_fills_and_moves_reports(env):
    d = _dept(env)
    old = _m(env, "Cũ", d); new = _m(env, "Mới", d); x = _m(env, "X", d, old); y = _m(env, "Y", d)
    d.head_member_id = old.id; env.db.commit()
    r = env.c.put(f"/api/team/departments/{d.id}/head", json={"member_id": new.id}, headers=env.tok("manager"))
    assert r.status_code == 200 and r.json()["reassigned"] == 3   # X (báo cáo trưởng cũ), Y (trống), Cũ (trống)
    env.db.expire_all()
    assert env.db.get(Department, d.id).head_member_id == new.id
    assert env.db.get(Member, x.id).manager_id == new.id and env.db.get(Member, y.id).manager_id == new.id
    assert env.c.put(f"/api/team/departments/{d.id}/head", json={"member_id": new.id}, headers=env.tok("member")).status_code == 403


def test_head_must_be_same_company(env):
    d = _dept(env); stranger = _m(env, "Lạ", company=env.co2)
    r = env.c.put(f"/api/team/departments/{d.id}/head", json={"member_id": stranger.id}, headers=env.tok("admin"))
    assert r.status_code == 422


def test_manager_cycle_and_cross_company_rejected(env):
    a = _m(env, "A"); b = _m(env, "B", manager=a); c = _m(env, "C", manager=b)
    h = env.tok("manager")
    r = env.c.put(f"/api/team/members/{a.id}/manager", json={"manager_id": c.id}, headers=h)
    assert r.status_code == 422 and "vòng" in r.json()["detail"]
    assert env.c.put(f"/api/team/members/{a.id}/manager", json={"manager_id": a.id}, headers=h).status_code == 422
    z = _m(env, "Z", company=env.co2)
    assert env.c.put(f"/api/team/members/{a.id}/manager", json={"manager_id": z.id}, headers=h).status_code == 422
    assert env.c.put(f"/api/team/members/{c.id}/manager", json={"manager_id": None}, headers=h).status_code == 200


# ------------------------------------------------------------------ mẫu công ty

@pytest.mark.parametrize("key,deps,agents", [("shop", 4, 6), ("agency", 4, 6), ("ketoan", 4, 5)])
def test_template_builds_departments_and_correct_chart(env, key, deps, agents):
    r = env.c.post("/api/team/companies/from-template", json={"template_key": key, "company_name": f"Cty {key}"},
                   headers=env.tok("admin"))
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["departments"], out["agents"], out["agents_bound"], out["job_status"]) == (deps, agents, agents, "ready")
    assert len(env.fake.created) == agents
    assert all(re.fullmatch(r"[a-z0-9-]+", x) for x in env.fake.created) and len(set(env.fake.created)) == agents
    chart = env.c.get("/api/team/org-chart", params={"company_id": out["company_id"]}, headers=env.tok("member")).json()
    assert all(d["head_member_id"] for d in chart["departments"]) and chart["stats"]["without_head"] == 0
    assert all(d["guide"] for d in chart["departments"])
    assert len(chart["tree"]) == 1                      # một gốc: Giám đốc
    director = chart["tree"][0]
    assert director["role"] == "Giám đốc" and director["department"] == "Ban điều hành" and director["is_head"]
    heads = director["children"]
    assert len(heads) == deps - 1 and all(h["is_head"] for h in heads)
    for h in heads:
        for s in h["children"]:
            assert s["department_id"] == h["department_id"] and not s["is_head"] and s["children"] == []
    total = 1 + len(heads) + sum(len(h["children"]) for h in heads)
    assert total == agents


def test_template_twice_gets_unique_runtime_ids(env):
    h = env.tok("owner")
    env.c.post("/api/team/companies/from-template", json={"template_key": "ketoan"}, headers=h)
    env.c.post("/api/team/companies/from-template", json={"template_key": "ketoan"}, headers=h)
    assert len(set(env.fake.created)) == 10


def test_template_requires_admin(env):
    assert env.c.post("/api/team/companies/from-template", json={"template_key": "shop"}, headers=env.tok("manager")).status_code == 403
    assert env.c.post("/api/team/companies/from-template", json={"template_key": "xyz"}, headers=env.tok("admin")).status_code == 422


def test_template_with_refusing_gateway_is_honest(env):
    env.fake.refuse = {"-cskh", "-noi-dung"}
    out = env.c.post("/api/team/companies/from-template", json={"template_key": "shop"}, headers=env.tok("admin")).json()
    assert out["job_status"] == "partial" and out["agents_bound"] == 4
    assert {i["lifecycle"] for i in out["runtime_issues"]} == {"runtime_missing"}
    assert all("OPENCLAW_REQUEST_ADMIN_SCOPE" in i["hint"] for i in out["runtime_issues"])
    env.db.expire_all()
    ag = env.db.query(Agent).filter(Agent.runtime_agent_id.like("%-cskh")).one()
    assert env.db.get(Member, ag.member_id).status == "pending_runtime"
    job = env.db.query(AgentProvisioningJob).filter_by(agent_id=ag.id).one()
    assert job.status == "needs_runtime"


def test_templates_listing(env):
    t = env.c.get("/api/team/templates", headers=env.tok("member")).json()
    assert [x["key"] for x in t] == ["shop", "agency", "ketoan"] and all(x["departments"][0]["name"] == "Ban điều hành" for x in t)


# ------------------------------------------------------------------ CSV

GOOD = """tên,loại,chức danh,phòng ban,quản lý,email,trưởng phòng
Hà,người,Giám đốc,Ban điều hành,,ha@shop.vn,x
Minh,người,Trưởng kho,Kho,Hà,minh@shop.vn,x
Bot đóng gói,agent,Đóng gói,Kho,Minh,,
Tư,human,Thủ kho,Kho,Minh,,
"""


def test_csv_dry_run_writes_nothing(env):
    r = env.c.post("/api/team/import-csv", json={"company_id": env.co.id, "csv_text": GOOD, "dry_run": True}, headers=env.tok("admin"))
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["ok"] and rep["summary"]["create"] == 4 and rep["summary"]["departments_new"] == ["Ban điều hành", "Kho"]
    assert rep["summary"]["invitations"] == 2 and rep["summary"]["agents"] == 1
    env.db.expire_all()
    assert env.db.query(Member).count() == 0 and env.db.query(Department).count() == 0 and env.fake.created == []


def test_csv_errors_block_apply(env):
    bad = """name,type,role,department,manager,email,is_head
A,human,,P1,B,,x
B,agent,,P1,A,,x
C,robot,,P2,Không Ai,bad-mail,
A,human,,,,,
"""
    rep = env.c.post("/api/team/import-csv", json={"company_id": env.co.id, "csv_text": bad, "dry_run": False}, headers=env.tok("admin")).json()
    assert rep["ok"] is False and rep["applied"] is False
    errs = {r["line"]: " | ".join(r["errors"]) for r in rep["rows"]}
    assert "vòng" in errs[2] and "đã có trưởng phòng" in errs[3]
    assert "không hợp lệ" in errs[4] and "không thấy người quản lý" in errs[4] and "email" in errs[4]
    assert "trùng tên" in errs[5]
    env.db.expire_all()
    assert env.db.query(Member).count() == 0


def test_csv_apply_builds_chart_and_invites_then_reimport_is_idempotent(env):
    h = env.tok("admin")
    rep = env.c.post("/api/team/import-csv", json={"company_id": env.co.id, "csv_text": GOOD, "dry_run": False}, headers=h).json()
    assert rep["applied"] and rep["ok"], rep
    assert {i["email"] for i in rep["invitations"]} == {"ha@shop.vn", "minh@shop.vn"}
    assert len(env.fake.created) == 1 and re.fullmatch(r"csv-[0-9a-f]{4}-bot-dong-goi", env.fake.created[0])
    chart = env.c.get("/api/team/org-chart", params={"company_id": env.co.id}, headers=h).json()
    assert [n["name"] for n in chart["tree"]] == ["Hà"]
    minh = chart["tree"][0]["children"][0]
    assert minh["name"] == "Minh" and minh["is_head"] and {c["name"] for c in minh["children"]} == {"Bot đóng gói", "Tư"}
    heads = {d["name"]: d["head_name"] for d in chart["departments"]}
    assert heads == {"Ban điều hành": "Hà", "Kho": "Minh"}
    # người được mời nhận link → gắn đúng ghế đã nhập
    tok = next(i["token"] for i in rep["invitations"] if i["email"] == "minh@shop.vn")
    acc = env.c.post("/api/team/invitations/accept", json={"token": tok, "password": "Matkhau123"}).json()
    assert acc["member_id"] == minh["id"] and acc["role"] == "member"
    # nhập lại cùng file: cập nhật, không nhân đôi
    rep2 = env.c.post("/api/team/import-csv", json={"company_id": env.co.id, "csv_text": GOOD, "dry_run": False}, headers=h).json()
    assert rep2["ok"] and rep2["summary"]["update"] == 4 and rep2["summary"]["create"] == 0
    env.db.expire_all()
    assert env.db.query(Member).filter_by(company_id=env.co.id).count() == 4 and len(env.fake.created) == 1


def test_csv_requires_admin_and_own_company(env):
    assert env.c.post("/api/team/import-csv", json={"company_id": env.co.id, "csv_text": GOOD}, headers=env.tok("manager")).status_code == 403
    foreign = Company(organization_id=env.other.id, name="Ngoài"); env.db.add(foreign); env.db.commit()
    assert env.c.post("/api/team/import-csv", json={"company_id": foreign.id, "csv_text": GOOD}, headers=env.tok("admin")).status_code == 404


def test_slug_ascii():
    assert svc.slug_ascii("Giám đốc sáng tạo") == "giam-doc-sang-tao"
    assert svc.slug_ascii("Đặng Thị Ánh") == "dang-thi-anh"
