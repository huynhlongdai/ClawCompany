"""v21: a shared lease so only one process follows an OpenClaw session.

v20 shipped session followers with an honest warning: the registry lived in
one process, so two uvicorn workers could both subscribe to the same session
and double-write every event. This module removes that warning by putting the
claim somewhere both workers can see it.

Design:

- Redis holds the lease (``SET key value NX EX ttl``). Renewal only succeeds
  if we still own it, checked by comparing the stored owner token, so a
  process that was paused past the TTL cannot stomp on the new owner.
- When Redis is unavailable the store degrades to an in-process dict and says
  so through ``backend``. That is a real single-worker deployment, not a
  pretend distributed lock -- callers can surface the difference.
- Nothing here blocks. A lease that cannot be acquired means "someone else is
  already following", which is a normal outcome, not an error.

v26 changes two things without changing the contract:

- The connection comes from ``redis_pool`` instead of a private client, so
  the lease store and the stream registry can no longer disagree about
  whether Redis exists, and a blip is retried instead of being permanent.
- ``scan()`` reads an index set rather than walking the keyspace. ``SCAN``
  is O(all keys in the database), which is fine for a few hundred sessions
  and not fine when ClawCompany shares a Redis with anything else.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.services.redis_pool import owner_token, pool

KEY_PREFIX = "clawcompany:stream-lease:"
# v26: members are session keys with a live lease. The set is a hint, not the
# truth -- a key can expire while its member lingers, so readers always verify
# against the actual lease key and prune what has gone.
INDEX_KEY = "clawcompany:stream-lease-index"
DEFAULT_TTL = 90  # seconds; renewed roughly every TTL/3 by the follower
# v33: an index prune is bounded, so one scheduled call can never turn
# into a multi-second Redis round trip on a large deployment.
MAX_INDEX_PRUNE = 5000


@dataclass
class Lease:
    session_key: str
    owner: str
    backend: str  # "redis" | "memory"
    expires_at: float

    def public(self) -> dict:
        return {"session_key": self.session_key, "owner": self.owner,
                "backend": self.backend, "expires_in": max(0, round(self.expires_at - time.time()))}


class LeaseStore:
    def __init__(self, ttl: int = DEFAULT_TTL) -> None:
        self.ttl = ttl
        self.owner = pool.owner
        self._memory: dict[str, tuple[str, float]] = {}
        self._index_pruned = 0

    # -- backend -----------------------------------------------------------

    def _client(self):
        return pool.client()

    @property
    def backend(self) -> str:
        return pool.backend

    def status(self) -> dict:
        shared = pool.status()
        return {"backend": shared["backend"], "ttl_seconds": self.ttl, "owner": self.owner,
                "single_process_only": not shared["available"],
                "redis_error": shared["error"],
                "index_key": INDEX_KEY,
                "index_pruned": self._index_pruned,
                "index_size": self.index_size(),
                "shared_pool": True}

    # -- v33: the index set no longer leaks -------------------------------

    def index_size(self) -> int | None:
        """How many session keys the index claims. None when unknowable.

        v26 pruned stale members only when :meth:`scan` happened to run, so
        a deployment that never calls scan grew the set forever: one member
        per session that ever ran. Reporting the size is the cheap half of
        the fix -- a set that keeps growing is now visible.
        """
        client = self._client()
        if client is None:
            return None
        try:
            return int(client.scard(INDEX_KEY))
        except Exception as exc:  # noqa: BLE001
            pool.drop(str(exc))
            return None

    def prune_index(self, *, dry_run: bool = True, limit: int = 5000) -> dict:
        """Drop index members whose lease key is already gone.

        Unlike :meth:`scan`, this can be called on a schedule, is bounded,
        and defaults to a dry run. A member whose lease key still exists is
        never removed, so it cannot unfollow a live session.
        """
        client = self._client()
        if client is None:
            live = [k for k, held in self._memory.items() if held[1] > time.time()]
            return {"backend": "memory", "index_size": len(self._memory),
                    "live": len(live), "stale": 0, "removed": 0,
                    "dry_run": dry_run,
                    "note": "No Redis: there is no shared index set to leak."}
        cap = max(1, min(int(limit), MAX_INDEX_PRUNE))
        try:
            members = [str(x) for x in client.smembers(INDEX_KEY)]
            stale: list[str] = []
            live = 0
            for start in range(0, len(members), 200):
                batch = members[start:start + 200]
                owners = client.mget([KEY_PREFIX + key for key in batch])
                for session_key, owner in zip(batch, owners):
                    if owner:
                        live += 1
                    elif len(stale) < cap:
                        stale.append(session_key)
            removed = 0
            if stale and not dry_run:
                client.srem(INDEX_KEY, *stale)
                self._index_pruned += len(stale)
                removed = len(stale)
            return {"backend": "redis", "index_size": len(members), "live": live,
                    "stale": len(stale), "removed": removed, "dry_run": dry_run,
                    "max_remove_per_call": cap, "sample_stale": stale[:20]}
        except Exception as exc:  # noqa: BLE001
            pool.drop(str(exc))
            return {"backend": "redis", "error": str(exc), "removed": 0,
                    "dry_run": dry_run}


    # -- lease lifecycle ---------------------------------------------------

    def acquire(self, session_key: str) -> Lease | None:
        """Claim a session. Returns None when another process already holds it."""
        now = time.time()
        client = self._client()
        if client is not None:
            try:
                if client.set(KEY_PREFIX + session_key, self.owner, nx=True, ex=self.ttl):
                    client.sadd(INDEX_KEY, session_key)
                    return Lease(session_key, self.owner, "redis", now + self.ttl)
                held = client.get(KEY_PREFIX + session_key)
                if held == self.owner:  # our own lease, e.g. after a reconnect
                    client.expire(KEY_PREFIX + session_key, self.ttl)
                    client.sadd(INDEX_KEY, session_key)
                    return Lease(session_key, self.owner, "redis", now + self.ttl)
                return None
            except Exception as exc:  # noqa: BLE001 - fall through to memory
                pool.drop(str(exc))
        held = self._memory.get(session_key)
        if held and held[1] > now and held[0] != self.owner:
            return None
        self._memory[session_key] = (self.owner, now + self.ttl)
        return Lease(session_key, self.owner, "memory", now + self.ttl)

    def renew(self, session_key: str) -> bool:
        """Extend a lease we still own. False means we lost it."""
        now = time.time()
        client = self._client()
        if client is not None:
            try:
                if client.get(KEY_PREFIX + session_key) != self.owner:
                    return False
                client.expire(KEY_PREFIX + session_key, self.ttl)
                return True
            except Exception as exc:  # noqa: BLE001
                pool.drop(str(exc))
        held = self._memory.get(session_key)
        if not held or held[0] != self.owner:
            return False
        self._memory[session_key] = (self.owner, now + self.ttl)
        return True

    def release(self, session_key: str) -> bool:
        """Release only our own lease; never steal someone else's."""
        client = self._client()
        if client is not None:
            try:
                if client.get(KEY_PREFIX + session_key) != self.owner:
                    return False
                client.delete(KEY_PREFIX + session_key)
                client.srem(INDEX_KEY, session_key)
                return True
            except Exception as exc:  # noqa: BLE001
                pool.drop(str(exc))
        held = self._memory.get(session_key)
        if not held or held[0] != self.owner:
            return False
        del self._memory[session_key]
        return True

    def scan(self) -> dict[str, str]:
        """Every held lease, session key -> owner token.

        v22: used to tell a session nobody is following from one another
        worker already owns. Only the Redis backend can answer this across
        processes; the memory backend can only speak for itself.

        v26: reads the index set instead of walking the keyspace, and prunes
        members whose lease has expired. Pruning on read is why no cleanup
        job is needed: the only thing that reads the index is also the only
        thing that can tell a stale member from a live one.
        """
        client = self._client()
        if client is not None:
            try:
                members = list(client.smembers(INDEX_KEY))
                if members:
                    out: dict[str, str] = {}
                    stale: list[str] = []
                    owners = client.mget([KEY_PREFIX + key for key in members])
                    for session_key, owner in zip(members, owners):
                        if owner:
                            out[session_key] = owner
                        else:
                            stale.append(session_key)
                    if stale:
                        client.srem(INDEX_KEY, *stale)
                        self._index_pruned += len(stale)
                    return out
                # No index yet (fresh deploy, or leases taken by a v25 worker
                # that never wrote one). Fall back to the old walk and rebuild
                # the set, so the upgrade needs no migration step.
                return self._scan_and_rebuild(client)
            except Exception as exc:  # noqa: BLE001
                pool.drop(str(exc))
        now = time.time()
        return {key: held[0] for key, held in self._memory.items() if held[1] > now}

    def _scan_and_rebuild(self, client) -> dict[str, str]:
        out: dict[str, str] = {}
        for key in client.scan_iter(match=KEY_PREFIX + "*", count=200):
            owner = client.get(key)
            if owner:
                out[str(key)[len(KEY_PREFIX):]] = owner
        if out:
            client.sadd(INDEX_KEY, *out.keys())
        return out

    def holder(self, session_key: str) -> str | None:
        client = self._client()
        if client is not None:
            try:
                return client.get(KEY_PREFIX + session_key)
            except Exception as exc:  # noqa: BLE001
                pool.drop(str(exc))
        held = self._memory.get(session_key)
        if held and held[1] > time.time():
            return held[0]
        return None


store = LeaseStore()
