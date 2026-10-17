"""Giọng thương hiệu — văn bản có cấu trúc theo phiên bản (duyệt để ban hành), biên dịch vào AGENTS.md + tool, bộ chấm tất định,
cưỡng chế trên kết quả gửi khách (flag / rework), điểm giọng vào Agent HR, bộ eval giọng, giọng nói (TTS adapter, nghe thử, từ
điển phát âm, lỗi nhà cung cấp nói thật), nhiều công ty + cho thuê (ghế thuê dùng giọng bên thuê, sàn từ cấm của bên cho
thuê không nới được). Hành vi qua API thật + ORM SQLite + gateway giả."""
import json
import urllib.error

import pytest

from app.models import Agent, Member, Task
from app.models.agent_native import TaskOutput
from app.models.brand_voice import BrandVoice, VoiceCheck, VoiceSample
from app.models.extended import InboxItem
from app.services import brand_voice as bv
from app.services import company_mcp
from tests.test_m2b_company_foundation import E, mkpos, put_profile  # noqa: F401  (fixture)
from tests.test_m2e_io_contracts import GOOD, _flow
from tests.test_m2e_runtime_rules import _mcp
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)
from tests.test_r2_leases import L, leased, ok  # noqa: F401  (fixture)

SPEC = {
    "persona": "Nova nói ấm áp, gọn, thật thà.",
    "personality": ["Ấm áp", "Gọn"],
    "traits": [{"is": "ấm áp", "is_not": "suồng sã"}, {"is": "rõ ràng", "is_not": "vòng vo"}],
    "address": {"customer": {"self": "em", "customer": "anh/chị"},
                "segments": [{"key": "si", "label": "Khách sỉ", "self": "em", "customer": "quý khách"}],
                "internal": {"self": "mình", "other": "bạn"}},
    "preferred_terms": [{"use": "đổi trả", "instead_of": ["bồi thường"]}],
    "banned_words": ["rẻ nhất", "VOICE-BAN"],
    "banned_claims": ["hoàn tiền ngay lập tức", "không bao giờ vỡ"],
    "emoji": {"policy": "light", "max": 1},
    "signature": "Nova Shop — CSKH",
    "channels": {"email": {"emoji": "none"}, "zalo": {"max_chars": 120}},
    "examples": [{"channel": "zalo", "situation": "Khách hỏi giá", "good": "Dạ em gửi anh/chị bảng giá ạ.",
                  "bad": "Rẻ nhất thị trường bạn ơi!!"}],
    "lexicon": [{"term": "COD", "say": "xi ô đi"}],
}


def publish(E, spec=SPEC, company_id=None, tok=None):
    """Soạn nháp (manager) → gửi duyệt → chủ duyệt. Trả bản đã ban hành."""
    cid = company_id or E.co.id
    t_m, t_o = (tok, tok) if tok else (E.tok("manager"), E.tok("owner"))
    d = ok(E.c.put("/api/team/brand-voice/draft", json={"company_id": cid, "spec": spec}, headers=t_m), "draft")
    ok(E.c.post(f"/api/team/brand-voice/versions/{d['id']}/submit", json={}, headers=t_m), "submit")
    return ok(E.c.post(f"/api/team/brand-voice/versions/{d['id']}/decide", json={"decision": "approve"}, headers=t_o), "approve")


# ------------------------------------------------------------------ 1. phiên bản + duyệt + AGENTS.md

