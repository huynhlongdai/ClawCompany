"""M3 cleanup — ngưỡng % đổi giá cần chủ duyệt (price_change) là cài đặt theo công ty, không còn hằng số 10 trong code:
mặc định 10; quản trị công ty (chủ) đổi được 1..100 hoặc trả về mặc định (null); trưởng phòng / nhân viên không đổi được;
cùng một mức +15% đi trưởng phòng khi ngưỡng 20 nhưng đi chủ khi ngưỡng 10; công ty khác không bị ảnh hưởng; giá đầu tiên
luôn rủi ro cao; listing trả ngưỡng đang áp dụng (UI hiện trong lời giải thích)."""
from app.services import catalog
from tests.test_m2b_company_foundation import E  # noqa: F401  (fixture)
from tests.test_m3_agents import env  # noqa: F401  (fixture)
from tests.test_m3a_document_library import _seats
from tests.test_m3f_catalog import mkp, propose


def _set(E, pct, role="owner", company_id=None):
    return E.c.put("/api/team/catalog/settings", json={"company_id": company_id or E.co.id, "high_pct": pct}, headers=E.tok(role))


def test_threshold_is_a_company_setting_that_routes_price_changes(E):
    _seats(E)
    s = E.c.get(f"/api/team/catalog/settings?company_id={E.co.id}", headers=E.tok("member")).json()
    assert s["high_pct"] == 10 and s["default_high_pct"] == 10 and s["custom"] is False
    p = mkp(E, sku="BINH-GOM", name="Bình gốm men rạn", price=200000).json()

    # mặc định 10%: +15% → rủi ro cao → chủ
    big = propose(E, p["id"], 230000).json()
    assert big["risk"] == "high" and big["approver_member_id"] == E.boss.id
    assert E.c.post(f"/api/team/catalog/prices/{big['id']}/cancel", headers=E.tok("manager")).status_code == 200

    # chỉ quản trị đổi ngưỡng; ngoài 1..100 → 422 có mã lỗi
    assert _set(E, 20, role="member").status_code == 403
    assert _set(E, 20, role="manager").status_code == 403
    for bad in (0, 101, "abc"):
        r = _set(E, bad)
        assert r.status_code == 422 and r.json()["detail"]["error"] in ("threshold_range", "invalid_threshold"), r.text
    r = _set(E, 20)
    assert r.status_code == 200 and r.json()["high_pct"] == 20 and r.json()["custom"] is True
    assert catalog.high_pct(E.db, E.co.id) == 20
    assert E.c.get(f"/api/team/catalog?company_id={E.co.id}", headers=E.tok("member")).json()["high_pct"] == 20

    # ngưỡng 20%: cùng +15% → thường → trưởng phòng
    small = propose(E, p["id"], 230000).json()
    assert small["risk"] == "normal" and small["approver_member_id"] == E.lead_s.id
    assert E.c.post(f"/api/team/catalog/prices/{small['id']}/cancel", headers=E.tok("manager")).status_code == 200
    # +25% vẫn vượt ngưỡng → chủ
    assert propose(E, p["id"], 250000).json()["risk"] == "high"

    # giá đầu tiên luôn rủi ro cao dù ngưỡng cao
    q = mkp(E, role="manager", sku="DIA-SEN", name="Đĩa sen", price=90000).json()
    assert q["price_request"]["risk"] == "high"

    # null → về mặc định
    r = _set(E, None)
    assert r.status_code == 200 and r.json()["high_pct"] == 10 and r.json()["custom"] is False


def test_threshold_of_one_company_does_not_leak_to_another(E):
    _seats(E)
    from app.models import Company
    other = Company(organization_id=E.org.id, name="Công ty khác", status="active")
    E.db.add(other); E.db.commit()
    assert _set(E, 35).status_code == 200
    assert catalog.high_pct(E.db, E.co.id) == 35
    assert catalog.high_pct(E.db, other.id) == catalog.HIGH_PCT == 10
