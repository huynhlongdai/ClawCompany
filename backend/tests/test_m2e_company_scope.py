"""M2e.1 — phạm vi công ty bên trong module Công ty: hai công ty cùng một tổ chức không thấy/ghi nhầm sang nhau.
Ghi phải có company_id; SOP và hộp việc mang company_id; tick nền bỏ qua công ty đã lưu trữ; KPI không trỏ được
sang mục tiêu của công ty khác. ORM thật trên SQLite, gateway giả."""
import asyncio
from datetime import datetime

import pytest

from app.core.authz import Principal
from app.models import Agent, Company, Department, Member
from app.models.company_ops import ComplianceRule, RhythmConfig
from app.models.extended import SOP, InboxItem
from app.services import company_mcp, compliance_calendar, inbox, inbox_hub, kpi_cascade, operating_rhythm
from tests.test_m2b_company_foundation import E, mkpos  # noqa: F401  (fixture)
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


@pytest.fixture()
def T(E):
    """Công ty thứ hai trong CÙNG tổ chức (Tiệm Gốm 2), có phòng ban + một chức danh."""
    co2 = Company(organization_id=E.org.id, name="Tiệm Gốm 2", status="active")
    E.db.add(co2); E.db.commit()
    d2 = Department(company_id=co2.id, name="CSKH 2", access_level="restricted")
    E.db.add(d2); E.db.commit()
    E.co2, E.d2 = co2, d2
    return E


def test_writes_without_company_id_are_rejected_not_sent_to_the_first_company(T):
    E = T
    for path, body in (("/api/team/positions", {"title": "Kế toán"}),
                       ("/api/team/authority/rules", {"action_type": "refund", "approver_kind": "owner"}),
                       ("/api/team/processes", {"name": "Đơn mới", "steps": [{"name": "Nhận"}]}),
                       ("/api/team/kpis", {"name": "Đơn/tháng", "level": "company", "metric": "manual"})):
        r = E.c.post(path, json=body, headers=E.tok("owner"))
        assert r.status_code == 422, (path, r.status_code, r.text)
        assert "company_id" in r.text
    r = E.c.put("/api/team/company-profile", json={"mission": "x"}, headers=E.tok("owner"))
    assert r.status_code == 422
    # đọc không company_id khi org có 2 công ty: không đoán
    assert E.c.get("/api/team/positions", headers=E.tok("member")).status_code == 422
    # nothing landed on company #1 by accident
    assert E.c.get(f"/api/team/positions?company_id={E.co.id}", headers=E.tok("member")).json()["items"] == []


