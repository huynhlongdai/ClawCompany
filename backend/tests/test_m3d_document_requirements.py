"""M3d — hồ sơ bắt buộc & lưu trữ: danh mục theo điều kiện (số lao động là NGƯỜI, agent không tính), căn cứ pháp lý +
"cần kiểm tra", lớp "Hồ sơ & tài liệu" trong chấm sẵn sàng, hạn lưu tự tính (NĐ 174 mốc kết thúc năm), xoá/huỷ trước hạn →
409, huỷ cần chủ + giữ hash, đúng một thẻ nhắc huỷ, giấy phép hết hạn → lịch tuân thủ. ORM thật trên SQLite, gateway giả."""
from datetime import date, datetime, timedelta

from app.models import KnowledgeDocument, Member
from app.models.company_ops import ComplianceDeadline
from app.models.extended import InboxItem
from app.services import doc_library
from tests.test_m2b_company_foundation import CHARTER, E, put_profile  # noqa: F401  (fixture)
from tests.test_m3_agents import env, hire  # noqa: F401  (fixture)


def _reqs(E, role="member"):
    r = E.c.get(f"/api/team/doc-requirements?company_id={E.co.id}", headers=E.tok(role))
    assert r.status_code == 200, r.text
    return r.json()


def _item(ev, key):
    return next(i for i in ev["items"] if i["key"] == key)


def _humans(E):
    return E.db.query(Member).filter(Member.company_id == E.co.id, Member.member_type == "human",
                                     Member.status != "archived").all()


def _set_humans(E, n):
    cur = _humans(E)
    for i in range(len(cur), n):
        E.db.add(Member(organization_id=E.org.id, company_id=E.co.id, name=f"NV {i}", member_type="human", role="Nhân viên"))
    for m in cur[n:]:
        m.status = "archived"
    E.db.commit()


def test_labor_rules_follow_human_headcount_agents_not_counted(E):
    put_profile(E, **CHARTER)
    hire(E)                                   # một ghế agent: không được tính là người lao động
    _set_humans(E, 12)
    ev = _reqs(E)
    assert ev["facts"]["humans"] == 12 and "không phải tư vấn pháp lý" in ev["disclaimer_vi"]
    w = _item(ev, "labor_rules_written")
    assert w["status"] == "missing" and w["level"] == "required" and "Đ118" in w["legal_basis"] and "Đ119" in w["legal_basis"]
    assert _item(ev, "labor_rules_basic")["status"] == "na"
    assert _item(ev, "member_register")["status"] == "na"          # TNHH 1 TV: không có sổ thành viên
    assert _item(ev, "dpia")["needs_review"] is True
    _set_humans(E, 8)
    ev = _reqs(E)
    assert ev["facts"]["humans"] == 8
    assert _item(ev, "labor_rules_written")["status"] == "na" and "8 người lao động" in _item(ev, "labor_rules_written")["why"]
    b = _item(ev, "labor_rules_basic")
    assert b["status"] == "missing" and b["level"] == "recommended"
    # có nội quy đang ban hành → đạt
    d = E.c.post("/api/team/docs", json={"company_id": E.co.id, "title": "Nội quy lao động", "doc_type": "labor_rules",
                                         "content": "## Giờ làm\n\nTừ 8h đến 17h, nghỉ trưa 1 tiếng."}, headers=E.tok("owner")).json()
    v = d["versions"][0]
    assert E.c.post(f"/api/team/docs/{d['id']}/versions/{v['id']}/submit", headers=E.tok("owner")).status_code == 200
    r = E.c.post(f"/api/team/docs/{d['id']}/versions/{v['id']}/decide", json={"decision": "approved"}, headers=E.tok("owner"))
    assert r.status_code == 200, r.text
    assert _item(_reqs(E), "labor_rules_basic")["status"] == "ok"


