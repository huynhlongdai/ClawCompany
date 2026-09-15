"""WP-2.1 + WP-2.2 — hồ sơ một "nhân sự AI": đọc và ghi.

Một AI employee trong ClawCompany không nằm ở một chỗ. Nó là ba thứ phải khớp
nhau:

1. **Postgres** — ``members`` (ai, phòng ban nào, báo cáo cho ai) và ``agents``
   (seat runtime, model, chi phí, vòng đời).
2. **``agents.entries.<id>`` trong openclaw.json** — model, thinking, sandbox,
   hạn mức, quyền dùng tool.
3. **5 file trong workspace** — ``IDENTITY.md``, ``SOUL.md``, ``AGENTS.md``,
   ``USER.md``, ``MEMORY.md``: danh tính, tính cách, mô tả công việc, sở thích
   của người quản lý, và ký ức đã hợp nhất.

Module này gộp ba nguồn đó thành một hồ sơ, và **ghi rõ mỗi trường đến từ
đâu**. Lý do không phải trang trí: khi một con số trên UI sai, câu hỏi đầu tiên
luôn là "số này từ database hay từ gateway", và nếu hồ sơ không trả lời được thì
người vận hành phải đi đọc code.

Ba chốt mà WP-2.2 bắt buộc có:

* **Ghi file phải có ``expectedHash``.** Upstream từ chối write lệch hash với
  ``details.type = "agent_file_conflict"`` kèm ``currentHash``. Không có chốt
  này thì hai người sửa ``SOUL.md`` cùng lúc, người sau xoá công của người trước
  và không ai biết.
* **Đếm ký tự trước khi ghi.** Vượt ``bootstrapMaxChars`` thì OpenClaw **cắt âm
  thầm** ở tầng prompt — file trên đĩa vẫn đủ, nhưng agent chỉ thấy một nửa tính
  cách của nó. Một lỗi không có thông báo là lỗi tệ nhất, nên ở đây nó thành lỗi
  có thông báo.
* **Đối chiếu roster.** Seat trong database phải có thật trên gateway. Lượt
  trước đã gặp đúng lỗi này ở ``ask_nina``: seat "detached" được chọn trước seat
  "active" vì không ai hỏi gateway.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Agent, Company, Department, Member
from app.runtime import openclaw_protocol as ocp
from app.services.openclaw_config import ConfigError, ConfigRegistry

# Thứ tự đọc của một người soát xét: tôi là ai → tôi là người thế nào → việc
# của tôi → người quản lý muốn gì → tôi đã học được gì.
SEAT_FILES = ocp.AGENT_BOOTSTRAP_FILES

# File nào thuộc tab nào. Tab 1-3 ghi file; tab 4-6 ghi config.
FILE_TABS = {
    "IDENTITY.md": "profile",
    "SOUL.md": "personality",
    "AGENTS.md": "job",
    "USER.md": "job",
    "MEMORY.md": "memory",
}

# Những khoá cấu hình mà mỗi tab được phép ghi. Danh sách đóng: một tab "Năng
# lực" không được sửa quyền dùng tool, kể cả khi frontend gửi lên.
CONFIG_TABS: dict[str, tuple[str, ...]] = {
    # Tab 1 — Hồ sơ: tên hiển thị, chủ đề, emoji, avatar.
    "profile": ("name", "identity.name", "identity.theme", "identity.emoji",
                "identity.avatar"),
    # Tab 4 — Năng lực: nghĩ sâu tới đâu, model nào, nén ngữ cảnh thế nào.
    "capability": ("model", "utilityModel", "thinkingDefault", "fastModeDefault",
                   "timeoutSeconds", "compaction.enabled", "compaction.notifyUser",
                   "modelPolicy.allow"),
    # Tab 5 — Quyền: tool và sandbox. Đây là tab nguy hiểm nhất.
    "permission": ("tools.profile", "tools.allow", "tools.deny",
                   "tools.elevated.enabled", "sandbox.mode", "sandbox.scope",
                   "sandbox.workspaceAccess", "sandbox.docker.network", "skills"),
    # Tab 6 — Hạn mức: tiền và khối lượng việc.
    "budget": ("heartbeat.every", "heartbeat.prompt", "heartbeat.activeHours.start",
               "heartbeat.activeHours.end", "maxConcurrent",
               "subagents.maxConcurrent", "subagents.maxChildrenPerAgent"),
}

# Mảng: ghi lại là thay, nên phải khai replacePaths. Giữ ở đây để tầng API
# không phải biết luật của config.patch.
ARRAY_CONFIG_KEYS = ("tools.allow", "tools.deny", "skills", "modelPolicy.allow")


class SeatError(RuntimeError):
    def __init__(self, reason: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.reason = reason
        self.details = details

    def as_dict(self) -> dict:
        return {"reason": self.reason, "message": str(self), **self.details}


class SeatFileConflict(SeatError):
    """Ai đó vừa sửa file này; hash đem đi so đã cũ."""

    def __init__(self, name: str, current_hash: str) -> None:
        super().__init__(
            "file_conflict",
            f"{name} vừa bị người khác (hoặc chính agent) sửa. Tải lại rồi ghi "
            "lại trên bản mới — đừng ghi đè.",
            file=name, current_hash=current_hash,
        )


def char_budget(name: str) -> int:
    """Hạn mức ký tự cho một file bootstrap.

    ``USER.md`` có hạn mức riêng **nhỏ hơn** (4 000 so với 20 000). Đây là chỗ
    rất dễ bỏ sót khi làm UI, vì bốn file kia đều 20 000.
    """
    return ocp.USER_MD_MAX_CHARS if name == "USER.md" else ocp.BOOTSTRAP_MAX_CHARS


class SeatProfileService:
    """Đọc/ghi hồ sơ một seat. Một instance cho một request.

    ``runtime`` cần ``async def rpc(method, params)``. ``registry`` là
    :class:`ConfigRegistry` của WP-1.2 — dùng lại toàn bộ chốt ``baseHash`` /
    ``replacePaths`` / ``reloadKind`` thay vì viết lại.
    """

    def __init__(self, db: Session, runtime: Any,
                 registry: ConfigRegistry | None = None) -> None:
        self.db = db
        self.runtime = runtime
        self.registry = registry or ConfigRegistry(runtime)

    # -- đọc ---------------------------------------------------------------

    def seat_row(self, agent_id: int, organization_id: int) -> tuple[Agent, Member]:
        """Seat trong database, đã chặn theo tenant.

        ``agents`` không có ``organization_id``; đường đi hợp lệ là qua
        ``members``. Đây đúng là lớp lỗi mà v35 ``live_channel`` đã mắc (lọc
        theo một cột không tồn tại), nên viết ra cho rõ.
        """
        row = self.db.execute(
            select(Agent, Member)
            .join(Member, Agent.member_id == Member.id)
            .where(Agent.id == agent_id, Member.organization_id == organization_id)
        ).first()
        if not row:
            raise SeatError("not_found", f"không có seat #{agent_id} trong tổ chức này")
        return row[0], row[1]

    async def read(self, agent_id: int, organization_id: int) -> dict:
        """Hồ sơ đầy đủ của một seat: bảy bộ phận, mỗi trường có nguồn.

        Mỗi nguồn hỏng độc lập. Gateway chết thì phần database vẫn hiện, kèm
        ``warnings`` nói rõ cái gì không đọc được — màn hình nhân sự không được
        trắng xoá chỉ vì gateway đang khởi động lại.
        """
        agent, member = self.seat_row(agent_id, organization_id)
        runtime_agent_id = (agent.runtime_agent_id or "").strip()

        profile: dict[str, Any] = {
            "seat": self._db_part(agent, member),
            "runtime_agent_id": runtime_agent_id,
            "warnings": [],
            "sources": {"seat": "db"},
        }
        warnings: list[str] = profile["warnings"]

        if not runtime_agent_id:
            warnings.append("Seat chưa gắn runtime_agent_id, nên không có gì để "
                            "đọc từ gateway. Đây là seat chỉ tồn tại trong database.")
            profile["roster_match"] = False
            return profile

        # 1) Đối chiếu roster: seat này có thật trên gateway không.
        try:
            roster = await self.runtime.list_agents()
            entry = next((a for a in roster
                          if str(a.get("id") or a.get("agentId")) == runtime_agent_id), None)
            profile["roster_match"] = entry is not None
            profile["roster_entry"] = entry or {}
            profile["sources"]["roster_entry"] = "gateway"
            if entry is None:
                warnings.append(
                    f"Database nói seat này là `{runtime_agent_id}`, nhưng gateway "
                    f"không có agent nào tên vậy (roster: "
                    f"{', '.join(sorted(str(a.get('id') or a.get('agentId')) for a in roster)) or 'rỗng'}). "
                    "Hồ sơ dưới đây là của database, không phải của một agent đang sống.")
        except Exception as exc:                          # noqa: BLE001
            profile["roster_match"] = None
            warnings.append(f"Không đọc được roster từ gateway: {exc}")

        # 2) Danh tính hiệu dụng — gateway tự tính, không phải ta suy ra.
        try:
            profile["identity"] = await self.runtime.rpc(
                ocp.M_AGENT_IDENTITY_GET, {"agentId": runtime_agent_id})
            profile["sources"]["identity"] = "gateway"
        except Exception as exc:                          # noqa: BLE001
            profile["identity"] = {}
            warnings.append(f"Không đọc được agent.identity.get: {exc}")

        # 3) Cấu hình: của riêng seat và phần thừa hưởng từ agents.defaults.
        try:
            profile["config"] = await self.registry.agent_entry(runtime_agent_id)
            profile["sources"]["config"] = "gateway"
        except Exception as exc:                          # noqa: BLE001
            profile["config"] = {}
            warnings.append(f"Không đọc được config: {exc}")

        # 3b) Hai nguồn "model" phải khớp nhau. Đo được lúc nghiệm thu WP-2.1:
        # database ghi "GPT-4.1" trong khi gateway đang chạy
        # "cometapi/gpt-4o-mini". Cột `agents.model` là thứ seed script đặt và
        # không ai cập nhật lại, nên mọi báo cáo chi phí dựa vào nó đều đang nói
        # về một model không chạy. Nói ra chỗ lệch, đừng chọn hộ bên nào đúng.
        db_model = (agent.model or "").strip()
        live_model = str((profile.get("config") or {}).get("effective", {}).get("model") or "").strip()
        profile["model_drift"] = {
            "db": db_model, "gateway": live_model,
            "match": (not db_model or not live_model or db_model == live_model),
        }
        if db_model and live_model and db_model != live_model:
            warnings.append(
                f"Database ghi model `{db_model}` nhưng gateway đang chạy "
                f"`{live_model}`. Gateway là sự thật về cái đang chạy; cột "
                "`agents.model` chỉ là bản ghi của ClawCompany và đang cũ.")

        # 4) Năm file, kèm hash để ghi có điều kiện và số ký tự để cảnh báo.
        files, total = [], 0
        for name in SEAT_FILES:
            record = await self._read_file(runtime_agent_id, name)
            files.append(record)
            total += record.get("chars", 0)
            if record.get("error"):
                warnings.append(f"{name}: {record['error']}")
            elif record.get("over_budget"):
                warnings.append(
                    f"{name} dài {record['chars']} ký tự, vượt hạn mức "
                    f"{record['max_chars']}. OpenClaw sẽ **cắt bớt khi dựng prompt** "
                    "mà không báo, nên agent chỉ thấy phần đầu.")
        profile["files"] = files
        profile["sources"]["files"] = "gateway"

        profile["budget"] = {
            "total_chars": total,
            "total_max_chars": ocp.BOOTSTRAP_TOTAL_MAX_CHARS,
            "over_budget": total > ocp.BOOTSTRAP_TOTAL_MAX_CHARS,
            "note": "Tổng của mọi file bootstrap. Vượt thì bị cắt âm thầm ở tầng prompt.",
        }
        if profile["budget"]["over_budget"]:
            warnings.append(
                f"Tổng {total} ký tự vượt hạn mức chung "
                f"{ocp.BOOTSTRAP_TOTAL_MAX_CHARS}; hồ sơ sẽ bị cắt khi dựng prompt.")

        profile["tabs"] = self._tab_map()
        return profile

    def _db_part(self, agent: Agent, member: Member) -> dict:
        department = self.db.get(Department, member.department_id) if member.department_id else None
        company = self.db.get(Company, member.company_id) if member.company_id else None
        manager = self.db.get(Member, member.manager_id) if getattr(member, "manager_id", None) else None
        return {
            "agent_id": agent.id,
            "member_id": member.id,
            "name": member.name,
            "role": member.role,
            "status": member.status,
            "member_type": member.member_type,
            "department": department.name if department else "",
            "company": company.name if company else "",
            "manager": manager.name if manager else "",
            "lifecycle": agent.lifecycle,
            "model_recorded_in_db": agent.model,
            "success_rate": agent.success_rate,
            "cost_30d": agent.cost_30d,
            "risk": agent.risk,
            # Nói thẳng: hai con số trên là của ClawCompany tự ghi, chưa đối
            # chiếu với usage.cost của gateway (việc đó là WP-1.4).
            "cost_source": "usage_events (ClawCompany), chưa đối chiếu usage.cost",
        }

    async def _read_file(self, runtime_agent_id: str, name: str) -> dict:
        try:
            payload = await self.runtime.rpc(
                ocp.M_AGENTS_FILES_GET, {"agentId": runtime_agent_id, "name": name})
        except Exception as exc:                          # noqa: BLE001
            return {"name": name, "tab": FILE_TABS.get(name, ""), "error": str(exc),
                    "missing": None, "content": "", "hash": "", "chars": 0,
                    "max_chars": char_budget(name)}

        record = payload.get("file") if isinstance(payload.get("file"), dict) else payload
        content = record.get("content") or ""
        chars = len(content)
        limit = char_budget(name)
        return {
            "name": name,
            "tab": FILE_TABS.get(name, ""),
            "missing": bool(record.get("missing")),
            # `expectedAbsent: true` nghĩa là vắng mặt là bình thường (MEMORY.md
            # chưa có gì để nhớ), khác với vắng mặt vì lỗi.
            "expected_absent": bool(record.get("expectedAbsent")),
            "content": content,
            "hash": record.get("hash", ""),
            "size": record.get("size", 0),
            "updated_at_ms": record.get("updatedAtMs"),
            "chars": chars,
            "max_chars": limit,
            "over_budget": chars > limit,
            "looks_like_shipped_sample": _looks_like_sample(name, content),
        }

    def _tab_map(self) -> dict:
        """Sáu tab, và mỗi tab ghi bằng cách nào — để UI không phải đoán."""
        return {
            "profile": {"label": "Hồ sơ", "files": ["IDENTITY.md"],
                        "config_keys": list(CONFIG_TABS["profile"])},
            "personality": {"label": "Tính cách", "files": ["SOUL.md"], "config_keys": []},
            "job": {"label": "Công việc", "files": ["AGENTS.md", "USER.md"],
                    "config_keys": []},
            "capability": {"label": "Năng lực", "files": [],
                           "config_keys": list(CONFIG_TABS["capability"])},
            "permission": {"label": "Quyền", "files": [],
                           "config_keys": list(CONFIG_TABS["permission"])},
            "budget": {"label": "Hạn mức", "files": [],
                       "config_keys": list(CONFIG_TABS["budget"])},
            "memory": {"label": "Bộ nhớ", "files": ["MEMORY.md"], "config_keys": [],
                       "note": "Tầng ký ức khác (DREAMS.md, memory/YYYY-MM-DD.md) "
                               "đọc qua agents.workspace.get — thuộc WP-2.4."},
        }

    # -- ghi file (tab 1-3) ------------------------------------------------

    async def write_file(self, agent_id: int, organization_id: int, *, name: str,
                         content: str, expected_hash: str | None,
                         force: bool = False) -> dict:
        """Ghi một file bootstrap, mặc định là ghi **có điều kiện**.

        ``force=True`` bỏ ``expectedHash`` và ghi đè vô điều kiện. Có nút đó vì
        đôi khi cần, nhưng nó phải là một lựa chọn nói ra được, không phải hành
        vi mặc định: upstream nói rõ "Omitting expectedHash keeps the
        unconditional overwrite".
        """
        agent, _ = self.seat_row(agent_id, organization_id)
        runtime_agent_id = (agent.runtime_agent_id or "").strip()
        if not runtime_agent_id:
            raise SeatError("no_seat", "seat chưa gắn runtime_agent_id")
        if name not in SEAT_FILES:
            raise SeatError("unsupported_file",
                            f"chỉ ghi được {', '.join(SEAT_FILES)}; "
                            f"{name} không thuộc nhóm file bootstrap",
                            file=name, supported=list(SEAT_FILES))

        limit = char_budget(name)
        if len(content) > limit:
            # Từ chối, chứ không cắt hộ. Cắt hộ là lặp lại đúng hành vi âm thầm
            # của tầng prompt, chỉ sớm hơn một bước.
            raise SeatError(
                "over_budget",
                f"{name} dài {len(content)} ký tự, vượt hạn mức {limit}. "
                "OpenClaw sẽ cắt âm thầm khi dựng prompt, nên viết ngắn lại "
                "thay vì để hệ thống chọn hộ phần nào bị mất.",
                file=name, chars=len(content), max_chars=limit)

        if not force and not expected_hash:
            raise SeatError(
                "hash_required",
                f"thiếu expected_hash cho {name}. Đọc hồ sơ để lấy hash hiện tại, "
                "hoặc truyền force=true nếu thật sự muốn ghi đè vô điều kiện.",
                file=name)
        if expected_hash and not force:
            if len(expected_hash) != ocp.AGENT_FILE_HASH_LENGTH:
                raise SeatError("bad_hash",
                                f"expectedHash phải đúng {ocp.AGENT_FILE_HASH_LENGTH} "
                                "ký tự hex (SHA-256)", file=name)

        params: dict[str, Any] = {"agentId": runtime_agent_id, "name": name,
                                  "content": content}
        if expected_hash and not force:
            params["expectedHash"] = expected_hash

        try:
            payload = await self.runtime.rpc(ocp.M_AGENTS_FILES_SET, params)
        except Exception as exc:                          # noqa: BLE001
            detail_type = getattr(exc, "detail_type", "")
            if detail_type == ocp.ERR_AGENT_FILE_CONFLICT:
                current = str(getattr(exc, "details", {}).get("currentHash", ""))
                raise SeatFileConflict(name, current) from exc
            raise

        record = payload.get("file") if isinstance(payload.get("file"), dict) else {}
        return {
            "ok": bool(payload.get("ok", True)),
            "file": name,
            "hash": record.get("hash", ""),
            "size": record.get("size", 0),
            "chars": len(content),
            "max_chars": limit,
            "conditional": "expectedHash" in params,
            # Nói ra để người dùng biết vì sao chưa thấy hiệu lực ngay: file mới
            # được nạp ở lần dựng prompt kế tiếp, không phải giữa một lượt chạy.
            "note": "File có hiệu lực từ lượt chạy kế tiếp của agent; một phiên "
                    "đang chạy vẫn dùng prompt đã dựng.",
        }

    # -- ghi config (tab 4-6) ----------------------------------------------

    async def write_config(self, agent_id: int, organization_id: int, *, tab: str,
                           values: dict[str, Any], base_hash: str | None = None,
                           allow_restart: bool = False,
                           dry_run: bool = False) -> dict:
        """Ghi cấu hình của một seat qua :class:`ConfigRegistry`.

        Khoá được phép ghi bị giới hạn theo tab (:data:`CONFIG_TABS`). Không
        phải vì frontend đáng tin, mà vì nó **không** đáng tin: một tab "Năng
        lực" gửi kèm ``tools.allow`` phải bị chặn ở server.
        """
        agent, _ = self.seat_row(agent_id, organization_id)
        runtime_agent_id = (agent.runtime_agent_id or "").strip()
        if not runtime_agent_id:
            raise SeatError("no_seat", "seat chưa gắn runtime_agent_id")

        allowed = CONFIG_TABS.get(tab)
        if allowed is None:
            raise SeatError("unknown_tab", f"tab {tab} không ghi cấu hình",
                            writable_tabs=sorted(CONFIG_TABS))
        if not values:
            raise SeatError("empty", "không có giá trị nào để ghi")

        rejected = [key for key in values if key not in allowed]
        if rejected:
            raise SeatError(
                "key_not_in_tab",
                f"tab '{tab}' không được ghi: {', '.join(rejected)}",
                rejected=rejected, allowed=list(allowed))

        # Khoá tương đối ("identity.name") thành path tuyệt đối của seat.
        patch = {self.registry.entry_path(runtime_agent_id, *key.split(".")): value
                 for key, value in values.items()}
        replace_paths = [
            self.registry.entry_path(runtime_agent_id, *key.split("."))
            for key in values if key in ARRAY_CONFIG_KEYS
        ]

        try:
            return await self.registry.patch(
                patch, base_hash=base_hash, replace_paths=replace_paths,
                note=f"ClawCompany seat {runtime_agent_id} · tab {tab}",
                allow_restart=allow_restart, dry_run=dry_run)
        except ConfigError as exc:
            raise SeatError(exc.reason, str(exc), **exc.details) from exc


def _looks_like_sample(name: str, content: str) -> bool:
    """File này còn là mẫu xuất xưởng của OpenClaw chứ chưa ai viết?

    Phát hiện thật lúc làm WP-2.1: seat ``dev`` mang ``identity.name = "Nina"``
    trong config, nhưng ``SOUL.md`` vẫn là bản mẫu về "C-3PO" mà OpenClaw seed
    sẵn. Nghĩa là **tính cách của Nina chưa từng được cấu hình** — UI phải nói
    ra điều đó, vì nhìn hồ sơ thì tưởng đã xong.

    Đây là heuristic, không phải bằng chứng, nên tên trường nói rõ "looks like".
    """
    if not content:
        return False
    markers = ("C-3PO", "Clawd's Third Protocol Observer", "Clawd’s Third Protocol Observer")
    return any(marker in content for marker in markers)
