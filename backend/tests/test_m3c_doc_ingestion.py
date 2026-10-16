"""M3c — nạp & phân loại tài liệu: PDF có/không lớp chữ (OCR nếu máy có Tesseract, không thì 422 rõ ràng), XLSX, URL,
GCN ĐKDN → đề xuất hồ sơ pháp nhân (≥4/5 trường trên 5 mẫu, không ghi thẳng), chống trùng sha256, PII → personal_data +
agent_use=none, mọi tài liệu nạp ở trạng thái nháp, "Tạo từ mẫu", nguồn Notion/Drive (token không bao giờ trả ra; sửa
trang → bản nháp mới trong 1 chu kỳ). ORM thật trên SQLite, gateway giả, API Notion giả."""
import io
import shutil
import subprocess
import zipfile

import pytest

from app.models import KnowledgeDocument
from app.models.company_foundation import CompanyProfile
from app.models.documents import DocumentVersion
from app.services import doc_ingest, knowledge_hub
from tests.test_m2b_company_foundation import E  # noqa: F401  (fixture)
from tests.test_m3_agents import env  # noqa: F401  (fixture)


def _pdf(lines: list[str]) -> bytes:
    """PDF 1 trang tối thiểu, chữ Helvetica (ASCII). lines=[] → trang không có lớp chữ (như bản scan)."""
    ops = "".join(f"BT /F1 12 Tf 50 {780 - 18 * i} Td ({ln}) Tj ET\n" for i, ln in enumerate(lines))
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(ops)} >>\nstream\n{ops}endstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return out


def _xlsx(rows: list[list[str]]) -> bytes:
    strings = sorted({c for r in rows for c in r})
    idx = {s: i for i, s in enumerate(strings)}
    sheet = "".join("<row>" + "".join(f'<c t="s"><v>{idx[c]}</v></c>' for c in r) + "</row>" for r in rows)
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns}><sheets><sheet name="Bang gia" sheetId="1"/></sheets></workbook>')
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{sheet}</sheetData></worksheet>")
    return buf.getvalue()


def up(E, name, data, role="manager", **form):
    return E.c.post("/api/team/doc-imports/file", files={"file": (name, data)},
                    data={"company_id": str(E.co.id), **form}, headers=E.tok(role))


