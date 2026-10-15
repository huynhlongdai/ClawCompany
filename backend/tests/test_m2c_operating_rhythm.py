"""M2c D6 — nhịp vận hành: giao ban sáng / báo cáo tuần sinh từ việc, quy trình, KPI, phê duyệt, chi phí,
ngoại lệ; gửi vào Hộp việc người phụ trách; agent trưởng phòng viết khi có gateway, lỗi thì bản tự động;
beat theo giờ địa phương, không trùng kỳ. ORM thật trên SQLite, gateway giả."""
import asyncio
from datetime import datetime

from app.models import Member
from app.models.company_ops import RhythmConfig, RhythmReport
from app.models.extended import InboxItem
from app.services import operating_rhythm as rh
from tests.test_m2b_company_foundation import E, mkpos  # noqa: F401  (fixture)
from tests.test_m2c_kpi_cascade import _run_once, kpi
from tests.test_m2c_process_map import _setup
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


class Writer:
    """Gateway giả cho chat_stream: trả một bản giao ban, hoặc nổ."""
    def __init__(self, text="- Ba việc quan trọng: hoàn tiền xong 1 ca\n- Cần anh duyệt 0 việc", boom=False):
        self.text, self.boom, self.prompts = text, boom, []

    async def chat_stream(self, rid, prompt, session_key=None, timeout_seconds=None):
        self.prompts.append((rid, prompt, session_key))
        if self.boom:
            raise RuntimeError("gateway down")
        yield {"kind": "final", "text": self.text}


