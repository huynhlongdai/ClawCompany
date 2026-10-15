"""M2c D8 — chẩn đoán sẵn sàng agent: chạy ngay khi tạo công ty, điểm từng lớp từ dữ liệu thật (hiến chương,
chức danh, ma trận, quy trình, KPI, tri thức, nhịp vận hành, tuân thủ) + bảng hỏi, mỗi việc cần sửa có đường dẫn,
đề xuất quy trình lighthouse. ORM thật trên SQLite."""
from app.models import Company, KnowledgeDocument
from tests.test_m2b_company_foundation import CHARTER, E, mkpos, put_profile  # noqa: F401  (fixture)
from tests.test_m2c_kpi_cascade import _run_once, kpi
from tests.test_m2c_process_map import _setup
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def _assess(E, answers=None):
    r = E.c.post("/api/team/readiness", json={"company_id": E.co.id, "answers": answers}, headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    return r.json()


def test_new_company_gets_a_diagnostic_on_creation_with_fix_links(E):
    r = E.c.post("/api/companies", json={"organization_id": E.org.id, "name": "Tiệm Mới"}, headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    got = E.c.get(f"/api/team/readiness?company_id={cid}", headers=E.tok("member")).json()
    a = got["assessment"]
    assert a["trigger"] == "company_created" and a["level"] == "starting"
    # công ty mới đã có ma trận mặc định (M2b) → lớp phân quyền có điểm, các lớp khác gần như 0
    layers = {x["key"]: x for x in a["layers"]}
    assert layers["authority"]["score"] == 100 and layers["process"]["score"] == 0
    assert all(c["fix_href"].startswith("/app/team?tab=") and c["fix_href"].endswith(f"company={cid}") for c in a["checks"])
    assert a["lighthouse"]["process_id"] is None and "gieo bộ quy trình mẫu" in a["lighthouse"]["reasons"][0]
    assert {q["key"] for q in got["questions"]} == {"volume", "documented", "digital", "reviewers", "risk"}


def test_score_rises_as_layers_are_built_and_lighthouse_is_picked(E):
    before = _assess(E)
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    put_profile(E, **CHARTER)
    p, inst = _run_once(E, cskh, kho, owner_pos)
    kpi(E, level="company", name="Ca hoàn tiền xong", metric="process_runs_done", target=4)
    E.c.patch(f"/api/team/positions/{cskh['id']}", json={"kpis": [{"name": "CSAT", "target": 4.5}]}, headers=E.tok("manager"))
    E.c.post("/api/team/kpis/sync-positions", json={"company_id": E.co.id}, headers=E.tok("manager"))
    E.db.add(KnowledgeDocument(organization_id=E.org.id, company_id=E.co.id, title="Chính sách đổi trả", content="7 ngày",
                               is_core=True, indexed=True)); E.db.commit()
    E.c.put("/api/team/rhythm/config", json={"company_id": E.co.id}, headers=E.tok("manager"))
    after = _assess(E, {"volume": "50_200", "documented": "partial", "digital": "system", "reviewers": "daily", "risk": "medium"})
    assert after["score"] > before["score"] + 30 and after["previous_score"] == before["score"]
    layers = {x["key"]: x["score"] for x in after["layers"]}
    assert layers["legal"] == 100 and layers["kpi"] == 100 and layers["rhythm"] == 100 and layers["operations"] == 83
    checks = {c["key"]: c for c in after["checks"]}
    assert checks["runs"]["ok"] and checks["core_docs"]["ok"] and not checks["compliance"]["ok"]
    assert checks["compliance"]["fix_href"] == f"/app/team?tab=compliance&company={E.co.id}"
    lh = after["lighthouse"]
    assert lh["process_id"] == p["id"] and lh["name"] == "Hoàn tiền / đổi trả" and lh["score"] > 50
    assert any("bước dính tiền đã có luật duyệt" in x for x in lh["reasons"])
    # câu trả lời được nhớ cho lần chấm sau
    again = _assess(E)
    assert again["answers"]["digital"] == "system"
    hist = E.c.get(f"/api/team/readiness?company_id={E.co.id}", headers=E.tok("member")).json()["history"]
    assert len(hist) == 3


def test_answer_validation_and_permissions(E):
    r = E.c.post("/api/team/readiness", json={"company_id": E.co.id, "answers": {"digital": "fax"}}, headers=E.tok("manager"))
    assert r.status_code == 422 and "paper, sheet, system" in r.json()["detail"]
    assert E.c.post("/api/team/readiness", json={"company_id": E.co.id}, headers=E.tok("member")).status_code == 403
    assert E.c.get("/api/team/readiness", headers=E.tok("other")).json()["company_id"] != E.co.id