GCN = [
    # 1. bản chữ chuẩn (có dấu)
    """GIẤY CHỨNG NHẬN ĐĂNG KÝ DOANH NGHIỆP
CÔNG TY TRÁCH NHIỆM HỮU HẠN MỘT THÀNH VIÊN
Mã số doanh nghiệp: 0312345678
Đăng ký lần đầu: ngày 05 tháng 03 năm 2021
1. Tên công ty
Tên công ty viết bằng tiếng Việt: CÔNG TY TNHH GỐM MỘC
2. Địa chỉ trụ sở chính: 12 Lê Lợi, Phường Bến Nghé, Quận 1, TP. Hồ Chí Minh
3. Vốn điều lệ: 500.000.000 đồng
4. Người đại diện theo pháp luật của công ty
Họ và tên: NGUYỄN THỊ LAN Giới tính: Nữ
""",
    # 2. OCR mất dấu
    """GIAY CHUNG NHAN DANG KY DOANH NGHIEP
Ma so doanh nghiep: 0109876543
Dang ky lan dau: ngay 12 thang 11 nam 2019
Ten cong ty viet bang tieng Viet: CONG TY CO PHAN HOA NONG
Dia chi tru so chinh: 45 Tran Phu, Ha Dong, Ha Noi
Von dieu le: 2.000.000.000 dong
Nguoi dai dien theo phap luat cua cong ty
Ho va ten: TRAN VAN MINH Gioi tinh: Nam
""",
    # 3. ngày dạng dd/mm/yyyy, MST có khoảng trắng
    """Giấy chứng nhận đăng ký doanh nghiệp công ty cổ phần
Mã số doanh nghiệp: 0315 678 901
Đăng ký lần đầu: 01/07/2022
Tên công ty viết bằng tiếng Việt: CÔNG TY CỔ PHẦN BẾP NHÀ
Địa chỉ trụ sở chính: 9 Nguyễn Huệ, Quận 1, TP. Hồ Chí Minh
Vốn điều lệ: 1.500.000.000 đồng
NGƯỜI ĐẠI DIỆN THEO PHÁP LUẬT CỦA CÔNG TY
* Họ và tên: LÊ THỊ HOA
""",
    # 4. bố cục xuống dòng, thiếu vốn
    """GIẤY CHỨNG NHẬN ĐĂNG KÝ DOANH NGHIỆP
Mã số doanh nghiệp : 0401234567
Đăng ký lần đầu : ngày 20 tháng 8 năm 2018
Tên công ty viết bằng tiếng Việt : CÔNG TY TNHH DU LỊCH BIỂN XANH
Địa chỉ trụ sở chính : 100 Bạch Đằng, Hải Châu, Đà Nẵng
Người đại diện theo pháp luật của công ty
Họ và tên : PHẠM QUỐC BẢO
""",
    # 5. hộ kinh doanh chuyển đổi, chữ thường
    """giấy chứng nhận đăng ký doanh nghiệp
mã số doanh nghiệp: 1801112223
đăng ký lần đầu: ngày 2 tháng 1 năm 2024
tên công ty viết bằng tiếng việt: công ty tnhh trà cần thơ
địa chỉ trụ sở chính: 3 Hai Bà Trưng, Ninh Kiều, Cần Thơ
vốn điều lệ: 300.000.000 đồng
người đại diện theo pháp luật
họ và tên: võ thị thu
""",
]
EXPECT = [
    {"tax_code": "0312345678", "founded_on": "2021-03-05", "legal_name": "CÔNG TY TNHH GỐM MỘC", "legal_representative": "NGUYỄN THỊ LAN"},
    {"tax_code": "0109876543", "founded_on": "2019-11-12", "legal_name": "CONG TY CO PHAN HOA NONG", "legal_representative": "TRAN VAN MINH"},
    {"tax_code": "0315678901", "founded_on": "2022-07-01", "legal_name": "CÔNG TY CỔ PHẦN BẾP NHÀ", "legal_representative": "LÊ THỊ HOA"},
    {"tax_code": "0401234567", "founded_on": "2018-08-20", "legal_name": "CÔNG TY TNHH DU LỊCH BIỂN XANH", "legal_representative": "PHẠM QUỐC BẢO"},
    {"tax_code": "1801112223", "founded_on": "2024-01-02", "legal_name": "công ty tnhh trà cần thơ", "legal_representative": "võ thị thu"},
]


def test_registration_extraction_hits_4_of_5_fields_on_5_samples_and_is_only_a_proposal(E):
    for text, want in zip(GCN, EXPECT):
        got = doc_ingest.extract_registration(text)
        hits = sum(1 for k, v in want.items() if got.get(k) == v) + (1 if got.get("registered_address") else 0)
        assert hits >= 4, (want, got)
    assert doc_ingest.extract_registration(GCN[0])["charter_capital_vnd"] == 500_000_000
    # upload as a text file → draft record + proposal; profile untouched until an admin applies
    r = up(E, "gcn-dkdn.txt", GCN[0].encode())
    assert r.status_code == 200, r.text
    im, doc = r.json()["import"], r.json()["document"]
    assert doc["status"] == "draft" and doc["doc_type"] == "legal_registration"
    assert im["proposals"]["company_profile"]["tax_code"] == "0312345678" and im["proposals_status"] == "pending"
    p = E.db.query(CompanyProfile).filter(CompanyProfile.company_id == E.co.id).first()
    assert p is None or p.tax_code != "0312345678"
    assert E.c.post(f"/api/team/doc-imports/{im['id']}/proposals", json={"action": "apply"},
                    headers=E.tok("manager")).status_code == 403          # hồ sơ pháp nhân: admin/chủ
    a = E.c.post(f"/api/team/doc-imports/{im['id']}/proposals", json={"action": "apply"}, headers=E.tok("owner"))
    assert a.status_code == 200, a.text
    E.db.expire_all()
    p = E.db.query(CompanyProfile).filter(CompanyProfile.company_id == E.co.id).one()
    assert p.tax_code == "0312345678" and p.legal_representative == "NGUYỄN THỊ LAN" and str(p.founded_on) == "2021-03-05"
    assert "500.000.000 ₫" in p.charter_capital_note and p.charter_capital_usd is None   # không tự quy đổi VND→USD
    assert E.c.post(f"/api/team/doc-imports/{im['id']}/proposals", json={"action": "apply"},
                    headers=E.tok("owner")).status_code == 409