def test_retention_computed_delete_before_term_409_disposal_owner_only_keeps_hash(E):
    r = E.c.post("/api/team/docs", json={"company_id": E.co.id, "title": "Phiếu chi 03/2026", "doc_type": "accounting_voucher",
                                         "content": "Chi mua men gốm 2.400.000 đ", "effective_from": "2026-03-05"},
                 headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["status"] == "published" and doc["retention_class"] == "acct_10y"
    assert doc["retain_until"].startswith("2036-12-31")
    assert E.c.delete(f"/api/learning/docs/{doc['id']}", headers=E.tok("manager")).status_code == 409
    assert E.c.post(f"/api/team/docs/{doc['id']}/dispose", json={}, headers=E.tok("owner")).status_code == 409
    ev = _reqs(E)
    assert any(x["id"] == doc["id"] and not x["due"] for x in ev["retention"]["items"])
    assert _item(ev, "accounting_books")["status"] == "ok"
    # tới hạn: đúng một thẻ cho chủ, giữ pháp lý thì không nhắc
    row = E.db.get(KnowledgeDocument, doc["id"])
    later = datetime(2037, 1, 2)
    assert doc_library.tick(E.db, now=later)["disposal_due"] == 1
    assert doc_library.tick(E.db, now=later + timedelta(hours=1))["disposal_due"] == 0
    assert E.db.query(InboxItem).filter(InboxItem.item_type == "record_disposal_due", InboxItem.related_id == str(doc["id"])).count() == 1
    # đưa hạn về quá khứ để huỷ thật hôm nay; manager không huỷ được, owner được; giữ hash, xoá nội dung
    E.db.refresh(row); row.retain_until = datetime.utcnow() - timedelta(days=1); E.db.commit()
    assert E.c.patch(f"/api/team/docs/{doc['id']}", json={"legal_hold": True}, headers=E.tok("manager")).status_code == 200
    assert E.c.post(f"/api/team/docs/{doc['id']}/dispose", json={}, headers=E.tok("owner")).status_code == 409   # đang giữ pháp lý
    assert E.c.patch(f"/api/team/docs/{doc['id']}", json={"legal_hold": False}, headers=E.tok("manager")).status_code == 403
    assert E.c.patch(f"/api/team/docs/{doc['id']}", json={"legal_hold": False}, headers=E.tok("owner")).status_code == 200
    E.db.refresh(row); row.retain_until = datetime.utcnow() - timedelta(days=1); E.db.commit()
    assert E.c.post(f"/api/team/docs/{doc['id']}/dispose", json={}, headers=E.tok("manager")).status_code == 403
    h = row.content_hash
    r = E.c.post(f"/api/team/docs/{doc['id']}/dispose", json={"reason": "hết hạn 10 năm"}, headers=E.tok("owner"))
    assert r.status_code == 200, r.text
    E.db.refresh(row)
    assert row.status == "disposed" and row.content == "" and row.content_hash == h and row.disposed_at is not None
    assert E.c.post(f"/api/team/docs/{doc['id']}/dispose", json={}, headers=E.tok("owner")).status_code == 409


def test_license_expiry_becomes_compliance_deadline_and_readiness_layer(E):
    put_profile(E, **CHARTER)
    exp = (datetime.utcnow() + timedelta(days=30)).date()
    r = E.c.post("/api/team/docs", json={"company_id": E.co.id, "title": "Giấy chứng nhận ATTP", "doc_type": "license",
                                         "content": "", "effective_to": exp.isoformat()}, headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    lic = r.json()
    dl = E.db.query(ComplianceDeadline).filter(ComplianceDeadline.company_id == E.co.id).all()
    mine = [d for d in dl if d.statutory_date == exp]
    assert len(mine) == 1 and mine[0].assignee_member_id is not None
    assert _item(_reqs(E), "licenses")["status"] == "ok"
    # chấm sẵn sàng có lớp "Hồ sơ & tài liệu" với đường sửa về tab records
    a = E.c.post("/api/team/readiness", json={"company_id": E.co.id}, headers=E.tok("manager")).json()
    layer = next(x for x in a["layers"] if x["key"] == "documents")
    assert layer["label"] == "Hồ sơ & tài liệu" and 0 <= layer["score"] < 100
    chk = {c["key"]: c for c in a["checks"]}
    assert chk["required_records"]["fix_href"] == f"/app/team?tab=records&company={E.co.id}"
    assert "mục bắt buộc" in chk["required_records"]["detail"]
    # lưu trữ giấy phép → nghĩa vụ gia hạn tắt
    assert E.c.post(f"/api/team/docs/{lic['id']}/archive", json={"reason": "đổi giấy"}, headers=E.tok("manager")).status_code == 200


def test_custom_requirement_attach_and_isolation(E):
    r = E.c.post("/api/team/doc-requirements", json={"company_id": E.co.id, "name": "Biên bản PCCC", "level": "required",
                                                     "legal_basis": "Luật PCCC — cần kiểm tra", "needs_review": True},
                 headers=E.tok("manager"))
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    assert E.c.post("/api/team/doc-requirements", json={"company_id": E.co.id, "name": "x"}, headers=E.tok("member")).status_code == 403
    assert E.c.post("/api/team/doc-requirements", json={"company_id": E.co.id, "name": "y", "level": "must"},
                    headers=E.tok("manager")).status_code == 422
    assert _item(_reqs(E), r.json()["key"])["status"] == "missing"
    # hồ sơ lớp record, loại 'other' (danh mục không có loại PCCC riêng) → gắn thẳng vào mục
    d = E.c.post("/api/team/docs", json={"company_id": E.co.id, "title": "Biên bản kiểm tra PCCC 2026", "doc_type": "other",
                                         "doc_class": "record", "content": ""}, headers=E.tok("manager"))
    assert d.status_code == 200, d.text
    assert E.c.post(f"/api/team/doc-requirements/{rid}/attach", json={"document_id": d.json()["id"]},
                    headers=E.tok("manager")).status_code == 200
    it = _item(_reqs(E), r.json()["key"])
    assert it["status"] == "ok" and it["documents"][0]["id"] == d.json()["id"]
    assert E.c.patch(f"/api/team/doc-requirements/{rid}", json={"enabled": False}, headers=E.tok("manager")).status_code == 200
    assert _item(_reqs(E), r.json()["key"])["status"] == "na"
    # tổ chức khác không thấy / không sửa được
    assert E.c.patch(f"/api/team/doc-requirements/{rid}", json={"enabled": True}, headers=E.tok("other")).status_code == 404
    other = E.c.get("/api/team/doc-requirements", headers=E.tok("other")).json()
    assert other["company_id"] != E.co.id and all(i["key"] != r.json()["key"] for i in other["items"])
