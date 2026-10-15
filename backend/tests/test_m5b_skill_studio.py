"""M5b việc 10 — Skill Studio trên Skill Workshop của OpenClaw: đồng bộ đề xuất → eval → duyệt → cài → rollback."""
import json

import pytest

from app.models import Agent, Approval, Member, User
from app.models.learning import CompanySkillInstall, CompanySkillVersion
from app.services import skill_studio
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


class Workshop:
    """Mô phỏng skills.proposals.* / skills.workshop.read theo hình dạng đo trên gateway 2026.9.8."""
    def __init__(self):
        self.proposals: dict[str, dict] = {}   # id -> {agentId, name, content, status, hash, kind}
        self.skills: dict[tuple[str, str], str] = {}
        self.n = 0

    def new(self, rid, name, content, kind="create", desc="d"):
        self.n += 1
        pid = f"{name}-2026-{self.n}"
        self.proposals[pid] = {"agentId": rid, "name": name, "content": content, "status": "pending",
                               "hash": f"h{self.n}", "kind": kind, "desc": desc}
        return pid

    async def rpc(self, method, p):
        if method == "skills.proposals.list":
            return {"proposals": [{"id": k, "status": v["status"], "skillName": v["name"]}
                                  for k, v in self.proposals.items() if v["agentId"] == p["agentId"]], "installedSkills": []}
        if method == "skills.proposals.inspect":
            v = self.proposals[p["proposalId"]]
            return {"record": {"id": p["proposalId"], "status": v["status"], "title": f"Create {v['name']}", "description": v["desc"],
                               "target": {"skillName": v["name"]}, "scan": {"state": "clean", "critical": 0, "warn": 0},
                               "goal": "học từ phiên trước"},
                    "revisionHash": v["hash"],
                    "content": f"---\nname: \"{v['name']}\"\nstatus: proposal\n---\n\n{v['content']}"}
        if method in ("skills.proposals.create", "skills.proposals.update"):
            name = p.get("name") or p.get("skillName")
            if method == "skills.proposals.update" and (p["agentId"], name) not in self.skills:
                raise RuntimeError("unknown skill")
            pid = self.new(p["agentId"], name, p["content"], kind=method.rsplit(".", 1)[1])
            return {"record": {"id": pid, "status": "pending"}, "revisionHash": self.proposals[pid]["hash"]}
        if method == "skills.proposals.apply":
            v = self.proposals[p["proposalId"]]
            assert p["expectedRevisionHash"] == v["hash"]
            v["status"] = "applied"; self.skills[(v["agentId"], v["name"])] = v["content"]
            return {"record": {"status": "applied"}}
        if method == "skills.proposals.reject":
            v = self.proposals[p["proposalId"]]
            assert p["expectedRevisionHash"] == v["hash"]
            v["status"] = "rejected"; v["reason"] = p.get("reason")
            return {"record": {"status": "rejected"}}
        if method == "skills.workshop.read":
            if (p["agentId"], p["name"]) not in self.skills:
                raise RuntimeError("not in workshop inventory")
            return {"name": p["name"], "content": self.skills[(p["agentId"], p["name"])]}
        raise AssertionError(method)


@pytest.fixture()
def S(env, monkeypatch):
    ws = Workshop()
    base = env.gw.rpc

    async def rpc(method, params=None):
        if method.startswith("skills."):
            return await ws.rpc(method, params or {})
        return await base(method, params)
    env.gw.rpc = rpc
    env.ws = ws
    monkeypatch.setattr("app.api.learning.get_runtime", lambda: env.gw)
    monkeypatch.setattr("app.runtime.factory.get_runtime", lambda: env.gw)
    u = env.db.query(User).filter(User.email == "manager@m3.test").one(); u.member_id = env.lead_s.id; env.db.commit()
    return env


CONTENT = """# Trả lời khách hỏi hàng vỡ

Khi khách báo hàng vỡ:
1. Xin lỗi và hỏi số đơn.
2. Nhắc khách gửi ảnh qua Zalo trong 48 giờ.
3. Hứa gửi bù miễn phí, không cần gửi lại hàng vỡ."""


