"""Phase 1 acceptance: self-service account management, and nothing wider.

The account API replaced a public `/users` CRUD surface that let anyone
list, edit or delete any account in the system. Most of what is asserted
here is that the replacement cannot be talked into doing the same thing.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories.user_repository import UserRepository

EMAIL = "ada@example.com"
OTHER_EMAIL = "alan@example.com"
PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a different correct horse"


def _register(client: TestClient, email: str = EMAIL) -> dict:
    return client.post(
        "/api/v1/auth/register",
        json={"name": "Ada Lovelace", "email": email, "password": PASSWORD},
    ).json()


def _login(client: TestClient, email: str = EMAIL, password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def _token(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> str:
    return _login(client, email, password).json()["access_token"]


def _change_password(
    client: TestClient,
    headers: dict[str, str],
    *,
    current: str = PASSWORD,
    new: str = NEW_PASSWORD,
):
    return client.post(
        "/api/v1/account/change-password",
        json={"current_password": current, "new_password": new},
        headers=headers,
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sign_up(client: TestClient, email: str = EMAIL) -> tuple[dict, dict[str, str]]:
    """Register an account and return it with headers that authenticate it."""
    created = _register(client, email)

    return created, _bearer(_token(client, email))


# --- the endpoints that replaced /users ------------------------------------


def test_read_account_returns_the_authenticated_user(client: TestClient) -> None:
    created, headers = _sign_up(client)

    response = client.get("/api/v1/account", headers=headers)

    assert response.status_code == 200
    assert response.json() == created


def test_update_account_changes_only_what_was_sent(client: TestClient) -> None:
    _, headers = _sign_up(client)

    response = client.patch(
        "/api/v1/account",
        json={"name": "Ada L"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Ada L"
    assert response.json()["email"] == EMAIL


def test_update_account_can_change_the_email(client: TestClient) -> None:
    _, headers = _sign_up(client)

    response = client.patch(
        "/api/v1/account",
        json={"email": "ada.lovelace@example.com"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["email"] == "ada.lovelace@example.com"


def test_an_update_is_visible_on_the_next_read(client: TestClient) -> None:
    _, headers = _sign_up(client)

    client.patch("/api/v1/account", json={"name": "Ada L"}, headers=headers)

    assert client.get("/api/v1/account", headers=headers).json()["name"] == "Ada L"


def test_update_account_with_an_empty_body_changes_nothing(
    client: TestClient,
) -> None:
    created, headers = _sign_up(client)

    response = client.patch("/api/v1/account", json={}, headers=headers)

    assert response.status_code == 200
    assert response.json() == created


def test_update_to_an_address_someone_else_holds_returns_409(
    client: TestClient,
) -> None:
    _register(client, OTHER_EMAIL)
    _, headers = _sign_up(client)

    response = client.patch(
        "/api/v1/account",
        json={"email": OTHER_EMAIL},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "email_already_exists"


def test_update_account_rejects_an_invalid_email(client: TestClient) -> None:
    _, headers = _sign_up(client)

    response = client.patch(
        "/api/v1/account",
        json={"email": "not-an-email"},
        headers=headers,
    )

    assert response.status_code == 422


def test_the_account_api_has_no_password_field(client: TestClient) -> None:
    # Changing a password is its own endpoint, because it needs the current
    # one. A password sent here is ignored rather than quietly applied.
    _, headers = _sign_up(client)

    client.patch(
        "/api/v1/account",
        json={"password": NEW_PASSWORD},
        headers=headers,
    )

    assert _login(client, password=NEW_PASSWORD).status_code == 401


# --- passwords are never returned ------------------------------------------


def _assert_no_password(response, hashed_password: str) -> None:
    assert PASSWORD not in response.text
    assert hashed_password not in response.text
    assert "password" not in response.json()


def _hashed_password(repository: UserRepository) -> str:
    user = repository.get_by_email(EMAIL)
    assert user is not None

    return user.hashed_password


def test_reading_an_account_never_returns_the_password_or_its_hash(
    client: TestClient,
    user_repository: UserRepository,
) -> None:
    _, headers = _sign_up(client)

    _assert_no_password(
        client.get("/api/v1/account", headers=headers),
        _hashed_password(user_repository),
    )


def test_updating_an_account_never_returns_the_password_or_its_hash(
    client: TestClient,
    user_repository: UserRepository,
) -> None:
    _, headers = _sign_up(client)

    _assert_no_password(
        client.patch("/api/v1/account", json={"name": "Ada L"}, headers=headers),
        _hashed_password(user_repository),
    )


# --- changing a password ----------------------------------------------------


def test_change_password_returns_204_with_no_body(client: TestClient) -> None:
    _, headers = _sign_up(client)

    response = _change_password(client, headers)

    assert response.status_code == 204
    assert not response.content


def test_the_new_password_is_the_one_that_logs_in(client: TestClient) -> None:
    _, headers = _sign_up(client)

    _change_password(client, headers)

    assert _login(client, password=NEW_PASSWORD).status_code == 200
    assert _login(client, password=PASSWORD).status_code == 401


def test_change_password_needs_the_current_one(client: TestClient) -> None:
    _, headers = _sign_up(client)

    response = _change_password(client, headers, current="not it")

    # Not a 401: the token is perfectly good, and answering with one would
    # send a valid session back to the login screen.
    assert response.status_code == 400
    assert response.json()["code"] == "incorrect_password"


def test_a_refused_password_change_leaves_the_old_password_working(
    client: TestClient,
) -> None:
    _, headers = _sign_up(client)

    _change_password(client, headers, current="not it")

    assert _login(client).status_code == 200


def test_change_password_applies_the_password_policy(client: TestClient) -> None:
    _, headers = _sign_up(client)

    response = _change_password(client, headers, new="short")

    assert response.status_code == 422


def test_a_wrong_current_password_is_not_echoed_back(client: TestClient) -> None:
    _, headers = _sign_up(client)

    response = _change_password(client, headers, current="a guess worth hiding")

    assert "a guess worth hiding" not in response.text


# --- deleting an account ----------------------------------------------------


def test_delete_account_returns_204_with_no_body(client: TestClient) -> None:
    _, headers = _sign_up(client)

    response = client.delete("/api/v1/account", headers=headers)

    assert response.status_code == 204
    assert not response.content


def test_a_deleted_account_can_no_longer_authenticate(client: TestClient) -> None:
    _, headers = _sign_up(client)

    client.delete("/api/v1/account", headers=headers)

    assert client.get("/api/v1/account", headers=headers).status_code == 401
    assert _login(client).status_code == 401


def test_deleting_an_account_frees_its_email_address(client: TestClient) -> None:
    _, headers = _sign_up(client)

    client.delete("/api/v1/account", headers=headers)

    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Someone Else", "email": EMAIL, "password": PASSWORD},
    )

    assert response.status_code == 201


# --- the authorization the phase exists for ---------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/account"),
        ("patch", "/api/v1/account"),
        ("post", "/api/v1/account/change-password"),
        ("delete", "/api/v1/account"),
    ],
)
def test_every_account_endpoint_requires_a_token(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    _register(client)

    # .request rather than .get/.delete: those take no body, and the point
    # here is that the verb is what varies.
    response = client.request(method, path, json={})

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/account"),
        ("patch", "/api/v1/account"),
        ("post", "/api/v1/account/change-password"),
        ("delete", "/api/v1/account"),
    ],
)
def test_an_inactive_account_reaches_nothing(
    client: TestClient,
    db_session: Session,
    user_repository: UserRepository,
    method: str,
    path: str,
) -> None:
    _, headers = _sign_up(client)

    user = user_repository.get_by_email(EMAIL)
    assert user is not None
    user.is_active = False
    db_session.flush()

    response = client.request(method, path, json={}, headers=headers)

    assert response.status_code == 403
    assert response.json()["code"] == "inactive_user"


def test_a_token_only_ever_reaches_its_own_account(client: TestClient) -> None:
    # The replacement for "user cannot update another user's account". There
    # is no path parameter to point at somebody else, so the way to state it
    # is that acting as one user leaves the other untouched.
    other, other_headers = _sign_up(client, OTHER_EMAIL)
    _, headers = _sign_up(client)

    client.patch("/api/v1/account", json={"name": "Renamed"}, headers=headers)

    assert client.get("/api/v1/account", headers=other_headers).json() == other


def test_deleting_one_account_leaves_the_others_alone(client: TestClient) -> None:
    other, other_headers = _sign_up(client, OTHER_EMAIL)
    _, headers = _sign_up(client)

    client.delete("/api/v1/account", headers=headers)

    assert client.get("/api/v1/account", headers=other_headers).json() == other


def test_changing_one_password_leaves_the_others_alone(client: TestClient) -> None:
    _sign_up(client, OTHER_EMAIL)
    _, headers = _sign_up(client)

    _change_password(client, headers)

    assert _login(client, OTHER_EMAIL).status_code == 200


# --- what was removed -------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/users"),
        ("get", "/api/v1/users"),
        ("get", "/api/v1/users/1"),
        ("patch", "/api/v1/users/1"),
        ("delete", "/api/v1/users/1"),
    ],
)
def test_the_public_user_administration_api_is_gone(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    # The gap this phase closed, as a test. These endpoints let anyone read,
    # edit or delete any account without authenticating at all.
    assert client.request(method, path, json={}).status_code == 404
