"""v22: a cluster-wide view of who is following which OpenClaw session.

v21 fixed *ownership* with a shared lease, but the answer to "what is running
right now?" still came from one process's memory. With two workers, each
/api/v20/streams response showed half the truth and neither said so.

This module publishes each follower's state to a shared registry so any worker
can answer the question. It is deliberately a *reporting* surface, not a
second source of ownership: the lease in ``runtime_leases`` remains the only
thing that decides who may consume a session. If the two ever disagree, the
lease wins and the registry entry simply expires.

Entries are written with a TTL slightly longer than the lease TTL and are
refreshed as events arrive. A worker that dies leaves no stale row behind
once the TTL lapses, so we never need a cleanup job.

v26: the connection is the shared one from ``redis_pool``, and reads use an
index set instead of ``SCAN``. Before that, this module kept its own client
and could report ``cluster_wide: false`` while the lease store on the same
worker was happily talking to the same Redis server.
"""

from __future__ import annotations

import json
import time

from app.services.redis_pool import pool
from app.services.runtime_leases import DEFAULT_TTL

KEY_PREFIX = "clawcompany:stream-state:"
INDEX_KEY = "clawcompany:stream-state-index"
TTL = DEFAULT_TTL + 30  # outlive the lease so a losing worker's row fades last


class StreamRegistry:
    """Shared, best-effort directory of active followers."""

    def __init__(self) -> None:
        self.owner = pool.owner
        self._index_pruned = 0

    def _client(self):
        return pool.client()

    @property
    def backend(self) -> str:
        return pool.backend

    @property
    def cluster_wide(self) -> bool:
        """False means callers are seeing this process only. Say so upstream."""
        return pool.available

    def status(self) -> dict:
        shared = pool.status()
        return {
            "backend": shared["backend"],
            "cluster_wide": shared["available"],
            "owner": self.owner,
            "ttl_seconds": TTL,
            "redis_error": shared["error"],
            "index_key": INDEX_KEY,
            "index_pruned": self._index_pruned,
            "shared_pool": True,
        }

    # -- writes ------------------------------------------------------------

    def publish(self, state: dict) -> bool:
        """Record/refresh one follower row. Returns False when not shared."""
        client = self._client()
        if client is None:
            return False
        session_key = str(state.get("session_key") or "")
        if not session_key:
            return False
        row = dict(state)
        row["owner"] = self.owner
        row["reported_at"] = time.time()
        try:
            client.set(KEY_PREFIX + session_key, json.dumps(row, default=str), ex=TTL)
            client.sadd(INDEX_KEY, session_key)
            return True
        except Exception as exc:  # noqa: BLE001 - reporting must never break a stream
            pool.drop(str(exc))
            return False

    def withdraw(self, session_key: str) -> bool:
        """Remove our row when we stop following on purpose."""
        client = self._client()
        if client is None:
            return False
        try:
            raw = client.get(KEY_PREFIX + session_key)
            if raw:
                row = json.loads(raw)
                if row.get("owner") != self.owner:
                    return False  # someone else's row; not ours to delete
            client.delete(KEY_PREFIX + session_key)
            client.srem(INDEX_KEY, session_key)
            return True
        except Exception as exc:  # noqa: BLE001
            pool.drop(str(exc))
            return False

    # -- reads -------------------------------------------------------------

    def snapshot(self, organization_id: int | None = None) -> list[dict]:
        """Every follower any worker has reported, newest first."""
        client = self._client()
        if client is None:
            return []
        rows: list[dict] = []
        try:
            members = list(client.smembers(INDEX_KEY))
            if not members:
                members = self._rebuild_index(client)
            stale: list[str] = []
            raws = client.mget([KEY_PREFIX + key for key in members]) if members else []
            for session_key, raw in zip(members, raws):
                if not raw:
                    stale.append(session_key)
                    continue
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if organization_id is not None and row.get("organization_id") != organization_id:
                    continue
                rows.append(row)
            if stale:
                client.srem(INDEX_KEY, *stale)
                self._index_pruned += len(stale)
        except Exception as exc:  # noqa: BLE001
            pool.drop(str(exc))
            return []
        return sorted(rows, key=lambda r: str(r.get("started_at") or ""), reverse=True)

    def _rebuild_index(self, client) -> list[str]:
        """Adopt rows written by a pre-v26 worker without a migration step."""
        found = [str(key)[len(KEY_PREFIX):]
                 for key in client.scan_iter(match=KEY_PREFIX + "*", count=200)]
        if found:
            client.sadd(INDEX_KEY, *found)
        return found


registry = StreamRegistry()
