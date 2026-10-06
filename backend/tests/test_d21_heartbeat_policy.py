"""D2.1 / WP-6.2 — skill heartbeat + chính sách heartbeat (ORM thật, gateway giả)."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Agent, Member, Organization
from app.services import heartbeat_policy as hp


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    org = Organization(name="A", slug="a"); other = Organization(name="B", slug="b")
    s.add_all([org, other]); s.flush()
    rows = {}
    for name, typ, rid, o in (("Nina", "agent", "dev", org), ("Ops", "agent", "ops", org),
                              ("Ghost", "agent", "ghost", org), ("Long", "human", None, org),
                              ("Khác", "agent", "other", other)):
        m = Member(organization_id=o.id, name=name, member_type=typ, role="", status="active")
        s.add(m); s.flush()
        if rid:
            s.add(Agent(member_id=m.id, runtime_agent_id=rid))
        rows[name] = m
    s.commit()
    yield s, org, rows
    s.close()


class FakeRegistry:
    def __init__(self, entries):
        self.cfg = {"agents": {"defaults": {}, "entries": {k: {} for k in entries}}}
        self.patches = []

    async def snapshot(self):
        return {"config": self.cfg, "hash": "h1"}

    async def patch(self, values, *, base_hash=None, dry_run=False, note=""):
        self.patches.append({"values": values, "base_hash": base_hash, "dry_run": dry_run})
        return {"raw": values}


def test_policy_turns_off_everyone_but_the_keeper_and_never_creates_ghost_entries(db):
    s, org, m = db
    reg = FakeRegistry(["dev", "ops"])  # "ghost" chưa có entry trong config gateway
    hours = {"start": "08:00", "end": "20:00", "timezone": "Asia/Ho_Chi_Minh"}
    out = asyncio.run(hp.apply(s, org.id, reg, keeper_member_id=m["Nina"].id, active_hours=hours))
    (p,) = reg.patches
    assert p["base_hash"] == "h1"
    assert p["values"] == {
        ("agents", "entries", "dev", "heartbeat", "every"): "30m",
        ("agents", "entries", "dev", "heartbeat", "activeHours"): hours,
        ("agents", "entries", "ops", "heartbeat", "every"): "0m",
    }
    by = {r["agent_id"]: r["heartbeat"] for r in out["rows"]}
    assert by == {"dev": "keep", "ops": "off", "ghost": "not_in_config"}  # người & công ty khác không có mặt


def test_dry_run_is_passed_through(db):
    s, org, m = db
    reg = FakeRegistry(["dev"])
    out = asyncio.run(hp.apply(s, org.id, reg, keeper_member_id=None, active_hours=None, dry_run=True))
    assert reg.patches[0]["dry_run"] is True and out["patched"] is False


def test_daily_cost_counts_only_active_minutes():
    rows = [{"every": "30m"}, {"every": "0m"}, {"every": "30m", "activeHours": {"start": "08:00", "end": "20:00"}}]
    # 48 lượt + 0 + 24 lượt
    assert hp.daily_cost(rows, 0.033) == round(72 * 0.033, 4)
    assert hp.active_minutes({"start": "22:00", "end": "06:00"}) == 8 * 60
    assert hp.every_minutes("1h") == 60


class FakeRuntime:
    def __init__(self, fail_install=None):
        self.calls = []
        self.fail_install = fail_install

    async def rpc(self, method, params=None):
        self.calls.append((method, params))
        if method == "skills.upload.begin":
            return {"uploadId": f"u{len(self.calls)}"}
        if method == "skills.install" and self.fail_install:
            raise RuntimeError(self.fail_install)
        if method == "skills.status":
            return {"skills": [{"name": hp.SKILL_SLUG, "source": "openclaw-workspace", "eligible": True}]}
        return {"ok": True}


def test_install_uploads_the_real_skill_file_once_per_agent():
    rt = FakeRuntime()
    rows = asyncio.run(hp.install_skill(rt, ["dev", "ops"]))
    assert [r["status"] for r in rows] == ["installed", "installed"]
    methods = [c[0] for c in rt.calls]
    assert methods == ["skills.upload.begin", "skills.upload.chunk", "skills.upload.commit", "skills.install"] * 2
    installs = [c[1] for c in rt.calls if c[0] == "skills.install"]
    assert [i["agentId"] for i in installs] == ["dev", "ops"] and installs[0]["uploadId"] != installs[1]["uploadId"]
    data, sha = hp.skill_archive()
    assert installs[0]["sha256"] == sha
    import io, zipfile
    body = zipfile.ZipFile(io.BytesIO(data)).read("SKILL.md").decode()
    for tool in ("company_context", "company_tasks_list", "company_task_checkout", "company_task_comment"):
        assert tool in body
    assert body.startswith("---\nname: clawcompany-heartbeat")


def test_disabled_uploads_are_reported_not_faked():
    rt = FakeRuntime(fail_install="Uploaded skill archive installs are disabled by skills.install.allowUploadedArchives")
    (row,) = asyncio.run(hp.install_skill(rt, ["dev"]))
    assert row["status"] == "failed" and row["reason"] == "uploads_disabled"