def test_pdf_text_layer_scan_without_ocr_is_422_and_duplicates_are_409(E, monkeypatch):
    body = ["Chinh sach doi tra", "Khach duoc doi tra trong 7 ngay ke tu khi nhan hang neu san pham loi."]
    r = up(E, "doi-tra.pdf", _pdf(body))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["import"]["method"] == "pypdf" and not j["import"]["ocr_used"]
    assert j["document"]["status"] == "draft" and j["document"]["doc_type"] == "policy"
    assert j["import"]["sha256"] and len(j["import"]["sha256"]) == 64
    # same bytes again → 409 with the existing code; recorded as a duplicate import
    d = up(E, "doi-tra-copy.pdf", _pdf(body))
    assert d.status_code == 409 and d.json()["detail"]["doc_code"] == j["document"]["doc_code"]
    # same content through another path (URL) → 409 too
    monkeypatch.setattr(knowledge_hub, "fetch_url", lambda url: ("Doi tra", "\n".join(body)))
    u = E.c.post("/api/team/doc-imports/url", json={"company_id": E.co.id, "url": "https://shop.example/doi-tra"},
                 headers=E.tok("manager"))
    assert u.status_code == 409, u.text
    # scan PDF (no text layer) on a server without Tesseract → explicit 422, never an empty document
    monkeypatch.setattr(doc_ingest, "ocr_status", lambda: {"tesseract": False, "pdftoppm": False, "langs": [], "vie": False})
    s = up(E, "scan.pdf", _pdf([]))
    assert s.status_code == 422 and s.json()["detail"]["error"] == "empty_text"
    assert "Tesseract" in s.json()["detail"]["message"]
    assert E.db.query(KnowledgeDocument).filter(KnowledgeDocument.title == "scan").count() == 0
    # … but the same scan chosen explicitly as a record is stored (file + metadata) as a draft
    rec = up(E, "scan-gcn.pdf", _pdf([]), doc_type="legal_registration")
    assert rec.status_code == 200, rec.text
    assert rec.json()["document"]["status"] == "draft" and rec.json()["document"]["doc_class"] == "record"
    lst = E.c.get(f"/api/team/doc-imports?company_id={E.co.id}", headers=E.tok("member")).json()
    assert {x["status"] for x in lst["items"]} >= {"done", "duplicate", "empty"}
    assert "tesseract" in lst["ocr"]


@pytest.mark.skipif(not (shutil.which("tesseract") and shutil.which("pdftoppm") and shutil.which("convert")),
                    reason="máy test không có tesseract/pdftoppm/ImageMagick")
def test_scanned_pdf_is_ocrd_when_tesseract_is_installed(E, tmp_path):
    png = tmp_path / "scan.png"
    subprocess.run(["convert", "-size", "1400x300", "xc:white", "-pointsize", "48", "-fill", "black", "-annotate",
                    "+40+120", "MA SO DOANH NGHIEP: 0312345678", str(png)], check=True)
    pdf = tmp_path / "scan.pdf"
    subprocess.run(["convert", str(png), str(pdf)], check=True)
    r = up(E, "scan-ocr.pdf", pdf.read_bytes())
    assert r.status_code == 200, r.text
    assert r.json()["import"]["ocr_used"] and r.json()["import"]["method"] == "ocr:tesseract"
    assert "0312345678" in r.json()["import"]["proposals"]["company_profile"]["tax_code"]


def test_xlsx_pii_and_templates(E):
    x = up(E, "bang-gia.xlsx", _xlsx([["San pham", "Gia (VND)"], ["Binh hoa men lam", "450000"], ["Chen com", "65000"]]))
    assert x.status_code == 200, x.text
    v = E.db.query(DocumentVersion).filter(DocumentVersion.document_id == x.json()["document"]["id"]).one()
    assert "| Binh hoa men lam | 450000 |" in v.content and x.json()["document"]["doc_type"] == "price_list"
    # ≥3 CCCD numbers → personal_data + agent_use none (even if the user asked for 'retrieve')
    staff = "Danh sach nhan vien\n" + "\n".join(f"Nguyen Van {c} CCCD 0791990{n:05d}" for c, n in zip("ABC", (11, 22, 33)))
    p = up(E, "nhan-vien.txt", staff.encode(), agent_use="retrieve")
    assert p.status_code == 200, p.text
    d = p.json()["document"]
    assert d["sensitivity"] == "personal_data" and d["agent_use"] == "none"
    assert p.json()["import"]["suggestions"]["pii"]["cccd"] == 3
    # templates
    lst = E.c.get(f"/api/team/doc-imports?company_id={E.co.id}", headers=E.tok("member")).json()
    keys = {t["key"] for t in lst["templates"]}
    assert {"noi_quy", "doi_tra", "cskh", "bao_mat_dlcn"} <= keys
    t = E.c.post("/api/team/doc-imports/template", json={"company_id": E.co.id, "key": "noi_quy"}, headers=E.tok("manager"))
    assert t.status_code == 200, t.text
    td = t.json()["document"]
    assert td["status"] == "draft" and td["doc_type"] == "labor_rules"
    tv = E.db.query(DocumentVersion).filter(DocumentVersion.document_id == td["id"]).one()
    assert E.co.name in tv.content and "Đ118" in tv.change_note
    assert E.c.post("/api/team/doc-imports/template", json={"company_id": E.co.id, "key": "noi_quy"},
                    headers=E.tok("member")).status_code == 403


