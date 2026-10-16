"""M3a — thư viện tài liệu lõi: phân loại, vòng đời nháp → chờ duyệt → ban hành → thay thế, duyệt theo ma trận
(doc_publish: trưởng phòng; rủi ro cao → chủ), phiên bản bất biến, hồ sơ khoá, tệp gốc + sha256, diff, nhắc rà soát
(đúng một thẻ Hộp việc), hiệu lực từ/đến, agent CHỈ thấy bản đã ban hành (search/get/core), cô lập tổ chức.
ORM thật trên SQLite, gateway giả."""
from datetime import datetime, timedelta

from app.models import Agent, KnowledgeDocument, Member, User
from app.models.extended import InboxItem
from app.services import doc_library, knowledge_hub
from tests.test_m2b_company_foundation import E  # noqa: F401  (fixture)
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)

POLICY_V1 = "## Đổi trả\n\nKhách được đổi trả trong 7 ngày kể từ khi nhận hàng nếu sản phẩm lỗi do vận chuyển."
POLICY_V2 = "## Đổi trả\n\nKhách được đổi trả trong 10 ngày kể từ khi nhận hàng nếu sản phẩm lỗi do vận chuyển."


def _seats(E):
    """manager = Chị Thảo (nhân viên phòng Bán hàng, không phải trưởng phòng); member = Anh Minh (trưởng phòng
    Bán hàng); owner = Chị Lan (CEO)."""
    thao = Member(organization_id=E.org.id, company_id=E.co.id, department_id=E.sales.id, name="Chị Thảo",
                  member_type="human", role="Chuyên viên", manager_id=E.lead_s.id)
    E.db.add(thao); E.db.commit()
    for email, mid in (("manager@m3.test", thao.id), ("member@m3.test", E.lead_s.id), ("owner@m3.test", E.boss.id)):
        u = E.db.query(User).filter(User.email == email).one()
        u.member_id = mid
    E.db.commit()
    from app.services import authority
    authority.seed_defaults(E.db, E.org.id, E.co.id)
    return thao


def mk(E, role="manager", **body):
    return E.c.post("/api/team/docs", json={"company_id": E.co.id, **body}, headers=E.tok(role))


def _agent_member(E):
    a = hire(E)
    ag = E.db.get(Agent, a["agent_id"])
    return ag, E.db.get(Member, ag.member_id)


