"""M2e.3 — hợp đồng dữ liệu vào/ra chuẩn: CRUD + kiểm schema, việc từ bước quy trình mang dữ liệu vào + hợp đồng,
MCP company_task_submit_output (sai → trả lỗi + đếm lần, đúng → ghi bước + kết quả bước), agent không tự sang Chờ duyệt
khi chưa đạt, quá số lần → Bị chặn + Hộp việc của người, lượt chạy kết thúc chưa nộp → về Cần làm + đánh thức,
điều kiện bước đọc step<N>.output.<trường>, company_process_step_outcome, KPI tỷ lệ đạt chuẩn + scorecard, AGENTS.md.
ORM thật trên SQLite, gateway giả."""
import json

from app.models import Agent, Member, Task
from app.models.agent_native import TaskContract, TaskOutput
from app.models.extended import InboxItem
from app.models.work_graph import Wakeup
from app.services import io_contracts as ioc
from tests.test_m2b_company_foundation import E, mkpos  # noqa: F401  (fixture)
from tests.test_m2c_process_map import _finish, _setup
from tests.test_m2e_runtime_rules import _mcp
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)

GOOD = {"order_id": "DH-1024", "amount_usd": 18.5, "reason": "Bình vỡ khi giao, có ảnh, đúng chính sách 7 ngày",
        "decision": "approve", "customer_message": "Dạ em xin lỗi chị, em đã ghi nhận và hoàn 18.5 USD trong 24 giờ ạ."}


def mkc(E, role="manager", **body):
    return E.c.post("/api/team/contracts", json={"company_id": E.co.id, **body}, headers=E.tok(role))


def test_schema_subset_validator_messages():
    s = ioc.TEMPLATES["refund_request"]["output_schema"]
    assert ioc.check_schema(s) == []
    assert ioc.validate(s, GOOD) == []
    errs = {e["path"]: e["message"] for e in ioc.validate(s, {"order_id": "DH", "amount_usd": "18", "decision": "ok",
                                                               "extra": 1})}
    assert "ít nhất 3 ký tự" in errs["order_id"] and "phải là số" in errs["amount_usd"]
    assert "chỉ nhận một trong" in errs["decision"] and "bắt buộc" in errs["reason"] and "trường lạ" in errs["extra"]
    assert ioc.check_schema({"type": "object", "properties": {"a": {"type": "strin"}}, "oneOf": []})   # khoá/kiểu lạ
    assert ioc.check_acceptance([{"text": "tiền > 0", "field": "amount_usd", "op": ">", "value": 0}], {"amount_usd": 0})
    nested = ioc.TEMPLATES["order_confirm"]["output_schema"]
    bad = ioc.validate(nested, {"order_id": "DH-1", "customer_name": "Lan", "items": [{"sku": "B1", "qty": 0}],
                                "total_usd": 10, "confirmed": True})
    assert bad == [{"path": "items[0].qty", "message": "phải ≥ 1"}]


def test_contract_crud_templates_versions_and_validate_endpoint(E):
    pos = mkpos(E, title="CSKH online", department_id=E.sales.id, headcount=2)
    assert mkc(E, role="member", template="refund_request").status_code == 403
    assert mkc(E, template="khong_co").status_code == 422
    assert mkc(E, name="x", output_schema={"type": "object", "properties": {}}).status_code == 422          # không trường
    assert mkc(E, name="x", output_schema={"type": "object", "properties": {"a": {"type": "string"}}, "anyOf": []}).status_code == 422
    assert mkc(E, name="x", output_schema='{"type": "object", "properties": {"a": {"type": "string"}}}',
               outcome_field="b").status_code == 422                                                 # trường kết quả bước lạ
    r = mkc(E, template="refund_request", position_id=pos["id"])
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["name"] == "Đơn hoàn tiền" and c["outcome_field"] == "decision" and c["version"] == 1
    assert c["position"] == "CSKH online" and "decision: approve|reject|escalate*" in c["fields"]
    # đổi tên không đổi version; đổi schema/tiêu chí → version mới
    assert E.c.patch(f"/api/team/contracts/{c['id']}", json={"name": "Đơn hoàn tiền v"}, headers=E.tok("manager")).json()["version"] == 1
    v = E.c.patch(f"/api/team/contracts/{c['id']}", json={"max_attempts": 2}, headers=E.tok("manager")).json()
    assert v["version"] == 2 and v["max_attempts"] == 2
    assert E.c.patch(f"/api/team/contracts/{c['id']}", json={"max_attempts": 0}, headers=E.tok("manager")).status_code == 422
    ok = E.c.post(f"/api/team/contracts/{c['id']}/validate", json={"output": GOOD}, headers=E.tok("member")).json()
    assert ok == {"valid": True, "errors": []}
    bad = E.c.post(f"/api/team/contracts/{c['id']}/validate", json={"output": {**GOOD, "amount_usd": 0}},
                   headers=E.tok("member")).json()
    assert not bad["valid"] and "tiêu chí nghiệm thu #1" in bad["errors"][0]["message"]
    lst = E.c.get(f"/api/team/contracts?company_id={E.co.id}", headers=E.tok("member")).json()
    assert [x["id"] for x in lst["items"]] == [c["id"]] and {t["key"] for t in lst["templates"]} >= {"refund_request", "daily_report"}
    assert E.c.delete(f"/api/team/contracts/{c['id']}", headers=E.tok("manager")).json()["status"] == "archived"
    assert E.c.get(f"/api/team/contracts?company_id={E.co.id}", headers=E.tok("member")).json()["items"] == []
    assert E.c.patch(f"/api/team/contracts/{c['id']}", json={"name": "x"}, headers=E.tok("other")).status_code == 404