def test_team_endpoints_are_isolated_per_company(T):
    E = T
    p1 = mkpos(E, title="CSKH Nova", department_id=E.sales.id)
    r = E.c.post("/api/team/positions", json={"company_id": E.co2.id, "title": "CSKH Gốm 2", "department_id": E.d2.id},
                 headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    p2 = r.json()
    a = E.c.get(f"/api/team/positions?company_id={E.co.id}", headers=E.tok("member")).json()
    b = E.c.get(f"/api/team/positions?company_id={E.co2.id}", headers=E.tok("member")).json()
    assert [x["id"] for x in a["items"]] == [p1["id"]] and [x["id"] for x in b["items"]] == [p2["id"]]
    # cross-company references are refused (department / reports_to of another company)
    r = E.c.post("/api/team/positions", json={"company_id": E.co2.id, "title": "Lạc", "department_id": E.sales.id},
                 headers=E.tok("manager"))
    assert r.status_code == 422
    for c in (E.co.id, E.co2.id):
        assert E.c.post("/api/team/authority/seed-defaults", json={"company_id": c}, headers=E.tok("owner")).status_code == 200
    r1 = E.c.get(f"/api/team/authority?company_id={E.co.id}", headers=E.tok("member")).json()
    r2 = E.c.get(f"/api/team/authority?company_id={E.co2.id}", headers=E.tok("member")).json()
    assert {x["company_id"] for x in r1["rules"]} == {E.co.id} and {x["company_id"] for x in r2["rules"]} == {E.co2.id}
    # processes seeded per company carry their own SOPs
    for c in (E.co.id, E.co2.id):
        assert E.c.post("/api/team/processes/seed", json={"company_id": c, "template": "shop"},
                        headers=E.tok("manager")).status_code == 200
    l1 = E.c.get(f"/api/team/processes?company_id={E.co.id}", headers=E.tok("member")).json()
    l2 = E.c.get(f"/api/team/processes?company_id={E.co2.id}", headers=E.tok("member")).json()
    assert l1["items"] and l2["items"]
    assert not {p["id"] for p in l1["items"]} & {p["id"] for p in l2["items"]}
    sop1 = {s["id"] for s in l1["sops"]}; sop2 = {s["id"] for s in l2["sops"]}
    assert sop1 and sop2 and not sop1 & sop2
    assert {s.company_id for s in E.db.query(SOP).filter(SOP.id.in_(sop1)).all()} == {E.co.id}
    # a step cannot point at the other company's SOP
    pid = l1["items"][0]["id"]
    r = E.c.patch(f"/api/team/processes/{pid}", json={"steps": [{"name": "Nhận", "sop_id": next(iter(sop2))}]},
                headers=E.tok("manager"))
    assert r.status_code == 422 and "SOP" in r.text


def test_company_sop_get_only_returns_the_agents_own_company_sops(T):
    E = T
    for c in (E.co.id, E.co2.id):
        E.c.post("/api/team/processes/seed", json={"company_id": c, "template": "shop"}, headers=E.tok("manager"))
    legacy = SOP(organization_id=E.org.id, title="SOP chung cũ", status="published")   # NULL company = org-wide
    E.db.add(legacy); E.db.commit()
    assert legacy.company_id is None
    a = hire(E)                                  # agent of company #1
    ag = E.db.get(Agent, a["agent_id"]); m = E.db.get(Member, ag.member_id)
    ctx = company_mcp.ToolContext(db=E.db, member=m, agent=ag, scopes=["company.knowledge:read"])
    got = company_mcp.TOOLS["company_sop_get"].handler(ctx, {})["sops"]
    ids = {s["id"] for s in got}
    own = {s.id for s in E.db.query(SOP).filter(SOP.company_id == E.co.id).all()}
    foreign = {s.id for s in E.db.query(SOP).filter(SOP.company_id == E.co2.id).all()}
    assert own and foreign and own <= ids and not ids & foreign and legacy.id in ids
    with pytest.raises(company_mcp.ToolError):
        company_mcp.TOOLS["company_sop_get"].handler(ctx, {"sop_id": next(iter(foreign))})


def test_inbox_items_carry_company_and_feed_filters_per_company(T):
    E = T
    boss = E.boss
    agent2 = Member(organization_id=E.org.id, company_id=E.co2.id, department_id=E.d2.id, name="CSKH 2",
                    member_type="human", role="CSKH", manager_id=boss.id, status="active")
    E.db.add(agent2); E.db.commit()
    inbox.notify(E.db, organization_id=E.org.id, recipients=[boss.id], kind="mention", title="Nova việc",
                 company_id=E.co.id)
    inbox.notify(E.db, organization_id=E.org.id, recipients=[boss.id], kind="mention", title="Gốm 2 việc",
                 related_type="x", related_id="2", company_id=E.co2.id)
    # inferred from the recipient when not given
    E.db.add(InboxItem(organization_id=E.org.id, recipient_member_id=agent2.id, source="t", title="suy ra"))
    E.db.commit()
    assert E.db.query(InboxItem).filter(InboxItem.title == "suy ra").one().company_id == E.co2.id
    p = Principal(user_id=None, organization_id=E.org.id, role="owner", auth_type="jwt", scopes=[], member_id=boss.id)
    titles = lambda f: [c["title"] for g in f["groups"] for c in g["items"]]  # noqa: E731
    assert set(titles(inbox_hub.feed(E.db, E.org.id, p))) >= {"Nova việc", "Gốm 2 việc"}
    assert titles(inbox_hub.feed(E.db, E.org.id, p, company_id=E.co2.id)) == ["Gốm 2 việc"]
    f1 = inbox_hub.feed(E.db, E.org.id, p, company_id=E.co.id)
    assert titles(f1) == ["Nova việc"] and all(c["company_id"] == E.co.id for g in f1["groups"] for c in g["items"])


def test_ticks_skip_archived_companies(T, monkeypatch):
    E = T
    for c in (E.co, E.co2):
        E.db.add(RhythmConfig(organization_id=E.org.id, company_id=c.id))
        E.db.add(ComplianceRule(organization_id=E.org.id, company_id=c.id, key=f"t{c.id}", name="Thuế",
                                frequency="monthly"))
    E.db.commit()
    E.co2.status = "archived"; E.db.commit()
    seen = []

    async def fake_all(db, org_id, company_id, kind, **kw):
        seen.append(("rhythm", company_id)); return []

    monkeypatch.setattr(operating_rhythm, "generate_all", fake_all)
    monkeypatch.setattr(operating_rhythm, "due", lambda cfg, now: ["daily"])
    asyncio.run(operating_rhythm.tick(E.db, now=datetime(2026, 10, 16, 1, 0)))
    monkeypatch.setattr(compliance_calendar, "generate", lambda db, o, c, **k: seen.append(("cc", c)) or {"created": 0})
    monkeypatch.setattr(compliance_calendar, "remind", lambda db, o, c, **k: {"reminded": 0})
    out = compliance_calendar.tick(E.db)
    assert ("rhythm", E.co.id) in seen and ("cc", E.co.id) in seen
    assert ("rhythm", E.co2.id) not in seen and ("cc", E.co2.id) not in seen
    assert not any("error" in x for x in out)


def test_kpi_goal_must_belong_to_the_company(T):
    E = T
    from app.models.v9 import ExecutiveGoal
    g_other = ExecutiveGoal(organization_id=E.org.id, company_id=E.co2.id, title="Mục tiêu Gốm 2", objective="x")
    g_org = ExecutiveGoal(organization_id=E.org.id, company_id=None, title="Mục tiêu chung", objective="y")
    E.db.add_all([g_other, g_org]); E.db.commit()
    base = {"company_id": E.co.id, "name": "Doanh thu", "level": "company", "metric": "manual"}
    r = E.c.post("/api/team/kpis", json={**base, "goal_id": g_other.id}, headers=E.tok("manager"))
    assert r.status_code == 422 and "không thuộc" in r.text
    r = E.c.post("/api/team/kpis", json={**base, "goal_id": g_org.id}, headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    assert kpi_cascade is not None
