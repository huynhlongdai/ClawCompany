"""v31: the before-values v29 and v30 both admitted the audit was missing.

Every handover since v28 repeated the same sentence: ``board.write.guarded``
carries the *names* of the fields that changed, never their previous
contents, so the audit log can answer "who touched status" but not "what did
status used to be". That is the difference between a log and an audit trail.

This module snapshots the guarded columns immediately before the conditional
UPDATE and turns the pair into a per-field diff that goes into the event
payload. Three decisions worth stating plainly:

* The snapshot is taken from the in-session row that the guard is about to
  compare against, not re-read afterwards. Re-reading would race with the
  very writer the guard exists to detect.
* Only guarded writes get diffs. Events written before v31 have no
  before-values and nothing here invents them: ``changes`` is simply absent
  and the reader says so instead of showing an empty "from" column.
* Long text is truncated with a marker rather than stored whole. An audit
  payload is not a document store, and a 40 KB description pasted twice per
  write would make the event table the largest thing in the database.
"""

from __future__ import annotations

from datetime import date, datetime

# Long values are cut here. Chosen to keep a name, status or role intact
# while refusing to carry a full project description twice per event.
MAX_VALUE_CHARS = 500
TRUNCATION_MARKER = "...[truncated]"

# A field the diff must never echo back. Nothing in WRITABLE is a secret
# today, but a guarded write is a generic mechanism and the next version to
# add a column here should not have to remember to redact it.
REDACTED_FIELDS: tuple[str, ...] = ("password", "password_hash", "token",
                                    "secret", "api_key")
REDACTED_PLACEHOLDER = "[redacted]"

# Sentinel for "this write clears the column". JSON null in a request body
# is ambiguous -- v28's guarded write treated null as "leave alone", which
# is why section 20.6 said owner_member_id could not be cleared.
CLEAR = "__clear__"


def is_clear(value) -> bool:
    return isinstance(value, str) and value == CLEAR


def normalize(value):
    """Make a column value JSON-safe and bounded."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    text = str(value)
    if len(text) > MAX_VALUE_CHARS:
        return text[:MAX_VALUE_CHARS] + TRUNCATION_MARKER
    return text


def _safe(field: str, value):
    if field.lower() in REDACTED_FIELDS:
        return REDACTED_PLACEHOLDER
    return normalize(value)


def snapshot(entity, fields) -> dict:
    """Current values of ``fields`` on ``entity``, JSON-safe."""
    return {field: _safe(field, getattr(entity, field, None)) for field in fields}


def diff(before: dict, after: dict) -> dict:
    """Per-field ``{"from": old, "to": new}`` for fields that actually moved.

    A guarded write that sets a column to the value it already held is not a
    change, and recording it would bury the real edits. The revision counter
    still moves, because the row was written -- the audit says what changed,
    not what was attempted.
    """
    out: dict[str, dict] = {}
    for field, new_value in after.items():
        old_value = before.get(field)
        if old_value != new_value:
            out[field] = {"from": old_value, "to": new_value}
    return out


def unchanged(before: dict, after: dict) -> list[str]:
    """Fields the write touched that held the same value already."""
    return sorted(f for f, v in after.items() if before.get(f) == v)


def describe(changes: dict) -> str:
    """One human-readable line for an audit row."""
    if not changes:
        return "no field values changed"
    parts = []
    for field in sorted(changes):
        entry = changes[field] or {}
        parts.append(f"{field}: {_render(entry.get('from'))} -> {_render(entry.get('to'))}")
    return "; ".join(parts)


def _render(value) -> str:
    if value is None:
        return "(empty)"
    text = str(value)
    if text == "":
        return "(blank)"
    if len(text) > 60:
        return text[:60] + "..."
    return text


def reconstruct(rows) -> dict:
    """Walk audit rows newest-first and rebuild each field's value timeline.

    Returns ``{field: [{"from", "to", "event_id", "at", "actor_member_id"}]}``
    newest-first. Rows without a ``changes`` block are counted separately
    rather than skipped silently: a caller needs to know that part of the
    history predates v31 and cannot be reconstructed at all.
    """
    history: dict[str, list[dict]] = {}
    without = 0
    for row in rows:
        changes = row.get("changes") if isinstance(row, dict) else None
        if not isinstance(changes, dict) or not changes:
            if (row.get("category") if isinstance(row, dict) else None) == "write":
                without += 1
            continue
        for field, entry in changes.items():
            history.setdefault(field, []).append({
                "from": (entry or {}).get("from"),
                "to": (entry or {}).get("to"),
                "event_id": row.get("id"),
                "at": row.get("occurred_at") or "",
                "actor_member_id": row.get("actor_member_id"),
            })
    return {
        "fields": history,
        "field_names": sorted(history),
        "writes_without_values": without,
        "note": ("Guarded writes made before v31 recorded field names only, so "
                 "their previous values cannot be reconstructed."
                 if without else ""),
    }
