"""M2b — hồ sơ pháp nhân + hiến chương (biên dịch vào AGENTS.md), chức danh tách khỏi người,
ma trận phân quyền và các đường cũ đọc từ nó. ORM thật trên SQLite, gateway giả (FakeGateway)."""
import json

import pytest

from app.models import Agent, Approval, Member
from app.models.company_foundation import AuthorityRule, Position
from app.services import authority, company_foundation as cf, company_mcp, tool_permissions as perms
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


@pytest.fixture()
def E(env, monkeypatch):
    # sinh lại AGENTS.md chạy nền bằng SessionLocal → trỏ về DB của test và gateway giả
    from app.api import learning
    monkeypatch.setattr("app.api.learning.get_runtime", lambda: env.gw)
    monkeypatch.setattr("app.runtime.factory.get_runtime", lambda: env.gw)
    bind = env.db.get_bind()
    from sqlalchemy.orm import sessionmaker
    monkeypatch.setattr("app.db.session.SessionLocal", sessionmaker(bind=bind, autoflush=False))
    return env


def put_profile(E, role="owner", **body):
    return E.c.put("/api/team/company-profile", json={"company_id": E.co.id, **body}, headers=E.tok(role))


CHARTER = dict(
    legal_name="Công ty TNHH Nova Shop", entity_type="tnhh_1tv", tax_code="0312345678",
    legal_representative="Chị Lan", registered_address="12 Lê Lợi, Q1, TP.HCM", charter_capital_usd=40000,
    mission="Mang gốm Việt đẹp và bền tới từng nhà.", values=["Thật thà với khách", "Giao đúng hẹn"],
    brand_voice="Ấm áp, xưng em gọi anh/chị, không dùng tiếng lóng.",
    prohibitions=["Không hứa hoàn tiền ngoài chính sách", "Không tiết lộ số điện thoại khách khác"],
    customer_promises=["Đổi trả trong 7 ngày", "Trả lời trong 5 phút giờ hành chính"],
)


# ------------------------------------------------------------------ 1. hồ sơ + hiến chương

def test_charter_is_compiled_into_every_agents_md_and_edits_resync(E):
    a = hire(E)
    b = hire(E, name="Minh Khoa", role="Nhân viên kho", department_id=E.mkt.id)
    r = put_profile(E, **CHARTER)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["core_sync"] is True and out["charter_version"] == 1 and out["warnings"] == []
    for x in (a, b):    # sync_core chạy nền sau response (TestClient chạy xong background task)
        md = E.gw.files[(x["runtime_agent_id"], "AGENTS.md")]
        assert "### Hiến chương Nova Shop" in md and "Không hứa hoàn tiền ngoài chính sách" in md
        assert "Mang gốm Việt" in md and "MST 0312345678" in md
    # sửa một điều cấm → bản mới lên gateway, bản cũ mất
    r = put_profile(E, prohibitions=["Không tiết lộ số điện thoại khách khác", "Không chê sản phẩm đối thủ"])
    assert r.json()["core_sync"] is True and r.json()["charter_version"] == 2
    md = E.gw.files[(a["runtime_agent_id"], "AGENTS.md")]
    assert "Không chê sản phẩm đối thủ" in md and "Không hứa hoàn tiền" not in md
    # chỉ đổi phần pháp nhân không vào hiến chương (địa chỉ) → không đồng bộ lại
    assert put_profile(E, registered_address="99 Hai Bà Trưng").json()["core_sync"] is False
    # agent tuyển SAU cũng mang hiến chương ngay lúc tuyển
    c = hire(E, name="Bé Ba", role="Nhân viên nội dung", department_id=E.mkt.id)
    assert "Không chê sản phẩm đối thủ" in E.gw.files[(c["runtime_agent_id"], "AGENTS.md")]
    # preview tri thức cốt lõi cũng thấy
    pv = E.c.get(f"/api/learning/core/{a['agent_id']}", headers=E.tok("member")).json()
    assert "Hiến chương" in pv["text"]


