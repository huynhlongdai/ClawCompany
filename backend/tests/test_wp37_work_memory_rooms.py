"""v37 — bộ nhớ công việc và phòng họp có chủ toạ: kiểm hành vi.

Database thật (SQLite in-memory, model ORM thật) cho mọi thứ liên quan tới tenant
và ràng buộc; fake runtime cho phần gọi model, vì cái cần kiểm ở đó là **prompt
gửi đi** và **cách xử lý trả lời**, không phải chất lượng model.

Phần chạm gateway thật (hai agent nói trong một phòng, chủ toạ chốt) nằm ở
`tools/probe_room.py`.
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
import app.models  # noqa: F401
from app.models.entities import (Agent, Company, Department, Member, Organization,
                                 Project, Task)
from app.models.v10 import ArtifactHandoff
from app.models.v16 import CollaborationRoom, RoomTurn
from app.models.v37 import RoomConductorRun, TaskJournalEntry
from app.services import collaboration_rooms as rooms
from app.services import room_conductor as rc
from app.services import task_journal as journal
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
    """Một công ty nhỏ: hai agent, một người, một dự án, một task."""
    org = Organization(name="Nova", slug="nova-v37")
    db.add(org); db.commit(); db.refresh(org)
    company = Company(organization_id=org.id, name="Nova Fashion", status="active")
    db.add(company); db.commit(); db.refresh(company)
    dept = Department(company_id=company.id, name="Marketing", status="active")
    db.add(dept); db.commit(); db.refresh(dept)

    boss = Member(organization_id=org.id, company_id=company.id, name="Long",
                  member_type="human", role="Founder", status="active")
    db.add(boss); db.commit(); db.refresh(boss)

    def seat(name, role, runtime_id, *, decide=False):
        member = Member(organization_id=org.id, company_id=company.id,
                        department_id=dept.id, manager_id=boss.id, name=name,
                        member_type="agent", role=role, status="active")
        db.add(member); db.commit(); db.refresh(member)
        agent = Agent(member_id=member.id, runtime_provider="openclaw",
                      runtime_agent_id=runtime_id, lifecycle="active",
                      model="cometapi/gpt-4o-mini")
        db.add(agent); db.commit(); db.refresh(agent)
        return member

    nina = seat("Nina", "AI Chief of Staff", "dev")
    mia = seat("Mia", "Content Lead", "mia")

    project = Project(company_id=company.id, name="Summer Dress Campaign",
                      description="Tăng doanh thu váy hè 30% trong quý 3",
                      status="active", progress=68)
    db.add(project); db.commit(); db.refresh(project)
    task = Task(project_id=project.id, title="Create 20 TikTok hooks",
                description="Viết 20 hook dựa trên nghiên cứu trend.",
                assignee_member_id=mia.id, status="backlog", priority="high")
    db.add(task); db.commit(); db.refresh(task)
    return {"org": org, "company": company, "dept": dept, "boss": boss,
            "nina": nina, "mia": mia, "project": project, "task": task}


# ============================================================ gói ngữ cảnh

def test_pack_carries_the_facts_the_old_brief_dropped(db, world):
    """Đo được: brief cũ bỏ 10/12 dữ kiện. Gói mới phải mang chúng."""
    pack = wc.build_pack(db, world["task"], organization_id=world["org"].id)
    text = pack["text"]

    assert "Mia" in text and "Content Lead" in text      # người và vai
    assert "Marketing" in text                            # phòng ban
    assert "Long" in text                                 # quản lý trực tiếp
    assert "Summer Dress Campaign" in text                # dự án
    assert "váy hè 30%" in text                           # mục tiêu dự án
    assert "68%" in text                                  # tiến độ
    assert "Nova Fashion" in text                         # công ty
    assert "high" in text                                 # mức ưu tiên


def test_pack_is_much_longer_than_the_old_brief_but_stays_in_budget(db, world):
    from app.services import openclaw_alignment as align
    old = align.task_brief(db, world["task"])
    pack = wc.build_pack(db, world["task"], organization_id=world["org"].id)
    assert pack["chars"] > len(old) * 2
    assert pack["over_budget"] is False


def test_seven_blocks_always_present_even_when_data_is_missing(db, world):
    """Khối trống phải nói 'không có', không được biến mất im lặng."""
    task = Task(project_id=world["project"].id, title="Task trơ trọi",
                description="", status="backlog", priority="low")
    db.add(task); db.commit(); db.refresh(task)

    pack = wc.build_pack(db, task, organization_id=world["org"].id)
    assert len(pack["blocks"]) == 7
    assert "Chưa có lượt nào trước" in pack["text"]
    assert "Không có bàn giao nào" in pack["text"]
    # Task không mô tả thì nói thẳng, và dặn hỏi lại thay vì đoán.
    assert "hỏi lại thay vì đoán" in pack["text"]


def test_deadline_shows_days_left_not_just_a_date(db, world):
    from datetime import timedelta
    from app.services.v36_insights import local_today
    world["project"].due_date = local_today() + timedelta(days=14)
    db.add(world["project"]); db.commit()

    pack = wc.build_pack(db, world["task"], organization_id=world["org"].id)
    assert "còn 14 ngày" in pack["text"]


def test_overdue_project_is_stated_loudly(db, world):
    from datetime import timedelta
    from app.services.v36_insights import local_today
    world["project"].due_date = local_today() - timedelta(days=3)
    db.add(world["project"]); db.commit()

    pack = wc.build_pack(db, world["task"], organization_id=world["org"].id)
    assert "QUÁ HẠN 3 ngày" in pack["text"]


def test_journal_entries_appear_in_block_four(db, world):
    journal.append(db, world["task"], kind="attempt", actor_member_id=world["mia"].id,
                   summary="Đã chọn 5 hướng", outcome="partial")
    journal.append(db, world["task"], kind="review", actor_member_id=world["boss"].id,
                   summary="3/5 lệch tông thương hiệu", outcome="rejected")

    pack = wc.build_pack(db, world["task"], organization_id=world["org"].id)
    assert "Đã chọn 5 hướng" in pack["text"]
    assert "lệch tông thương hiệu" in pack["text"]
    assert "rejected" in pack["text"]


def test_long_journal_is_compressed_not_dropped(db, world):
    """Task chạy 30 lần vẫn phải vừa ngân sách, và phải nói rõ đã lược."""
    for i in range(30):
        journal.append(db, world["task"], kind="attempt",
                       actor_member_id=world["mia"].id,
                       summary=f"Lần thử {i}: " + "x" * 120)

    pack = wc.build_pack(db, world["task"], organization_id=world["org"].id)
    block4 = next(b for b in pack["blocks"] if b["index"] == 4)
    assert block4["original_count"] == 30
    assert block4["trimmed"] is True
    assert "Sổ ghi có 30 mục" in pack["text"]
    assert pack["chars"] <= pack["budget_chars"]


def test_trim_never_touches_the_task_or_the_rules(db, world):
    """Chốt thiết kế: thiếu bối cảnh thì làm kém, thiếu luật thì làm SAI."""
    for i in range(40):
        journal.append(db, world["task"], kind="note",
                       actor_member_id=world["mia"].id,
                       summary=f"Ghi chú rất dài số {i} " + "y" * 200)

    pack = wc.build_pack(db, world["task"], organization_id=world["org"].id,
                         budget_chars=1_500)
    # Khối 2 và 6 và 7 còn nguyên
    assert "Create 20 TikTok hooks" in pack["text"]
    assert "Thoả thuận làm việc" in pack["text"]
    assert "Không công bố ra ngoài" in pack["text"]
    trimmed_indexes = {b["index"] for b in pack["blocks"] if b["trimmed"]}
    assert not (trimmed_indexes & set(wc.NEVER_TRIM))


def test_handoff_instructions_reach_the_agent(db, world):
    """Bàn giao mà không mang theo hướng dẫn thì không phải bàn giao."""
    db.add(ArtifactHandoff(organization_id=world["org"].id, artifact_id=1,
                           from_member_id=world["nina"].id, to_member_id=world["mia"].id,
                           task_id=world["task"].id, purpose="review",
                           instructions="Kiểm tông thương hiệu trước khi đăng"))
    db.commit()
    pack = wc.build_pack(db, world["task"], organization_id=world["org"].id)
    assert "Nina bàn giao" in pack["text"]
    assert "Kiểm tông thương hiệu" in pack["text"]


# ============================================================== sổ ghi task

def test_journal_allocates_sequential_numbers(db, world):
    first = journal.append(db, world["task"], kind="note", summary="một")
    second = journal.append(db, world["task"], kind="note", summary="hai")
    assert (first.seq, second.seq) == (1, 2)


def test_journal_rejects_unknown_kind_and_outcome(db, world):
    with pytest.raises(journal.JournalError):
        journal.append(db, world["task"], kind="bịa", summary="x")
    with pytest.raises(journal.JournalError):
        journal.append(db, world["task"], kind="note", summary="x", outcome="bịa")


def test_journal_rejects_empty_summary(db, world):
    """Một mục sổ ghi không nói được câu nào thì vô dụng hơn là không có."""
    with pytest.raises(journal.JournalError):
        journal.append(db, world["task"], kind="note", summary="   ")


def test_long_summary_moves_to_detail_instead_of_being_lost(db, world):
    entry = journal.append(db, world["task"], kind="note", summary="z" * 900)
    assert len(entry.summary) <= journal.SUMMARY_MAX
    assert entry.summary.endswith("…")
    assert len(entry.detail) == 900, "phần đầy đủ phải còn trong detail"


def test_digest_reports_null_success_rate_when_nothing_measurable(db, world):
    """Chưa đo được khác với 0% — cùng lý lẽ với success_rate của v36."""
    journal.append(db, world["task"], kind="note", summary="chưa có kết quả")
    out = journal.digest(db, world["task"].id)
    assert out["entries"] == 1
    assert out["measurable_outcomes"] == 0
    assert out["success_rate"] is None


def test_digest_computes_rate_only_over_measured_entries(db, world):
    journal.append(db, world["task"], kind="attempt", summary="a", outcome="success")
    journal.append(db, world["task"], kind="attempt", summary="b", outcome="failed")
    journal.append(db, world["task"], kind="note", summary="c")   # không đo được
    out = journal.digest(db, world["task"].id)
    assert out["measurable_outcomes"] == 2
    assert out["success_rate"] == 50.0


def test_journal_refuses_a_task_with_no_tenant_path(db, world):
    """tasks không có organization_id; đường đi là project → company."""
    orphan = Task(project_id=99999, title="Không có dự án", status="backlog",
                  priority="low")
    db.add(orphan); db.commit(); db.refresh(orphan)
    with pytest.raises(journal.JournalError) as exc:
        journal.append(db, orphan, kind="note", summary="x")
    assert "không xác định được tenant" in str(exc.value)


# ======================================================= phòng họp: chuẩn bị

def _room(db, world, *, mode="round_robin", chair=None, budget=1.0,
          created_by=None):
    """Mở một phòng.

    ``created_by=None`` có chủ ý. Phát hiện khi chạy test: ``open_room`` với
    ``created_by_member_id`` **tự thêm người tạo** làm ``lead`` có
    ``can_decide=True`` ở ``seat_order=1``. Nghĩa là một phòng do NGƯỜI mở thì
    người đó nằm trong vòng round-robin, và bộ điều phối sẽ dừng chờ họ nói —
    hành vi đúng, nhưng nó làm mọi test khác đo sai thứ mình định đo. Trường hợp
    đó có test riêng bên dưới.
    """
    room = rooms.open_room(db, organization_id=world["org"].id,
                           company_id=world["company"].id,
                           project_id=world["project"].id,
                           room_key="launch-review", topic="Chốt 5 hook cuối",
                           objective="Chọn 5 hook để chạy tuần này",
                           mode=mode, created_by_member_id=created_by)
    room.cost_budget_usd = budget
    if chair:
        room.chair_member_id = chair.id
    db.add(room); db.commit(); db.refresh(room)
    return room


class FakeRuntime:
    """Runtime giả: ghi lại prompt, trả lời theo kịch bản."""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.prompts: list[tuple[str, str]] = []   # (agent_id, prompt)
        self.history_by_session: dict[str, list[dict]] = {}
        self.pending: dict[str, str] = {}

    async def run_agent(self, runtime_agent_id, input_text, metadata=None,
                        session_key=None):
        self.prompts.append((runtime_agent_id, input_text))
        # Câu trả lời của lượt này chỉ xuất hiện trong lịch sử ở lần poll SAU,
        # giống gateway thật.
        self.pending[session_key or ""] = (
            self.replies.pop(0) if self.replies else "(im lặng)")
        from app.runtime.base import RuntimeRun
        return RuntimeRun(task_id="t", run_id=f"run-{len(self.prompts)}",
                          session_key=session_key or "", status="running", raw={})

    async def history(self, session_key, limit=50):
        """Lịch sử **tích luỹ** như một session thật của phòng họp.

        Bản đầu của fake này trả về đúng một message mỗi lần, nên nó không thể
        tái hiện lỗi "đọc lại câu cũ" mà lần chạy thật phát hiện. Nay nó giữ
        lịch sử theo session, kèm id — đúng hình dạng mà bộ điều phối phải xử lý.
        """
        log = self.history_by_session.setdefault(session_key, [])
        pending = self.pending.pop(session_key, None)
        if pending is not None:
            log.append({"id": f"m{len(log)}-{session_key}", "role": "assistant",
                        "text": pending})
        return {"messages": list(log)}


def test_conductor_refuses_a_room_without_a_cost_ceiling(db, world):
    """Phòng toàn agent không có trần tiền là một hoá đơn mở."""
    room = _room(db, world, budget=0.0)
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True)
    with pytest.raises(rc.ConductorError) as exc:
        asyncio.run(rc.conduct(db, room, FakeRuntime()))
    assert "cost_budget_usd" in str(exc.value)


def test_conductor_refuses_a_room_with_only_humans(db, world):
    """Bộ điều phối không nói hộ người thật.

    Dùng mode ``lead_routed``: ở đó v16 kiểm theo vai chứ không theo vị trí, nên
    bộ điều phối tự chọn người nói và phát hiện ra không có agent nào. Ở
    ``round_robin`` thì lý do dừng là ``waiting_for_human`` (tới lượt một người
    cụ thể) — hai tình huống khác nhau và có hai lý do dừng khác nhau.
    """
    room = _room(db, world, mode="lead_routed")
    rooms.join_room(db, room, member_id=world["boss"].id, participant_role="lead",
                    can_decide=True)
    out = asyncio.run(rc.conduct(db, room, FakeRuntime()))
    assert out["stopped_reason"] == rc.STOP_NO_SPEAKER
    assert "không nói hộ được" in out["turns"][0]["error"]


# ===================================================== phòng họp: vòng lặp

def test_human_in_a_round_robin_rotation_stops_the_conductor(db, world):
    """Phát hiện khi chạy test, và đây là hành vi ĐÚNG.

    ``open_room(created_by_member_id=<người>)`` tự thêm người đó vào phòng với
    vai ``lead`` và ``can_decide=True``. Ở phòng ``round_robin``, tới lượt họ
    thì bộ điều phối **phải dừng và chờ**, không được nhảy qua: nhảy lượt trong
    một phòng có thứ tự là âm thầm đổi luật cuộc họp.
    """
    room = _room(db, world, created_by=world["boss"].id, chair=world["boss"])
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="contributor",
                    seat_order=0)

    roster = rooms.room_roster(db, room)
    assert [p.member_id for p in roster] == [world["nina"].id, world["boss"].id], \
        "người mở phòng được tự thêm vào seat_order=1"

    runtime = FakeRuntime(["Nina nói trước.", "không tới lượt này"])
    out = asyncio.run(rc.conduct(db, room, runtime, max_turns=3))

    assert out["ran"] == 2, "lượt 1 của Nina, lượt 2 dừng vì tới lượt người thật"
    assert out["stopped_reason"] == rc.STOP_WAITING_HUMAN
    assert "Long" in out["turns"][1]["error"]
    # Phòng vẫn mở: người thật vào nói rồi gọi lại là tiếp tục được.
    assert out["room_status"] == "open"
    assert db.query(RoomTurn).count() == 1


def test_turn_prompt_carries_objective_roster_and_transcript(db, world):
    room = _room(db, world, chair=world["nina"])
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)
    rooms.join_room(db, room, member_id=world["mia"].id, participant_role="contributor",
                    seat_order=1)
    rooms.post_turn(db, room, member_id=world["nina"].id,
                    content="Tôi đề xuất chọn theo lượt xem", turn_type="proposal")

    speaker, blocker = rc.next_speaker(db, room)
    assert blocker == ""
    prompt = rc.build_turn_prompt(db, room, speaker, chair=rc.chair_of(db, room))

    assert "Chọn 5 hook để chạy tuần này" in prompt        # mục tiêu
    assert "Nina" in prompt and "Mia" in prompt            # ai trong phòng
    assert "chủ toạ" in prompt                             # ai giữ búa
    assert "lượt xem" in prompt                            # biên bản
    assert "Summer Dress Campaign" in prompt               # gói ngữ cảnh công việc
    assert "một lượt duy nhất" in prompt                   # nhiệm vụ của lượt


def test_non_chair_is_told_it_cannot_decide(db, world):
    room = _room(db, world, chair=world["nina"])
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)
    rooms.join_room(db, room, member_id=world["mia"].id, participant_role="contributor",
                    seat_order=1)
    mia_participant = next(p for p in rooms.room_roster(db, room)
                           if p.member_id == world["mia"].id)
    prompt = rc.build_turn_prompt(db, room, mia_participant, chair=rc.chair_of(db, room))
    assert "không** có quyền chốt" in prompt
    assert "Nina" in prompt


def test_conduct_writes_real_turns_and_advances_the_cursor(db, world):
    room = _room(db, world, chair=world["nina"])
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)
    rooms.join_room(db, room, member_id=world["mia"].id, participant_role="contributor",
                    seat_order=1)

    runtime = FakeRuntime(["Tôi đề xuất hook A và B.", "Bổ sung: hook C hợp trend."])
    out = asyncio.run(rc.conduct(db, room, runtime, max_turns=2, cost_per_turn_usd=0.01))

    assert out["ran"] == 2
    turns = db.query(RoomTurn).order_by(RoomTurn.sequence).all()
    assert [t.sequence for t in turns] == [1, 2]
    assert turns[0].content.startswith("Tôi đề xuất")
    db.refresh(room)
    assert room.turn_cursor == 2
    assert room.cost_spent_usd == pytest.approx(0.02)


def test_each_speaker_gets_its_own_room_session(db, world):
    """Biên bản họp không được làm bẩn phiên chính của agent."""
    room = _room(db, world, chair=world["nina"])
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)
    rooms.join_room(db, room, member_id=world["mia"].id, participant_role="contributor",
                    seat_order=1)
    runtime = FakeRuntime(["a", "b"])
    asyncio.run(rc.conduct(db, room, runtime, max_turns=2))

    runs = db.query(RoomConductorRun).order_by(RoomConductorRun.id).all()
    keys = {r.runtime_session_key for r in runs}
    assert keys == {"agent:dev:room-launch-review", "agent:mia:room-launch-review"}
    assert all(":main" not in k for k in keys)


def test_round_robin_alternates_speakers(db, world):
    room = _room(db, world, mode="round_robin", chair=world["nina"])
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)
    rooms.join_room(db, room, member_id=world["mia"].id, participant_role="contributor",
                    seat_order=1)
    runtime = FakeRuntime(["một", "hai", "ba", "bốn"])
    out = asyncio.run(rc.conduct(db, room, runtime, max_turns=4))
    speakers = [t["speaker"] for t in out["turns"]]
    assert speakers == ["Nina", "Mia", "Nina", "Mia"]


# ================================================ bốn điều kiện dừng

def test_stops_when_the_chair_records_a_decision(db, world):
    room = _room(db, world, chair=world["nina"])
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)
    rooms.join_room(db, room, member_id=world["mia"].id, participant_role="contributor",
                    seat_order=1)
    # Lượt đầu của Nina (chủ toạ) chốt luôn, bằng dấu hiệu tường minh.
    runtime = FakeRuntime(["QUYẾT ĐỊNH: chọn hook A, B, C.\nMia triển khai trước thứ Năm."])
    out = asyncio.run(rc.conduct(db, room, runtime, max_turns=5))

    assert out["ran"] == 1
    assert out["stopped_reason"] == rc.STOP_CHAIR_CLOSED
    assert out["room_status"] == "closed"
    assert db.query(RoomTurn).one().turn_type == "decision"


def test_a_non_chair_saying_decide_does_not_close_the_room(db, world):
    """Chốt ``can_decide`` của v16 phải còn hiệu lực qua bộ điều phối."""
    room = _room(db, world, chair=world["nina"])
    rooms.join_room(db, room, member_id=world["mia"].id, participant_role="contributor",
                    seat_order=0)
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=1)

    runtime = FakeRuntime(["QUYẾT ĐỊNH: chọn hook A.", "QUYẾT ĐỊNH: chọn hook A."])
    out = asyncio.run(rc.conduct(db, room, runtime, max_turns=2))

    turns = db.query(RoomTurn).order_by(RoomTurn.sequence).all()
    assert turns[0].turn_type == "message", \
        "Mia không phải chủ toạ: dấu hiệu QUYẾT ĐỊNH của cô không có hiệu lực"
    assert turns[1].turn_type == "decision"
    assert out["stopped_reason"] == rc.STOP_CHAIR_CLOSED


def test_chair_saying_we_will_decide_later_does_not_close_the_room(db, world):
    """Hồi quy cho lỗi gặp ở lần chạy thật đầu tiên.

    Nina mở đầu cuộc họp bằng "sau khi lắng nghe, chúng ta **sẽ quyết định** và
    giao nhiệm vụ" — một dự định tương lai. Bộ phân loại theo từ khoá đọc thành
    "tôi chốt ngay", phòng đóng sau một lượt và Mia không nói được câu nào.
    Nay chỉ dòng bắt đầu bằng `QUYẾT ĐỊNH:` mới kết thúc cuộc họp.
    """
    room = _room(db, world, chair=world["nina"])
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)
    rooms.join_room(db, room, member_id=world["mia"].id, participant_role="contributor",
                    seat_order=1)

    runtime = FakeRuntime([
        "Chào cả phòng. Sau khi lắng nghe Mia, chúng ta sẽ quyết định và giao việc.",
        "Em đề xuất hook A và B ạ.",
        "QUYẾT ĐỊNH: chọn hook A và B. Mia triển khai trước thứ Năm.",
    ])
    out = asyncio.run(rc.conduct(db, room, runtime, max_turns=4))

    turns = db.query(RoomTurn).order_by(RoomTurn.sequence).all()
    assert turns[0].turn_type != "decision", "dự định tương lai không phải quyết định"
    assert len(turns) == 3, "Mia phải được nói trước khi chủ toạ chốt"
    assert turns[2].turn_type == "decision"
    assert out["stopped_reason"] == rc.STOP_CHAIR_CLOSED


def test_stops_when_the_budget_runs_out(db, world):
    room = _room(db, world, chair=world["nina"], budget=0.02)
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)
    rooms.join_room(db, room, member_id=world["mia"].id, participant_role="contributor",
                    seat_order=1)
    runtime = FakeRuntime(["một", "hai", "ba", "bốn", "năm"])
    out = asyncio.run(rc.conduct(db, room, runtime, max_turns=5, cost_per_turn_usd=0.01))

    assert out["ran"] == 2, "trần 0,02 USD với 0,01 mỗi lượt thì chỉ chạy được 2 lượt"
    assert out["stopped_reason"] == rc.STOP_BUDGET
    # Hết tiền thì phòng vẫn MỞ để người thật vào xem và quyết định tiếp.
    assert out["room_status"] == "open"


def test_stops_when_two_turns_add_nothing_new(db, world):
    """Không có chốt này, hai agent có thể lịch sự đồng ý với nhau mãi mãi."""
    room = _room(db, world, chair=world["nina"])
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)
    rooms.join_room(db, room, member_id=world["mia"].id, participant_role="contributor",
                    seat_order=1)
    same = "Tôi đồng ý với phương án đã nêu, không có gì thêm."
    runtime = FakeRuntime([same, same, same, same, same])
    out = asyncio.run(rc.conduct(db, room, runtime, max_turns=5))

    assert out["stopped_reason"] == rc.STOP_STALLED
    assert out["ran"] < 5


def test_stops_at_max_turns(db, world):
    room = _room(db, world, chair=world["nina"])
    room.max_turns = 2
    db.add(room); db.commit()
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)
    rooms.join_room(db, room, member_id=world["mia"].id, participant_role="contributor",
                    seat_order=1)
    runtime = FakeRuntime(["một", "hai", "ba"])
    out = asyncio.run(rc.conduct(db, room, runtime, max_turns=5))
    assert out["stopped_reason"] == rc.STOP_MAX_TURNS
    assert out["turn_cursor"] == 2


def test_timeout_is_recorded_without_killing_the_session(db, world):
    """Một agent chậm không được treo cả phiên họp."""
    room = _room(db, world, chair=world["nina"])
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)

    class Silent(FakeRuntime):
        async def history(self, session_key, limit=50):
            return {"messages": []}

    original = rc.REPLY_TIMEOUT_SECONDS
    rc.REPLY_TIMEOUT_SECONDS = 0.1
    rc.POLL_SECONDS = 0.05
    try:
        out = asyncio.run(rc.conduct(db, room, Silent(), max_turns=1))
    finally:
        rc.REPLY_TIMEOUT_SECONDS = original
        rc.POLL_SECONDS = 5

    assert out["turns"][0]["status"] == "timeout"
    run = db.query(RoomConductorRun).one()
    assert run.status == "timeout" and run.turn_id is None
    assert db.query(RoomTurn).count() == 0, "không có trả lời thì không ghi biên bản"


def test_conductor_runs_record_operations_separately_from_the_minutes(db, world):
    """Biên bản cho người đọc, vận hành cho người vận hành — hai bảng khác nhau."""
    room = _room(db, world, chair=world["nina"])
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)
    asyncio.run(rc.conduct(db, room, FakeRuntime(["Xin chào cả phòng."]), max_turns=1))

    run = db.query(RoomConductorRun).one()
    assert run.prompt_chars > 500, "prompt phải mang mục tiêu + biên bản + ngữ cảnh"
    assert run.reply_chars > 0
    assert run.runtime_agent_id == "dev"
    turn = db.query(RoomTurn).one()
    # Biên bản KHÔNG chứa dữ liệu kỹ thuật
    assert "prompt_chars" not in turn.content


def test_room_is_tenant_scoped_through_its_organization(db, world):
    other = Organization(name="Rival", slug="rival-v37")
    db.add(other); db.commit(); db.refresh(other)
    room = _room(db, world, chair=world["nina"])
    assert room.organization_id == world["org"].id != other.id


def test_alternating_repetition_is_detected_as_a_stall(db, world):
    """Hồi quy cho lỗi mà chỉ lần chạy thật phát hiện được.

    Trong cuộc họp thật (`_reports/room-conductor-e2e.md`), Nina lặp lại nguyên
    văn ở lượt 1 và 3, Mia ở lượt 2 và 4 — nhưng `stall_count` vẫn bằng 0, vì
    bản đầu của chốt chỉ so lượt mới với lượt **liền trước** của phòng. Vòng lặp
    luân phiên có hình A B A B, nên hai lượt liền nhau luôn khác nhau và chốt đó
    không bao giờ bắt được.

    Nay so thêm với lượt gần nhất của **chính người nói**.
    """
    room = _room(db, world, chair=world["nina"])
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)
    rooms.join_room(db, room, member_id=world["mia"].id, participant_role="contributor",
                    seat_order=1)

    nina_says = "Mia, bạn cho tôi thêm thông tin về hai trend còn lại nhé."
    mia_says = "Em đã nghiên cứu xong hai trend và sẽ trình bày lý do chọn."
    runtime = FakeRuntime([nina_says, mia_says, nina_says, mia_says, nina_says])
    out = asyncio.run(rc.conduct(db, room, runtime, max_turns=5))

    assert out["stopped_reason"] == rc.STOP_STALLED
    assert out["ran"] < 5, "phải dừng trước khi tiêu hết lượt"


def test_running_out_of_call_turns_is_not_reported_as_a_room_stop(db, world):
    """Hết lượt của lời gọi khác với phòng đã dừng.

    Trước khi sửa, trường hợp này trả `stopped_reason: ""` và báo cáo in ra
    "dừng vì ****". Rỗng không phải một lý do.
    """
    room = _room(db, world, chair=world["nina"])
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)
    rooms.join_room(db, room, member_id=world["mia"].id, participant_role="contributor",
                    seat_order=1)
    runtime = FakeRuntime(["một điều mới", "hai điều khác", "ba điều nữa"])
    out = asyncio.run(rc.conduct(db, room, runtime, max_turns=2))

    assert out["stopped_reason"] == rc.STOP_CALL_LIMIT
    assert out["room_status"] == "open"
    assert "gọi lại để họp tiếp" in out["note"]
    db.refresh(room)
    assert room.stopped_reason == "", "phòng chưa dừng thì đừng ghi lý do dừng vào phòng"


def test_a_stale_reply_in_a_long_session_is_not_read_as_a_new_turn(db, world):
    """Hồi quy cho lỗi GỐC của hiện tượng agent lặp lại nguyên văn.

    Phòng họp dùng một session dài cho cả cuộc họp, nên từ lượt hai trở đi
    session đã có câu trả lời cũ. Bản đầu của `_ask` đọc "message trợ lý cuối
    cùng" nên khi model chưa kịp trả lời, nó đọc lại câu cũ và tưởng là câu mới.

    Đo được trên bản chạy thật: lượt 1 mất 10,09s, lượt 3 chỉ 5,06s và trả về
    đúng từng ký tự câu của lượt 1.

    Fake ở đây mô phỏng một model **chậm**: câu trả lời chỉ vào lịch sử sau hai
    nhịp poll. Nếu `_ask` chấp nhận message cũ, nó sẽ trả về "câu cũ".
    """
    room = _room(db, world, chair=world["nina"])
    rooms.join_room(db, room, member_id=world["nina"].id, participant_role="lead",
                    can_decide=True, seat_order=0)

    class SlowRuntime(FakeRuntime):
        """Trả lời chỉ xuất hiện ở nhịp poll thứ hai."""

        def __init__(self, replies):
            super().__init__(replies)
            self.polls: dict[str, int] = {}

        async def history(self, session_key, limit=50):
            log = self.history_by_session.setdefault(session_key, [])
            self.polls[session_key] = self.polls.get(session_key, 0) + 1
            if session_key in self.pending and self.polls[session_key] >= 2:
                log.append({"id": f"m{len(log)}", "role": "assistant",
                            "text": self.pending.pop(session_key)})
                self.polls[session_key] = 0
            return {"messages": list(log)}

    runtime = SlowRuntime(["câu cũ", "câu mới"])
    original = rc.POLL_SECONDS
    rc.POLL_SECONDS = 0.01
    try:
        asyncio.run(rc.conduct(db, room, runtime, max_turns=2))
    finally:
        rc.POLL_SECONDS = original

    turns = db.query(RoomTurn).order_by(RoomTurn.sequence).all()
    assert [t.content for t in turns] == ["câu cũ", "câu mới"], \
        "lượt hai phải là câu MỚI, không phải đọc lại câu cũ trong cùng session"
