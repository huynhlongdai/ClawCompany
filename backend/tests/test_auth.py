from fastapi.testclient import TestClient
from app.main import app
client=TestClient(app)

def test_register_and_login():
    email="testuser@example.com"
    client.post("/api/auth/register",json={"email":email,"password":"ExamplePass123!","display_name":"Tester"})
    r=client.post("/api/auth/login",json={"email":email,"password":"ExamplePass123!"})
    assert r.status_code==200
    assert "access_token" in r.json()
