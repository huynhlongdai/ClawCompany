"""v30: the monotonic revision counter three versions kept postponing.

v27 built its revision token out of ``updated_at`` and said why: no schema
change. v28 kept that choice, v29 kept it again, and each handover repeated
the same admission -- ``updated_at`` has a storage-dependent resolution, so
two writes inside one clock tick can produce the same token. A guard that
cannot tell two writes apart is exactly the guard v28 exists to replace.

This module adds the column (migration ``0013``) and an integer counter that
moves once per guarded write. It never goes backwards and never repeats, so
"did this row change since I read it" has an exact answer.

Backwards compatibility is not optional here: rows written before the
migration have ``row_revision = NULL``, and every client shipped since v27
holds timestamp tokens. So both token shapes are accepted and each one says
which mode it is:

    project:12:r7                 counter mode - exact
    project:12:2026-09-14T10:00   timestamp mode - v27 semantics, ambiguous

Callers that want the guarantee ask for ``token()``; callers that hold an old
token still work, and the response tells them which protection they actually
got instead of implying the stronger one.
"""

from __future__ import annotations

from datetime import datetime

# Entities that carry a counter. Everything else keeps v27 semantics.
COUNTED_KINDS: tuple[str, ...] = ("company", "department", "member", "project", "task")

COUNTER_MODE = "counter"
TIMESTAMP_MODE = "timestamp"


class RevisionError(ValueError):
    """Malformed token. Distinct from a lost race, which is a 409."""


def kind_of(entity) -> str:
    return getattr(entity, "__entity_kind__", None) or entity.__class__.__name__.lower()


def supports_counter(entity) -> bool:
    return kind_of(entity) in COUNTED_KINDS and hasattr(entity, "row_revision")


def counter(entity) -> int | None:
    """Current counter, or ``None`` for a row that predates the migration.

    ``None`` is not zero. A row that has never been counted cannot be
    guarded by counter, and pretending it sits at 0 would let the first
    guarded write claim a guarantee it does not have.
    """
    if not supports_counter(entity):
        return None
    value = getattr(entity, "row_revision", None)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def timestamp_token(entity) -> str:
    stamp = getattr(entity, "updated_at", None)
    return f"{kind_of(entity)}:{entity.id}:{stamp.isoformat() if stamp else '0'}"


def token(entity) -> str:
    """Preferred token: counter when the row has one, timestamp otherwise."""
    count = counter(entity)
    if count is None:
        return timestamp_token(entity)
    return f"{kind_of(entity)}:{entity.id}:r{count}"


def describe(entity) -> dict:
    """Both tokens plus which mode a guarded write would run in."""
    count = counter(entity)
    return {
        "kind": kind_of(entity),
        "id": entity.id,
        "revision": token(entity),
        "legacy_revision": timestamp_token(entity),
        "counter": count,
        "mode": COUNTER_MODE if count is not None else TIMESTAMP_MODE,
        "exact": count is not None,
        # Said out loud so a client can decide whether to trust the guard.
        "note": ("Counter tokens are exact." if count is not None else
                 "This row predates the counter column; timestamp guards "
                 "cannot separate two writes inside one clock tick."),
    }


def parse(raw: str) -> tuple[str, int, str, object]:
    """Split a token into ``(kind, id, mode, value)``.

    Split from the left with a fixed field count: ISO timestamps contain
    colons, and splitting on every colon is how v21 broke policy keys.
    """
    parts = (raw or "").split(":", 2)
    if len(parts) != 3 or not parts[1].isdigit():
        raise RevisionError("Malformed revision token")
    name, row_id, tail = parts[0], int(parts[1]), parts[2]
    if tail.startswith("r") and tail[1:].isdigit():
        return name, row_id, COUNTER_MODE, int(tail[1:])
    if tail == "0":
        return name, row_id, TIMESTAMP_MODE, None
    try:
        return name, row_id, TIMESTAMP_MODE, datetime.fromisoformat(tail)
    except ValueError as exc:
        raise RevisionError("Malformed revision timestamp") from exc


def next_counter(entity) -> int:
    """The value a guarded write should store. Adopts uncounted rows at 1."""
    count = counter(entity)
    return 1 if count is None else count + 1