def test_profile_validation_and_legal_warnings(E):
    r = put_profile(E, tax_code="12345")
    assert r.status_code == 422 and "10 chữ số" in r.json()["detail"]
    assert put_profile(E, tax_code="0312345678-001").status_code == 200       # chi nhánh
    assert put_profile(E, entity_type="llc").status_code == 422
    assert put_profile(E, founded_on="15/03/2024").status_code == 422
    assert put_profile(E, charter_capital_usd=-1).status_code == 422
    w = put_profile(E, legal_name="Nova Shop", entity_type="co_phan").json()["warnings"]
    assert any("Điều 37" in x for x in w)
    assert put_profile(E, role="manager", mission="x").status_code == 403         # admin+ mới sửa
    assert put_profile(E, mission="m " * 2000).status_code == 422                 # quá hạn mức ký tự
    got = E.c.get(f"/api/team/company-profile?company_id={E.co.id}", headers=E.tok("member")).json()
    assert got["entity_type"] == "co_phan" and got["tax_code"] == "0312345678-001"
    assert E.c.get("/api/team/company-profile", headers=E.tok("other")).json()["company_id"] != E.co.id


# ------------------------------------------------------------------ 2. chức danh

def mkpos(E, **body):
    r = E.c.post("/api/team/positions", json={"company_id": E.co.id, **body}, headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    return r.json()


def test_position_headcount_vacancy_and_jd_kpi_flow_into_agents_md(E):
    p = mkpos(E, title="Nhân viên CSKH", department_id=E.sales.id, headcount=2,
              job_description="Chăm sóc khách trên mọi kênh chat.",
              responsibilities=["Trả lời tin nhắn khách", "Ghi nhận khiếu nại vào hệ thống"],
              kpis=[{"name": "Phản hồi trong 5 phút", "target": 95, "unit": "%", "period": "week"},
                    {"name": "CSAT", "target": 4.5, "unit": "điểm", "period": "month"}],
              allowed_tools=["company_knowledge_search", "company_task_comment"])
    assert p["headcount"] == 2 and p["filled"] == 0 and p["vacancies"] == 2
    a = hire(E, position_id=p["id"], role="")
    assert a["position_id"] == p["id"]
    m = E.db.get(Member, a["member_id"]); E.db.refresh(m)
    assert m.role == "Nhân viên CSKH" and m.position_id == p["id"]
    lst = E.c.get(f"/api/team/positions?company_id={E.co.id}", headers=E.tok("member")).json()
    row = next(i for i in lst["items"] if i["id"] == p["id"])
    assert row["filled"] == 1 and row["vacancies"] == 1 and row["seats"][0]["name"] == "Thu Trang"
    md = E.gw.files[(a["runtime_agent_id"], "AGENTS.md")]
    assert "Chăm sóc khách trên mọi kênh chat." in md and "- Ghi nhận khiếu nại vào hệ thống" in md
    assert "## KPI của chức danh" in md and "- Phản hồi trong 5 phút: 95 % / tuần" in md
    assert "Riêng ghế này" in md and "Trả lời khách trên kênh chat" in md        # JD riêng của seat vẫn giữ
    # công cụ của chức danh là cổng thật
    assert perms.resolve(E.db, m, "company_budget_check")[0] == "off"
    assert perms.resolve(E.db, m, "company_budget_check")[1] == f"position:{p['id']}"
    assert perms.resolve(E.db, m, "company_knowledge_search")[0] == "allowed"
    # sửa KPI → AGENTS.md của người đang ngồi sinh lại
    r = E.c.patch(f"/api/team/positions/{p['id']}", json={"kpis": [{"name": "Tỷ lệ chốt đơn", "target": 30, "unit": "%"}]},
                  headers=E.tok("manager"))
    assert r.status_code == 200 and r.json()["resync_agents"] == [a["agent_id"]]
    md = E.gw.files[(a["runtime_agent_id"], "AGENTS.md")]
    assert "Tỷ lệ chốt đơn: 30 % / tháng" in md and "Phản hồi trong 5 phút" not in md
    # đổi tên chức danh → members.role theo (lớp nghề + eval theo vai đọc role)
    E.c.patch(f"/api/team/positions/{p['id']}", json={"title": "Chuyên viên CSKH"}, headers=E.tok("manager"))
    E.db.refresh(m)
    assert m.role == "Chuyên viên CSKH"


def test_headcount_limits_and_archive_rules(E):
    p = mkpos(E, title="Trưởng kho", headcount=1, department_id=E.mkt.id)
    r = E.c.post(f"/api/team/positions/{p['id']}/seats", json={"member_id": E.lead_m.id}, headers=E.tok("manager"))
    assert r.status_code == 200 and r.json()["vacancies"] == 0
    r = E.c.post(f"/api/team/positions/{p['id']}/seats", json={"member_id": E.lead_s.id}, headers=E.tok("manager"))
    assert r.status_code == 409 and "đủ định biên (1/1)" in r.json()["detail"]
    bad = E.c.post("/api/agents/hire", json={"name": "X", "position_id": p["id"]}, headers=E.tok("manager"))
    assert bad.status_code == 409 and "Tăng định biên" in bad.json()["detail"]
    assert E.c.patch(f"/api/team/positions/{p['id']}", json={"headcount": 0}, headers=E.tok("manager")).status_code == 409
    assert E.c.delete(f"/api/team/positions/{p['id']}", headers=E.tok("manager")).status_code == 409
    assert E.c.delete(f"/api/team/positions/{p['id']}/seats/{E.lead_m.id}", headers=E.tok("manager")).status_code == 200
    assert E.c.delete(f"/api/team/positions/{p['id']}", headers=E.tok("manager")).json()["status"] == "archived"
    # báo cáo vòng tròn bị chặn
    x = mkpos(E, title="A"); y = mkpos(E, title="B", reports_to_position_id=x["id"])
    r = E.c.patch(f"/api/team/positions/{x['id']}", json={"reports_to_position_id": y["id"]}, headers=E.tok("manager"))
    assert r.status_code == 422 and "vòng tròn" in r.json()["detail"]
    assert E.c.post("/api/team/positions", json={"company_id": E.co.id, "title": "Z"}, headers=E.tok("member")).status_code == 403


def test_positions_from_existing_members_same_rule_as_migration(E):
    hire(E); hire(E, name="Minh Khoa")      # hai agent cùng "Nhân viên chăm sóc khách" ở phòng Bán hàng
    r = E.c.post(f"/api/team/positions/from-members?company_id={E.co.id}", headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    items = {i["title"]: i for i in E.c.get(f"/api/team/positions?company_id={E.co.id}", headers=E.tok("member")).json()["items"]}
    cs = items["Nhân viên chăm sóc khách"]
    assert cs["headcount"] == 2 and cs["filled"] == 2 and cs["vacancies"] == 0
    assert cs["reports_to"] == "Trưởng phòng bán hàng"           # chức danh của người quản lý
    assert items["CEO"]["department_id"] is None


def test_migration_0038_turns_job_titles_into_positions(tmp_path):
    """Chạy chuỗi migration tới 0037, ghi dữ liệu kiểu cũ, rồi lên 0038."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    from sqlalchemy import create_engine, text
    backend = Path(__file__).resolve().parents[1]
    url = f"sqlite:///{tmp_path / 'm.db'}"
    envv = {**os.environ, "DATABASE_URL": url, "JWT_SECRET": "test"}

    def up(rev):
        p = subprocess.run([sys.executable, "-m", "alembic", "upgrade", rev], cwd=backend, env=envv,
                           capture_output=True, text=True, timeout=300)
        assert p.returncode == 0, p.stderr[-2000:]
    up("0037_a2a")
    eng = create_engine(url)
    with eng.begin() as c:
        c.execute(text("INSERT INTO organizations (id, name, slug, created_at, updated_at) VALUES (1,'O','o',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO companies (id, organization_id, name, industry, status, created_at, updated_at) VALUES (1,1,'C','', 'active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        c.execute(text("INSERT INTO departments (id, company_id, name, access_level, status, guide, created_at, updated_at) VALUES (1,1,'Bán hàng','restricted','active','',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        for mid, name, role, dept, mgr in ((1, "Lan", "Giám đốc", None, None), (2, "Minh", "Trưởng phòng", 1, 1),
                                           (3, "Bot1", "CSKH", 1, 2), (4, "Bot2", "CSKH", 1, 2), (5, "Trống", "", 1, 2)):
            c.execute(text("INSERT INTO members (id, organization_id, company_id, department_id, name, member_type, role, manager_id, status, created_at, updated_at) "
                           "VALUES (:i,1,1,:d,:n,'agent',:r,:m,'active',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"),
                      {"i": mid, "d": dept, "n": name, "r": role, "m": mgr})
    up("head")
    with eng.connect() as c:
        pos = {r.title: r for r in c.execute(text("SELECT * FROM positions")).fetchall()}
        assert set(pos) == {"Giám đốc", "Trưởng phòng", "CSKH"}
        assert pos["CSKH"].headcount == 2 and pos["CSKH"].reports_to_position_id == pos["Trưởng phòng"].id
        assert pos["Trưởng phòng"].reports_to_position_id == pos["Giám đốc"].id
        seat = dict(c.execute(text("SELECT id, position_id FROM members")).fetchall())
        assert seat[3] == seat[4] == pos["CSKH"].id and seat[5] is None
        roles = dict(c.execute(text("SELECT id, role FROM members")).fetchall())
        assert roles[3] == "CSKH"                                 # members.role giữ nguyên


# ------------------------------------------------------------------ 3. ma trận phân quyền

def seed(E):
    r = E.c.post("/api/team/authority/seed-defaults", json={"company_id": E.co.id}, headers=E.tok("owner"))
    assert r.status_code == 200, r.text
    return r.json()


def rule(E, **body):
    r = E.c.post("/api/team/authority/rules", json={"company_id": E.co.id, **body}, headers=E.tok("owner"))
    assert r.status_code == 200, r.text
    return r.json()


def mcp(E, out, name, args):
    ag = E.db.get(Agent, out["agent_id"]); m = E.db.get(Member, ag.member_id)
    ctx = company_mcp.ToolContext(db=E.db, member=m, agent=ag, scopes=["company.approvals:write", "company.policy:read"])
    return company_mcp.TOOLS[name].handler(ctx, args)


def test_refund_over_50_needs_department_head_and_inbox_card_names_rule(E):
    out = hire(E)                                          # agent ở Bán hàng, trưởng phòng là Anh Minh (người)
    r = rule(E, action_type="refund", min_amount_usd=50, approver_kind="department_head",
             note="Hoàn tiền trên $50 cần trưởng phòng")
    assert r["band"] == "từ $50" and "Trưởng phòng" in r["label"]
    small = mcp(E, out, "company_approval_request", {"action": "refund", "amount_usd": 20, "evidence": "Đơn #12 hỏng"})
    assert small["decision"] == "deny" and small["policy_key"] == "default_deny"   # dưới dải: không luật → đường cũ
    big = mcp(E, out, "company_approval_request", {"action": "hoàn tiền", "amount_usd": 80,
                                                     "evidence": "Khách Lan, đơn #77 vỡ 2 bình"})
    assert big["decision"] == "approval_required" and big["policy_key"] == f"authority:r{r['id']}"
    a = E.db.get(Approval, big["approval_id"])
    assert a.approver_member_id == E.lead_s.id and a.payload["authority"]["rule_id"] == r["id"]
    assert "$80" in a.action
    # gọi lại cùng việc → không tạo trùng
    again = mcp(E, out, "company_approval_request", {"action": "refund", "amount_usd": 80,
                                                       "evidence": "Khách Lan, đơn #77 vỡ 2 bình"})
    assert again["approval_id"] == a.id
    # Hộp việc: thẻ hiện luật
    from app.core.authz import Principal
    from app.services import inbox_hub
    p = Principal(user_id=None, organization_id=E.org.id, role="manager", auth_type="jwt", scopes=[],
                  member_id=E.lead_s.id)
    feed = inbox_hub.feed(E.db, E.org.id, p)
    cards = [c for g in feed["groups"] for c in g["items"] if (c.get("approval") or {}).get("id") == a.id]
    assert cards and cards[0]["group"] == "approvals"
    card = cards[0]["approval"]
    assert card["authority"]["rule_id"] == r["id"] and card["kind"] == "authority" and card["can_decide"] is True
    assert "Trưởng phòng" in card["authority"]["label"]
    # policy_check (không tạo duyệt) trả cùng luật
    pc = mcp(E, out, "company_policy_check", {"action": "refund", "amount_usd": 120})
    assert pc["requires_approval"] is True and pc["approver"] == "Anh Minh"


def test_default_matrix_bands_agent_levels_and_human_routing(E):
    seed(E)
    out = hire(E)
    ag = E.db.get(Agent, out["agent_id"]); m = E.db.get(Member, ag.member_id)
    d = authority.decide(E.db, m, "spend", amount_usd=10)
    assert d.approver_kind == "manager" and d.requires_approval is True       # agent chính thức, luật: chỉ tin cậy
    assert d.approver_member_id == E.lead_s.id
    assert authority.decide(E.db, m, "spend", amount_usd=50).approver_kind == "department_head"
    own = authority.decide(E.db, m, "spend", amount_usd=500)
    assert own.approver_kind == "owner" and own.approver_member_id == E.boss.id   # owner không gắn member → đầu sơ đồ
    assert authority.decide(E.db, m, "refund", amount_usd=5).requires_approval is False   # chính thức được tự hoàn <$20
    # agent tin cậy → tự chi khoản nhỏ
    from app.services import agent_hr
    spec = agent_hr.hire_spec(E.db, ag); spec["career_level"] = "trusted"; agent_hr._save_spec(E.db, ag, spec); E.db.commit()
    assert authority.decide(E.db, m, "spend", amount_usd=10).requires_approval is False
    # trưởng phòng là agent → chuyển lên người quản lý của nó
    E.sales.head_member_id = m.id; E.db.commit()
    other = hire(E, name="Bé Tư")
    m2 = E.db.get(Member, E.db.get(Agent, other["agent_id"]).member_id)
    m2.manager_id = m.id; E.db.commit()
    d2 = authority.decide(E.db, m2, "spend", amount_usd=50)
    assert d2.approver_member_id == E.lead_s.id and any("agent" in n for n in d2.notes)
    # không có luật cho loại này ở công ty khác → None (đường cũ)
    assert authority.decide(E.db, m, "spend", amount_usd=10, company_id=999) is None


def test_matrix_tightens_tool_grid_but_never_loosens(E):
    out = hire(E)
    m = E.db.get(Member, E.db.get(Agent, out["agent_id"]).member_id)
    perms.set_level(E.db, E.org.id, "action:send", "allowed", member_id=m.id)
    assert perms.resolve(E.db, m, "action:send")[0] == "allowed"                # chưa có ma trận: như cũ
    rule(E, action_type="external_message", approver_kind="manager", agent_alone_level="trusted")
    lvl, src = perms.resolve(E.db, m, "action:send")
    assert lvl == "ask" and src.startswith("authority:r")                        # agent chính thức → siết
    st, a = perms.ask_approval(E.db, m, "action:send", "gửi email cho khách")
    assert st == "pending" and a.approver_member_id == E.lead_s.id and a.payload["authority"]["action_type"] == "external_message"
    perms.set_level(E.db, E.org.id, "action:pay", "off", member_id=m.id)
    rule(E, action_type="spend", approver_kind="none")
    assert perms.resolve(E.db, m, "action:pay")[0] == "off"                      # luật "không cần duyệt" không mở được "Tắt"


def test_rule_validation_overlap_and_permissions(E):
    rule(E, action_type="spend", min_amount_usd=0, max_amount_usd=100, approver_kind="manager")
    r = E.c.post("/api/team/authority/rules", json={"company_id": E.co.id, "action_type": "spend", "min_amount_usd": 50,
                                                    "approver_kind": "owner"}, headers=E.tok("owner"))
    assert r.status_code == 409 and "Trùng dải tiền" in r.json()["detail"]
    r = E.c.post("/api/team/authority/rules", json={"company_id": E.co.id, "action_type": "spend", "min_amount_usd": 300,
                                                    "max_amount_usd": 200, "approver_kind": "owner"}, headers=E.tok("owner"))
    assert r.status_code == 422
    r = E.c.post("/api/team/authority/rules", json={"company_id": E.co.id, "action_type": "bay", "approver_kind": "owner"},
                 headers=E.tok("owner"))
    assert r.status_code == 422 and "Loại việc" in r.json()["detail"]
    r = E.c.post("/api/team/authority/rules", json={"company_id": E.co.id, "action_type": "contract",
                                                    "approver_kind": "position"}, headers=E.tok("owner"))
    assert r.status_code == 422 and "chọn chức danh" in r.json()["detail"]
    assert E.c.post("/api/team/authority/rules", json={"company_id": E.co.id, "action_type": "contract", "approver_kind": "owner"},
                    headers=E.tok("manager")).status_code == 403
    assert E.c.post("/api/team/authority/seed-defaults", json={"company_id": E.co.id}, headers=E.tok("owner")).status_code == 409
    r = E.c.post("/api/team/authority/seed-defaults", json={"company_id": E.co.id, "template": "shop", "replace": True},
                 headers=E.tok("owner"))
    assert r.status_code == 200 and r.json()["source"] == "template:shop"
    labels = [x["label"] for x in r.json()["rules"]]
    assert any("dưới $30" in x for x in labels)
    ev = E.c.post("/api/team/authority/evaluate", json={"member_id": E.lead_s.id, "action_type": "contract"},
                  headers=E.tok("member")).json()
    assert ev["matched"] and ev["approver_kind"] == "owner" and ev["requires_approval"] is True


def test_position_approver_and_hire_guard(E):
    p = mkpos(E, title="Kế toán trưởng", headcount=1)
    E.c.post(f"/api/team/positions/{p['id']}/seats", json={"member_id": E.lead_m.id}, headers=E.tok("manager"))
    rule(E, action_type="data_export", approver_kind="position", approver_position_id=p["id"])
    out = hire(E)
    m = E.db.get(Member, E.db.get(Agent, out["agent_id"]).member_id)
    assert authority.decide(E.db, m, "data_export").approver_member_id == E.lead_m.id
    rule(E, action_type="hire_agent", approver_kind="owner")
    r = E.c.post("/api/agents/hire", json={"name": "Y", "company_id": E.co.id, "department_id": E.sales.id},
                 headers=E.tok("manager"))
    assert r.status_code == 403 and "ma trận phân quyền" in r.json()["detail"]
    r = E.c.post("/api/agents/hire", json={"name": "Y", "company_id": E.co.id, "department_id": E.sales.id},
                 headers=E.tok("owner"))
    assert r.status_code == 200, r.text


def test_budget_soft_stop_and_exec_read_the_matrix(E):
    out = hire(E)
    m = E.db.get(Member, E.db.get(Agent, out["agent_id"]).member_id)
    rule(E, action_type="budget_overrun", approver_kind="owner")
    from app.models import BudgetEnvelope
    from app.services import budget_scope
    env_row = BudgetEnvelope(organization_id=E.org.id, company_id=E.co.id, name="Tháng 10", amount_limit=10,
                             amount_spent=9.5, soft_stop_pct=90, scope_type="company")
    E.db.add(env_row); E.db.commit()

    class T:   # việc tối thiểu cho approval
        id, title = 1, "Viết mô tả"
    a = budget_scope._request_soft_approval(E.db, env_row, m, T(), "budget_soft:e1:t1")
    assert a.approver_member_id == E.boss.id and a.payload["authority"]["action_type"] == "budget_overrun"
    # exec từ gateway: người duyệt theo luật exec
    rule(E, action_type="exec", approver_kind="department_head")
    d = authority.decide(E.db, m, "exec", risk="high")
    assert d.approver_member_id == E.lead_s.id and d.requires_approval


def test_template_company_gets_matrix_and_positions(E, monkeypatch):
    r = E.c.post("/api/team/companies/from-template", json={"template_key": "shop", "company_name": "Gốm Bát Tràng"},
                 headers=E.tok("owner"))
    assert r.status_code == 200, r.text
    cid = r.json()["company_id"]
    rules = E.db.query(AuthorityRule).filter(AuthorityRule.company_id == cid).all()
    assert rules and all(x.source == "template:shop" for x in rules)
    pos = E.db.query(Position).filter(Position.company_id == cid).all()
    titles = {p.title for p in pos}
    assert "Chăm sóc khách hàng" in titles and all(p.headcount >= 1 for p in pos)
    cskh = next(p for p in pos if p.title == "Chăm sóc khách hàng")
    assert "trả lời khách" in cskh.job_description and cskh.reports_to_position_id is not None
