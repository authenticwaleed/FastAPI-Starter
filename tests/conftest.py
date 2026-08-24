from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.user_service import UserService, get_user_service


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A test client backed by a fresh, isolated user store."""
    app = create_app()

    # One instance for the whole test: the override is called per request, so
    # returning `UserService` itself would hand out an empty store every time.
    service = UserService()
    app.dependency_overrides[get_user_service] = lambda: service

    with TestClient(app) as test_client:
        yield test_client