class FakeNotion:
    def __init__(self):
        self.edited, self.text = "2026-10-16T01:00:00.000Z", "Giờ mở cửa 8:00 đến 21:00 mỗi ngày, kể cả Chủ nhật."

    def __call__(self, conn, s, path, **params):
        assert doc_ingest.unseal(s.credential_enc) == "secret_notion_TOKEN1234"
        if path.startswith("/pages/"):
            return {"last_edited_time": self.edited,
                    "properties": {"Name": {"type": "title", "title": [{"plain_text": "Giờ mở cửa"}]}}}
        return {"results": [{"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Giờ mở cửa"}]}},
                            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": self.text}]}}],
                "has_more": False}


def test_notion_and_drive_sources_sync_to_drafts_and_never_leak_the_token(E, monkeypatch):
    fake = FakeNotion()
    monkeypatch.setattr(doc_ingest.NotionConnector, "_get", lambda self, s, path, **p: fake(self, s, path, **p))
    g = E.c.post("/api/team/doc-sources", json={"company_id": E.co.id, "kind": "gdrive", "name": "Drive CSKH",
                                                "config": {"folder_id": "abc"}}, headers=E.tok("manager"))
    assert g.status_code == 200 and g.json()["status"] == "needs_account"
    assert E.c.post(f"/api/team/doc-sources/{g.json()['id']}/sync", headers=E.tok("manager")).json()["status"] == "needs_account"
    n = E.c.post("/api/team/doc-sources", json={"company_id": E.co.id, "kind": "notion", "name": "Notion",
                                                "config": {"page_ids": ["https://notion.so/Gio-1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"]},
                                                "credential": "secret_notion_TOKEN1234"}, headers=E.tok("manager"))
    assert n.status_code == 200, n.text
    assert "TOKEN1234" not in n.text and n.json()["credential_hint"] == "…1234" and n.json()["status"] == "active"
    sid = n.json()["id"]
    s1 = E.c.post(f"/api/team/doc-sources/{sid}/sync", headers=E.tok("manager")).json()
    assert s1["created"] == 1, s1
    lst = E.c.get(f"/api/team/doc-imports?company_id={E.co.id}", headers=E.tok("member"))
    assert "TOKEN1234" not in lst.text
    doc = E.db.query(KnowledgeDocument).filter(KnowledgeDocument.title == "Giờ mở cửa").one()
    assert doc.status == "draft"
    # unchanged page → nothing new
    assert E.c.post(f"/api/team/doc-sources/{sid}/sync", headers=E.tok("manager")).json()["unchanged"] == 1
    # publish v1, then edit the Notion page → one sync later there is a NEW DRAFT version (never auto-published)
    E.db.refresh(doc)
    v1 = E.db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).one()
    from app.services import doc_library
    doc_library._publish(E.db, doc, v1, now=__import__("datetime").datetime.utcnow()); E.db.commit()
    fake.edited, fake.text = "2026-10-16T05:00:00.000Z", "Giờ mở cửa 9:00 đến 20:00, nghỉ Chủ nhật."
    s3 = doc_ingest.sync_due(E.db, now=__import__("datetime").datetime.utcnow() + __import__("datetime").timedelta(hours=2))
    got = [x for x in s3["synced"] if x["source"] == sid][0]
    assert got["updated"] == 1, got
    vs = E.db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).order_by(DocumentVersion.version_no).all()
    assert [v.status for v in vs] == ["published", "draft"] and "9:00" in vs[1].content
    E.db.refresh(doc)
    assert "8:00" in doc.content            # agents still read the published text until someone approves v2