def test_workshop_proposal_synced_to_inbox_and_applied_on_approve(S):
    out = hire(S); ag = S.db.get(Agent, out["agent_id"]); rid = out["runtime_agent_id"]
    pid = S.ws.new(rid, "xu-ly-hang-vo", CONTENT, desc="Quy trình khi khách báo hàng vỡ")
    H = S.tok("manager")
    r = S.c.post("/api/learning/skills/sync", headers=H)
    assert r.status_code == 200 and r.json()["imported"] == 1, r.text
    assert S.c.post("/api/learning/skills/sync", headers=H).json()["imported"] == 0       # không nhập trùng
    v = S.db.query(CompanySkillVersion).one()
    assert v.source == "workshop" and v.status == "in_review" and v.content.startswith("# Trả lời") and "status: proposal" not in v.content
    a = S.db.get(Approval, v.approval_id)
    assert a.policy_key == f"skill:v{v.id}" and a.approver_member_id == S.lead_s.id
    groups = S.c.get("/api/inbox/items", headers=H).json()["groups"]
    assert any((c.get("approval") or {}).get("id") == a.id for c in next(g for g in groups if g["key"] == "lessons")["items"])
    det = S.c.get(f"/api/inbox/approvals/{a.id}", headers=H).json()
    labels = {f["label"]: f["value"] for f in det["fields"]}
    assert labels["Kỹ năng"] == "xu-ly-hang-vo" and "48 giờ" in labels["Nội dung"] and labels["Agent đề xuất"]
    r = S.c.post(f"/api/inbox/approvals/{a.id}/decide", json={"decision": "approve"}, headers=H)
    assert r.status_code == 200, r.text
    assert "đã cài" in r.json()["message"]
    assert S.ws.proposals[pid]["status"] == "applied" and (rid, "xu-ly-hang-vo") in S.ws.skills
    d = S.c.get(f"/api/learning/skills/{v.skill_id}", headers=H).json()
    assert d["current_version"] == 1 and d["installs"][0]["agent_id"] == ag.id


def test_reject_workshop_proposal_tells_gateway(S):
    out = hire(S); rid = out["runtime_agent_id"]
    pid = S.ws.new(rid, "giam-gia-tuy-y", "# Giảm giá\n\nLuôn giảm 50% khi khách phàn nàn để giữ khách lâu dài.")
    H = S.tok("manager")
    S.c.post("/api/learning/skills/sync", headers=H)
    v = S.db.query(CompanySkillVersion).one()
    r = S.c.post(f"/api/inbox/approvals/{v.approval_id}/decide", json={"decision": "reject", "note": "Sai chính sách giảm giá"}, headers=H)
    assert r.status_code == 200, r.text
    assert S.ws.proposals[pid]["status"] == "rejected" and S.ws.proposals[pid]["reason"] == "Sai chính sách giảm giá"
    S.db.refresh(v); assert v.status == "rejected"


