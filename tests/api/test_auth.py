"""Phase 8 acceptance: register, log in, and reach a protected endpoint."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.repositories.user_repository import UserRepository

EMAIL = "ada@example.com"
PASSWORD = "correct horse battery staple"


def _registration(email: str = EMAIL) -> dict[str, str]:
    return {"name": "Ada Lovelace", "email": email, "password": PASSWORD}


def _register(client: TestClient, email: str = EMAIL) -> dict:
    return client.post("/api/v1/auth/register", json=_registration(email)).json()


def _login(client: TestClient, email: str = EMAIL, password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def _token(client: TestClient, email: str = EMAIL) -> str:
    _register(client, email)

    return _login(client, email).json()["access_token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _deactivate(repository: UserRepository, session: Session, email: str) -> None:
    user = repository.get_by_email(email)
    assert user is not None
    user.is_active = False
    session.flush()


def _tamper(token: str) -> str:
    """Return a token whose signature is guaranteed to be wrong.

    Changing the *last* character would not do: 32 bytes need 43 base64url
    characters to carry 256 bits, so the final one holds four significant
    bits and two spare. Three of its sixty-three alternatives therefore
    decode to the same signature and leave the token valid, which is a test
    that passes roughly nineteen runs in twenty. The first character of the
    signature carries a full six bits, so changing it always bites.
    """
    header, payload, signature = token.split(".")
    swapped = "B" if signature[0] != "B" else "C"

    return f"{header}.{payload}.{swapped}{signature[1:]}"


def test_register_returns_201_and_the_new_user(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json=_registration())

    assert response.status_code == 201

    created = response.json()
    assert created["id"] > 0
    assert created["email"] == EMAIL
    assert created["is_active"] is True


def test_register_never_returns_the_password(client: TestClient) -> None:
    response = client.post("/api/v1/auth/register", json=_registration())

    assert PASSWORD not in response.text
    assert "hashed_password" not in response.json()


def test_register_rejects_an_address_already_taken(client: TestClient) -> None:
    client.post("/api/v1/auth/register", json=_registration())

    response = client.post("/api/v1/auth/register", json=_registration())

    assert response.status_code == 409
    assert response.json()["detail"] == "Email already registered"


def test_register_applies_the_same_rules_as_creating_a_user(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Ada", "email": EMAIL, "password": "short"},
    )

    assert response.status_code == 422


def test_a_registered_user_is_a_user(client: TestClient) -> None:
    # What registration returns and what the account API reads back have to
    # be the same user, described the same way. They share one schema and
    # one service, and this is that, as a test.
    created = _register(client)
    token = _login(client).json()["access_token"]

    response = client.get("/api/v1/account", headers=_bearer(token))

    assert response.status_code == 200
    assert response.json() == created


def test_login_returns_a_bearer_token(client: TestClient) -> None:
    _register(client)

    response = _login(client)

    assert response.status_code == 200

    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_never_echoes_the_password(client: TestClient) -> None:
    _register(client)

    assert PASSWORD not in _login(client).text


def test_login_rejects_a_wrong_password(client: TestClient) -> None:
    _register(client)

    response = _login(client, password="not the password")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_login_rejects_an_unknown_address(client: TestClient) -> None:
    response = _login(client, email="nobody@example.com")

    assert response.status_code == 401


def test_a_wrong_password_and_an_unknown_address_look_identical(
    client: TestClient,
) -> None:
    # Otherwise the endpoint answers "does this person have an account?"
    _register(client)

    wrong = _login(client, password="not the password")
    unknown = _login(client, email="nobody@example.com")

    assert wrong.status_code == unknown.status_code
    assert wrong.json() == unknown.json()


def test_login_rejects_a_deactivated_account(
    client: TestClient,
    user_repository: UserRepository,
    db_session: Session,
) -> None:
    _register(client)
    _deactivate(user_repository, db_session, EMAIL)

    response = _login(client)

    assert response.status_code == 403
    assert response.json()["detail"] == "Inactive user"


def test_login_rejects_a_malformed_address(client: TestClient) -> None:
    response = _login(client, email="not-an-email")

    assert response.status_code == 422


def test_a_valid_token_reaches_the_protected_endpoint(client: TestClient) -> None:
    token = _token(client)

    response = client.get("/api/v1/auth/me", headers=_bearer(token))

    assert response.status_code == 200
    assert response.json()["email"] == EMAIL


def test_the_protected_endpoint_returns_the_token_holder(
    client: TestClient,
) -> None:
    _register(client, "alan@example.com")
    token = _token(client, EMAIL)

    response = client.get("/api/v1/auth/me", headers=_bearer(token))

    assert response.json()["email"] == EMAIL


def test_the_protected_endpoint_never_returns_a_password(
    client: TestClient,
) -> None:
    token = _token(client)

    response = client.get("/api/v1/auth/me", headers=_bearer(token))

    assert PASSWORD not in response.text
    assert "hashed_password" not in response.json()


def test_no_token_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_a_token_that_is_not_one_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me", headers=_bearer("not-a-token"))

    assert response.status_code == 401


def test_an_expired_token_is_rejected(client: TestClient) -> None:
    created = _register(client)
    expired = create_access_token(
        str(created["id"]),
        expires_in=timedelta(seconds=-1),
    )

    response = client.get("/api/v1/auth/me", headers=_bearer(expired))

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired token"


def test_a_tampered_token_is_rejected(client: TestClient) -> None:
    tampered = _tamper(_token(client))

    response = client.get("/api/v1/auth/me", headers=_bearer(tampered))

    assert response.status_code == 401


def test_another_authorization_scheme_is_rejected(client: TestClient) -> None:
    token = _token(client)

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Basic {token}"},
    )

    assert response.status_code == 401


def test_a_token_survives_an_email_change(client: TestClient) -> None:
    # The subject is the user id, so changing the address does not lock the
    # holder out of a token they already have.
    _register(client)
    token = _login(client).json()["access_token"]

    client.patch(
        "/api/v1/account",
        json={"email": "ada.lovelace@example.com"},
        headers=_bearer(token),
    )

    response = client.get("/api/v1/auth/me", headers=_bearer(token))

    assert response.status_code == 200
    assert response.json()["email"] == "ada.lovelace@example.com"


def test_a_token_for_a_deleted_account_is_rejected(client: TestClient) -> None:
    _register(client)
    token = _login(client).json()["access_token"]

    client.delete("/api/v1/account", headers=_bearer(token))

    response = client.get("/api/v1/auth/me", headers=_bearer(token))

    assert response.status_code == 401


def test_a_token_for_a_deactivated_account_is_rejected(
    client: TestClient,
    user_repository: UserRepository,
    db_session: Session,
) -> None:
    token = _token(client)

    _deactivate(user_repository, db_session, EMAIL)

    response = client.get("/api/v1/auth/me", headers=_bearer(token))

    assert response.status_code == 403
    assert response.json()["detail"] == "Inactive user"
