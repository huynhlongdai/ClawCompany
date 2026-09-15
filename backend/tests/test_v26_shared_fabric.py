"""v26 tests: one Redis opinion per worker, and a way back from a blip.

These pin the three defects v26 fixes: two private clients that could
disagree, a first error that demoted a worker forever, and a keyspace walk
where an index set belongs. FakeRedis exercises the logic only -- real SET NX
EX / SMEMBERS semantics still need a live server.
"""
import time

import pytest

from app.services import redis_pool as rp
from app.services import runtime_leases as rl
from app.services import stream_registry as sr
from app.services import stream_reconcile as rec


class FakeRedis:
    def __init__(self, broken=False):
        self.kv = {}
        self.sets = {}
        self.broken = broken
        self.scans = 0

    def _boom(self):
        if self.broken:
            raise ConnectionError("redis is down")

    def ping(self):
        self._boom()
        return True

    def set(self, key, value, nx=False, ex=None):
        self._boom()
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    def get(self, key):
        self._boom()
        return self.kv.get(key)

    def mget(self, keys):
        self._boom()
        return [self.kv.get(k) for k in keys]

    def delete(self, key):
        self._boom()
        self.kv.pop(key, None)
        return 1

    def expire(self, key, ttl):
        self._boom()
        return key in self.kv

    def sadd(self, key, *values):
        self._boom()
        self.sets.setdefault(key, set()).update(values)
        return len(values)

    def srem(self, key, *values):
        self._boom()
        self.sets.setdefault(key, set()).difference_update(values)
        return len(values)

    def smembers(self, key):
        self._boom()
        return set(self.sets.get(key, set()))

    def scard(self, key):
        # LeaseStore.index_size() calls scard; without it AttributeError is
        # caught by pool.drop(), clearing _client and breaking all other tests
        # in the same fixture.
        self._boom()
        return len(self.sets.get(key, set()))

    def scan_iter(self, match="*", count=100):
        self._boom()
        self.scans += 1
        prefix = match.rstrip("*")
        return [k for k in list(self.kv) if k.startswith(prefix)]


@pytest.fixture()
def fake(monkeypatch):
    client = FakeRedis()
    pool = rp.RedisPool()
    pool._client = client
    monkeypatch.setattr(rp, "pool", pool)
    monkeypatch.setattr(rl, "pool", pool)
    monkeypatch.setattr(sr, "pool", pool)
    monkeypatch.setattr(rec, "pool", pool)
    rec.clear()
    yield client, pool
    rec.clear()


# --- one opinion -----------------------------------------------------------


def test_lease_and_registry_cannot_disagree_about_redis(fake):
    """The v26 bug in one line: two stores, two private clients, two answers."""
    client, pool = fake
    store = rl.LeaseStore()
    registry = sr.StreamRegistry()
    assert store.status()["backend"] == "redis"
    assert registry.status()["cluster_wide"] is True
    pool.drop("simulated outage")
    assert store.status()["backend"] == "memory"
    assert registry.status()["cluster_wide"] is False


def test_one_store_noticing_an_outage_tells_the_others(fake):
    client, pool = fake
    store = rl.LeaseStore()
    registry = sr.StreamRegistry()
    client.broken = True
    store.acquire("agent:nina:main")  # swallows the error and drops the pool
    assert registry.publish({"session_key": "agent:nina:main"}) is False
    assert pool.status()["available"] is False


# --- recovery --------------------------------------------------------------


def test_a_blip_is_not_a_one_way_door(fake, monkeypatch):
    """Pre-v26 a single error demoted the worker until someone restarted it."""
    client, pool = fake
    pool.drop("blip")
    assert pool.client() is None
    pool._next_attempt = 0.0
    monkeypatch.setattr(rp, "pool", pool)
    fresh = FakeRedis()
    monkeypatch.setattr("redis.from_url", lambda *a, **k: fresh, raising=False)
    # Without a real redis package the import fails and we stay down, which is
    # also correct: the point is that we *tried* again.
    pool.client()
    assert pool.status()["connect_attempts"] >= 1


def test_backoff_stops_us_dialling_on_every_request(fake):
    client, pool = fake
    pool.drop("down")
    before = pool.status()["connect_attempts"]
    for _ in range(5):
        assert pool.client() is None
    assert pool.status()["connect_attempts"] == before
    assert pool.status()["retry_in"] > 0


def test_password_never_leaves_the_process(fake, monkeypatch):
    monkeypatch.setattr(rp.settings, "redis_url", "redis://user:hunter2@cache:6379/0")
    url = rp.pool.status()["url"]
    assert "hunter2" not in url
    assert "***@cache:6379/0" in url


