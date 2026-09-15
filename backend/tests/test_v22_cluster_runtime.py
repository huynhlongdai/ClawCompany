"""v22 tests: shared run reporting and automatic takeover of orphan sessions.

Two claims are under test. First, a run view that cannot see the whole
cluster must say so rather than look complete. Second, taking over an
unattended session must never steal one another worker is actively following.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.base import Base
import app.models  # noqa: F401
from app.models import Agent, Company, Member, Organization, Project, Task
from app.runtime import openclaw_protocol as ocp
from app.services import runtime_stream as rs
from app.services.runtime_leases import KEY_PREFIX, LeaseStore
from app.services.stream_registry import StreamRegistry


class FakeRedis:
    """Enough Redis to exercise the shared paths without a server.

    v26 moved all Redis access through redis_pool.pool.client(); direct
    assignment to registry._redis no longer has any effect. This double
    is injected at the pool seam via monkeypatch (see shared_registry and
    the helpers below). Data lives in kv + sets, matching the v26 FakeRedis
    shape so scard/sadd/smembers/srem/mget do not raise AttributeError and
    accidentally call pool.drop().
    """

    def __init__(self):
        self.kv = {}
        self.sets = {}

    def ping(self):
        return True

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return None
        self.kv[key] = value
        return True

    def get(self, key):
        return self.kv.get(key)

    def mget(self, keys):
        return [self.kv.get(k) for k in keys]

    def delete(self, key):
        return bool(self.kv.pop(key, None))

    def expire(self, key, ttl):
        return key in self.kv

    def sadd(self, key, *values):
        self.sets.setdefault(key, set()).update(values)
        return len(values)

    def srem(self, key, *values):
        self.sets.setdefault(key, set()).difference_update(values)
        return len(values)

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def scard(self, key):
        return len(self.sets.get(key, set()))

    def scan_iter(self, match="*", count=100):
        prefix = match.rstrip("*")
        return [k for k in list(self.kv) if k.startswith(prefix)]


def _make_fake_pool(fake_client):
    """Create a RedisPool whose client() always returns fake_client."""
    import app.services.redis_pool as rp
    p = rp.RedisPool()
    p._client = fake_client
    return p


def _patch_pool(monkeypatch, fake_pool):
    """Inject fake_pool at the shared seam every service reads from."""
    import app.services.redis_pool as rp
    import app.services.runtime_leases as rl_mod
    import app.services.stream_registry as sr_mod
    monkeypatch.setattr(rp, "pool", fake_pool)
    monkeypatch.setattr(rl_mod, "pool", fake_pool)
    monkeypatch.setattr(sr_mod, "pool", fake_pool)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def memory_registry():
    # StreamRegistry.cluster_wide delegates to pool.available.  In the test
    # environment no real Redis is running so pool.client() returns None and
    # the registry naturally reports "memory".  We keep the fixture lean;
    # the old `reg._redis = None` assignment was a no-op after v26.
    return StreamRegistry()


@pytest.fixture()
def shared_registry(monkeypatch):
    # v26: the client is fetched from redis_pool.pool, not from a private
    # field.  Inject the fake at the shared seam so registry._client() sees it.
    fake_client = FakeRedis()
    fake_pool = _make_fake_pool(fake_client)
    _patch_pool(monkeypatch, fake_pool)
    reg = StreamRegistry()
    reg._fake_client = fake_client   # expose so tests can inspect raw Redis data
    return reg


@pytest.fixture()
def world(db):
    org = Organization(name="Nova Holding", slug="nova-holding-v22")
    db.add(org); db.commit(); db.refresh(org)
    other = Organization(name="Rival", slug="rival-v22")
    db.add(other); db.commit(); db.refresh(other)
    labs = Company(organization_id=org.id, name="Nova Labs", industry="AI", status="active")
    db.add(labs); db.commit(); db.refresh(labs)
    nina = Member(organization_id=org.id, company_id=labs.id, name="Nina",
                  member_type="agent", role="Chief of Staff", status="active")
    db.add(nina); db.commit(); db.refresh(nina)
    db.add(Agent(member_id=nina.id, runtime_provider="openclaw",
                 runtime_agent_id="nina", lifecycle="active"))
    project = Project(company_id=labs.id, name="Launch", status="active", progress=0)
    db.add(project); db.commit(); db.refresh(project)
    running = Task(project_id=project.id, title="Draft plan", assignee_member_id=nina.id,
                   status="in_progress", priority="high",
                   runtime_session_key=ocp.task_session_key("nina", 1))
    second = Task(project_id=project.id, title="Review deck", assignee_member_id=nina.id,
                  status="in_progress", priority="high",
                  runtime_session_key=ocp.task_session_key("nina", 2))
    done = Task(project_id=project.id, title="Shipped", assignee_member_id=nina.id,
                status="review", priority="low",
                runtime_session_key=ocp.task_session_key("nina", 3))
    db.add_all([running, second, done]); db.commit()
    for t in (running, second, done):
        db.refresh(t)
    return {"org": org, "other": other, "nina": nina, "running": running,
            "second": second, "done": done}


# -- honest reporting --------------------------------------------------------

def test_memory_registry_admits_it_is_not_cluster_wide(memory_registry):
    status = memory_registry.status()
    assert status["backend"] == "memory"
    assert status["cluster_wide"] is False


def test_memory_registry_publish_reports_failure_instead_of_pretending(memory_registry):
    assert memory_registry.publish({"session_key": "agent:nina:main"}) is False
    assert memory_registry.snapshot() == []


def test_shared_registry_round_trips_a_row(shared_registry):
    assert shared_registry.publish(
        {"session_key": "agent:nina:main", "organization_id": 1, "started_at": "2026-01-01"}
    ) is True
    rows = shared_registry.snapshot()
    assert [r["session_key"] for r in rows] == ["agent:nina:main"]
    assert rows[0]["owner"] == shared_registry.owner


def test_registry_snapshot_filters_by_organization(shared_registry):
    shared_registry.publish({"session_key": "a", "organization_id": 1, "started_at": "1"})
    shared_registry.publish({"session_key": "b", "organization_id": 2, "started_at": "2"})
    assert [r["session_key"] for r in shared_registry.snapshot(organization_id=2)] == ["b"]


def test_registry_will_not_withdraw_another_workers_row(shared_registry):
    shared_registry.publish({"session_key": "a", "organization_id": 1, "started_at": "1"})
    # Both registries share the same pool (already patched by the fixture), so
    # theirs._client() returns the same FakeRedis.  Give theirs a different owner
    # so the row ownership check fires correctly.
    theirs = StreamRegistry()
    theirs.owner = "other-worker-token"
    assert theirs.withdraw("a") is False
    assert shared_registry.withdraw("a") is True


def test_cluster_snapshot_flags_process_local_without_redis(monkeypatch, memory_registry):
    monkeypatch.setattr(rs, "registry", memory_registry)
    snap = rs.cluster_snapshot()
    assert snap["process_local"] is True
    assert snap["registry"]["cluster_wide"] is False


def test_cluster_snapshot_prefers_local_state_over_published_row(monkeypatch, shared_registry):
    monkeypatch.setattr(rs, "registry", shared_registry)
    shared_registry.publish({"session_key": "agent:nina:main", "organization_id": 7,
                             "started_at": "2026-01-01", "events": 1})
    state = rs.ConsumerState(session_key="agent:nina:main", task_id=5, organization_id=7)
    state.events = 42
    monkeypatch.setitem(rs.supervisor._state, "agent:nina:main", state)
    snap = rs.cluster_snapshot(7)
    assert snap["process_local"] is False
    assert [r["events"] for r in snap["streams"]] == [42]


# -- lease visibility -------------------------------------------------------

def test_lease_scan_lists_memory_holdings():
    store = LeaseStore(ttl=30)
    store._redis = None
    store.acquire("agent:nina:main")
    assert store.scan() == {"agent:nina:main": store.owner}


def test_lease_scan_strips_the_redis_prefix(monkeypatch):
    fake_client = FakeRedis()
    fake_pool = _make_fake_pool(fake_client)
    _patch_pool(monkeypatch, fake_pool)
    store = LeaseStore(ttl=30)
    store.acquire("agent:nina:company-task-4")
    assert list(store.scan()) == ["agent:nina:company-task-4"]
    assert KEY_PREFIX + "agent:nina:company-task-4" in fake_client.kv


# -- takeover ---------------------------------------------------------------

def test_claimable_excludes_sessions_another_worker_holds(monkeypatch, db, world):
    fake_client = FakeRedis()
    fake_pool = _make_fake_pool(fake_client)
    _patch_pool(monkeypatch, fake_pool)
    store = LeaseStore(ttl=30)
    monkeypatch.setattr(rs, "lease_store", store)
    held = world["running"].runtime_session_key
    fake_client.kv[KEY_PREFIX + held] = "other-host:99:abcd"
    keys = [t.runtime_session_key for t in rs.claimable_sessions(db)]
    assert held not in keys
    assert world["second"].runtime_session_key in keys


def test_claimable_only_covers_mid_run_tasks(monkeypatch, db, world):
    store = LeaseStore(ttl=30)
    store._redis = None
    monkeypatch.setattr(rs, "lease_store", store)
    keys = [t.runtime_session_key for t in rs.claimable_sessions(db)]
    assert world["done"].runtime_session_key not in keys


def test_claim_orphans_takes_over_unattended_sessions(monkeypatch, db, world):
    store = LeaseStore(ttl=30)
    store._redis = None
    monkeypatch.setattr(rs, "lease_store", store)
    followed = []

    def fake_follow(*, session_key, organization_id, task_id=None):
        followed.append(session_key)
        state = rs.ConsumerState(session_key=session_key, task_id=task_id,
                                 organization_id=organization_id)
        state.status = "running"
        return state

    monkeypatch.setattr(rs.supervisor, "follow", fake_follow)
    result = rs.claim_orphans(db, organization_id=world["org"].id)
    assert sorted(result["claimed"]) == sorted([world["running"].id, world["second"].id])
    assert len(followed) == 2


def test_claim_orphans_reports_declines_instead_of_stealing(monkeypatch, db, world):
    store = LeaseStore(ttl=30)
    store._redis = None
    monkeypatch.setattr(rs, "lease_store", store)

    def refusing_follow(*, session_key, organization_id, task_id=None):
        state = rs.ConsumerState(session_key=session_key, task_id=task_id,
                                 organization_id=organization_id)
        state.status = "declined"
        state.error = "Session already followed by other-host"
        return state

    monkeypatch.setattr(rs.supervisor, "follow", refusing_follow)
    result = rs.claim_orphans(db, organization_id=world["org"].id)
    assert result["claimed"] == []
    assert sorted(result["declined"]) == sorted([world["running"].id, world["second"].id])


def test_claim_orphans_skips_tasks_from_another_tenant(monkeypatch, db, world):
    store = LeaseStore(ttl=30)
    store._redis = None
    monkeypatch.setattr(rs, "lease_store", store)
    monkeypatch.setattr(rs.supervisor, "follow",
                        lambda **kw: pytest.fail("must not follow another tenant's session"))
    result = rs.claim_orphans(db, organization_id=world["other"].id)
    assert result["claimed"] == []
    assert sorted(result["skipped"]) == sorted([world["running"].id, world["second"].id])


def test_claim_orphans_reports_both_backends(monkeypatch, db, world, memory_registry):
    store = LeaseStore(ttl=30)
    store._redis = None
    monkeypatch.setattr(rs, "lease_store", store)
    monkeypatch.setattr(rs, "registry", memory_registry)
    monkeypatch.setattr(rs.supervisor, "follow",
                        lambda **kw: rs.ConsumerState(session_key=kw["session_key"], task_id=None,
                                                      organization_id=kw["organization_id"]))
    result = rs.claim_orphans(db, organization_id=world["org"].id)
    assert result["lease"]["single_process_only"] is True
    assert result["registry"]["cluster_wide"] is False


# -- configuration ----------------------------------------------------------

def test_orphan_sweep_is_disabled_by_default():
    assert settings.openclaw_claim_sweep_seconds == 0