def test_lifecycle_approval_by_matrix_and_agents_only_see_published(E):
    thao = _seats(E)
    ag, am = _agent_member(E)
    r = mk(E, title="Chính sách đổi trả", doc_type="policy", content=POLICY_V1, customer_facing=True)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "draft" and d["doc_code"] == "POL-001" and d["doc_class"] == "document"
    assert d["agent_use"] == "core" and d["group"] == "policy" and d["owner_member_id"] == thao.id
    v1 = d["versions"][0]
    assert v1["status"] == "draft" and v1["version_no"] == 1
    # nháp: agent không thấy (search / get / cốt lõi)
    assert knowledge_hub.search(E.db, E.org.id, "đổi trả 7 ngày", member=am, agent=ag)["hits"] == []
    core = knowledge_hub.core_for_member(E.db, am, ag)
    assert "7 ngày" not in core
    assert E.c.post("/api/team/docs", json={"company_id": E.co.id, "title": "x", "doc_type": "policy", "content": "ngắn"},
                    headers=E.tok("manager")).status_code == 422
    assert mk(E, role="member", title="y", doc_type="policy", content=POLICY_V1).status_code == 403
    # gửi duyệt: chính sách gửi khách = rủi ro cao → chủ (Chị Lan)
    s = E.c.post(f"/api/team/docs/{d['id']}/versions/{v1['id']}/submit", headers=E.tok("manager"))
    assert s.status_code == 200, s.text
    s = s.json()
    assert s["status"] == "in_review" and s["pending_version"]["approver_member_id"] == E.boss.id
    assert s["authority"]["approver_kind"] == "owner" and s["approval_id"]
    # bản đã gửi duyệt là bất biến
    assert E.c.patch(f"/api/team/docs/{d['id']}/versions/{v1['id']}", json={"content": POLICY_V2 + " sửa"},
                     headers=E.tok("manager")).status_code == 409
    assert knowledge_hub.search(E.db, E.org.id, "đổi trả 7 ngày", member=am, agent=ag)["hits"] == []
    # tác giả / người không phải người duyệt không duyệt được
    assert E.c.post(f"/api/team/docs/{d['id']}/versions/{v1['id']}/decide", json={"decision": "approved"},
                    headers=E.tok("manager")).status_code == 403
    assert E.c.post(f"/api/team/docs/{d['id']}/versions/{v1['id']}/decide", json={"decision": "approved"},
                    headers=E.tok("member")).status_code == 403
    ok = E.c.post(f"/api/team/docs/{d['id']}/versions/{v1['id']}/decide", json={"decision": "approved", "note": "OK"},
                  headers=E.tok("owner"))
    assert ok.status_code == 200, ok.text
    ok = ok.json()
    assert ok["published"] and ok["status"] == "published" and ok["version_no"] == 1 and ok["review_due_at"]
    from app.models import Approval
    assert E.db.get(Approval, s["approval_id"]).status == "approved"
    E.db.expire_all()
    hits = knowledge_hub.search(E.db, E.org.id, "đổi trả 7 ngày", member=am, agent=ag)["hits"]
    assert hits and hits[0]["document_id"] == d["id"]
    assert "7 ngày" in knowledge_hub.core_for_member(E.db, am, ag)
    # phiên bản 2: trong lúc soạn/chờ duyệt agent vẫn đọc v1
    v2 = E.c.post(f"/api/team/docs/{d['id']}/versions", json={"content": POLICY_V2 + " (nháp)", "change_note": "7 → 10 ngày"},
                  headers=E.tok("manager"))
    assert v2.status_code == 200, v2.text
    v2 = v2.json()
    assert v2["version_no"] == 2 and v2["status"] == "draft"
    assert E.c.post(f"/api/team/docs/{d['id']}/versions", json={"content": POLICY_V2}, headers=E.tok("manager")).status_code == 409
    assert E.c.patch(f"/api/team/docs/{d['id']}/versions/{v2['id']}", json={"content": POLICY_V2}, headers=E.tok("manager")).status_code == 200
    E.c.post(f"/api/team/docs/{d['id']}/versions/{v2['id']}/submit", headers=E.tok("manager"))
    E.db.expire_all()
    assert "7 ngày" in knowledge_hub.core_for_member(E.db, am, ag) and "10 ngày" not in knowledge_hub.core_for_member(E.db, am, ag)
    # duyệt qua Hộp việc chung (/api/approvals/{id}/resolve) cũng ban hành
    det = E.c.get(f"/api/team/docs/{d['id']}", headers=E.tok("owner")).json()
    assert det["i_can_approve"] is True
    aid = det["pending_version"]["approval_id"]
    assert E.c.post(f"/api/approvals/{aid}/resolve", json={"status": "approved"}, headers=E.tok("manager")).status_code == 403
    rr = E.c.post(f"/api/approvals/{aid}/resolve", json={"status": "approved", "resolution_note": "Đồng ý"}, headers=E.tok("owner"))
    assert rr.status_code == 200, rr.text
    E.db.expire_all()
    det = E.c.get(f"/api/team/docs/{d['id']}", headers=E.tok("owner")).json()
    assert det["version_no"] == 2 and [v["status"] for v in det["versions"]] == ["published", "superseded"]
    core = knowledge_hub.core_for_member(E.db, am, ag)
    assert "10 ngày" in core and "7 ngày" not in core
    df = E.c.get(f"/api/team/docs/{d['id']}/diff?a=1&b=2", headers=E.tok("manager")).json()
    assert df["added"] == 1 and df["removed"] == 1 and any("10 ngày" in ln for ln in df["lines"])
    # MCP get của agent: chỉ bản đã ban hành
    from app.services.company_mcp import ToolContext, _knowledge_get
    got = _knowledge_get(ToolContext(db=E.db, member=am, agent=ag), {"document_id": d["id"]})
    assert "10 ngày" in got["content"] if "content" in got else "10 ngày" in str(got)


