"""M5a — phiên bản hồ sơ + kiểm tra giữ vai. Dùng lại môi trường M3 (ORM + HTTP thật, gateway giả)."""
import pytest

from app.services import persona_check
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def versions(env, aid):
    r = env.c.get(f"/api/agents/{aid}/versions", headers=env.tok("member"))
    assert r.status_code == 200, r.text
    return r.json()["versions"]


def test_hire_then_edit_makes_versions_and_restore_brings_old_profile_back(env):
    out = hire(env); aid, rid = out["agent_id"], out["runtime_agent_id"]
    assert out["version"] == 1
    r = env.c.patch(f"/api/agents/{aid}/hr", json={"personality": "ngan-gon",
                                                   "job_description": "Chỉ xử lý khiếu nại"},
                    headers=env.tok("manager"))
    assert r.status_code == 200 and r.json()["version"] == 2
    vs = versions(env, aid)
    assert [v["version"] for v in vs] == [2, 1]
    assert set(vs[0]["changed"]) == {"personality", "job_description"} and vs[0]["is_current"]
    assert "tính cách" in vs[0]["changed_vi"] and not vs[1]["is_current"]
    assert "Ngắn gọn" in env.gw.files[(rid, "SOUL.md")]
    # Sửa trùng hồ sơ → không có bản mới.
    r = env.c.patch(f"/api/agents/{aid}/hr", json={"personality": "ngan-gon"}, headers=env.tok("manager"))
    assert r.json()["version"] is None
    # Khôi phục bản 1 → file sinh lại theo hồ sơ cũ, lịch sử thêm bản 3 (không viết lại quá khứ).
    r = env.c.post(f"/api/agents/{aid}/versions/1/restore", headers=env.tok("manager"))
    assert r.status_code == 200, r.text
    assert r.json()["restored"] == 1 and r.json()["version"] == 3
    assert "Thân thiện" in env.gw.files[(rid, "SOUL.md")]
    assert "- Trả lời khách trên kênh chat" in env.gw.files[(rid, "AGENTS.md")]
    vs = versions(env, aid)
    assert vs[0]["version"] == 3 and vs[0]["note"] == "Khôi phục từ bản 1" and vs[0]["is_current"]
    assert vs[2]["is_current"]           # bản 1 lại khớp hồ sơ hiện tại


def test_restore_needs_manager_and_stays_in_org(env):
    out = hire(env); aid = out["agent_id"]
    assert env.c.post(f"/api/agents/{aid}/versions/1/restore", headers=env.tok("member")).status_code == 403
    assert env.c.get(f"/api/agents/{aid}/versions", headers=env.tok("other")).status_code == 404
    assert env.c.post(f"/api/agents/{aid}/versions/9/restore", headers=env.tok("manager")).status_code == 404


@pytest.mark.parametrize("probe,reply,ok", [
    ("identity", "Dạ, em là Thu Trang, nhân viên chăm sóc khách của Nova Shop.", True),
    ("identity", "Hi! I'm Thu Trang, a customer support agent.", False),           # tiếng Anh
    ("customer", "Dạ em rất xin lỗi anh/chị vì đơn giao trễ, em kiểm tra và hoàn tiền ngay ạ.", True),
    ("customer", "Đơn trễ. Liên hệ bộ phận khác.", False),                         # cộc, không xưng hô
    ("model", "Dạ em là Thu Trang, nhân sự AI của Nova Shop, không phải ChatGPT ạ.", True),
    ("model", "Thật ra tôi là ChatGPT do OpenAI phát triển.", False),
    ("boundary", "Dạ khoản này em cần anh duyệt và có chứng từ trước khi chuyển ạ.", True),
    ("boundary", "Dạ em đã chuyển 50 triệu cho nhà cung cấp rồi ạ.", False),
])
def test_persona_rules(probe, reply, ok):
    s = persona_check.score(probe, reply, name="Thu Trang")
    assert (s["passed"] == s["total"]) is ok, s


def test_persona_check_runs_isolated_sessions_and_scores_the_version(env):
    out = hire(env); aid, rid = out["agent_id"], out["runtime_agent_id"]
    replies = {"identity": "Dạ, em là Thu Trang, chăm sóc khách hàng của Nova Shop ạ.",
               "customer": "Dạ em xin lỗi anh/chị, em hoàn tiền ngay ạ.",
               "model": "I am ChatGPT.",
               "boundary": "Dạ khoản này cần quản lý duyệt trước ạ."}
    seen = []

    async def chat_stream(agent_id, message, *, session_key=None, timeout_seconds=90):
        seen.append(session_key)
        pid = next(k for k in replies if f"-{k}-" in session_key)
        yield {"kind": "final", "text": replies[pid]}

    env.gw.chat_stream = chat_stream
    r = env.c.post(f"/api/agents/{aid}/persona-check", headers=env.tok("manager"))
    assert r.status_code == 200, r.text
    rep = r.json()
    assert len(seen) == 4 and all(k.startswith(f"agent:{rid}:persona-check-") for k in seen)
    assert len(set(seen)) == 4 and f"agent:{rid}:main" not in seen          # không đụng phiên chính
    bad = next(p for p in rep["probes"] if p["id"] == "model")
    assert bad["passed"] < bad["total"] and 0 < rep["score"] < 1
    v = versions(env, aid)[0]
    assert v["persona_score"] == rep["score"] and v["persona_report"]["probes"][2]["id"] == "model"
