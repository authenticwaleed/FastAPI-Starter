"""Phase 9 acceptance: one error shape, decided in one place."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import UserNotFoundError
from app.main import create_app

PASSWORD = "correct horse battery staple"


def _register(client: TestClient, email: str = "ada@example.com") -> dict:
    return client.post(
        "/api/v1/auth/register",
        json={"name": "Ada", "email": email, "password": PASSWORD},
    ).json()


def test_a_missing_user_is_reported_consistently() -> None:
    # No route raises this any more: `/users` is gone, and the account API
    # only ever reaches the account its own token resolved. The mapping from
    # the error to a 404 is still what every service will rely on, so it is
    # tested where it lives rather than through a route that used to raise
    # it by accident of having an id in the path.
    app = create_app()

    @app.get("/missing")
    def missing() -> None:
        raise UserNotFoundError(999)

    with TestClient(app) as error_client:
        response = error_client.get("/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found", "code": "user_not_found"}


def test_a_duplicate_email_is_reported_consistently(client: TestClient) -> None:
    _register(client)

    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Ada", "email": "ada@example.com", "password": PASSWORD},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "email_already_exists"


def test_the_conflict_message_does_not_repeat_the_address(
    client: TestClient,
) -> None:
    # The address is in the log line, not the response.
    _register(client)

    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Ada", "email": "ada@example.com", "password": PASSWORD},
    )

    assert "ada@example.com" not in response.text


def test_a_rejected_login_is_reported_consistently(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": PASSWORD},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_a_validation_failure_uses_the_same_shape(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Ada", "email": "not-an-email", "password": PASSWORD},
    )

    body = response.json()

    assert response.status_code == 422
    assert body["code"] == "validation_error"
    assert isinstance(body["detail"], str)
    # The per-field detail is still there, just no longer masquerading as the
    # `detail` string every other error puts there.
    assert body["errors"]


def test_an_unknown_path_uses_the_same_shape(client: TestClient) -> None:
    body = client.get("/api/v1/nothing-here").json()

    assert set(body) == {"detail", "code"}
    assert body["code"] == "http_error"


def test_a_wrong_method_uses_the_same_shape(client: TestClient) -> None:
    body = client.put("/api/v1/health").json()

    assert body["code"] == "http_error"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/v1/account", "invalid_credentials"),
        ("/api/v1/auth/me", "invalid_credentials"),
        ("/api/v1/nothing-here", "http_error"),
    ],
)
def test_every_error_carries_a_detail_and_a_code(
    client: TestClient,
    path: str,
    expected: str,
) -> None:
    body = client.get(path).json()

    assert isinstance(body["detail"], str)
    assert body["code"] == expected


def test_an_unexpected_error_becomes_a_500_that_says_nothing() -> None:
    app = create_app()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("connection string with a password in it")

    # raise_server_exceptions=False so the handler's response is returned
    # rather than the exception being re-raised into the test.
    with TestClient(app, raise_server_exceptions=False) as boom_client:
        response = boom_client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error",
        "code": "internal_error",
    }
    assert "password" not in response.text


def test_no_service_knows_what_an_httpexception_is() -> None:
    # The point of the phase, as a test: business logic must not import the
    # web framework's error type.
    for module in sorted(Path("app/services").glob("*.py")):
        assert "HTTPException" not in module.read_text(), module


def test_no_route_raises_an_httpexception_by_hand() -> None:
    for module in sorted(Path("app/api/routes").glob("*.py")):
        assert "HTTPException" not in module.read_text(), module


def test_a_500_never_ships_a_stack_trace() -> None:
    # Starlette's debug mode answers an unhandled exception with the
    # traceback instead of calling the handler, which is why app.main does
    # not pass `debug` through. This is that decision, as a test.
    app = create_app()

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret")

    with TestClient(app, raise_server_exceptions=False) as boom_client:
        response = boom_client.get("/boom")

    assert "Traceback" not in response.text
    assert "site-packages" not in response.text
    assert "secret" not in response.text