def test_sop_goes_to_department_head_and_rejection_returns_to_draft(E):
    _seats(E)
    r = mk(E, title="SOP đóng gói hàng gốm", doc_type="sop", department_id=E.sales.id,
           content="## Bước 1\n\nBọc mút hai lớp quanh sản phẩm.\n\n## Bước 2\n\nĐóng thùng carton 5 lớp.").json()
    assert r["doc_code"] == "PRC-001" and r["agent_use"] == "retrieve" and r["review_interval_days"] == 90
    vid = r["versions"][0]["id"]
    s = E.c.post(f"/api/team/docs/{r['id']}/versions/{vid}/submit", headers=E.tok("manager")).json()
    assert s["pending_version"]["approver_member_id"] == E.lead_s.id and s["authority"]["approver_kind"] == "department_head"
    no = E.c.post(f"/api/team/docs/{r['id']}/versions/{vid}/decide", json={"decision": "rejected", "note": "Thiếu bước dán nhãn"},
                  headers=E.tok("member"))
    assert no.status_code == 200, no.text
    no = no.json()
    assert no["status"] == "draft" and no["versions"][0]["status"] == "rejected" and no["versions"][0]["review_note"]
    # bản bị trả về không sửa được nữa → phiên bản mới
    v2 = E.c.post(f"/api/team/docs/{r['id']}/versions", json={"content": "## Bước 1\n\nBọc mút.\n\n## Bước 3\n\nDán nhãn dễ vỡ."},
                  headers=E.tok("manager")).json()
    assert v2["version_no"] == 2
    E.c.post(f"/api/team/docs/{r['id']}/versions/{v2['id']}/submit", headers=E.tok("manager"))
    ok = E.c.post(f"/api/team/docs/{r['id']}/versions/{v2['id']}/decide", json={"decision": "approved"}, headers=E.tok("member")).json()
    assert ok["status"] == "published" and ok["version_no"] == 2
    lst = E.c.get(f"/api/team/docs?company_id={E.co.id}&group=process", headers=E.tok("member")).json()
    assert [x["doc_code"] for x in lst["items"]] == ["PRC-001"]
    assert next(g for g in lst["tree"] if g["key"] == "process")["types"] == {"sop": 1}
    # owner gửi duyệt chính sách của mình → chính chủ là người duyệt → ban hành ngay
    p = mk(E, role="owner", title="Chính sách bảo mật", doc_type="policy", content=POLICY_V1).json()
    o = E.c.post(f"/api/team/docs/{p['id']}/versions/{p['versions'][0]['id']}/submit", headers=E.tok("owner")).json()
    assert o["status"] == "published" and o["published"]


