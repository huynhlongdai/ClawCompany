"""v32: before-values for the write paths that never had a guard.

v31 gave guarded writes a field-level diff. It did not touch the ordinary
cockpit write paths -- update_company, update_department, move_member,
update_project, move_task, assign_task -- which kept emitting a 'changed'
map of *new* values only. So the field history screen could reconstruct an
edit made through /api/v28/guarded/... and not the same edit made by
clicking the form, which is the path almost everybody actually uses.

This module is the smallest thing that fixes that: a snapshot taken before
the mutation, compared after it, emitted in the same 'changes' shape that
field_diff already defines and write_audit already reads. No new table, no
new event type, no second format for a reader to learn.

Three deliberate choices:

* The tracked field list is per entity kind and hard-coded here, not derived
  from the ORM. A snapshot loop over __table__.columns would start recording
  tenancy columns and runtime session keys the first time somebody added
  one, which is the escalation surface row_guard avoided with an explicit
  allow-list.
* The trail never raises. A write path must not fail because auditing
  failed. Every helper degrades to an empty diff and says so via
  values_error rather than propagating.
* 'changed' is kept alongside 'changes'. Clients from v18 onward read
  'changed'; removing it to make the payload tidy would break them for no
  gain. 'changes' is additive.
"""

from __future__ import annotations

from app.services import field_diff

SOURCE = "write_trail"

# Columns worth remembering the previous value of, per entity kind. These are
# supersets of row_guard.WRITABLE because the non-guarded paths can touch a
# few columns the generic guarded endpoint deliberately refuses (a task's
# status moves through move_task, a member's department through move_member).
# They are still explicit lists: no tenancy column (organization_id), no
# runtime column (runtime_session_key).
TRACKED: dict[str, tuple[str, ...]] = {
    "company": ("name", "industry", "status"),
    "department": ("name", "head_member_id", "access_level", "status"),
    "member": ("name", "role", "status", "manager_id", "company_id", "department_id"),
    "project": ("name", "description", "status", "progress", "owner_member_id"),
    "task": ("title", "description", "status", "priority", "assignee_member_id"),
}


def tracked_fields(kind: str) -> tuple[str, ...]:
    return TRACKED.get(kind, ())


class Trail:
    """A before-snapshot waiting for an after-snapshot.

    Usage inside a write path::

        trail = write_trail.start("project", project)
        ...mutate and commit...
        payload = {"project_id": project.id, "changed": changed}
        payload.update(trail.finish(project))

    finish() returns the payload fragment rather than a bare diff so every
    call site emits the same keys and a reader never has to guess whether a
    missing 'changes' means "no diff" or "this path does not record one".
    """

    __slots__ = ("kind", "fields", "before", "ok", "error")

    def __init__(self, kind: str, before: dict, fields: tuple[str, ...],
                 ok: bool = True, error: str = "") -> None:
        self.kind = kind
        self.fields = fields
        self.before = before
        self.ok = ok
        self.error = error

    def diff(self, entity) -> dict:
        """Per-field {from, to} for the fields that actually moved."""
        if not self.ok or not self.fields:
            return {}
        try:
            after = field_diff.snapshot(entity, self.fields)
        except Exception as exc:  # noqa: BLE001 - auditing must not break writes
            self.ok = False
            self.error = str(exc)[:200]
            return {}
        return field_diff.diff(self.before, after)

    def finish(self, entity) -> dict:
        """The payload fragment to merge into the event payload."""
        changes = self.diff(entity)
        fragment: dict[str, object] = {
            "changes": changes,
            "values_source": SOURCE,
        }
        if not self.ok:
            # Say so in the payload instead of emitting an empty diff that
            # reads as "nothing changed". v31.1's bugfix pass exists because
            # an empty map once claimed to be a complete history.
            fragment["values_error"] = self.error or "snapshot failed"
        return fragment


def start(kind: str, entity) -> Trail:
    """Snapshot the tracked columns of entity before it is mutated."""
    fields = tracked_fields(kind)
    if not fields:
        return Trail(kind, {}, (), ok=False, error=f"no tracked fields for kind: {kind}")
    try:
        before = field_diff.snapshot(entity, fields)
    except Exception as exc:  # noqa: BLE001
        return Trail(kind, {}, fields, ok=False, error=str(exc)[:200])
    return Trail(kind, before, fields)


def coverage() -> dict:
    """Which write paths record before-values, for the coverage endpoint."""
    return {
        "tracked": {kind: list(fields) for kind, fields in sorted(TRACKED.items())},
        "paths": {
            "guarded": ["row_guard.compare_and_set"],
            "cockpit": [
                "workspace_ops.update_company",
                "workspace_ops.update_department",
                "workspace_ops.move_member",
                "workspace_ops.update_project",
                "workspace_ops.move_task",
                "workspace_ops.assign_task",
            ],
        },
        "not_covered": [
            # Creation has no before-value by definition, and archive/restore
            # already record their own previous-state maps.
            "create_* (no prior value exists)",
            "entity_archive / board_restore (record previous.* instead)",
        ],
        "redacted_fields": list(field_diff.REDACTED_FIELDS),
        "max_value_chars": field_diff.MAX_VALUE_CHARS,
    }
