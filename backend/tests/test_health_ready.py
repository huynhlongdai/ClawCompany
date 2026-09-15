from fastapi.testclient import TestClient
from app.main import app
client=TestClient(app)

def test_live():
    r=client.get("/api/health/live")
    assert r.status_code==200
    assert r.json()["status"]=="ok"