def test_records_are_locked_files_are_kept_with_hash(E):
    _seats(E)
    r = mk(E, title="GCN đăng ký doanh nghiệp", doc_type="legal_registration", content="MST 0312345678, cấp ngày 01/02/2024").json()
    assert r["doc_class"] == "record" and r["status"] == "published" and r["agent_use"] == "none"
    assert r["retention_class"] == "company_life" and r["doc_code"] == "LEG-001"
    assert E.c.patch(f"/api/team/docs/{r['id']}", json={"content": "sửa"}, headers=E.tok("manager")).status_code == 409
    assert E.c.patch(f"/api/team/docs/{r['id']}", json={"title": "Tên khác"}, headers=E.tok("manager")).status_code == 409
    assert E.c.post(f"/api/team/docs/{r['id']}/versions", json={"content": "x" * 30}, headers=E.tok("manager")).status_code == 409
    assert E.c.patch(f"/api/team/docs/{r['id']}", json={"legal_hold": True}, headers=E.tok("manager")).json()["legal_hold"] is True
    # hồ sơ mới thay thế hồ sơ cũ
    r2 = mk(E, title="GCN ĐKDN (thay đổi lần 1)", doc_type="legal_registration", content="MST 0312345678, thay đổi 01/03/2026",
            supersedes_id=r["id"]).json()
    assert r2["supersedes_id"] == r["id"]
    assert E.c.get(f"/api/team/docs/{r['id']}", headers=E.tok("manager")).json()["status"] == "superseded"
    # tệp gốc: markdown → tài liệu nháp có nội dung trích + tệp sha256 tải lại đúng bytes
    raw = "# Sổ tay CSKH\n\nChào khách bằng tên, trả lời trong 5 phút giờ hành chính.".encode()
    up = E.c.post("/api/team/docs/upload", data={"company_id": str(E.co.id), "doc_type": "handbook"},
                  files={"file": ("so-tay.md", raw, "text/markdown")}, headers=E.tok("manager"))
    assert up.status_code == 200, up.text
    up = up.json()
    import hashlib
    assert up["title"] == "so-tay" and up["file"]["sha256"] == hashlib.sha256(raw).hexdigest() and up["status"] == "draft"
    got = E.c.get(f"/api/team/docs/files/{up['file']['id']}", headers=E.tok("manager"))
    assert got.status_code == 200 and got.content == raw
    # ảnh scan: không thành tài liệu (không có chữ) nhưng lưu được làm hồ sơ
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    bad = E.c.post("/api/team/docs/upload", data={"company_id": str(E.co.id), "doc_type": "handbook"},
                   files={"file": ("scan.png", png, "image/png")}, headers=E.tok("manager"))
    assert bad.status_code == 422
    rec = E.c.post("/api/team/docs/upload", data={"company_id": str(E.co.id), "doc_type": "license", "title": "Giấy phép ATTP"},
                   files={"file": ("scan.png", png, "image/png")}, headers=E.tok("manager"))
    assert rec.status_code == 200, rec.text
    assert rec.json()["doc_class"] == "record" and rec.json()["chars"] == 0 and rec.json()["status"] == "published"
    # dữ liệu cá nhân không bao giờ cho agent dùng
    hr = mk(E, title="HĐLĐ Chị Thảo", doc_type="employment_contract", content="CCCD 079123456789 — lương 9 triệu").json()
    assert hr["sensitivity"] == "personal_data" and hr["agent_use"] == "none"
    assert E.c.patch(f"/api/team/docs/{hr['id']}", json={"agent_use": "retrieve"}, headers=E.tok("manager")).json()["agent_use"] == "none"
    # người xem thường (member) không đọc được nội dung mức personal_data/confidential
    det = E.c.get(f"/api/team/docs/{hr['id']}", headers=E.tok("member")).json()
    assert det["can_read"] is False and det["content"] == ""