def test_legacy_charter_voice_becomes_v1_and_publish_flow_recompiles_agents_md(E):
    a = hire(E)
    assert put_profile(E, brand_voice="Ấm áp, xưng em gọi anh/chị, không dùng tiếng lóng.").status_code == 200
    md = E.gw.files[(a["runtime_agent_id"], "AGENTS.md")]
    assert "**Giọng thương hiệu:** Ấm áp, xưng em" in md          # trước khi có trang giọng: dòng cũ của hiến chương
    ov = ok(E.c.get(f"/api/team/brand-voice?company_id={E.co.id}", headers=E.tok("member")))
    assert ov["published"]["version_no"] == 1 and ov["published"]["spec"]["persona"].startswith("Ấm áp, xưng em")
    assert ov["published"]["spec"]["migrated_from_charter"] is True and ov["draft"] is None
    # viewer/member không soạn được; manager soạn + gửi; manager không ban hành được; chủ ban hành
    assert E.c.put("/api/team/brand-voice/draft", json={"company_id": E.co.id, "spec": SPEC}, headers=E.tok("member")).status_code == 403
    d = ok(E.c.put("/api/team/brand-voice/draft", json={"company_id": E.co.id, "spec": SPEC, "change_note": "v2"},
                   headers=E.tok("manager")))
    assert d["version_no"] == 2 and d["status"] == "draft"
    bad = E.c.put("/api/team/brand-voice/draft", json={"company_id": E.co.id,
                                                       "spec": {**SPEC, "preferred_terms": [{"use": "rẻ nhất"}]}}, headers=E.tok("manager"))
    assert bad.status_code == 422 and bad.json()["detail"]["error"] == "term_conflict"
    ok(E.c.post(f"/api/team/brand-voice/versions/{d['id']}/submit", json={}, headers=E.tok("manager")))
    assert E.c.put("/api/team/brand-voice/draft", json={"company_id": E.co.id, "spec": SPEC},
                   headers=E.tok("manager")).json()["detail"]["error"] == "in_review"
    assert E.c.post(f"/api/team/brand-voice/versions/{d['id']}/decide", json={"decision": "approve"},
                    headers=E.tok("manager")).status_code == 403
    r = ok(E.c.post(f"/api/team/brand-voice/versions/{d['id']}/decide", json={"decision": "approve"}, headers=E.tok("owner")))
    assert r["status"] == "published" and r["core_sync"] is True
    vs = {v.version_no: v.status for v in E.db.query(BrandVoice).filter(BrandVoice.company_id == E.co.id).all()}
    assert vs == {1: "archived", 2: "published"}
    # AGENTS.md sinh lại (nền): mục giọng mới, dòng hiến chương cũ không còn
    md = E.gw.files[(a["runtime_agent_id"], "AGENTS.md")]
    assert "### Giọng thương hiệu Nova Shop (v2" in md and "**Giọng thương hiệu:** Ấm áp" not in md
    assert "rẻ nhất" in md and "hoàn tiền ngay lập tức" in md and "company_doc_get doc_code=VOICE" in md
    assert "xưng \"em\", gọi \"anh/chị\"" in md
    core = bv.core_block(E.db, E.co.id)
    assert len(core) <= bv.CORE_VOICE_BUDGET
    prof = ok(E.c.get(f"/api/team/company-profile?company_id={E.co.id}", headers=E.tok("member")))
    assert prof["brand_voice_superseded"] is True
    # agent tuyển SAU cũng mang giọng ngay
    b = hire(E, name="Bé Ba", role="Nhân viên nội dung", department_id=E.mkt.id)
    assert "### Giọng thương hiệu Nova Shop (v2" in E.gw.files[(b["runtime_agent_id"], "AGENTS.md")]
    # từ chối một bản nháp → không đổi bản ban hành
    d3 = ok(E.c.put("/api/team/brand-voice/draft", json={"company_id": E.co.id, "spec": {**SPEC, "persona": "V3"}},
                    headers=E.tok("manager")))
    ok(E.c.post(f"/api/team/brand-voice/versions/{d3['id']}/submit", json={}, headers=E.tok("manager")))
    rj = ok(E.c.post(f"/api/team/brand-voice/versions/{d3['id']}/decide", json={"decision": "reject", "note": "chưa"},
                     headers=E.tok("owner")))
    assert rj["status"] == "rejected" and rj["core_sync"] is False and bv.published(E.db, E.co.id).version_no == 2
    # tổ chức khác không thấy
    assert E.c.get(f"/api/team/brand-voice/versions/{d['id']}", headers=E.tok("other")).status_code == 404