def test_standup_from_real_data_lands_in_department_head_inbox_once(E):
    cskh, agent, kho, keeper, owner_pos = _setup(E)
    _run_once(E, cskh, kho, owner_pos, minutes=30)
    kpi(E, level="department", department_id=E.sales.id, name="Việc xong phòng bán hàng", metric="tasks_done", target=10)
    r = E.c.put("/api/team/rhythm/config", json={"company_id": E.co.id, "standup_hour": 8, "weekly_dow": 4}, headers=E.tok("manager"))
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["agent_author"] is True
    r = E.c.post("/api/team/rhythm/run", json={"company_id": E.co.id, "kind": "standup", "department_id": E.sales.id},
                 headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["created"] is True and rep["scope"] == "Bán hàng" and rep["by_agent"] is False
    assert "Anh Minh là người" in rep["author_note"]            # trưởng phòng là người → bản tự động
    assert rep["recipients"] == ["Anh Minh"]
    d = rep["data"]
    assert d["tasks"]["done"] == 2 and d["processes"]["done"] == 1 and d["kpis"]["watch"][0]["name"] == "Việc xong phòng bán hàng"
    assert "**Đã xong (24 giờ qua):** 2 việc" in rep["content"] and "1 lần chạy xong" in rep["content"]
    assert "Việc xong phòng bán hàng" in rep["content"] and "Chi phí AI" in rep["content"]
    items = E.db.query(InboxItem).filter(InboxItem.related_type == "rhythm_report").all()
    assert len(items) == 1 and items[0].recipient_member_id == E.lead_s.id and items[0].item_type == "standup"
    assert items[0].body.startswith("## Giao ban sáng")
    # cùng kỳ → không gửi lại
    again = E.c.post("/api/team/rhythm/run", json={"company_id": E.co.id, "kind": "standup", "department_id": E.sales.id},
                     headers=E.tok("manager")).json()
    assert again["created"] is False and again["id"] == rep["id"]
    assert E.db.query(InboxItem).filter(InboxItem.related_type == "rhythm_report").count() == 1
    # Hộp việc của trưởng phòng hiện mục giao ban (người dùng 'manager' chưa gắn member → xem qua API báo cáo)
    got = E.c.get(f"/api/team/rhythm?company_id={E.co.id}", headers=E.tok("member")).json()
    assert got["reports"][0]["id"] == rep["id"] and got["config"]["standup_hour"] == 8


def test_agent_department_head_writes_it_and_falls_back_when_gateway_fails(E):
    a = hire(E, name="Trưởng MKT", role="Trưởng phòng marketing", department_id=E.mkt.id)
    head = E.db.get(Member, a["member_id"]); head.manager_id = E.boss.id
    E.mkt.head_member_id = head.id; E.db.commit()
    w = Writer()
    rep = asyncio.run(rh.generate(E.db, E.org.id, E.co.id, "standup", department_id=E.mkt.id, runtime=w))
    assert rep["by_agent"] is True and rep["author"] == f"agent:{a['runtime_agent_id']}"
    assert "Ba việc quan trọng" in rep["content"] and "**Đã xong" in rep["fallback"]
    rid, prompt, key = w.prompts[0]
    assert rid == a["runtime_agent_id"] and "Không bịa thêm số" in prompt and key.startswith(f"agent:{rid}:rhythm-d{E.mkt.id}-standup-")
    assert rep["recipients"] == ["Chị Lan"]                      # agent không đọc Hộp việc → người quản lý là người
    # gateway lỗi → bản tự động, ghi lý do, vẫn gửi
    wk = asyncio.run(rh.generate(E.db, E.org.id, E.co.id, "weekly", department_id=E.mkt.id, runtime=Writer(boom=True)))
    assert wk["by_agent"] is False and "không viết được" in wk["author_note"] and wk["content"].startswith("## Báo cáo tuần")
    assert wk["period_key"].count("-W") == 1


def test_beat_tick_follows_local_hour_and_covers_company_and_departments(E):
    E.db.add(RhythmConfig(organization_id=E.org.id, company_id=E.co.id, standup_hour=8, weekly_dow=4, weekly_hour=17))
    E.db.commit()
    at_8 = datetime(2026, 10, 16, 1, 15)        # 08:15 thứ Sáu giờ VN
    out = asyncio.run(rh.tick(E.db, now=at_8))
    assert out == [{"company_id": E.co.id, "kind": "standup", "created": 3}]     # công ty + 2 phòng
    assert asyncio.run(rh.tick(E.db, now=datetime(2026, 10, 16, 1, 50)))[0]["created"] == 0   # chạy lại: không trùng
    assert asyncio.run(rh.tick(E.db, now=datetime(2026, 10, 16, 5, 0))) == []    # 12:00 — ngoài khung
    late = asyncio.run(rh.tick(E.db, now=datetime(2026, 10, 16, 10, 5)))        # 17:05 thứ Sáu → báo cáo tuần
    assert late == [{"company_id": E.co.id, "kind": "weekly", "created": 3}]
    company = E.db.query(RhythmReport).filter(RhythmReport.scope_key == f"c{E.co.id}", RhythmReport.kind == "standup").one()
    assert company.period_key == "2026-10-16" and company.title == "Giao ban sáng 16/10 — Nova Shop"
    assert E.db.query(InboxItem).filter(InboxItem.item_type == "weekly_report").count() >= 3


def test_config_validation_and_permissions(E):
    assert E.c.put("/api/team/rhythm/config", json={"company_id": E.co.id, "standup_hour": 25}, headers=E.tok("manager")).status_code == 422
    r = E.c.put("/api/team/rhythm/config", json={"company_id": E.co.id, "timezone": "Mars/Base"}, headers=E.tok("manager"))
    assert r.status_code == 422 and "IANA" in r.json()["detail"]
    assert E.c.put("/api/team/rhythm/config", json={"company_id": E.co.id}, headers=E.tok("member")).status_code == 403
    r = E.c.post("/api/team/rhythm/run", json={"company_id": E.co.id, "kind": "standup", "department_id": 99999}, headers=E.tok("manager"))
    assert r.status_code == 422 and "không thuộc công ty" in r.json()["detail"]
    assert E.c.get(f"/api/team/rhythm?company_id={E.co.id}", headers=E.tok("member")).json()["config"]["enabled"] is False
