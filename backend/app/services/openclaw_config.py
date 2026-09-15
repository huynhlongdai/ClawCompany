"""WP-1.2 — Config Registry: đọc schema sống của gateway và ghi có kiểm soát.

Module này là nền cho mọi màn hình cấu hình của ClawCompany. Không có nó thì
cách duy nhất để đổi model, tính cách hay quyền của một agent là SSH vào máy
gateway sửa ``openclaw.json`` bằng tay.

Bốn mệnh đề của upstream mà module này tuân theo, trích nguyên văn từ
``docs/gateway/configuration/config-rpc.md`` của ``openclaw@2026.9.4``:

1. ``config.patch`` nhận ``raw``, ``baseHash``, ``sessionKey``, ``note``,
   ``restartDelayMs``. **``raw`` là một chuỗi** chứa cấu hình (JSON5), không
   phải một object — gửi object là sai kiểu.
2. "``baseHash`` is required for both methods once a config file already
   exists" — nên service tự lấy hash nếu caller không truyền.
3. "If a patch removes existing array entries or deletes an array, the Gateway
   rejects the write unless that exact array path appears in ``replacePaths``."
   Và: "Parent paths and ``*`` wildcards do not authorize descendant arrays."
4. Ghi ở control plane bị giới hạn "30 requests per 60 seconds, per method,
   per deviceId+clientIp".

Ba lựa chọn thiết kế đáng nói, vì chúng là chỗ dễ mất dữ liệu:

* **Chặn tại chỗ trước khi gửi.** Nếu một patch làm mất phần tử mảng mà caller
  chưa khai ``replacePaths``, service từ chối ngay thay vì để gateway từ chối.
  Lý do: thông báo lỗi của ta nói được *mảng nào* và *mất phần tử nào*, còn
  gateway chỉ nói yêu cầu bị từ chối.
* **Wildcard bị từ chối thẳng.** Hai file docs nói khác nhau về việc
  ``agents.entries.*.skills`` có hợp lệ hay không (xem ``ocp.DOC_CONFLICTS``).
  Ta theo bản nghiêm hơn: chỉ nhận khoá bản ghi chính xác.
* **Tự đếm nhịp ghi.** Vượt hạn mức thì trả lỗi có ``retry_after`` chứ không
  nã tiếp vào gateway.

Mọi hàm ở đây **không** tự quyết định cấu hình đúng hay sai về nghiệp vụ. Nó
chỉ lo: hỏi schema, so hash, dựng patch tối thiểu, và nói thật chuyện gì vừa
xảy ra.
"""
from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Sequence
from typing import Any

from app.runtime import openclaw_protocol as ocp

# Đường dẫn cấu hình: hoặc chuỗi phân tách bằng dấu chấm, hoặc tuple từng đoạn.
# Tuple là bắt buộc khi một khoá bản ghi có chứa dấu chấm trong tên.
ConfigPath = str | tuple[str, ...]

_PLACEHOLDER_SEGMENTS = ("*", "[]")