# ------------------------------------------------------------------ 2. bộ chấm tất định

def test_deterministic_checker_rules():
    sp = bv.clean_spec(SPEC)
    good = bv.check_text(sp, "Dạ em gửi anh/chị bảng giá ạ.", channel="zalo")
    assert good["passed"] and good["score"] == 1.0 and good["violations"] == []
    r = bv.check_text(sp, "Rẻ nhất luôn bạn ơi, tao hoàn tiền ngay lập tức!!", channel="zalo")
    codes = {v["code"]: v for v in r["violations"]}
    assert set(codes) >= {"banned_word", "banned_claim", "wrong_address", "excess_punctuation"} and not r["passed"]
    assert r["score"] == 0.0
    # "bán" không bị nhầm với "bạn"; cụm cấm gõ không dấu vẫn bị bắt
    assert bv.check_text(sp, "Dạ em bán cho anh/chị ạ.", channel="zalo")["violations"] == []
    assert any(v["code"] == "banned_claim" for v in bv.check_text(sp, "em se hoan tien ngay lap tuc a", channel="zalo")["violations"])
    # emoji: email không dùng; zalo tối đa 1
    assert bv.check_text(sp, "Kính gửi anh/chị 😀\nNova Shop — CSKH", channel="email")["violations"][0]["code"] == "emoji_not_allowed"
    assert {v["code"] for v in bv.check_text(sp, "Dạ anh/chị 😀😀", channel="zalo")["violations"]} == {"emoji_too_many"}
    # độ dài kênh, markdown ở chat, thiếu ký tên email, từ nên thay
    long = bv.check_text(sp, "Dạ em gửi anh/chị " + "x" * 200, channel="zalo")
    assert any(v["code"] == "too_long" and v["params"]["max"] == 120 for v in long["violations"])
    assert any(v["code"] == "markdown_in_chat" for v in bv.check_text(sp, "Dạ anh/chị **giá mới** ạ", channel="facebook")["violations"])
    assert any(v["code"] == "missing_signature" for v in bv.check_text(sp, "Kính gửi anh/chị, em gửi báo giá.", channel="email")["violations"])
    assert any(v["code"] == "preferred_term" and v["params"]["use"] == "đổi trả"
               for v in bv.check_text(sp, "Dạ em hỗ trợ anh/chị bồi thường ạ", channel="zalo")["violations"])
    # nhóm khách: khách sỉ gọi "quý khách"; nội bộ cho "bạn"
    assert bv.check_text(sp, "Dạ em gửi quý khách báo giá sỉ ạ.", channel="zalo", segment="si")["passed"]
    assert bv.check_text(sp, "Bạn ơi mình gửi số liệu tuần này nhé.", channel="internal")["violations"] == []
    with pytest.raises(Exception):
        bv.check_text(sp, "x", channel="tiktok")
    st = bv.selftest(sp)
    assert st["all_ok"] and st["good_pass"] == 1 and st["bad_caught"] == 1