def test_manual_draft_eval_submit_install_and_rollback(S):
    a1 = hire(S); a2 = hire(S, name="Minh Khoa")
    H = S.tok("manager")
    cases = [{"prompt": "Khách báo bình bị vỡ, trả lời thế nào?", "must_include": ["48 giờ"], "must_not_include": ["hoàn tiền ngay"]}]
    r = S.c.post("/api/learning/skills", json={"slug": "xu-ly-hang-vo", "title": "Xử lý hàng vỡ", "description": "Quy trình hàng vỡ",
                                              "content": CONTENT, "eval_cases": cases}, headers=H)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]; vid = r.json()["versions"][0]["id"]
    assert S.c.post(f"/api/learning/skill-versions/{vid}/submit", headers=H).status_code == 409   # phải eval trước
    seen = []

    async def chat_stream(agent_id, message, *, session_key=None, timeout_seconds=90):
        seen.append(session_key)
        yield {"kind": "final", "text": "Dạ anh gửi ảnh qua Zalo trong 48 giờ ạ" if "<skill>" in message else "Dạ em hoàn tiền ngay ạ"}
    S.gw.chat_stream = chat_stream
    r = S.c.post(f"/api/learning/skill-versions/{vid}/eval", json={"agent_id": a1["agent_id"]}, headers=H)
    assert r.status_code == 200, r.text
    rep = r.json()["eval_report"]
    assert rep["with_skill"] == 1 and rep["baseline"] == 0 and len(seen) == 2
    sub = S.c.post(f"/api/learning/skill-versions/{vid}/submit", headers=H).json()
    a = S.db.get(Approval, sub["approval_id"])
    assert "1/1" in json.loads(a.evidence)["eval"]
    S.c.post(f"/api/inbox/approvals/{a.id}/decide", json={"decision": "approve"}, headers=H)
    r = S.c.post(f"/api/learning/skills/{sid}/install", json={"agent_ids": [a1["agent_id"], a2["agent_id"]]}, headers=H)
    assert r.status_code == 200, r.text
    assert all(x["status"] == "installed" for x in r.json()["results"])
    assert (a2["runtime_agent_id"], "xu-ly-hang-vo") in S.ws.skills
    # v2 rồi rollback về v1
    S.c.post("/api/learning/skills", json={"slug": "xu-ly-hang-vo", "description": "v2", "content": CONTENT + "\n4. Tặng voucher 20k.",
                                          "eval_cases": []}, headers=H)
    v2 = S.db.query(CompanySkillVersion).filter(CompanySkillVersion.version == 2).one()
    sub2 = S.c.post(f"/api/learning/skill-versions/{v2.id}/submit", headers=H).json()
    S.c.post(f"/api/inbox/approvals/{sub2['approval_id']}/decide", json={"decision": "approve"}, headers=H)
    S.c.post(f"/api/learning/skills/{sid}/install", json={"agent_ids": [a1["agent_id"]]}, headers=H)
    assert "voucher" in S.ws.skills[(a1["runtime_agent_id"], "xu-ly-hang-vo")]
    r = S.c.post(f"/api/learning/skills/{sid}/rollback", json={"version_id": vid}, headers=H)
    assert r.status_code == 200, r.text
    assert "voucher" not in S.ws.skills[(a1["runtime_agent_id"], "xu-ly-hang-vo")]
    assert "voucher" not in S.ws.skills[(a2["runtime_agent_id"], "xu-ly-hang-vo")]
    assert r.json()["current_version"] == 1
    assert S.db.query(CompanySkillInstall).filter(CompanySkillInstall.version_id == vid).count() == 2
    assert S.c.post(f"/api/learning/skills/{sid}/install", json={"agent_ids": [a1["agent_id"]]},
                    headers=S.tok("member")).status_code == 403


def test_validation_and_score():
    with pytest.raises(Exception):
        skill_studio.clean_cases([{"prompt": "x"}])
    assert skill_studio.score("Gửi ảnh trong 48 GIỜ", {"must_include": ["48 giờ"], "must_not_include": []})["passed"]
    assert skill_studio.body_of("---\nname: a\n---\n\n# X\n") == "# X\n"


def test_governance_patch_sets_propose_and_pending(S, monkeypatch):
    import asyncio
    sent = {}

    class Reg:
        def __init__(self, rt): pass
        async def snapshot(self): return {"hash": "abc", "config": {"skills": {"workshop": sent.get("ws", {})}}}
        async def patch(self, values, **kw):
            sent["values"] = values
            sent["ws"] = {"autonomous": {"mode": values[("skills", "workshop", "autonomous", "mode")]},
                          "approvalPolicy": values[("skills", "workshop", "approvalPolicy")]}
    monkeypatch.setattr("app.services.openclaw_config.ConfigRegistry", Reg)
    before = asyncio.run(skill_studio.governance(S.gw))
    assert before["autonomous_mode"] == "auto" and not before["governed"]
    after = asyncio.run(skill_studio.enforce_governance(S.gw))
    assert after == {"autonomous_mode": "propose", "approval_policy": "pending", "governed": True}