def _flow(E, max_attempts=3):
    """Quy trình: B1 tiếp nhận (hợp đồng Đơn hoàn tiền) → B2 hoàn tiền chỉ khi step1.output.decision == approve
    → B3 báo khách (hợp đồng Báo cáo ngày, đọc dữ liệu từ B1)."""
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    c = mkc(E, template="refund_request", position_id=cskh["id"], max_attempts=max_attempts).json()
    d = mkc(E, template="daily_report").json()
    body = {"company_id": E.co.id, "name": "Hoàn tiền có hợp đồng", "category": "6", "owner_position_id": owner_pos["id"],
            "steps": [{"name": "Tiếp nhận", "position_id": cskh["id"], "contract_id": c["id"]},
                      {"name": "Hoàn tiền", "position_id": cskh["id"],
                       "condition": {"field": "step1.output.decision", "op": "==", "value": "approve"}},
                      {"name": "Báo khách", "position_id": cskh["id"], "contract_id": d["id"], "depends_on": [1]}]}
    r = E.c.post("/api/team/processes", json=body, headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["steps"][0]["contract"] == "Đơn hoàn tiền" and p["steps"][1]["condition"]["field"] == "step1.output.decision"
    inst = E.c.post(f"/api/team/processes/{p['id']}/start", json={"title": "Khách Lan", "amount_usd": 18.5,
                                                                   "input": {"order_id": "DH-1024"}},
                    headers=E.tok("member")).json()
    ag = E.db.get(Agent, agent["agent_id"]); m = E.db.get(Member, ag.member_id)
    return c, d, p, inst, m


def test_step_task_carries_input_and_contract_submit_rework_accept_and_branch_on_output(E):
    c, d, p, inst, m = _flow(E)
    t1, t2, t3 = [s["task_id"] for s in inst["steps"]]
    task1 = E.db.get(Task, t1)
    assert "## Hợp đồng dữ liệu: Đơn hoàn tiền" in task1.description and '"order_id": "DH-1024"' in task1.description
    tc = E.db.query(TaskContract).filter(TaskContract.task_id == t1).one()
    assert tc.input_json == {"order_id": "DH-1024"} and tc.input_errors is None and tc.status == "open"
    # agent đọc hợp đồng qua company_task_get
    got = _mcp(E, m, "company_task_get", {"task_id": t1})["structuredContent"]
    assert got["contract"]["name"] == "Đơn hoàn tiền" and got["contract"]["input"] == {"order_id": "DH-1024"}
    for to in ("todo", "in_progress"):
        if E.db.get(Task, t1).status != to:
            _mcp(E, m, "company_task_status", {"task_id": t1, "status": to, "reason": "làm"})
    # chưa nộp → không tự sang Chờ duyệt
    res = _mcp(E, m, "company_task_status", {"task_id": t1, "status": "review", "reason": "xong"})
    assert res["isError"] and res["structuredContent"]["error"] == "contract_output_required"
    # nộp sai → lỗi cụ thể, đếm lần
    bad = _mcp(E, m, "company_task_submit_output", {"task_id": t1, "output": {"order_id": "DH-1024", "decision": "yes"}})
    sc = bad["structuredContent"]
    assert not bad["isError"] and sc["valid"] is False and sc["status"] == "rework" and sc["attempts_left"] == 2
    assert {e["path"] for e in sc["errors"]} >= {"decision", "amount_usd", "reason", "customer_message"}
    # đúng → đạt, kết quả vào bước, kết quả bước = decision
    ok = _mcp(E, m, "company_task_submit_output", {"task_id": t1, "output": GOOD})["structuredContent"]
    assert ok["valid"] and ok["status"] == "accepted" and ok["attempt"] == 2
    again = _mcp(E, m, "company_task_submit_output", {"task_id": t1, "output": GOOD})
    assert again["isError"] and again["structuredContent"]["error"] == "already_accepted"
    run1 = E.c.get(f"/api/team/process-instances/{inst['id']}", headers=E.tok("member")).json()["steps"][0]
    assert run1["output"] == GOOD and run1["outcome"] == "approve" and run1["contract"]["status"] == "accepted"
    assert _mcp(E, m, "company_task_status", {"task_id": t1, "status": "review", "reason": "đã nộp"})["isError"] is False
    _finish(E, t1)
    got = E.c.get(f"/api/team/process-instances/{inst['id']}", headers=E.tok("member")).json()
    assert [s["status"] for s in got["steps"]] == ["done", "active", "active"]      # decision approve → B2 chạy
    # B3 nhận dữ liệu vào = đầu vào lần chạy + kết quả B1
    tc3 = E.db.query(TaskContract).filter(TaskContract.task_id == t3).one()
    assert tc3.input_json["customer_message"] == GOOD["customer_message"] and tc3.input_json["order_id"] == "DH-1024"
    assert "Dữ liệu vào" in E.db.get(Task, t3).description
    # bước không có hợp đồng (B2) vẫn nhận kết quả chuẩn của B1 trong mô tả việc
    assert "## Dữ liệu từ bước trước" in E.db.get(Task, t2).description and '"decision": "approve"' in E.db.get(Task, t2).description
    outs = E.db.query(TaskOutput).filter(TaskOutput.task_id == t1).order_by(TaskOutput.id).all()
    assert [(o.attempt, o.valid, o.via) for o in outs] == [(1, False, "mcp"), (2, True, "mcp")]
    lst = E.c.get(f"/api/team/contracts?company_id={E.co.id}", headers=E.tok("member")).json()
    seat = next(s for s in lst["seats"] if s["member_id"] == m.id)
    assert (seat["submissions"], seat["valid"], seat["rate"], seat["first_try_rate"]) == (2, 1, 0.5, 0.0)


def test_reject_decision_skips_branch(E):
    c, d, p, inst, m = _flow(E)
    t1 = inst["steps"][0]["task_id"]
    _mcp(E, m, "company_task_submit_output", {"task_id": t1, "output": {**GOOD, "decision": "reject"}})
    _finish(E, t1)
    got = E.c.get(f"/api/team/process-instances/{inst['id']}", headers=E.tok("member")).json()
    assert got["steps"][1]["status"] == "skipped" and "step1.output.decision" in got["steps"][1]["skip_reason"]


def test_too_many_bad_outputs_blocks_task_and_escalates_to_a_human(E):
    c, d, p, inst, m = _flow(E, max_attempts=2)
    t1 = inst["steps"][0]["task_id"]
    _mcp(E, m, "company_task_status", {"task_id": t1, "status": "in_progress", "reason": "làm"})
    _mcp(E, m, "company_task_submit_output", {"task_id": t1, "output": {"order_id": "x"}})
    sc = _mcp(E, m, "company_task_submit_output", {"task_id": t1, "output": {"order_id": "y"}})["structuredContent"]
    assert sc["status"] == "escalated" and sc["escalated_to"]
    t = E.db.get(Task, t1); E.db.refresh(t)
    assert t.status == "blocked"
    items = E.db.query(InboxItem).filter(InboxItem.task_id == t1).all()
    assert any("output_escalated" in (i.kinds or [i.kind]) or i.kind == "output_escalated" for i in items)
    target = E.db.get(Member, E.db.query(TaskContract).filter(TaskContract.task_id == t1).one().escalated_to_member_id)
    assert target.member_type == "human"
    late = _mcp(E, m, "company_task_submit_output", {"task_id": t1, "output": GOOD})
    assert late["isError"] and late["structuredContent"]["error"] == "escalated"


def test_run_end_without_output_counts_attempt_returns_to_todo_and_wakes_seat(E):
    from app.services import runtime_stream
    c, d, p, inst, m = _flow(E, max_attempts=2)
    t1 = inst["steps"][0]["task_id"]
    _mcp(E, m, "company_task_status", {"task_id": t1, "status": "in_progress", "reason": "làm"})
    task = E.db.get(Task, t1)
    state = runtime_stream.ConsumerState(session_key="agent:x:task-1", task_id=t1, organization_id=E.org.id)
    runtime_stream.apply_terminal_state(E.db, task, state, {"state": "complete"})
    E.db.refresh(task)
    assert task.status == "todo"
    tc = E.db.query(TaskContract).filter(TaskContract.task_id == t1).one()
    assert tc.attempts == 1 and "chưa nộp" in tc.last_errors[0]["message"]
    assert E.db.query(Wakeup).filter(Wakeup.task_id == t1, Wakeup.reason == "changes_requested").count() == 1
    # lần hai cũng không nộp → hết lượt → Bị chặn, giữ nguyên Bị chặn
    lifecycle_task = E.db.get(Task, t1)
    _mcp(E, m, "company_task_status", {"task_id": t1, "status": "in_progress", "reason": "làm lại"})
    runtime_stream.apply_terminal_state(E.db, lifecycle_task, state, {"state": "complete"})
    E.db.refresh(lifecycle_task)
    assert lifecycle_task.status == "blocked" and E.db.query(TaskContract).filter(TaskContract.task_id == t1).one().status == "escalated"


def test_step_outcome_tool_kpi_scorecard_and_agents_md(E):
    c, d, p, inst, m = _flow(E)
    t1, t2 = inst["steps"][0]["task_id"], inst["steps"][1]["task_id"]
    out = _mcp(E, m, "company_process_step_outcome", {"task_id": t1, "outcome": "hàng lỗi do vận chuyển"})
    assert out["structuredContent"]["outcome"] == "hàng lỗi do vận chuyển"
    other = E.db.query(Member).filter(Member.member_type == "human", Member.company_id == E.co.id).first()
    task2 = E.db.get(Task, t2)
    task2.assignee_member_id = other.id; E.db.commit()
    assert _mcp(E, m, "company_process_step_outcome", {"task_id": t2, "outcome": "x"})["isError"]
    _mcp(E, m, "company_task_submit_output", {"task_id": t1, "output": GOOD})
    # KPI tính từ lần nộp
    k = E.c.post("/api/team/kpis", json={"company_id": E.co.id, "name": "Đúng chuẩn", "level": "seat", "member_id": m.id,
                                         "metric": "output_conformance_rate", "target": 95, "period": "month"},
                 headers=E.tok("manager"))
    assert k.status_code == 200, k.text
    assert k.json()["value"] == 100.0
    ag = E.db.query(Agent).filter(Agent.member_id == m.id).one()
    card = E.c.get(f"/api/learning/career/{ag.id}", headers=E.tok("manager")).json()
    card = card.get("scorecard", card)
    assert card["output_conformance_rate"] == 1.0 and "rule_compliance_rate" in card
    # AGENTS.md của chức danh có mục hợp đồng (+ hợp đồng của bước do chức danh làm)
    from app.services import agent_hr
    from app.services.company_foundation import position_brief
    pb = position_brief(E.db, m)
    assert any("Đơn hoàn tiền" in x for x in pb["contracts"])
    files = agent_hr.render_files(name="Thu", role="CSKH", company="Co", department="Bán", manager="Lan",
                                  personality="than-thien", job_description="", manager_notes="", position=pb)
    assert "## Hợp đồng dữ liệu" in files["AGENTS.md"] and "company_task_submit_output" in files["AGENTS.md"]


def test_position_tool_list_never_blocks_contract_tools(E):
    cskh, agent, *_ = _setup(E)
    assert E.c.patch(f"/api/team/positions/{cskh['id']}", json={"allowed_tools": ["company_task_get"]},
                     headers=E.tok("manager")).status_code == 200
    ag = E.db.get(Agent, agent["agent_id"]); m = E.db.get(Member, ag.member_id); E.db.refresh(m)
    r = _mcp(E, m, "company_task_submit_output", {"task_id": 999999, "output": {}})
    assert r["structuredContent"].get("error") == "not_found"          # tới được tool (không bị chức danh tắt)
    from app.services.tool_permissions import _position_gate
    assert _position_gate(E.db, m, "company_event_emit") == ("off", f"position:{cskh['id']}")   # tool khác vẫn bị tắt
    assert _position_gate(E.db, m, "company_process_step_outcome") is None