def test_try_box_endpoint_records_and_model_check_is_behind_a_flag(E, monkeypatch):
    r = E.c.post("/api/team/brand-voice/check", json={"company_id": E.co.id, "text": "abc"}, headers=E.tok("member"))
    assert r.status_code == 409 and r.json()["detail"]["error"] == "no_published_voice"
    # kiểm theo bản nháp trước khi ban hành
    d = ok(E.c.put("/api/team/brand-voice/draft", json={"company_id": E.co.id, "spec": SPEC}, headers=E.tok("manager")))
    res = ok(E.c.post("/api/team/brand-voice/check", json={"company_id": E.co.id, "version_id": d["id"],
                                                           "text": "VOICE-BAN nha bạn", "channel": "zalo"}, headers=E.tok("member")))
    assert not res["passed"] and {v["code"] for v in res["violations"]} >= {"banned_word", "wrong_address"}
    ok(E.c.post(f"/api/team/brand-voice/versions/{d['id']}/submit", json={}, headers=E.tok("manager")))
    ok(E.c.post(f"/api/team/brand-voice/versions/{d['id']}/decide", json={"decision": "approve"}, headers=E.tok("owner")))
    res = ok(E.c.post("/api/team/brand-voice/check", json={"company_id": E.co.id, "text": "Dạ em chào anh/chị ạ.",
                                                           "use_model": True}, headers=E.tok("member")))
    assert res["passed"] and res["model_result"]["status"] == "disabled"     # cờ tắt → không gọi model
    assert E.c.put("/api/team/brand-voice/settings", json={"company_id": E.co.id, "model_check": True},
                   headers=E.tok("manager")).status_code == 403                 # cài đặt: chỉ quản trị
    s = ok(E.c.put("/api/team/brand-voice/settings", json={"company_id": E.co.id, "model_check": True, "enforcement": "rework",
                                                           "min_score": 0.8}, headers=E.tok("owner")))
    assert s["enforcement"] == "rework" and s["min_score"] == 0.8
    assert E.c.put("/api/team/brand-voice/settings", json={"company_id": E.co.id, "enforcement": "loud"},
                   headers=E.tok("owner")).status_code == 422
    # chưa cấu hình API → nói thật là lỗi, điểm tất định vẫn có
    monkeypatch.setattr(bv, "_api_configured", lambda: False)
    res = ok(E.c.post("/api/team/brand-voice/check", json={"company_id": E.co.id, "text": "Dạ em chào anh/chị ạ.",
                                                           "use_model": True}, headers=E.tok("member")))
    assert res["model_result"]["status"] == "error" and res["passed"]
    # model trả JSON → điểm tham khảo
    monkeypatch.setattr(bv, "model_tone_check", lambda spec, text, ch: {"status": "ok", "score": 0.9, "issues": []})
    res = ok(E.c.post("/api/team/brand-voice/check", json={"company_id": E.co.id, "text": "Dạ em chào anh/chị ạ.",
                                                           "use_model": True}, headers=E.tok("member")))
    assert res["model_result"]["score"] == 0.9
    hist = ok(E.c.get(f"/api/team/brand-voice/checks?company_id={E.co.id}", headers=E.tok("member")))
    assert len(hist["items"]) == 4 and {i["source"] for i in hist["items"]} == {"try"}


# ------------------------------------------------------------------ 3. tool cho agent

def test_agent_reads_voice_through_doc_get_without_a_new_tool(E):
    a = hire(E)
    ag = E.db.get(Agent, a["agent_id"])
    ctx = company_mcp.ToolContext(db=E.db, member=E.db.get(Member, ag.member_id), agent=ag)
    ok_, res = company_mcp.call(ctx, "company_doc_get", {"doc_code": "VOICE"})
    assert ok_ and res["found"] is False
    publish(E)
    ok_, res = company_mcp.call(ctx, "company_doc_get", {"doc_code": "voice", "channel": "email"})
    assert ok_, res
    assert list(res["channels"]) == ["email"] and res["channels"]["email"]["emoji"] == "none"
    assert res["channels"]["email"]["signature_required"] is True and res["cite"] == "[VOICE v1]"
    assert res["banned_words"] == ["rẻ nhất", "VOICE-BAN"] and res["provider_floor"] is None
    ok_, res = company_mcp.call(ctx, "company_doc_get", {"doc_code": "VOICE", "channel": "tiktok"})
    assert not ok_ and res["error"] == "invalid_argument"
    assert "company_brand_voice" not in company_mcp.TOOLS        # không thêm tool: giữ số tool của MCP
    pv = ok(E.c.get(f"/api/team/brand-voice/agent-view/{a['agent_id']}?channel=zalo", headers=E.tok("member")))
    assert pv["tool"]["channels"]["zalo"]["max_chars"] == 120 and "Giọng thương hiệu" in pv["core"]


