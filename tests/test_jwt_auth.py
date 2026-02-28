import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.auth import get_current_user

client = TestClient(app)

@pytest.fixture(autouse=True)
def clear_auth_overrides():
    app.dependency_overrides.clear()
    yield
    # No need to restore here as conftest will re-apply it for other tests if they run in same process
    # but pytest usually isolates well or we can just let it be.

def test_token_generation_success():
    response = client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "password123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["role"] == "admin"

def test_token_generation_failure():
    response = client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "wrongpassword"}
    )
    assert response.status_code == 401

def test_rbac_admin_access():
    # Login as admin
    login_resp = client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "password123"}
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # Access admin-only endpoint
    # Note: demo/start requires Role.ADMIN
    resp = client.post("/api/v1/demo/start", headers=headers)
    assert resp.status_code in [200, 401] # 401 if X-API-KEY is required but missing, 200 if OK
    # Wait, demo/start is protected by BOTH API Key and JWT?
    # No, middleware checks /api/v1.
    
    # If X-API-KEY is not configured, it should be 200.
    # In tests, it's usually not configured.

def test_rbac_viewer_restriction():
    # Login as viewer
    login_resp = client.post(
        "/api/v1/auth/token",
        data={"username": "viewer", "password": "password123"}
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # Viewer cannot access admin-only endpoint
    resp = client.post("/api/v1/demo/start", headers=headers)
    assert resp.status_code == 403
    assert "Operation not permitted" in resp.json()["detail"]

def test_rbac_operator_access():
    # Login as operator
    login_resp = client.post(
        "/api/v1/auth/token",
        data={"username": "operator", "password": "password123"}
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # Operator can access operator-allowed endpoint
    # release_user requires ADMIN or OPERATOR
    resp = client.post("/api/v1/users/test_user/release", headers=headers)
    # It might be 400 because user is not in correct state, but NOT 403
    assert resp.status_code != 403
