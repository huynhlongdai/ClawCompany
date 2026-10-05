"""WP-4.3 — bàn giao gọi được agent: kiểm hành vi.

Database thật (SQLite in-memory, model ORM thật); runtime giả để ghi lại **prompt
gửi đi**, vì đó chính là thứ cần kiểm: người nhận bàn giao có nhận được hướng dẫn
bàn giao trong gói ngữ cảnh hay không.

Phần chạm gateway thật nằm ở `tools/probe_handoff.py`.
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.models.entities import (Agent, Company, Department, Member, Organization,
                                 Project, Task)
from app.models.v10 import Artifact, ArtifactHandoff
from app.models.v37 import TaskJournalEntry
from app.services import handoff_dispatch as hd
from app.services import work_context as wc


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def world(db):
    org = Organization(name="Nova", slug="nova-wp43")
    db.add(org); db.commit(); db.refresh(org)
    company = Company(organization_id=org.id, name="Nova Fashion", status="active")
    db.add(company); db.commit(); db.refresh(company)
    dept = Department(company_id=company.id, name="Marketing", status="active")
    db.add(dept); db.commit(); db.refresh(dept)

    boss = Member(organization_id=org.id, company_id=company.id, name="Long",
                  member_type="human", role="Founder", status="active")
    db.add(boss); db.commit(); db.refresh(boss)

    def member(name, role, *, kind="agent", runtime_id=None, lifecycle="active"):
        row = Member(organization_id=org.id, company_id=company.id,
                     department_id=dept.id, manager_id=boss.id, name=name,
                     member_type=kind, role=role, status="active")
        db.add(row); db.commit(); db.refresh(row)
        if kind == "agent":
            db.add(Agent(member_id=row.id, runtime_provider="openclaw",
                         runtime_agent_id=runtime_id or "", lifecycle=lifecycle,
                         model="cometapi/gpt-4o-mini"))
            db.commit()
        return row

    nina = member("Nina", "AI Chief of Staff", runtime_id="dev")
    mia = member("Mia", "Content Lead", runtime_id="mia")
    human = member("Sophia", "CMO", kind="human")
    seatless = member("Kai", "Designer", runtime_id="")

    project = Project(company_id=company.id, name="Summer Dress Campaign",
                      description="Tăng doanh thu váy hè 30%", status="active",
                      progress=68)
    db.add(project); db.commit(); db.refresh(project)
    task = Task(project_id=project.id, title="Create 20 TikTok hooks",
                description="Viết 20 hook.", assignee_member_id=nina.id,
                status="backlog", priority="high")
    db.add(task); db.commit(); db.refresh(task)
    artifact = Artifact(organization_id=org.id, company_id=company.id,
                        task_id=task.id, name="hooks.md", logical_path="content/hooks.md",
                        version=1, artifact_type="document", bundle_key="hooks")
    db.add(artifact); db.commit(); db.refresh(artifact)

    return {"org": org, "company": company, "boss": boss, "nina": nina, "mia": mia,
            "human": human, "seatless": seatless, "project": project, "task": task,
            "artifact": artifact}


class FakeRuntime:
    """Ghi lại prompt gửi đi — đó là thứ cần kiểm ở gói này."""

    def __init__(self):
        self.calls: list[dict] = []

    async def run_agent(self, runtime_agent_id, input_text, metadata=None,
                        session_key=None):
        self.calls.append({"agent": runtime_agent_id, "prompt": input_text,
                           "session_key": session_key, "metadata": metadata or {}})
        from app.runtime.base import RuntimeRun
        return RuntimeRun(task_id="t", run_id=f"run-{len(self.calls)}",
                          session_key=session_key or "", status="running", raw={})


@pytest.fixture()
def runtime(monkeypatch):
    fake = FakeRuntime()
    monkeypatch.setattr("app.services.agent_dispatch.get_runtime", lambda: fake)
    return fake


def make_handoff(db, world, *, to_member, instructions="Kiểm tông thương hiệu trước khi đăng",
                 purpose="review", task_id=...):
    handoff = ArtifactHandoff(
        organization_id=world["org"].id, artifact_id=world["artifact"].id,
        from_member_id=world["nina"].id, to_member_id=to_member.id,
        task_id=world["task"].id if task_id is ... else task_id,
        purpose=purpose, instructions=instructions, status="pending")
    db.add(handoff); db.commit(); db.refresh(handoff)
    return handoff


# ============================================== ghi sổ luôn xảy ra

def test_handoff_is_written_to_the_task_journal(db, world, runtime):
    handoff = make_handoff(db, world, to_member=world["mia"])
    out = asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=True))

    assert out["journal"]["recorded"] is True
    entry = db.query(TaskJournalEntry).filter(
        TaskJournalEntry.kind == "handoff").one()
    assert "Nina bàn giao cho Mia" in entry.summary
    assert "Kiểm tông thương hiệu" in entry.summary
    # Chi tiết đầy đủ ở detail, không nhồi vào summary.
    assert "handoff_id:" in entry.detail
    assert "content/hooks.md" in entry.detail


def test_journal_is_written_even_when_dispatch_is_off(db, world, runtime):
    """Lịch sử công việc không phụ thuộc vào việc có tiêu tiền hay không."""
    handoff = make_handoff(db, world, to_member=world["mia"])
    out = asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=False))

    assert out["dispatched"] is False
    assert out["reason"] == hd.SKIP_DISABLED
    assert out["journal"]["recorded"] is True
    assert db.query(TaskJournalEntry).count() == 1
    assert runtime.calls == [], "tắt dispatch thì không được gọi model"


def test_journal_is_written_for_a_human_target_too(db, world, runtime):
    handoff = make_handoff(db, world, to_member=world["human"])
    out = asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=True))

    assert out["reason"] == hd.SKIP_TARGET_IS_HUMAN
    assert out["journal"]["recorded"] is True
    assert "không tự làm việc thay người" in out["note"]
    assert runtime.calls == []


def test_handoff_without_a_task_says_so_instead_of_guessing(db, world, runtime):
    handoff = make_handoff(db, world, to_member=world["mia"], task_id=None)
    out = asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=True))

    assert out["reason"] == hd.SKIP_NO_TASK
    assert out["journal"]["recorded"] is False
    assert runtime.calls == []


def test_target_agent_without_an_active_seat_is_refused_with_a_reason(db, world, runtime):
    handoff = make_handoff(db, world, to_member=world["seatless"])
    out = asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=True))

    assert out["reason"] == hd.SKIP_NO_SEAT
    assert "runtime_agent_id" in out["note"]
    # Sổ ghi vẫn có: bàn giao đã xảy ra, chỉ là không chạy được.
    assert out["journal"]["recorded"] is True
    assert runtime.calls == []


def test_detached_seat_is_treated_as_no_seat(db, world, runtime):
    """Seat `detached` không phải seat đang hoạt động — lỗi đã gặp ở ask_nina."""
    agent = db.query(Agent).filter(Agent.member_id == world["mia"].id).one()
    agent.lifecycle = "detached"
    db.add(agent); db.commit()

    handoff = make_handoff(db, world, to_member=world["mia"])
    out = asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=True))
    assert out["reason"] == hd.SKIP_NO_SEAT
    assert runtime.calls == []


# ======================================= chủ việc phải chuyển sang người nhận

def test_task_is_reassigned_to_the_receiver_before_dispatch(db, world, runtime):
    """Chốt quan trọng nhất của gói này.

    Khối 1 của gói ngữ cảnh mở đầu bằng "Bạn là <người được giao>". Nếu task vẫn
    thuộc Nina mà lượt chạy gửi tới seat của Mia thì Mia nhận hồ sơ của người
    khác — đúng lỗi đã đo được trong `_reports/work-memory-gap.md`, nơi agent
    trả lời sai câu "ai là quản lý của tôi".
    """
    assert world["task"].assignee_member_id == world["nina"].id

    handoff = make_handoff(db, world, to_member=world["mia"])
    out = asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=True))

    assert out["reassign"]["reassigned"] is True
    assert out["reassign"]["from_member_id"] == world["nina"].id
    assert out["reassign"]["to_member_id"] == world["mia"].id

    db.refresh(world["task"])
    assert world["task"].assignee_member_id == world["mia"].id
    # Và lượt chạy đi tới seat của Mia, không phải của Nina.
    assert runtime.calls[0]["agent"] == "mia"


def test_reassigning_to_the_current_owner_is_a_no_op(db, world, runtime):
    world["task"].assignee_member_id = world["mia"].id
    db.add(world["task"]); db.commit()

    handoff = make_handoff(db, world, to_member=world["mia"])
    out = asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=True))
    assert out["reassign"]["reassigned"] is False
    assert out["reassign"]["reason"] == "already_owner"


# ===================================== hướng dẫn bàn giao tới được agent

def test_the_receiver_prompt_carries_the_handoff_instructions(db, world, runtime):
    """Đây là mệnh đề cần chứng minh của WP-4.3."""
    handoff = make_handoff(db, world, to_member=world["mia"],
                           instructions="Đừng dùng nhạc có bản quyền; ưu tiên 3 hook đầu")
    asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=True))

    prompt = runtime.calls[0]["prompt"]
    # Khối 5: ai bàn giao và nói gì
    assert "Nina bàn giao" in prompt
    assert "Đừng dùng nhạc có bản quyền" in prompt
    # Khối 1: danh tính đúng của người NHẬN
    assert "Bạn là **Mia**" in prompt
    assert "Content Lead" in prompt
    # Khối 4: chính lần bàn giao này đã vào sổ và được đọc lại
    assert "handoff" in prompt


def test_two_handoffs_in_a_row_both_appear_in_the_journal(db, world, runtime):
    """Việc đi qua ba người thì sổ phải kể được cả ba chặng."""
    first = make_handoff(db, world, to_member=world["mia"],
                         instructions="Viết bản nháp")
    asyncio.run(hd.dispatch_on_handoff(db, first, dispatch=True))

    second = ArtifactHandoff(
        organization_id=world["org"].id, artifact_id=world["artifact"].id,
        from_member_id=world["mia"].id, to_member_id=world["nina"].id,
        task_id=world["task"].id, purpose="review",
        instructions="Nháp xong, soát lại giúp", status="pending")
    db.add(second); db.commit(); db.refresh(second)
    asyncio.run(hd.dispatch_on_handoff(db, second, dispatch=True))

    entries = db.query(TaskJournalEntry).order_by(TaskJournalEntry.seq).all()
    handoffs = [e for e in entries if e.kind == "handoff"]
    assert len(handoffs) == 2
    assert "Nina bàn giao cho Mia" in handoffs[0].summary
    assert "Mia bàn giao cho Nina" in handoffs[1].summary

    # Và lượt chạy thứ hai đọc được cả hai chặng.
    prompt = runtime.calls[-1]["prompt"]
    assert "Viết bản nháp" in prompt and "soát lại giúp" in prompt


# ============================================ trạng thái và dấu vết

def test_agent_handoff_is_auto_accepted_through_v10(db, world, runtime):
    """Nhân viên AI không bấm nút, nhưng trạng thái vẫn đi đúng đường.

    Gọi `accept_handoff` của v10 thay vì tự đặt status, để không sinh định nghĩa
    thứ hai của "đã nhận".
    """
    handoff = make_handoff(db, world, to_member=world["mia"])
    out = asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=True))

    assert out["accepted"] is True
    db.refresh(handoff)
    assert handoff.status == "accepted"
    assert handoff.accepted_at is not None


def test_dispatch_records_the_run_on_the_task(db, world, runtime):
    handoff = make_handoff(db, world, to_member=world["mia"])
    out = asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=True))

    assert out["dispatched"] is True and out["reason"] == "ok"
    db.refresh(world["task"])
    assert world["task"].runtime_run_id == "run-1"
    assert world["task"].status == "in_progress"
    assert out["runtime_session_key"].startswith("agent:mia:company-task-")


def test_explicit_flag_beats_the_config_default(db, world, runtime, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "openclaw_auto_dispatch", False)

    handoff = make_handoff(db, world, to_member=world["mia"])
    # dispatch=None -> theo cấu hình (tắt)
    out = asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=None))
    assert out["reason"] == hd.SKIP_DISABLED

    # caller nói rõ -> thắng cấu hình
    out = asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=True))
    assert out["dispatched"] is True


def test_config_default_on_means_no_flag_needed(db, world, runtime, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "openclaw_auto_dispatch", True)
    handoff = make_handoff(db, world, to_member=world["mia"])
    out = asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=None))
    assert out["dispatched"] is True


def test_every_outcome_carries_a_reason(db, world, runtime):
    """Không có nhánh nào trả về im lặng — người đọc log không phải suy ra."""
    cases = [
        (world["mia"], True),
        (world["mia"], False),
        (world["human"], True),
        (world["seatless"], True),
    ]
    for target, flag in cases:
        handoff = make_handoff(db, world, to_member=target)
        out = asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=flag))
        assert out["reason"], f"thiếu reason cho {target.name}/{flag}"
        assert "journal" in out


def test_dispatch_failure_does_not_lose_the_handoff(db, world, monkeypatch):
    """Không chạy được thì bàn giao vẫn còn, và nói rõ người thật làm gì tiếp."""
    class Broken:
        async def run_agent(self, *a, **kw):
            raise RuntimeError("gateway sập")

    monkeypatch.setattr("app.services.agent_dispatch.get_runtime", lambda: Broken())
    handoff = make_handoff(db, world, to_member=world["mia"])

    with pytest.raises(RuntimeError):
        asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=True))

    # Sổ ghi đã có trước khi gọi runtime, nên lịch sử không mất.
    assert db.query(TaskJournalEntry).filter(
        TaskJournalEntry.kind == "handoff").count() == 1


def test_handoff_block_appears_even_without_dispatch(db, world, runtime):
    """Người thật dispatch tay sau đó vẫn thấy hướng dẫn bàn giao."""
    handoff = make_handoff(db, world, to_member=world["mia"],
                           instructions="Ưu tiên ba hook đầu")
    asyncio.run(hd.dispatch_on_handoff(db, handoff, dispatch=False))

    db.refresh(world["task"])
    pack = wc.build_pack(db, world["task"], organization_id=world["org"].id)
    assert "Ưu tiên ba hook đầu" in pack["text"]
