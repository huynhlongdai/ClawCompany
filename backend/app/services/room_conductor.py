"""v37 — Bộ điều phối phòng họp: khiến các agent thật sự nói trong phòng.

Máy trạng thái phòng họp của v16 đã tốt và **không cần xây lại**: nó có thứ tự
lượt (``turn_cursor``), quyền nói và quyền chốt (``can_post`` / ``can_decide``),
năm loại lượt (``message|proposal|decision|handoff|summary``), trần số lượt
(``max_turns``), và phát company event cho mỗi lượt.

Nó thiếu đúng **một** thứ, và đó là lý do module này tồn tại: trong toàn bộ 93
service của repo, chỉ ``agent_dispatch``, ``workflow_executor`` và
``v36_insights.ask_nina`` từng gọi ``run_agent``. ``collaboration_rooms.py``
không có một lời gọi runtime nào — nên phòng họp chỉ ghi được lượt khi **một
người** POST vào API. Một phòng toàn agent thì không ai nói cả.

Vòng lặp chín bước cho mỗi lượt:

1. Kiểm phòng còn mở và còn ngân sách.
2. Xác định ai nói lượt tới (round-robin theo ``seat_order``, hoặc chủ toạ chỉ định).
3. Dựng prompt cho đúng người đó: mục tiêu phòng + biên bản + gói ngữ cảnh + vai.
4. ``chat.send`` vào **phiên riêng của phòng**, không dùng phiên chính của agent.
5. Chờ trả lời qua ``chat.history``.
6. Ghi lại thành ``room_turns`` bằng ``post_turn`` (đi qua đúng mọi chốt của v16).
7. Ghi vận hành vào ``room_conductor_runs``: tốn bao lâu, bao nhiêu tiền.
8. Cập nhật ``turn_cursor``, ``cost_spent_usd``, ``stall_count``.
9. Kiểm bốn điều kiện dừng.

**Bốn điều kiện dừng**, và vì sao mỗi cái cần thiết:

* ``max_turns`` — trần cứng đã có từ v16.
* ``budget`` — mỗi lượt là một lời gọi model có phí. Một phòng không có trần
  tiền là một hoá đơn mở, nên bộ điều phối **từ chối chạy** khi
  ``cost_budget_usd`` bằng 0.
* ``stalled`` — hai lượt liên tiếp không thêm thông tin mới. Không có chốt này,
  hai agent có thể lịch sự đồng ý với nhau mãi mãi.
* ``chair_closed`` — chủ toạ ghi một lượt ``decision`` hoặc ``summary``.

**Ràng buộc vật lý của runtime, đã đo được**, định hình thiết kế này:

* Một phiên chỉ chạy một lượt tại một thời điểm, nên các agent nói **lần lượt**.
  Đây không phải giới hạn của ta mà của OpenClaw, và nó khớp với mô hình phòng
  họp thật: cuộc họp mà mọi người nói cùng lúc thì không ai nghe được gì.
* ``idempotencyKey`` phải gồm vân tay nội dung. Khoá theo lượt sẽ làm lượt gửi
  thứ hai bị ``chat-request-conflict`` — đã gặp thật ở v35.1.
* Mỗi agent dùng session key riêng theo phòng
  (``agent:<id>:room-<key>``) để biên bản họp không lẫn vào phiên chính.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Agent, Member, Project, Task
from app.models.v16 import CollaborationRoom, RoomParticipant, RoomTurn
from app.models.v37 import RoomConductorRun
from app.services import collaboration_rooms as rooms
from app.services import work_context
from app.services.company_event_bus import emit_event

# Trần mềm cho một lời gọi. Vượt thì ghi timeout và chuyển lượt, không treo cả
# phiên họp vì một agent chậm.
REPLY_TIMEOUT_SECONDS = 150
POLL_SECONDS = 5

# Biên bản đưa vào prompt: chỉ N lượt gần nhất. Một phòng 200 lượt không thể
# nhồi hết vào mỗi prompt, và lượt cũ đã nằm trong database để tra khi cần.
TRANSCRIPT_LINES = 12
TRANSCRIPT_CHARS = 3_000

# Ngưỡng "không thêm thông tin mới": hai câu trả lời giống nhau tới mức này.
STALL_SIMILARITY = 0.92
STALL_LIMIT = 2

STOP_MAX_TURNS = "max_turns"
STOP_BUDGET = "budget"
STOP_STALLED = "stalled"
STOP_CHAIR_CLOSED = "chair_closed"
STOP_ERROR = "error"
STOP_NO_SPEAKER = "no_speaker"
# Lý do dừng thứ năm, phát hiện khi chạy test: ở phòng round-robin, đến lượt
# một người thật thì bộ điều phối phải DỪNG và chờ, không được nhảy lượt.
STOP_WAITING_HUMAN = "waiting_for_human"
# Hết số lượt của LỜI GỌI này, không phải của phòng. Phân biệt với
# ``max_turns`` để người đọc báo cáo không tưởng phòng đã cạn trần.
STOP_CALL_LIMIT = "call_limit"


COST_NOTE = ("cost_usd là ƯỚC LƯỢNG do caller đưa vào, không phải giá thật từ "
             "usage.cost của gateway. Hai nguồn tiền chưa được đối chiếu — "
             "xem WP-1.4.")


class ConductorError(RuntimeError):
    pass


def _turn_dict(result: "TurnResult") -> dict:
    return {
        "speaker": result.speaker_name, "member_id": result.speaker_member_id,
        "turn_id": result.turn_id, "turn_type": result.turn_type,
        "status": result.status, "elapsed_seconds": result.elapsed_seconds,
        "error": result.error, "reply_preview": result.reply[:280],
    }


@dataclass
class TurnResult:
    speaker_member_id: int
    speaker_name: str
    turn_id: int | None
    turn_type: str
    reply: str
    elapsed_seconds: float
    status: str
    error: str = ""


def room_session_key(runtime_agent_id: str, room: CollaborationRoom) -> str:
    """Phiên riêng cho phòng họp.

    Không dùng ``agent:<id>:main``: phiên chính là nơi người vận hành nói
    chuyện với agent qua kênh chat, và nhồi biên bản họp vào đó sẽ làm bẩn
    ngữ cảnh của họ. Cũng không dùng phiên của task: một phòng có thể bàn nhiều
    task.
    """
    return f"agent:{runtime_agent_id}:room-{room.room_key}"


def _similar(a: str, b: str) -> float:
    """Độ giống nhau thô giữa hai câu trả lời, để phát hiện phòng bị treo.

    Dùng SequenceMatcher của stdlib: không cần chính xác, chỉ cần phát hiện hai
    lượt nói gần như y nhau. Nếu dùng model để đánh giá thì mỗi lượt lại tốn
    thêm một lời gọi — trả tiền để kiểm tra việc trả tiền.
    """
    from difflib import SequenceMatcher
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def chair_of(db: Session, room: CollaborationRoom) -> RoomParticipant | None:
    """Ai giữ búa.

    Thứ tự tìm: ``chair_member_id`` của phòng (v37), rồi participant đầu tiên
    có ``can_decide``. Chủ toạ **có thể là người thật hoặc agent** — người thật
    thì bộ điều phối không tự sinh lượt cho họ, nó dừng và chờ.
    """
    roster = rooms.room_roster(db, room)
    if room.chair_member_id:
        for participant in roster:
            if participant.member_id == room.chair_member_id:
                return participant
    for participant in roster:
        if participant.can_decide:
            return participant
    return None


def next_speaker(db: Session, room: CollaborationRoom) -> tuple[RoomParticipant | None, str]:
    """Ai nói lượt tới. Trả về ``(participant, blocker)``.

    **Sửa một lỗi mà test tìm ra, và nó đúng là lớp lỗi repo này đã gặp.** Bản
    đầu của hàm này tự tính lượt: nó lọc bỏ người thật rồi lấy
    ``turn_cursor % len(agents_only)``. Kết quả là nó chọn một người, còn
    ``rooms.post_turn`` — vốn kiểm bằng ``rooms.expected_speaker`` trên roster
    **đầy đủ** — từ chối với ``Out of turn``. Hai định nghĩa cho cùng một câu
    hỏi "đến lượt ai", y như ``row_guard.kind()`` so với
    ``row_revision.kind_of()`` ở v28.

    Nay ở mode ``round_robin``, hàm này **không tự tính**: nó hỏi
    ``rooms.expected_speaker`` và tôn trọng câu trả lời. Nếu đến lượt một
    **người thật**, bộ điều phối dừng và nói rõ đang chờ ai — chứ không nhảy
    qua lượt của họ. Nhảy lượt trong một phòng có thứ tự là âm thầm đổi luật
    của cuộc họp.

    Ở ``lead_routed`` và ``free``, v16 kiểm theo vai chứ không theo vị trí, nên
    bộ điều phối được chọn: lấy người chưa nói lâu nhất, và chỉ trong số agent.
    """
    roster = [p for p in rooms.room_roster(db, room) if p.can_post]
    if not roster:
        return None, "phòng không có người dự nào được phép nói"

    agent_member_ids = {
        row[0] for row in db.execute(
            select(Agent.member_id).where(
                Agent.member_id.in_([p.member_id for p in roster]),
                Agent.runtime_agent_id.isnot(None),
                Agent.runtime_agent_id != "",
                Agent.lifecycle == "active",
            )
        ).all()
    }

    if room.mode == "round_robin":
        # Một nguồn sự thật duy nhất cho "đến lượt ai".
        expected = rooms.expected_speaker(db, room)
        if expected is None:
            return None, "v16 không xác định được người nói kế tiếp"
        if expected.member_id not in agent_member_ids:
            person = db.get(Member, expected.member_id)
            name = person.name if person else f"member#{expected.member_id}"
            return None, (f"đến lượt {name}, là người thật (hoặc seat chưa hoạt "
                          f"động). Bộ điều phối không nói hộ; chờ họ phát biểu "
                          f"rồi gọi lại.")
        return expected, ""

    agents = [p for p in roster if p.member_id in agent_member_ids]
    if not agents:
        return None, ("không có người dự nào là agent đang hoạt động và được "
                      "phép nói. Phòng chỉ có người thật thì bộ điều phối "
                      "không nói hộ được.")

    spoken: dict[int, int] = {}
    for turn in db.execute(
        select(RoomTurn.member_id, RoomTurn.sequence)
        .where(RoomTurn.room_id == room.id).order_by(RoomTurn.sequence)
    ).all():
        spoken[turn[0]] = turn[1]
    return min(agents, key=lambda p: (spoken.get(p.member_id, -1), p.seat_order, p.id)), ""


def build_turn_prompt(db: Session, room: CollaborationRoom,
                      speaker: RoomParticipant, *, chair: RoomParticipant | None) -> str:
    """Prompt cho một lượt nói.

    Bốn phần: phòng này đang bàn gì, ai đang ở đây, đã nói tới đâu, và bạn được
    yêu cầu làm gì trong lượt này. Cộng gói ngữ cảnh công việc nếu phòng gắn với
    một dự án — vì một cuộc họp về dự án mà người dự không biết dự án đang ở đâu
    thì chỉ là nói chuyện.
    """
    member = db.get(Member, speaker.member_id)
    chair_member = db.get(Member, chair.member_id) if chair else None
    roster = rooms.room_roster(db, room)
    names = {p.member_id: db.get(Member, p.member_id) for p in roster}

    parts: list[str] = []
    parts.append(f"# Phòng họp: {room.topic or room.room_key}")
    if room.objective:
        parts.append(f"**Mục tiêu cần đạt:** {room.objective}")

    who = []
    for participant in roster:
        person = names.get(participant.member_id)
        if not person:
            continue
        tag = participant.participant_role
        if chair and participant.member_id == chair.member_id:
            tag += ", chủ toạ"
        who.append(f"- {person.name} ({person.role or 'chưa có chức danh'}) — {tag}")
    parts.append("## Ai đang trong phòng\n" + "\n".join(who))

    transcript = rooms.transcript(db, room, limit=200)
    if transcript:
        recent = transcript[-TRANSCRIPT_LINES:]
        lines = []
        for turn in recent:
            person = db.get(Member, turn.member_id)
            speaker_name = person.name if person else f"member#{turn.member_id}"
            content = turn.content.strip().replace("\n", " ")
            lines.append(f"{turn.sequence}. **{speaker_name}** [{turn.turn_type}]: {content}")
        text = "\n".join(lines)
        if len(text) > TRANSCRIPT_CHARS:
            text = text[-TRANSCRIPT_CHARS:]
            text = "(…phần đầu biên bản đã lược cho vừa ngân sách)\n" + text
        omitted = len(transcript) - len(recent)
        header = "## Biên bản tới lúc này"
        if omitted > 0:
            header += f" ({omitted} lượt trước đã lược, còn trong hồ sơ phòng)"
        parts.append(f"{header}\n{text}")
    else:
        parts.append("## Biên bản tới lúc này\n(Chưa ai nói. Bạn mở đầu.)")

    # Gói ngữ cảnh công việc: chỉ khi phòng gắn với dự án, và lấy task đang mở
    # đầu tiên làm điểm neo. Không có dự án thì không bịa ra.
    if room.project_id:
        task = db.execute(
            select(Task).where(Task.project_id == room.project_id,
                               Task.status.notin_(["done", "cancelled", "archived"]))
            .order_by(Task.priority.desc(), Task.id)
        ).scalars().first()
        if task:
            pack = work_context.build_pack(db, task, organization_id=room.organization_id,
                                           budget_chars=2_500)
            parts.append("## Bối cảnh công việc đang bàn\n" + pack["text"])

    duty = [
        f"Bạn là **{member.name if member else 'người dự'}**, vai "
        f"{speaker.participant_role} trong phòng này.",
        "Nói **một lượt duy nhất**, ngắn gọn, đi thẳng vào mục tiêu của phòng.",
        "Đừng nhắc lại điều người khác đã nói; hãy thêm thông tin mới hoặc nêu "
        "điểm chưa ai nói.",
        "Nếu bạn đồng ý với một đề xuất, hãy nói rõ đồng ý phần nào và điều kiện gì.",
    ]
    if speaker.can_decide and chair and speaker.member_id == chair.member_id:
        duty.append(
            "Bạn là chủ toạ. Khi **đã đủ dữ kiện để chốt**, hãy viết một dòng "
            f"riêng bắt đầu bằng đúng chữ `{DECISION_MARKER}` rồi nêu quyết "
            "định và việc tiếp theo cho từng người. Nếu chưa đủ dữ kiện thì "
            f"ĐỪNG viết dòng đó — hãy hỏi thêm. Chỉ dòng `{DECISION_MARKER}` "
            "mới kết thúc cuộc họp; nói 'chúng ta sẽ quyết định' thì cuộc họp "
            "vẫn tiếp tục.")
    else:
        duty.append("Bạn **không** có quyền chốt; đề xuất thì được, quyết định "
                    "thuộc chủ toạ"
                    + (f" ({chair_member.name})" if chair_member else "") + ".")
    parts.append("## Lượt của bạn\n" + "\n".join(f"- {d}" for d in duty))

    return "\n\n".join(parts)


# Chủ toạ phải **nói ra** ý định chốt bằng một dấu hiệu chính xác, không để hệ
# thống suy từ văn phong. Lý do, đo được ở lần chạy thật đầu tiên
# (`_reports/room-conductor-e2e.md`): Nina mở đầu cuộc họp bằng câu "sau khi
# lắng nghe, chúng ta **sẽ quyết định** và giao nhiệm vụ" — một *dự định tương
# lai* — và bộ phân loại theo từ khoá đọc thành "tôi chốt ngay". Phòng đóng sau
# một lượt, Mia không kịp nói câu nào.
#
# Nguyên tắc rút ra: **đừng suy diễn cái có thể yêu cầu.** Prompt dặn chủ toạ
# đặt đúng một dòng bắt đầu bằng dấu hiệu dưới đây; không có dấu hiệu thì cuộc
# họp tiếp tục.
DECISION_MARKER = "QUYẾT ĐỊNH:"
SUMMARY_MARKER = "TÓM TẮT:"


def classify_turn(reply: str, *, is_chair: bool) -> str:
    """Lượt này thuộc loại nào trong năm loại của v16.

    Chỉ chủ toạ mới có thể tạo ``decision``/``summary``, và **chỉ khi** có dòng
    mở đầu bằng dấu hiệu tường minh. Một agent thường viết "tôi quyết định" thì
    vẫn chỉ là ``proposal`` — đúng theo chốt ``can_decide`` của v16.
    """
    if not reply:
        return "message"
    lines = [line.strip() for line in reply.splitlines() if line.strip()]
    if is_chair:
        for line in lines:
            upper = line.upper()
            if upper.startswith(DECISION_MARKER):
                return "decision"
            if upper.startswith(SUMMARY_MARKER):
                return "summary"
    lowered = reply.lower()
    if any(k in lowered for k in ("đề xuất", "tôi nghĩ nên", "phương án", "proposal")):
        return "proposal"
    return "message"


def _assistant_messages(payload: dict) -> list[dict]:
    entries = (payload.get("messages") or payload.get("entries")
               or payload.get("items") or [])
    return [e for e in entries
            if str(e.get("role") or e.get("author") or "") in ("assistant", "agent")]


def _message_text(entry: dict) -> str:
    for key in ("text", "content", "message"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            blocks = [b.get("text", "") for b in value
                      if isinstance(b, dict) and b.get("text")]
            if blocks:
                return "\n".join(blocks).strip()
    return ""


def _fingerprint(entry: dict, index: int) -> str:
    """Nhận dạng một message để biết nó mới hay cũ.

    Dùng id nếu upstream cho; nếu không thì dùng (vị trí, 64 ký tự đầu). Không
    dùng riêng nội dung: hai lượt có thể trùng nội dung một cách hợp lệ.
    """
    for key in ("id", "messageId", "entryId", "uuid"):
        value = entry.get(key)
        if value:
            return f"id:{value}"
    return f"pos:{index}:{_message_text(entry)[:64]}"


async def _baseline(runtime, session_key: str) -> set[str]:
    """Những message trợ lý ĐÃ có trong phiên, trước khi ta gửi lượt mới."""
    try:
        payload = await runtime.history(session_key, limit=50)
    except Exception:                                     # noqa: BLE001
        return set()
    return {_fingerprint(entry, index)
            for index, entry in enumerate(_assistant_messages(payload))}


async def _ask(runtime, room: CollaborationRoom, agent: Agent,
               prompt: str) -> tuple[str, str, float]:
    """Gửi một lượt và chờ **câu trả lời MỚI**. Trả về (reply, run_id, elapsed).

    **Sửa một lỗi mà chỉ lần chạy thật phát hiện được, và nó là lỗi gốc của
    hiện tượng "agent lặp lại nguyên văn".** Bản đầu gửi prompt rồi đọc
    ``chat.history`` và lấy *message trợ lý cuối cùng*. Nhưng phòng họp dùng một
    session dài cho cả cuộc họp, nên từ lượt thứ hai trở đi session **đã có**
    câu trả lời cũ. Nếu model chưa kịp trả lời trong nhịp poll đầu, hàm này đọc
    lại câu cũ và tưởng đó là câu mới.
    
    Đo được trong `_reports/room-conductor-e2e.md`: lượt 1 mất 10,09s (hai nhịp
    poll), lượt 3 chỉ 5,06s (một nhịp) và trả về **đúng từng ký tự** câu của
    lượt 1. Chốt chống treo bắt được hệ quả, nhưng nguyên nhân nằm ở đây.

    Nay hàm chụp "vân tay" các message trợ lý **trước khi gửi**, rồi chỉ nhận
    message không có trong tập đó.
    """
    session_key = room_session_key(agent.runtime_agent_id, room)
    seen = await _baseline(runtime, session_key)
    started = time.monotonic()
    run = await runtime.run_agent(
        agent.runtime_agent_id, prompt,
        metadata={"room_id": room.id, "room_key": room.room_key,
                  "label": f"Room {room.room_key}"},
        session_key=session_key,
    )
    deadline = started + REPLY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(POLL_SECONDS)
        try:
            payload = await runtime.history(session_key, limit=50)
        except Exception as exc:                          # noqa: BLE001
            raise ConductorError(f"không đọc được chat.history: {exc}") from exc
        messages = _assistant_messages(payload)
        for index, entry in enumerate(messages):
            if _fingerprint(entry, index) in seen:
                continue
            text = _message_text(entry)
            if text:
                return text, run.run_id or "", time.monotonic() - started
    return "", run.run_id or "", time.monotonic() - started


async def run_turn(db: Session, room: CollaborationRoom, runtime, *,
                   cost_per_turn_usd: float = 0.0) -> TurnResult:
    """Một lượt: chọn người, hỏi, ghi biên bản, ghi vận hành.

    ``cost_per_turn_usd`` là ước lượng do caller đưa vào. Cố ý **không** tự đoán
    giá ở đây: giá thật nằm ở ``usage.cost`` của gateway, và hai nguồn tiền của
    dự án này chưa từng được đối chiếu (đó là WP-1.4, còn nợ). Ghi ước lượng vào
    ``cost_usd`` và nói rõ nó là ước lượng.
    """
    chair = chair_of(db, room)
    speaker, blocker = next_speaker(db, room)
    if not speaker:
        raise ConductorError(blocker or "không xác định được người nói kế tiếp")

    member = db.get(Member, speaker.member_id)
    agent = db.execute(
        select(Agent).where(Agent.member_id == speaker.member_id)
    ).scalars().first()
    if not agent or not agent.runtime_agent_id:
        raise ConductorError(f"{member.name if member else speaker.member_id} chưa gắn seat runtime")

    prompt = build_turn_prompt(db, room, speaker, chair=chair)
    is_chair = bool(chair and speaker.member_id == chair.member_id)

    status, error, reply, run_id, elapsed = "ok", "", "", "", 0.0
    try:
        reply, run_id, elapsed = await _ask(runtime, room, agent, prompt)
        if not reply:
            status, error = "timeout", f"không có trả lời trong {REPLY_TIMEOUT_SECONDS}s"
    except Exception as exc:                              # noqa: BLE001
        status, error = "error", str(exc)[:500]

    turn: RoomTurn | None = None
    turn_type = classify_turn(reply, is_chair=is_chair) if reply else "message"
    if reply:
        turn = rooms.post_turn(db, room, member_id=speaker.member_id, content=reply,
                               turn_type=turn_type,
                               references={"conducted": True, "runtime_run_id": run_id})

    db.add(RoomConductorRun(
        organization_id=room.organization_id, room_id=room.id,
        turn_id=turn.id if turn else None, speaker_member_id=speaker.member_id,
        runtime_agent_id=agent.runtime_agent_id,
        runtime_session_key=room_session_key(agent.runtime_agent_id, room),
        runtime_run_id=run_id, prompt_chars=len(prompt), reply_chars=len(reply),
        elapsed_seconds=round(elapsed, 2), cost_usd=cost_per_turn_usd,
        status=status, error=error,
    ))

    room.cost_spent_usd = (room.cost_spent_usd or 0.0) + cost_per_turn_usd

    # Phát hiện treo.
    #
    # **Sửa một lỗi mà chỉ lần chạy thật phát hiện được**
    # (`_reports/room-conductor-e2e.md`, lần chạy thứ hai): bản đầu chỉ so lượt
    # mới với lượt **liền trước** của phòng. Trong một cuộc họp luân phiên, vòng
    # lặp có hình A B A B — hai lượt liền nhau luôn khác nhau, nên chốt đó
    # không bao giờ bắt được. Đo được: Nina lặp lại nguyên văn ở lượt 1 và 3,
    # Mia ở lượt 2 và 4, mà ``stall_count`` vẫn bằng 0.
    #
    # Nay so với **lượt gần nhất của CHÍNH người đó**, cộng cả lượt liền trước.
    # Nina nói lại đúng điều Nina đã nói thì cuộc họp đứng, bất kể Mia chen gì
    # vào giữa.
    if reply:
        own_previous = db.execute(
            select(RoomTurn).where(RoomTurn.room_id == room.id,
                                   RoomTurn.member_id == speaker.member_id,
                                   RoomTurn.id != (turn.id if turn else -1))
            .order_by(RoomTurn.sequence.desc()).limit(1)
        ).scalars().first()
        room_previous = db.execute(
            select(RoomTurn).where(RoomTurn.room_id == room.id,
                                   RoomTurn.id != (turn.id if turn else -1))
            .order_by(RoomTurn.sequence.desc()).limit(1)
        ).scalars().first()
        scores = [_similar(previous.content, reply)
                  for previous in (own_previous, room_previous) if previous]
        if scores and max(scores) >= STALL_SIMILARITY:
            room.stall_count = (room.stall_count or 0) + 1
        else:
            room.stall_count = 0

    db.add(room); db.commit(); db.refresh(room)

    return TurnResult(
        speaker_member_id=speaker.member_id,
        speaker_name=member.name if member else f"member#{speaker.member_id}",
        turn_id=turn.id if turn else None, turn_type=turn_type, reply=reply,
        elapsed_seconds=round(elapsed, 2), status=status, error=error,
    )


def stop_reason(db: Session, room: CollaborationRoom) -> str:
    """Bốn điều kiện dừng. Rỗng nghĩa là còn chạy được."""
    if room.status != "open":
        return STOP_CHAIR_CLOSED if room.status == "closed" else room.status
    if room.turn_cursor >= room.max_turns:
        return STOP_MAX_TURNS
    if room.cost_budget_usd and room.cost_spent_usd >= room.cost_budget_usd:
        return STOP_BUDGET
    if (room.stall_count or 0) >= STALL_LIMIT:
        return STOP_STALLED
    last = db.execute(
        select(RoomTurn).where(RoomTurn.room_id == room.id)
        .order_by(RoomTurn.sequence.desc()).limit(1)
    ).scalars().first()
    if last and last.turn_type in ("decision", "summary"):
        chair = chair_of(db, room)
        if chair and last.member_id == chair.member_id:
            return STOP_CHAIR_CLOSED
    return ""


async def conduct(db: Session, room: CollaborationRoom, runtime, *, max_turns: int = 6,
                  cost_per_turn_usd: float = 0.01) -> dict:
    """Chạy phiên họp tới khi có điều kiện dừng, hoặc hết ``max_turns`` của lượt gọi này.

    Từ chối chạy khi phòng chưa có trần tiền: một phòng toàn agent không có
    ``cost_budget_usd`` là một hoá đơn mở, và "quên đặt hạn mức" không phải lý
    do để hệ thống tự tiêu tiền.
    """
    if not room.cost_budget_usd:
        raise ConductorError(
            "phòng chưa đặt cost_budget_usd. Mỗi lượt là một lời gọi model có "
            "phí, nên bộ điều phối không chạy phòng không có trần tiền.")

    initial = stop_reason(db, room)
    if initial:
        return {"room_id": room.id, "ran": 0, "stopped_reason": initial,
                "turns": [], "note": "phòng đã ở trạng thái dừng trước khi gọi"}

    results: list[TurnResult] = []
    reason = ""
    for _ in range(max(1, min(max_turns, 20))):
        try:
            result = await run_turn(db, room, runtime, cost_per_turn_usd=cost_per_turn_usd)
        except ConductorError as exc:
            message = str(exc)
            if "là người thật" in message:
                reason = STOP_WAITING_HUMAN
            elif "không có người dự" in message:
                reason = STOP_NO_SPEAKER
            else:
                reason = STOP_ERROR
            results.append(TurnResult(0, "(không có)", None, "message", "", 0.0,
                                      "error", str(exc)))
            break
        results.append(result)
        reason = stop_reason(db, room)
        if reason:
            break
    else:
        # Vòng for chạy hết mà không break: hết lượt của lời gọi này, phòng vẫn
        # còn chạy được. Nói rõ thay vì trả lý do rỗng.
        if not reason:
            reason = STOP_CALL_LIMIT

    if reason == STOP_CALL_LIMIT:
        return {
            "room_id": room.id, "ran": len(results), "stopped_reason": reason,
            "room_status": room.status, "turn_cursor": room.turn_cursor,
            "cost_spent_usd": round(room.cost_spent_usd or 0.0, 4),
            "cost_budget_usd": room.cost_budget_usd, "stall_count": room.stall_count,
            "turns": [_turn_dict(r) for r in results],
            "note": ("hết số lượt của lời gọi này; phòng vẫn mở và còn ngân "
                     "sách, gọi lại để họp tiếp."),
            "cost_note": COST_NOTE,
        }

    if reason and reason != room.stopped_reason:
        room.stopped_reason = reason
        # Chỉ chủ toạ chốt mới đóng phòng. Hết tiền hay hết lượt thì phòng vẫn
        # mở để người thật vào xem và quyết định tiếp.
        if reason == STOP_CHAIR_CLOSED:
            room.status = "closed"
        db.add(room); db.commit(); db.refresh(room)
        emit_event(db, organization_id=room.organization_id, company_id=room.company_id,
                   event_type="collaboration.room.stopped", source="room_conductor",
                   aggregate_type="collaboration_room", aggregate_id=str(room.id),
                   actor_member_id=room.chair_member_id,
                   payload={"reason": reason, "turns": room.turn_cursor,
                            "cost_spent_usd": room.cost_spent_usd})

    return {
        "room_id": room.id,
        "ran": len(results),
        "stopped_reason": reason,
        "room_status": room.status,
        "turn_cursor": room.turn_cursor,
        "cost_spent_usd": round(room.cost_spent_usd or 0.0, 4),
        "cost_budget_usd": room.cost_budget_usd,
        "stall_count": room.stall_count,
        "turns": [_turn_dict(r) for r in results],
        "cost_note": COST_NOTE,
    }
