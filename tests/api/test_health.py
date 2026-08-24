"""Phase 16 acceptance: health checks an orchestrator can act on."""

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db.session import get_db_session
from app.main import create_app


class _UnreachableSession:
    """Stands in for a session whose database has gone away."""

    def execute(self, *args: object, **kwargs: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("no route to host"))


def _client_without_a_database() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db_session] = _UnreachableSession

    return TestClient(app)


def test_health_check_returns_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_liveness_reports_the_process_is_up(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_the_database_is_reachable(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "reachable"}


def test_readiness_fails_when_the_database_is_unreachable() -> None:
    response = _client_without_a_database().get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "unready"


def test_liveness_survives_an_unreachable_database() -> None:
    # The distinction the two endpoints exist for. A database outage must
    # not make an orchestrator restart every healthy process it has.
    response = _client_without_a_database().get("/api/v1/health/live")

    assert response.status_code == 200