class ConfigError(RuntimeError):
    """Lỗi có thể giải thích cho người dùng, kèm mã lý do."""

    def __init__(self, reason: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.reason = reason
        self.details = details

    def as_dict(self) -> dict:
        return {"reason": self.reason, "message": str(self), **self.details}


class RateLimited(ConfigError):
    def __init__(self, method: str, retry_after: float) -> None:
        super().__init__(
            "rate_limited",
            f"{method} đã đạt hạn mức {ocp.CONTROL_PLANE_RATE_LIMIT[0]} lần/"
            f"{ocp.CONTROL_PLANE_RATE_LIMIT[1]}s; thử lại sau {retry_after:.1f}s",
            method=method,
            retry_after=round(retry_after, 3),
        )


# --------------------------------------------------------------- path helpers

def split_path(path: ConfigPath) -> tuple[str, ...]:
    if isinstance(path, tuple):
        segments = path
    else:
        segments = tuple(p for p in str(path).split(".") if p != "")
    if not segments:
        raise ConfigError("empty_path", "đường dẫn cấu hình rỗng")
    return segments


def join_path(segments: Sequence[str]) -> str:
    return ".".join(segments)


def _nest(values: dict[ConfigPath, Any]) -> dict:
    """Biến {"a.b": 1, "a.c": 2} thành {"a": {"b": 1, "c": 2}}.

    ``None`` được giữ nguyên: trong JSON merge patch, ``null`` nghĩa là **xoá**
    khoá đó, và đó là một hành động hợp lệ mà caller có thể muốn.
    """
    root: dict[str, Any] = {}
    for path, value in values.items():
        segments = split_path(path)
        cursor = root
        for segment in segments[:-1]:
            existing = cursor.get(segment)
            if existing is None:
                existing = {}
                cursor[segment] = existing
            elif not isinstance(existing, dict):
                raise ConfigError(
                    "path_collision",
                    f"đường dẫn {join_path(segments)} đè lên một giá trị đã đặt ở "
                    f"{segment}; không thể vừa đặt giá trị vừa đặt khoá con",
                    path=join_path(segments),
                )
            cursor = existing
        cursor[segments[-1]] = value
    return root


def _read_at(config: Any, segments: Sequence[str]) -> Any:
    cursor = config
    for segment in segments:
        if not isinstance(cursor, dict) or segment not in cursor:
            return None
        cursor = cursor[segment]
    return cursor


# ------------------------------------------------------- replacePaths guard

def _arrays_at_risk(current: dict, patch: dict, prefix: tuple[str, ...] = ()) -> list[dict]:
    """Những mảng mà patch này làm mất phần tử, hoặc xoá hẳn.

    Đúng theo luật của upstream: chỉ **mất** phần tử mới cần khai
    ``replacePaths``. Thêm phần tử vào cuối thì không.

    Trả về danh sách mô tả, không phải chỉ danh sách path, để thông báo lỗi nói
    được mất bao nhiêu phần tử — người dùng cần biết mình đang xoá gì.
    """
    risks: list[dict] = []
    for key, new_value in patch.items():
        here = prefix + (key,)
        old_value = _read_at(current, here)

        if isinstance(old_value, list):
            if new_value is None:
                risks.append({"path": join_path(here), "kind": "deleted",
                              "removed": len(old_value)})
            elif isinstance(new_value, list):
                kept = sum(1 for item in old_value if item in new_value)
                if kept < len(old_value):
                    risks.append({"path": join_path(here), "kind": "entries_removed",
                                  "removed": len(old_value) - kept,
                                  "was": len(old_value), "now": len(new_value)})
            else:
                # Mảng bị thay bằng một kiểu khác: mọi phần tử mất.
                risks.append({"path": join_path(here), "kind": "replaced_by_scalar",
                              "removed": len(old_value)})
            continue

        if isinstance(new_value, dict):
            risks.extend(_arrays_at_risk(current, new_value, here))
            continue

        if new_value is None and isinstance(old_value, dict):
            # "Deleting a containing object requires its contained array paths,
            # including empty arrays."
            for path in _contained_array_paths(old_value, here):
                risks.append({"path": path, "kind": "deleted_with_parent", "removed": None})

    return risks


def _contained_array_paths(node: Any, prefix: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.extend(_contained_array_paths(value, prefix + (key,)))
    elif isinstance(node, list):
        found.append(join_path(prefix))
    return found


def validate_replace_paths(paths: Sequence[ConfigPath]) -> list[str]:
    """Chuẩn hoá và từ chối những dạng upstream không chấp nhận.

    ``config-rpc.md``: "Use exact record keys, such as
    ``agents.entries.main.skills``. ... Parent paths and ``*`` wildcards do not
    authorize descendant arrays."

    Ngoại lệ duy nhất là ``[]`` cho mảng lồng trong entry được merge theo ``id``
    (ví dụ ``models.providers.custom.models[].input``) — đó là cú pháp upstream
    chỉ định, không phải wildcard.
    """
    out: list[str] = []
    for path in paths or ():
        segments = split_path(path)
        for segment in segments:
            if segment == "*":
                raise ConfigError(
                    "wildcard_replace_path",
                    f"replacePaths không nhận wildcard: {join_path(segments)}. "
                    "Phải khai khoá bản ghi chính xác, ví dụ "
                    "agents.entries.main.skills. Xem openclaw_protocol.DOC_CONFLICTS: "
                    "hai file docs của upstream nói khác nhau về điểm này và ta "
                    "theo bản nghiêm hơn.",
                    path=join_path(segments),
                )
        out.append(join_path(segments))
    return out


# --------------------------------------------------------------- rate limiter

class _WriteBudget:
    """Nhịp ghi control-plane, đếm theo từng method như upstream giới hạn."""

    def __init__(self, limit: int | None = None, window: float | None = None) -> None:
        default_limit, default_window = ocp.CONTROL_PLANE_RATE_LIMIT
        self.limit = limit or default_limit
        self.window = window or default_window
        self._calls: dict[str, deque[float]] = {}

    def check(self, method: str, *, now: float | None = None) -> None:
        moment = now if now is not None else time.monotonic()
        calls = self._calls.setdefault(method, deque())
        while calls and moment - calls[0] >= self.window:
            calls.popleft()
        if len(calls) >= self.limit:
            raise RateLimited(method, self.window - (moment - calls[0]))
        calls.append(moment)


# ------------------------------------------------------------------- registry

class ConfigRegistry:
    """Đọc/ghi cấu hình gateway. Một instance cho một runtime adapter.

    ``runtime`` chỉ cần có ``async def rpc(method, params) -> dict`` —
    ``NativeOpenClawRuntime.rpc`` đáp ứng, và một fake trong test cũng vậy.
    """

    def __init__(self, runtime: Any, *, budget: _WriteBudget | None = None) -> None:
        self.runtime = runtime
        self.budget = budget or _WriteBudget()
        self._schema_cache: dict[str, dict] = {}

    # -- đọc ---------------------------------------------------------------

    async def snapshot(self) -> dict:
        """``config.get``: cấu hình hiện tại kèm các hash để so sánh.

        Upstream trả "raw root-file ``hash``, resolved ``configRevisionHash``,
        and optional ``appliedConfigHash`` for the resolved revision accepted by
        the active Gateway runtime". ``hash`` mới là cái dùng cho ``baseHash``;
        ``appliedConfigHash`` cho biết bản đã *áp dụng* — hai thứ khác nhau khi
        có một lần ghi đã lưu nhưng chưa được nạp.
        """
        payload = await self.runtime.rpc(ocp.M_CONFIG_GET, {})
        config = payload.get("config")
        if not isinstance(config, dict):
            config = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        return {
            "config": config,
            "hash": payload.get("hash", ""),
            "config_revision_hash": payload.get("configRevisionHash", ""),
            "applied_config_hash": payload.get("appliedConfigHash", ""),
            # Đã lưu nhưng chưa áp dụng: UI phải nói rõ, không được hiện như đã xong.
            "pending_apply": bool(
                payload.get("appliedConfigHash")
                and payload.get("configRevisionHash")
                and payload["appliedConfigHash"] != payload["configRevisionHash"]
            ),
        }

    async def schema_node(self, path: ConfigPath, *, use_cache: bool = True) -> dict:
        """``config.schema.lookup`` cho đúng một path.

        Trả về ``reload_kind`` (``restart`` | ``hot`` | ``none``), node schema
        nông, và danh sách khoá con để UI đi sâu dần. Có cache vì một form mở ra
        sẽ hỏi hàng chục path và hạn mức đọc không đáng để tiêu.
        """
        normalized = join_path(split_path(path))
        if use_cache and normalized in self._schema_cache:
            return self._schema_cache[normalized]

        payload = await self.runtime.rpc(ocp.M_CONFIG_SCHEMA_LOOKUP, {"path": normalized})
        reload_kind = payload.get("reloadKind")
        if reload_kind is not None and reload_kind not in ocp.RELOAD_KINDS:
            # Upstream có thể thêm giá trị mới; nói ra thay vì im lặng coi là hot.
            reload_kind = f"unknown:{reload_kind}"
        node = {
            "path": payload.get("path", normalized),
            "reload_kind": reload_kind,
            "requires_restart": reload_kind == ocp.RELOAD_RESTART,
            "schema": payload.get("schema") or payload.get("node") or {},
            "hint": payload.get("hint", ""),
            "hint_path": payload.get("hintPath", ""),
            "children": payload.get("children") or [],
        }
        self._schema_cache[normalized] = node
        return node

    async def full_schema(self) -> dict:
        """``config.schema``: toàn bộ schema kèm ``uiHints``. **Rất to.**

        Đo được trên một gateway 2026.9.4 thật: **2.213.650 byte** — gấp 2,1 lần
        hạn mức frame mặc định 1 MiB của thư viện ``websockets``, nên trước
        WP-1.2 lời gọi này chết với ``1009 message too big`` và không ai biết vì
        chưa ai gọi. Nay ``settings.openclaw_max_frame_bytes`` nâng lên 16 MiB.

        Dù gọi được, **đừng gọi nó cho mỗi lần mở form**: dùng
        :meth:`schema_node` cho từng path. Hàm này để sinh tài liệu hoặc nạp
        cache một lần lúc khởi động.
        """
        payload = await self.runtime.rpc(ocp.M_CONFIG_SCHEMA, {})
        return {
            "schema": payload.get("schema") or {},
            "ui_hints": payload.get("uiHints") or {},
            "version": payload.get("version"),
            "generated_at": payload.get("generatedAt"),
        }

    async def reload_plan(self, paths: Sequence[ConfigPath]) -> dict:
        """Ghi những path này thì có phải khởi động lại gateway không.

        Gọi **trước** khi người dùng bấm Lưu. Cảnh báo sau khi ghi là vô dụng:
        lúc đó gateway đã ở trạng thái nửa vời.
        """
        per_path: dict[str, str | None] = {}
        for path in paths:
            node = await self.schema_node(path)
            per_path[node["path"]] = node["reload_kind"]
        return {
            "paths": per_path,
            "requires_restart": any(kind == ocp.RELOAD_RESTART for kind in per_path.values()),
            "unknown": sorted(p for p, k in per_path.items()
                              if k is None or str(k).startswith("unknown:")),
        }

    # -- ghi ---------------------------------------------------------------

    async def patch(
        self,
        values: dict[ConfigPath, Any],
        *,
        base_hash: str | None = None,
        replace_paths: Sequence[ConfigPath] = (),
        note: str = "",
        session_key: str = "",
        restart_delay_ms: int | None = None,
        allow_restart: bool = False,
        dry_run: bool = False,
    ) -> dict:
        """Ghi một patch tối thiểu, sau khi đã kiểm bốn điều kiện.

        ``allow_restart=False`` (mặc định) khiến một patch chạm vào path
        ``reloadKind: "restart"`` bị từ chối. Ý đồ: không ai vô tình khởi động
        lại gateway của cả công ty khi đang sửa một dòng mô tả công việc. Muốn
        làm thì phải nói ra.

        ``dry_run=True`` trả về đúng những gì *sẽ* gửi, không gọi gateway —
        dùng cho màn hình xem trước và cho test.
        """
        if not values:
            raise ConfigError("empty_patch", "không có giá trị nào để ghi")

        authorized = validate_replace_paths(replace_paths)
        patch_tree = _nest(values)

        current = await self.snapshot()
        effective_base = base_hash if base_hash is not None else current["hash"]
        # "baseHash is required ... once a config file already exists (a first
        # write with no existing config skips the check)."
        if not effective_base and current["config"]:
            raise ConfigError(
                "missing_base_hash",
                "cấu hình đã tồn tại nhưng không lấy được baseHash từ config.get; "
                "ghi mà không có baseHash là ghi đè mù",
            )

        risks = _arrays_at_risk(current["config"], patch_tree)
        unauthorized = [r for r in risks if r["path"] not in authorized]
        if unauthorized:
            raise ConfigError(
                "replace_path_required",
                "patch này làm mất phần tử mảng; phải khai chính xác các path đó "
                "trong replace_paths: " + ", ".join(r["path"] for r in unauthorized),
                arrays=unauthorized,
            )

        plan = await self.reload_plan(list(values.keys()))
        if plan["requires_restart"] and not allow_restart:
            raise ConfigError(
                "restart_required",
                "patch này chạm vào cấu hình cần khởi động lại gateway: "
                + ", ".join(p for p, k in plan["paths"].items() if k == ocp.RELOAD_RESTART)
                + ". Gọi lại với allow_restart=True nếu đúng ý.",
                paths=plan["paths"],
            )

        params: dict[str, Any] = {"raw": json.dumps(patch_tree, ensure_ascii=False)}
        if effective_base:
            params["baseHash"] = effective_base
        if authorized:
            params["replacePaths"] = authorized
        if note:
            params["note"] = note
        if session_key:
            params["sessionKey"] = session_key
        if restart_delay_ms is not None:
            params["restartDelayMs"] = restart_delay_ms

        preview = {
            "method": ocp.M_CONFIG_PATCH,
            "params": params,
            "reload": plan,
            "arrays_authorized": authorized,
            "base_hash_source": "caller" if base_hash is not None else "config.get",
        }
        if dry_run:
            return {"dry_run": True, **preview}

        self.budget.check(ocp.M_CONFIG_PATCH)
        payload = await self.runtime.rpc(ocp.M_CONFIG_PATCH, params)

        return {
            "dry_run": False,
            "applied": True,
            # "Its successful response includes changedPaths, the effective
            # runtime paths changed after validation and secret restoration, or
            # [] for a no-op." Một mảng rỗng nghĩa là không có gì đổi — đó là
            # câu trả lời thật, không phải lỗi.
            "changed_paths": payload.get("changedPaths", []),
            "no_op": payload.get("changedPaths") == [],
            "reload": plan,
            "requires_restart": plan["requires_restart"],
            "base_hash": effective_base,
            # Cùng trường với bản dry_run: người soát xét cần biết hash đem đi so
            # là của caller hay do service tự lấy — hai trường hợp có ý nghĩa
            # kiểm toán khác nhau.
            "base_hash_source": preview["base_hash_source"],
            "arrays_authorized": authorized,
            "raw_payload": payload,
        }

    # -- tiện ích cho tầng trên -------------------------------------------

    async def agent_entry(self, agent_id: str) -> dict:
        """Cấu hình hiệu dụng của một seat: defaults trộn với entry của nó.

        Trả về cả ba lớp để UI hiển thị được "giá trị này là của riêng seat hay
        thừa hưởng từ defaults" — người vận hành cần phân biệt, vì sửa defaults
        là sửa cho cả công ty.
        """
        snapshot = await self.snapshot()
        agents = _read_at(snapshot["config"], ("agents",)) or {}
        defaults = agents.get("defaults") or {}
        entry = ((agents.get("entries") or {}).get(agent_id)) or {}
        effective = {**defaults, **entry}
        return {
            "agent_id": agent_id,
            "exists": agent_id in (agents.get("entries") or {}),
            "defaults": defaults,
            "entry": entry,
            "effective": effective,
            "inherited_keys": sorted(k for k in effective if k not in entry),
            "hash": snapshot["hash"],
        }

    def entry_path(self, agent_id: str, *keys: str) -> tuple[str, ...]:
        """Path tới cấu hình của một seat, dạng tuple để chịu được tên có dấu chấm."""
        return ("agents", "entries", agent_id, *keys)
