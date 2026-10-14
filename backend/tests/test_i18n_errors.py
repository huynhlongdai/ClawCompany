"""i18n lỗi JSON: tiếng Việt mặc định, tiếng Anh khi Accept-Language ưu tiên en.

Kiểm bằng HTTP thật qua app (TestClient), không grep source.
"""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.errors import JSONErrorMiddleware
from app.core.i18n import CATALOG, LocaleErrorMiddleware, pick_locale, translate
from app.db.base import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Maker = sessionmaker(bind=engine, autoflush=False)

    def _db():
        db = Maker()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = _db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def test_real_endpoint_defaults_to_vietnamese(client):
    r = client.get("/api/team/invitations/lookup", params={"token": "khong-co"})
    assert r.status_code == 404
    assert r.json()["detail"] == "Link mời không đúng"
    assert r.headers["content-language"] == "vi"


def test_real_endpoint_english_when_asked(client):
    r = client.get("/api/team/invitations/lookup", params={"token": "khong-co"}, headers={"Accept-Language": "en-US,en;q=0.9"})
    assert r.status_code == 404
    assert r.json()["detail"] == "Invalid invitation link"
    assert r.headers["content-language"] == "en"
    # độ dài body khớp header sau khi dịch (body ngắn/dài hơn bản gốc)
    assert int(r.headers["content-length"]) == len(r.content)


def test_explicit_vietnamese_and_unknown_language_stay_vietnamese(client):
    for lang in ("vi-VN,vi;q=0.9,en;q=0.5", "fr-FR", ""):
        r = client.get("/api/team/invitations/lookup", params={"token": "x"}, headers={"Accept-Language": lang})
        assert r.json()["detail"] == "Link mời không đúng", lang


def test_success_responses_untouched(client):
    r = client.get("/health", headers={"Accept-Language": "en"})
    assert r.status_code == 200 and r.json()["status"] in ("ok", "degraded")
    assert r.headers["content-language"] == "en"


def _mini():
    mini = FastAPI()

    @mini.get("/plain")
    def plain():
        raise HTTPException(404, "Không thấy routine")

    @mini.get("/dict")
    def dict_():
        raise HTTPException(409, {"error": "already_decided", "message": "Yêu cầu này đã approved — không quyết lại được"})

    @mini.get("/param")
    def param():
        raise HTTPException(409, "Task #7 đang được lượt chạy #12 giữ")

    @mini.get("/unknown")
    def unknown():
        raise HTTPException(422, "Một câu chưa có trong bảng dịch")

    @mini.get("/boom")
    def boom():
        raise TimeoutError("db")

    mini.add_middleware(JSONErrorMiddleware)
    mini.add_middleware(LocaleErrorMiddleware)
    return TestClient(mini, raise_server_exceptions=False)


def test_dict_message_param_and_fallback():
    c = _mini()
    en = {"Accept-Language": "en"}
    assert c.get("/plain", headers=en).json()["detail"] == "Routine not found"
    body = c.get("/dict", headers=en).json()["detail"]
    assert body == {"error": "already_decided", "message": "This request is already approved — it cannot be decided again"}
    assert c.get("/param", headers=en).json()["detail"] == "Task #7 is held by run #12"
    # chưa có bản dịch → giữ tiếng Việt (fallback vi), không bịa
    assert c.get("/unknown", headers=en).json()["detail"] == "Một câu chưa có trong bảng dịch"
    assert c.get("/plain").json()["detail"] == "Không thấy routine"


def test_unhandled_exception_message_is_localised():
    c = _mini()
    vi = c.get("/boom").json()
    en = c.get("/boom", headers={"Accept-Language": "en"}).json()
    assert vi["code"] == en["code"] == "timeout"
    assert vi["detail"].startswith("Hết thời gian chờ")
    assert en["detail"].startswith("A backend service")


def test_pick_locale_q_weights():
    assert pick_locale(None) == "vi"
    assert pick_locale("en") == "en"
    assert pick_locale("vi;q=0.4, en;q=0.8") == "en"
    assert pick_locale("en;q=0.3, vi") == "vi"
    assert pick_locale("de, fr") == "vi"


def test_catalog_templates_are_consistent():
    # mỗi bản tiếng Anh dùng đúng số chỗ trống của mẫu tiếng Việt
    for pat, en in CATALOG:
        holes = pat.groups
        for i in range(holes):
            assert "{%d}" % i in en, (pat.pattern, en)
    assert translate("Không thấy routine", "vi") == "Không thấy routine"
