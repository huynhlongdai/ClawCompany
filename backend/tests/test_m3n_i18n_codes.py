"""M3 cleanup — chuỗi tiếng Việt do backend ghép không còn hiện ở giao diện EN: backend trả MÃ + tham số, giao diện dịch.
* lý do "không áp dụng" của hồ sơ bắt buộc → why_code/why_params (mỗi mã có khoá docs.why_<mã> ở cả vi và en);
* ghi chú nạp tài liệu (M3c) → note_code/note_params, kể cả dòng cũ chỉ có câu tiếng Việt;
* điều khoản thuê → terms_detail dạng số (USD) cho UI tự ghép; câu tiếng Việt vẫn giữ cho Hộp việc / agent."""
import json
from pathlib import Path
from types import SimpleNamespace

from app.services import doc_ingest, doc_requirements, seat_leases

MSG = Path(__file__).resolve().parents[2] / "messages"


def _msgs():
    return {lang: json.loads((MSG / f"{lang}.json").read_text(encoding="utf-8")) for lang in ("vi", "en")}


def test_requirement_reasons_are_codes_with_params_and_every_code_is_translated():
    f = {"entity_type": "tnhh_1tv", "humans": 3, "personal_data": False, "templates": []}
    cases = {
        "entity_type": {"entity_types": ["cp"]},
        "below_min_humans": {"min_humans": 10},
        "above_max_humans": {"max_humans": 1},
        "no_personal_data": {"personal_data": True},
        "other_industry": {"templates": ["shop"]},
    }
    m = _msgs()
    for code, cond in cases.items():
        ok, got, params = doc_requirements.applies_code(SimpleNamespace(condition=cond), f)
        assert not ok and got == code, (code, got)
        ok2, vi = doc_requirements.applies(SimpleNamespace(condition=cond), f)
        assert vi == doc_requirements.WHY_VI[code].format(**params)        # câu tiếng Việt cũ không đổi (Hộp việc, test M3d)
        for lang in ("vi", "en"):
            tpl = m[lang]["docs"][f"why_{code}"]
            out = tpl
            for k, v in params.items():
                out = out.replace("{" + k + "}", str(v))
            assert "{" not in out, (lang, code, out)                     # mọi tham số được dùng hết
    assert doc_requirements.applies_code(SimpleNamespace(condition={}), f) == (True, "", {})
    assert "disabled" in doc_requirements.WHY_VI and "why_disabled" in m["en"]["docs"]
    assert "người" not in m["en"]["docs"]["why_below_min_humans"]


def test_import_notes_map_to_codes_including_legacy_rows():
    samples = {
        "Ảnh scan: máy chủ chưa cài Tesseract nên chưa đọc được chữ — lưu như hồ sơ (record).": ("image_no_ocr", {}),
        "OCR chỉ có gói tiếng Anh — dấu tiếng Việt có thể sai, cần soát lại.": ("ocr_eng_only", {}),
        "PDF không có lớp chữ — đã OCR": ("pdf_ocr", {}),
        "PDF không có lớp chữ — đã OCR (chỉ gói tiếng Anh, cần soát dấu)": ("pdf_ocr_eng", {}),
        "PDF không có lớp chữ (bản scan) và máy chủ chưa cài Tesseract/pdftoppm để OCR.": ("pdf_no_ocr", {}),
        "Tệp trùng sha256 với PRC-006": ("dup_file", {"code": "PRC-006"}),
        "Nội dung trùng với POL-003": ("dup_text", {"code": "POL-003"}),
        "Không trích được chữ": ("no_text", {}),
        "Mẫu tham khảo, không phải tư vấn pháp lý — điền các chỗ '……' trước khi gửi duyệt": ("template_ref", {}),
        "ghi chú tự do của người dùng": ("", {}),
    }
    m = _msgs()
    for note, want in samples.items():
        assert doc_ingest.note_code(note) == want, note
        if want[0]:
            assert f"note_{want[0]}" in m["vi"]["ingest"] and f"note_{want[0]}" in m["en"]["ingest"]
    assert doc_ingest.note_code(None) == ("", {})


def test_lease_terms_have_numeric_detail_for_the_ui():
    ls = SimpleNamespace(price_per_task_usd=0.5, price_per_hour_usd=None, price_per_month_usd=20.0, markup_pct=15,
                         monthly_cost_cap_usd=50.0)
    d = seat_leases.terms_of(ls)
    assert d == {"price_per_task_usd": 0.5, "price_per_hour_usd": None, "price_per_month_usd": 20.0, "markup_pct": 15,
                 "monthly_cost_cap_usd": 50.0}
    assert seat_leases.terms_line(ls) == "0.5 USD/việc · 20 USD/tháng · chi phí model thật + 15% · trần 50 USD/tháng"
    m = _msgs()
    for k in ("t_task", "t_hour", "t_month", "t_markup", "t_cap"):
        assert "{p0}" in m["en"]["rental"][k] and "{p0}" in m["vi"]["rental"][k]