# ------------------------------------------------------------------ 4. cưỡng chế trên kết quả gửi khách

def _contract_task(E):
    c, d, p, inst, m = _flow(E)
    t1 = inst["steps"][0]["task_id"]
    for to in ("todo", "in_progress"):
        if E.db.get(Task, t1).status != to:
            _mcp(E, m, "company_task_status", {"task_id": t1, "status": to, "reason": "làm"})
    return t1, m


def test_rework_mode_sends_off_voice_output_back_and_flag_mode_only_flags(E):
    publish(E)
    ok(E.c.put("/api/team/brand-voice/settings", json={"company_id": E.co.id, "enforcement": "rework"}, headers=E.tok("owner")))
    t1, m = _contract_task(E)
    off = {**GOOD, "customer_message": "Bạn yên tâm, tao hoàn tiền ngay lập tức nhé!!"}
    sc = _mcp(E, m, "company_task_submit_output", {"task_id": t1, "output": off})["structuredContent"]
    assert sc["valid"] is False and sc["status"] == "rework"
    assert any(e["path"].startswith("giọng.") for e in sc["errors"]) and "hoàn tiền ngay lập tức" in sc["message"]
    ok_ = _mcp(E, m, "company_task_submit_output", {"task_id": t1, "output": GOOD})["structuredContent"]
    assert ok_["valid"] and ok_["status"] == "accepted"            # "Dạ em xin lỗi chị…" — đúng giọng
    checks = E.db.query(VoiceCheck).filter(VoiceCheck.task_id == t1).order_by(VoiceCheck.id).all()
    assert [(c.source, c.passed, c.action) for c in checks] == [("submit_output", False, "rework"), ("submit_output", True, "none")]
    outs = E.db.query(TaskOutput).filter(TaskOutput.task_id == t1).order_by(TaskOutput.id).all()
    assert [o.valid for o in outs] == [False, True] and checks[0].task_output_id == outs[0].id
    # người duyệt sạch thấy dòng điểm giọng
    assert "Kiểm giọng thương hiệu" in bv.review_note(E.db, t1) and "đạt" in bv.review_note(E.db, t1)
    # Agent HR: điểm giọng trung bình của ghế (ô thử không tính)
    hr = ok(E.c.get(f"/api/team/agent-hr?company_id={E.co.id}", headers=E.tok("member")))
    row = next(x for x in hr["agents"] if x["member_id"] == m.id)
    assert row["voice_checks"] == 2 and row["voice_pass_rate"] == 0.5 and 0 < row["voice_score"] < 1
    assert hr["totals"]["voice_score"] is not None


def test_flag_mode_accepts_but_records_and_notifies(E):
    publish(E)        # mặc định: flag
    t1, m = _contract_task(E)
    off = {**GOOD, "customer_message": "Bạn ơi VOICE-BAN, hàng không bao giờ vỡ đâu."}
    sc = _mcp(E, m, "company_task_submit_output", {"task_id": t1, "output": off})["structuredContent"]
    assert sc["valid"] is True and sc["status"] == "accepted"
    vc = E.db.query(VoiceCheck).filter(VoiceCheck.task_id == t1).one()
    assert vc.action == "flag" and not vc.passed
    card = E.db.query(InboxItem).filter(InboxItem.item_type == "voice_flag").one()
    assert card.task_id == t1 and "lệch giọng" in card.title
    # tắt cưỡng chế → không chấm
    ok(E.c.put("/api/team/brand-voice/settings", json={"company_id": E.co.id, "enforcement": "off"}, headers=E.tok("owner")))
    assert bv.check_output(E.db, m, off) is None


