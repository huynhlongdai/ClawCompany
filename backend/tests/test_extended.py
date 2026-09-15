from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_company_surfaces_require_authentication():
    for path in [
        "/api/dashboard/summary?organization_id=1",
        "/api/marketplace",
        "/api/agents/runtime/health",
        "/api/workforce/provisioning-jobs",
    ]:
        response = client.get(path)
        assert response.status_code == 401