def test_review_reminder_one_inbox_card_effective_window_and_isolation(E):
    thao = _seats(E)
    ag, am = _agent_member(E)
    p = mk(E, role="owner", title="Giờ làm việc", doc_type="handbook", agent_use="core", review_interval_days=30,
           content="Tiệm mở cửa 8:00–21:00 mỗi ngày, kể cả Chủ nhật.").json()
    E.c.post(f"/api/team/docs/{p['id']}/versions/{p['versions'][0]['id']}/submit", headers=E.tok("owner"))
    E.db.expire_all()
    later = datetime.utcnow() + timedelta(days=31)
    out = doc_library.tick(E.db, now=later)
    assert out["review_due"] == 1
    assert doc_library.tick(E.db, now=later + timedelta(hours=1))["review_due"] == 0     # đúng một thẻ mỗi hạn
    cards = E.db.query(InboxItem).filter(InboxItem.item_type == "doc_review_due").all()
    assert len(cards) == 1 and cards[0].recipient_member_id == E.boss.id and cards[0].related_id == str(p["id"])
    det = E.c.get(f"/api/team/docs/{p['id']}", headers=E.tok("owner")).json()
    assert det["review_state"] in ("due", "ok")
    assert doc_library.review_state(E.db.get(KnowledgeDocument, p["id"]), now=later + timedelta(days=31)) == "stale"
    # đánh dấu đã rà soát → hạn mới
    rv = E.c.post(f"/api/team/docs/{p['id']}/review", json={"note": "Vẫn đúng"}, headers=E.tok("manager")).json()
    assert rv["review_due_at"] > det["review_due_at"]
    # hết hiệu lực → lưu trữ + rời phần cốt lõi
    assert "8:00–21:00" in knowledge_hub.core_for_member(E.db, am, ag)
    E.c.patch(f"/api/team/docs/{p['id']}", json={"effective_to": (datetime.utcnow() + timedelta(days=1)).isoformat()},
              headers=E.tok("manager"))
    assert doc_library.tick(E.db, now=datetime.utcnow() + timedelta(days=2))["archived"] == 1
    E.db.expire_all()
    assert "8:00–21:00" not in knowledge_hub.core_for_member(E.db, am, ag)
    # đã duyệt nhưng hiệu lực từ ngày mai → chưa ban hành; tick tới ngày → ban hành
    tomorrow = datetime.utcnow() + timedelta(days=1)
    f = mk(E, role="owner", title="Bảng giá mùa Tết", doc_type="promo", content="Giảm 10% bình gốm men lam tới hết tháng Giêng.",
           effective_from=tomorrow.isoformat()).json()
    s = E.c.post(f"/api/team/docs/{f['id']}/versions/{f['versions'][0]['id']}/submit", headers=E.tok("owner")).json()
    assert s["status"] == "approved" and not s["published"]
    assert knowledge_hub.search(E.db, E.org.id, "giảm bình gốm men lam", member=am, agent=ag)["hits"] == []
    assert doc_library.tick(E.db, now=tomorrow + timedelta(minutes=1))["published"] == 1
    E.db.expire_all()
    fd = E.db.get(KnowledgeDocument, f["id"])
    assert fd.status == "published" and fd.effective_from == tomorrow.replace(microsecond=fd.effective_from.microsecond)
    # trong hiệu lực (giờ thật vẫn trước ngày hiệu lực → agent chưa thấy; dời ngày hiệu lực về quá khứ → thấy)
    fd.effective_from = datetime.utcnow() - timedelta(minutes=1); E.db.commit()
    assert knowledge_hub.search(E.db, E.org.id, "giảm bình gốm men lam", member=am, agent=ag)["hits"]
    # cô lập: tổ chức khác không thấy, không sửa được
    assert E.c.get(f"/api/team/docs/{p['id']}", headers=E.tok("other")).status_code == 404
    assert E.c.patch(f"/api/team/docs/{p['id']}", json={"title": "x"}, headers=E.tok("other")).status_code == 404
    assert E.c.get(f"/api/team/docs?company_id={E.co.id}", headers=E.tok("other")).status_code == 404
    assert E.c.get(f"/api/team/docs/files/{999}", headers=E.tok("other")).status_code == 404
    assert thao.id


def test_legacy_knowledge_ingest_is_published_v1_with_code(E):
    r = E.c.post("/api/learning/docs", json={"title": "Kịch bản CSKH", "content": "Chào anh/chị, Tiệm Gốm Mộc nghe ạ. " * 3,
                                              "company_id": E.co.id}, headers=E.tok("manager")).json()
    assert r["status"] == "published" and r["version_no"] == 1 and r["doc_code"].startswith("POL-")
    det = E.c.get(f"/api/team/docs/{r['id']}", headers=E.tok("manager")).json()
    assert [v["status"] for v in det["versions"]] == ["published"]