def test_voice_eval_suite_from_examples(E):
    assert E.c.post("/api/team/brand-voice/eval-suite", json={"company_id": E.co.id}, headers=E.tok("manager")).status_code == 409
    publish(E)
    s = ok(E.c.post("/api/team/brand-voice/eval-suite", json={"company_id": E.co.id}, headers=E.tok("manager")))
    assert s["title"].startswith("Giọng thương hiệu — Nova Shop") and len(s["cases"]) == 1
    case = s["cases"][0]
    assert "rẻ nhất" in case["must_not_include"] and case["must_include"] == ["anh"]
    again = ok(E.c.post("/api/team/brand-voice/eval-suite", json={"company_id": E.co.id}, headers=E.tok("manager")))
    assert again["id"] == s["id"]                                    # cập nhật, không nhân bản
    st = ok(E.c.post("/api/team/brand-voice/selftest", json={"company_id": E.co.id}, headers=E.tok("member")))
    assert st["all_ok"] is True


# ------------------------------------------------------------------ 5. giọng nói

def test_voice_profile_preview_uses_lexicon_and_adapter(E, monkeypatch):
    publish(E)
    assert E.c.post("/api/team/voice-profile/preview", json={"company_id": E.co.id}, headers=E.tok("manager")).status_code == 409
    assert E.c.put("/api/team/voice-profile", json={"company_id": E.co.id, "speed": 3}, headers=E.tok("manager")).status_code == 422
    assert E.c.put("/api/team/voice-profile", json={"company_id": E.co.id, "provider": "fake"}, headers=E.tok("manager")).status_code == 422
    assert E.c.put("/api/team/voice-profile", json={"company_id": E.co.id, "voice_name": "x y"}, headers=E.tok("manager")).status_code == 422
    assert E.c.put("/api/team/voice-profile", json={"company_id": E.co.id}, headers=E.tok("member")).status_code == 403
    p = ok(E.c.put("/api/team/voice-profile", json={"company_id": E.co.id, "voice_name": "coral", "speed": 0.9, "pitch": "low",
                                                    "greeting_script": "Dạ Nova xin nghe", "sample_text": "Đơn COD của anh chị"},
                   headers=E.tok("manager")))
    assert p["language"] == "vi-VN" and p["lexicon"] == [{"term": "COD", "say": "xi ô đi"}]
    calls = []

    class Spy:
        key, label = "cometapi", "spy"

        def configured(self):
            return True

        def synthesize(self, text, **kw):
            calls.append((text, kw))
            return b"ID3" + b"\x00" * 200, "audio/mpeg"
    monkeypatch.setitem(bv.ADAPTERS, "cometapi", Spy())
    s = ok(E.c.post("/api/team/voice-profile/preview", json={"company_id": E.co.id}, headers=E.tok("manager")))
    assert calls[0][0] == "Đơn xi ô đi của anh chị" and calls[0][1]["voice"] == "coral" and calls[0][1]["speed"] == 0.9
    assert "trầm" in calls[0][1]["instructions"] and s["text_spoken"] == "Đơn xi ô đi của anh chị" and s["size_bytes"] == 203
    audio = E.c.get(f"/api{s['audio_path']}", headers=E.tok("member"))
    assert audio.status_code == 200 and audio.content.startswith(b"ID3") and audio.headers["content-type"] == "audio/mpeg"
    assert E.c.get(f"/api{s['audio_path']}", headers=E.tok("other")).status_code == 404
    ok(E.c.post("/api/team/voice-profile/preview", json={"company_id": E.co.id, "which": "greeting"}, headers=E.tok("manager")))
    assert calls[1][0] == "Dạ Nova xin nghe"
    assert E.c.post("/api/team/voice-profile/preview", json={"company_id": E.co.id, "text": "a" * 700},
                    headers=E.tok("manager")).status_code == 422
    # adapter giả: chỉ khi bật cờ kiểm thử
    monkeypatch.setattr(bv.settings, "tts_fake_enabled", True)
    ok(E.c.put("/api/team/voice-profile", json={"company_id": E.co.id, "provider": "fake"}, headers=E.tok("manager")))
    f = ok(E.c.post("/api/team/voice-profile/preview", json={"company_id": E.co.id}, headers=E.tok("manager")))
    assert f["mime"] == "audio/wav" and f["provider"] == "fake"
    sp = ok(E.c.post("/api/team/voice-profile/spoken-text", json={"company_id": E.co.id, "text": "Ship COD"}, headers=E.tok("member")))
    assert sp["text"] == "Ship xi ô đi"
    # đang soạn bản nháp có từ điển mới → nghe thử dùng từ điển của bản nháp
    ok(E.c.put("/api/team/brand-voice/draft", json={"company_id": E.co.id, "spec": {**SPEC, "lexicon": [{"term": "Ship", "say": "giao"}]}},
               headers=E.tok("manager")))
    sp = ok(E.c.post("/api/team/voice-profile/spoken-text", json={"company_id": E.co.id, "text": "Ship COD"}, headers=E.tok("member")))
    assert sp["text"] == "giao COD"