# --- index sets ------------------------------------------------------------


def test_scan_uses_the_index_not_the_keyspace(fake):
    client, pool = fake
    store = rl.LeaseStore()
    store.acquire("agent:a:main")
    store.acquire("agent:b:main")
    client.scans = 0
    held = store.scan()
    assert set(held) == {"agent:a:main", "agent:b:main"}
    assert client.scans == 0


def test_expired_lease_is_pruned_from_the_index_on_read(fake):
    """The index is a hint; the lease key is the truth."""
    client, pool = fake
    store = rl.LeaseStore()
    store.acquire("agent:a:main")
    del client.kv[rl.KEY_PREFIX + "agent:a:main"]  # TTL lapsed
    assert store.scan() == {}
    assert client.smembers(rl.INDEX_KEY) == set()
    assert store.status()["index_pruned"] == 1


def test_leases_taken_by_an_older_worker_are_adopted(fake):
    """No migration step: a v25 lease with no index member still shows up."""
    client, pool = fake
    client.kv[rl.KEY_PREFIX + "agent:legacy:main"] = "other-worker"
    store = rl.LeaseStore()
    held = store.scan()
    assert held == {"agent:legacy:main": "other-worker"}
    assert "agent:legacy:main" in client.smembers(rl.INDEX_KEY)


def test_release_removes_the_index_member(fake):
    client, pool = fake
    store = rl.LeaseStore()
    store.acquire("agent:a:main")
    assert store.release("agent:a:main") is True
    assert client.smembers(rl.INDEX_KEY) == set()


def test_registry_snapshot_also_avoids_the_keyspace(fake):
    client, pool = fake
    registry = sr.StreamRegistry()
    registry.publish({"session_key": "agent:a:main", "organization_id": 1, "started_at": "2026-01-01"})
    client.scans = 0
    rows = registry.snapshot(1)
    assert len(rows) == 1
    assert client.scans == 0


def test_registry_still_refuses_to_delete_another_workers_row(fake):
    client, pool = fake
    registry = sr.StreamRegistry()
    registry.publish({"session_key": "agent:a:main"})
    import json
    client.kv[sr.KEY_PREFIX + "agent:a:main"] = json.dumps({"owner": "someone-else"})
    assert registry.withdraw("agent:a:main") is False


# --- shared reconcile ledger ----------------------------------------------


def test_cooldown_is_shared_so_it_does_not_multiply_by_worker_count(fake):
    """Three workers must not mean three gateway calls per cooldown window."""
    from datetime import datetime

    client, pool = fake
    now = datetime.utcnow()
    rec._remember({"session_key": "agent:a:main", "ran": True, "at": now.isoformat(),
                   "organization_id": 1})
    rec.clear()  # a *different* worker: no local memory of that pass
    assert rec._cooling_down("agent:a:main", now) is not None


def test_history_merges_other_workers_passes(fake):
    client, pool = fake
    rec._remember({"session_key": "agent:a:main", "ran": True, "at": "2026-01-02",
                   "organization_id": 1})
    rec.clear()
    rec._last["agent:b:main"] = {"session_key": "agent:b:main", "ran": True,
                                 "at": "2026-01-01", "organization_id": 1}
    rows = rec.history(1)
    assert [r["session_key"] for r in rows] == ["agent:a:main", "agent:b:main"]


def test_shared_row_wins_over_our_older_local_one(fake):
    client, pool = fake
    rec._remember({"session_key": "agent:a:main", "ran": True, "at": "2026-02-01",
                   "organization_id": 1, "reason": "takeover"})
    rec._last["agent:a:main"] = {"session_key": "agent:a:main", "ran": True,
                                 "at": "2026-01-01", "organization_id": 1,
                                 "reason": "stale-local"}
    rows = rec.history(1)
    assert len(rows) == 1
    assert rows[0]["reason"] == "takeover"


def test_ledger_falls_back_to_memory_without_redis(fake):
    client, pool = fake
    pool.drop("down")
    rec._remember({"session_key": "agent:a:main", "ran": True, "at": "2026-01-01",
                   "organization_id": 1})
    assert rec.cluster_wide() is False
    assert len(rec.history(1)) == 1


def test_ledger_write_failure_never_raises(fake):
    client, pool = fake
    client.broken = True
    rec._remember({"session_key": "agent:a:main", "ran": True, "at": "2026-01-01",
                   "organization_id": 1})
    assert rec._last["agent:a:main"]["ran"] is True
