"""v28: the race window v27 admitted to, actually closed.

v27 shipped ``check_revision``, which compares a token against the row it
just loaded and raises 409 on a mismatch. That catches the case it was
built for -- a human editing a stale form -- but section 18.7 of the
handover said the rest out loud: two writers who read the *same* revision
and race at the millisecond level both pass the check, because nothing
between the check and the write holds the row.

This module does the write itself as a conditional UPDATE:

    UPDATE projects SET ... WHERE id = :id AND updated_at = :expected

The database decides. If ``rowcount`` is 0 the row moved under us and the
write never happened, so the 409 is a statement about what the database
did, not a guess made a moment earlier.

Why not just use this everywhere and delete ``check_revision``? Because a
conditional UPDATE can only reject; it cannot tell a caller *why* before
trying, and a preview endpoint (``archive/preview``) must be able to
validate a revision without writing. The two are kept, with one honest
difference: ``check_revision`` is advisory, ``compare_and_set`` is binding.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.services import field_diff as fd
from app.services import row_revision as rev
from app.services.board_truth import CONFLICT_EVENT, revision
from app.services.company_event_bus import emit_event

SOURCE = "row_guard"

# A guarded write may only touch columns listed here. Taking the field list
# from the request body would let a caller with workspace:write set
# organization_id or runtime_session_key through a generic endpoint, which is
# a much larger grant than "edit this project".
WRITABLE: dict[str, tuple[str, ...]] = {
    "project": ("name", "description", "status", "progress", "owner_member_id"),
    "task": ("title", "description", "status", "priority", "assignee_member_id"),
    "company": ("name", "industry", "status"),
    "department": ("name", "head_member_id", "access_level", "status"),
    "member": ("name", "role", "status", "manager_id"),
}


# v31: columns a guarded write may set back to NULL. Everything else
# rejects a clear, because "" and NULL are not interchangeable for a name
# and a NOT NULL column would fail at the database with a 500 instead.
CLEARABLE: dict[str, tuple[str, ...]] = {
    "project": ("description", "owner_member_id"),
    "task": ("description", "assignee_member_id"),
    "department": ("head_member_id",),
    "member": ("manager_id",),
    "company": ("industry",),
}


def clearable_fields(entity) -> tuple[str, ...]:
    return CLEARABLE.get(kind(entity), ())


class GuardError(ValueError):
    """Raised for a malformed guard request, not for a lost race."""


def kind(entity) -> str:
    """One definition of "kind" for the whole guarded-write path.

    This used to be ``entity.__class__.__name__.lower()``, which disagreed
    with ``row_revision.kind_of()`` -- the function that *builds and parses*
    the revision token this module then compares against. For the five ORM
    entities the two happened to return the same string, so the split never
    surfaced; but ``compare_and_set`` reads the kind out of a token via
    ``rev.parse_revision`` and checks it against this function, so two
    definitions in one code path is a guard that can disagree with itself.
    Delegating removes the fork and honours ``__entity_kind__``.
    """
    return rev.kind_of(entity)


def parse_revision(token: str) -> tuple[str, int, datetime | None]:
    """Split a revision token back into its parts.

    The timestamp is ISO-8601, which contains colons, so the split is done
    from the left with a fixed field count -- splitting on every colon is how
    v21 broke policy keys that contained session keys.
    """
    parts = (token or "").split(":", 2)
    if len(parts) != 3 or not parts[1].isdigit():
        raise GuardError("Malformed revision token")
    name, raw_id, stamp = parts[0], int(parts[1]), parts[2]
    if stamp == "0":
        return name, raw_id, None
    try:
        return name, raw_id, datetime.fromisoformat(stamp)
    except ValueError as exc:  # noqa: PERF203
        raise GuardError("Malformed revision timestamp") from exc


def allowed_fields(entity) -> tuple[str, ...]:
    return WRITABLE.get(kind(entity), ())


def _conflict(db: Session, entity, expected: str, organization_id: int | None) -> HTTPException:
    db.refresh(entity)
    # v30: report the preferred token. A client that lost the race should
    # retry with the strongest token the row can offer, not the weakest.
    current = rev.token(entity)
    if organization_id is not None:
        try:
            emit_event(db, organization_id=organization_id, event_type=CONFLICT_EVENT,
                       source=SOURCE, aggregate_type=kind(entity), aggregate_id=str(entity.id),
                       payload={"expected": expected, "current": current, "binding": True})
        except Exception:  # noqa: BLE001 - a failed event never becomes a 500
            pass
    return HTTPException(409, detail={
        "error": "Lost the write race: the row changed before this update landed",
        "expected_revision": expected,
        "current_revision": current,
        "applied": False,
        "binding": True,
    })


def compare_and_set(db: Session, entity, values: dict, *, expected_revision: str,
                    organization_id: int | None = None,
                    actor_member_id: int | None = None) -> dict:
    """Apply ``values`` only if the row still matches ``expected_revision``.

    Unlike v27's advisory check, ``expected_revision`` is **required** here:
    a compare-and-set with nothing to compare against is just an UPDATE, and
    an endpoint that silently degrades to an unguarded write is worse than
    one that refuses.
    """
    if not expected_revision:
        raise GuardError("expected_revision is required for a guarded write")
    try:
        name, row_id, mode, expected_value = rev.parse(expected_revision)
    except rev.RevisionError as exc:
        raise GuardError(str(exc)) from exc
    if name != kind(entity) or row_id != entity.id:
        raise GuardError("Revision token belongs to a different row")
    if mode == rev.COUNTER_MODE and not rev.supports_counter(entity):
        raise GuardError("This row has no revision counter; use a timestamp token")

    fields = allowed_fields(entity)
    if not fields:
        raise GuardError(f"No guarded fields defined for {kind(entity)}")
    unknown = sorted(set(values) - set(fields))
    if unknown:
        raise GuardError(f"Fields not writable through a guarded update: {', '.join(unknown)}")
    # v31: JSON null still means "leave this column alone" -- that is what
    # every client shipped since v28 assumes. Clearing is a separate,
    # explicit request via the CLEAR sentinel, which is why section 20.6
    # could not clear owner_member_id without this.
    changes: dict = {}
    # v31 bugfix: this loop must not bind a name the guard condition below
    # still needs. An earlier draft called the loop variable ``value``,
    # which shadowed the parsed expected revision and made the conditional
    # UPDATE compare the row against the last value being written -- a
    # guard that could never match, and the whole point of v28.
    for field, incoming in values.items():
        if fd.is_clear(incoming):
            if field not in clearable_fields(entity):
                raise GuardError(f"Field cannot be cleared: {field}")
            changes[field] = None
        elif incoming is not None:
            changes[field] = incoming
    if not changes:
        raise GuardError("No values to write")

    # Snapshot before the UPDATE, from the row the guard is about to
    # compare against. Re-reading afterwards would race with the writer
    # the guard exists to catch.
    before = fd.snapshot(entity, list(changes))

    model = type(entity)
    now = datetime.utcnow()
    # updated_at is set explicitly: onupdate fires for ORM flushes, and this
    # is a Core UPDATE. Without it the revision would not move and the next
    # writer would pass a guard it should have failed.
    written = dict(changes)
    written["updated_at"] = now
    if rev.supports_counter(entity):
        # v30: the counter moves on every guarded write, including writes
        # guarded by an old timestamp token. That is how a row stops being
        # uncounted without a separate backfill pass.
        written["row_revision"] = rev.next_counter(entity)
    if mode == rev.COUNTER_MODE:
        condition = model.row_revision == expected_value
    else:
        condition = model.updated_at == expected_value
    stmt = (update(model)
            .where(model.id == entity.id, condition)
            .values(**written))
    result = db.execute(stmt)
    if (result.rowcount or 0) == 0:
        db.rollback()
        raise _conflict(db, entity, expected_revision, organization_id)
    db.commit()
    db.refresh(entity)

    after = rev.token(entity)
    written_values = fd.snapshot(entity, list(changes))
    field_changes = fd.diff(before, written_values)
    no_ops = fd.unchanged(before, written_values)
    if organization_id is not None:
        try:
            emit_event(db, organization_id=organization_id, event_type="board.write.guarded",
                       source=SOURCE, aggregate_type=kind(entity), aggregate_id=str(entity.id),
                       payload={"fields": sorted(changes), "revision": after,
                                # v31: the before-values v29 and v30 both
                                # said the audit was missing.
                                "changes": field_changes,
                                "unchanged": no_ops,
                                "actor_member_id": actor_member_id})
        except Exception:  # noqa: BLE001
            pass
    return {"entity": kind(entity), "id": entity.id, "applied": True,
            "fields": sorted(changes), "changes": field_changes,
            "unchanged": no_ops, "previous_revision": expected_revision,
            "revision": after,
            # Said out loud: a timestamp-guarded write is v27-grade and can
            # still collide inside one clock tick. Only counter mode is exact.
            "guard_mode": mode,
            "exact": mode == rev.COUNTER_MODE,
            "legacy_revision": rev.timestamp_token(entity)}
