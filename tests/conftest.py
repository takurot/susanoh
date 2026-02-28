import pytest
from backend.main import app
from backend.auth import get_current_user, User, Role

@pytest.fixture(autouse=True)
def override_auth_for_tests():
    # Bypass JWT authentication for existing API tests
    app.dependency_overrides[get_current_user] = lambda: User(username="test_admin", role=Role.ADMIN)
    yield
    app.dependency_overrides.clear()