def test_tts_provider_quota_error_is_reported_not_faked(E, monkeypatch):
    ok(E.c.put("/api/team/voice-profile", json={"company_id": E.co.id, "sample_text": "Xin chào"}, headers=E.tok("manager")))
    monkeypatch.setattr(bv, "_api_configured", lambda: True)
    monkeypatch.setattr(bv, "_api_base", lambda: "https://api.example.test/v1")
    monkeypatch.setattr(bv, "_api_key", lambda: "sk-test")
    seen = {}

    def boom(req, timeout=0):
        seen["url"], seen["body"] = req.full_url, json.loads(req.data)
        import io
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"error":{"message":"user quota is not enough"}}'))
    monkeypatch.setattr(bv.urllib.request, "urlopen", boom)
    r = E.c.post("/api/team/voice-profile/preview", json={"company_id": E.co.id}, headers=E.tok("manager"))
    assert r.status_code == 424
    det = r.json()["detail"]
    assert det["error"] == "tts_provider_quota" and "quota" in det["message"]
    assert seen["url"].endswith("/audio/speech") and seen["body"]["model"] == "gpt-4o-mini-tts" and seen["body"]["voice"] == "nova"
    s = E.db.get(VoiceSample, det["sample_id"])
    assert s.status == "error" and s.audio is None and "quota" in s.error
    lst = ok(E.c.get(f"/api/team/voice-samples?company_id={E.co.id}", headers=E.tok("member")))
    assert lst["items"][0]["status"] == "error" and lst["items"][0]["audio_path"] is None
    # chưa cấu hình → lỗi rõ
    monkeypatch.setattr(bv, "_api_configured", lambda: False)
    r = E.c.post("/api/team/voice-profile/preview", json={"company_id": E.co.id}, headers=E.tok("manager"))
    assert r.status_code == 424 and r.json()["detail"]["error"] == "tts_not_configured"


# ------------------------------------------------------------------ 6. nhiều công ty + cho thuê

def test_each_company_has_its_own_voice_and_leased_seat_uses_renter_voice_with_provider_floor(L):
    X = L
    publish(X, {**SPEC, "banned_words": ["PROVIDER-BAN"], "banned_claims": ["bảo hành trọn đời"],
                "address": {"customer": {"self": "em", "customer": "anh/chị"}}})
    o, a, ls, ag, m = leased(X)
    md = X.gw.files[(ag.runtime_agent_id, "AGENTS.md")]
    floor = md[:md.index("## Lớp của bên thuê")]
    assert "PROVIDER-BAN" in floor and "bảo hành trọn đời" in floor       # từ cấm của bên cho thuê nằm trong sàn
    # bên thuê ban hành giọng riêng (xưng "mình", gọi "bạn") — chủ bên thuê tự soạn + duyệt (là chủ)
    renter_spec = {"persona": "Renter vui vẻ.", "address": {"customer": {"self": "mình", "customer": "bạn"}},
                   "banned_words": ["RENTER-BAN"], "examples": []}
    publish(X, renter_spec, company_id=X.rco.id, tok=X.tR)
    X.db.expire_all()
    md = X.gw.files[(ag.runtime_agent_id, "AGENTS.md")]
    cut = md.index("## Lớp của bên thuê")
    assert "PROVIDER-BAN" in md[:cut] and "### Giọng thương hiệu Renter Shop (v1" in md[cut:]   # giọng bên thuê ở lớp bên thuê
    assert "### Giọng thương hiệu Nova Shop" not in md                                           # giọng bên cho thuê không vào
    ctx = company_mcp.ToolContext(db=X.db, member=m, agent=ag)
    ok_, res = company_mcp.call(ctx, "company_doc_get", {"doc_code": "VOICE", "channel": "zalo"})
    assert ok_ and res["persona"] == "Renter vui vẻ." and res["channels"]["zalo"]["address"]["customer"] == "bạn"
    assert res["provider_floor"] == {"banned_words": ["PROVIDER-BAN"], "banned_claims": ["bảo hành trọn đời"]}
    assert res["lease_id"] == ls.id
    # bộ chấm: giọng bên thuê ("bạn" hợp lệ) + sàn bên cho thuê (không tắt được)
    spec, fl, lid, v = bv.effective_for_member(X.db, m)
    r = bv.check_text(spec, "Mình gửi bạn nhé, PROVIDER-BAN", channel="zalo", floor=fl)
    assert [(x["code"], x["source"]) for x in r["violations"]] == [("banned_word", "provider_floor")]
    # bên thuê để off: vi phạm sàn vẫn trả làm lại; lỗi giọng riêng của bên thuê thì không chấm
    ok(X.c.put("/api/team/brand-voice/settings", json={"company_id": X.rco.id, "enforcement": "off"}, headers=X.tR))
    v1 = bv.check_output(X.db, m, {"customer_message": "Mình gửi bạn, bảo hành trọn đời luôn"})
    assert v1["action"] == "rework" and v1["lease_id"] == ls.id
    v2 = bv.check_output(X.db, m, {"customer_message": "Mình gửi bạn, RENTER-BAN"})
    assert v2["action"] == "none" and v2["result"]["violations"] == []     # chỉ sàn được chấm khi bên thuê tắt
    # bên thuê không đọc / sửa giọng của bên cho thuê; bên cho thuê không đọc giọng bên thuê
    assert X.c.get(f"/api/team/brand-voice?company_id={X.co.id}", headers=X.tR).status_code in (403, 404)
    assert X.c.get(f"/api/team/brand-voice?company_id={X.rco.id}", headers=X.tok("owner")).status_code in (403, 404)
    pv = bv.published(X.db, X.co.id)
    assert X.c.get(f"/api/team/brand-voice/versions/{pv.id}", headers=X.tR).status_code == 404
    # giọng hai công ty độc lập
    assert bv.published(X.db, X.co.id).spec["banned_words"] == ["PROVIDER-BAN"]
    assert bv.published(X.db, X.rco.id).spec["banned_words"] == ["RENTER-BAN"]


def test_seed_demo_creates_draft_not_published(E):
    out = bv.seed_demo(E.db, E.org.id, E.co.id)
    assert out["created"] is True
    v = E.db.get(BrandVoice, out["draft_id"])
    assert v.status == "draft" and v.is_demo and bv.published(E.db, E.co.id) is None
    assert bv.selftest(bv.clean_spec(v.spec))["all_ok"] is True
    assert bv.seed_demo(E.db, E.org.id, E.co.id)["created"] is False          # chạy lại không ghi đè
    p = ok(E.c.get(f"/api/team/voice-profile?company_id={E.co.id}", headers=E.tok("member")))
    assert p["is_demo"] and p["greeting_script"].startswith("Dạ Tiệm Gốm Mộc")
