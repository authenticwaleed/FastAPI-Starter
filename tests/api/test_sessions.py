"""Phase 15 acceptance: refresh, logout, and the list of live sessions.

The four things the phase is judged on: refreshing works, logging out
invalidates the session, a stolen refresh token cannot be reused
indefinitely, and there is a list of where an account is signed in.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.repositories.user_session_repository import UserSessionRepository

EMAIL = "ada@example.com"
PASSWORD = "correct horse battery staple"


def _register(client: TestClient, email: str = EMAIL) -> dict:
    return client.post(
        "/api/v1/auth/register",
        json={"name": "Ada Lovelace", "email": email, "password": PASSWORD},
    ).json()


def _login(
    client: TestClient,
    email: str = EMAIL,
    *,
    user_agent: str | None = None,
) -> dict:
    headers = {"User-Agent": user_agent} if user_agent is not None else {}

    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        headers=headers,
    ).json()


def _sign_in(client: TestClient, email: str = EMAIL, **kwargs: str) -> dict:
    _register(client, email)

    return _login(client, email, **kwargs)


def _bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _refresh(client: TestClient, refresh_token: str):
    return client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )


def _logout(client: TestClient, refresh_token: str):
    return client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": refresh_token},
    )


def _me(client: TestClient, access_token: str):
    return client.get("/api/v1/auth/me", headers=_bearer(access_token))


def _sessions(client: TestClient, access_token: str):
    return client.get("/api/v1/account/sessions", headers=_bearer(access_token))


# --- login ----------------------------------------------------------------


def test_login_returns_both_tokens_and_a_lifetime(client: TestClient) -> None:
    tokens = _sign_in(client)

    assert tokens["access_token"]
    assert tokens["refresh_token"]
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] > 0


def test_the_two_tokens_are_not_the_same_thing(client: TestClient) -> None:
    tokens = _sign_in(client)

    assert tokens["access_token"] != tokens["refresh_token"]


# --- refresh --------------------------------------------------------------


def test_refresh_returns_a_working_pair(client: TestClient) -> None:
    first = _sign_in(client)

    response = _refresh(client, first["refresh_token"])

    assert response.status_code == 200

    second = response.json()
    assert _me(client, second["access_token"]).status_code == 200


def test_refresh_rotates_the_refresh_token(client: TestClient) -> None:
    first = _sign_in(client)

    second = _refresh(client, first["refresh_token"]).json()

    assert second["refresh_token"] != first["refresh_token"]


def test_refresh_stays_inside_the_same_session(client: TestClient) -> None:
    first = _sign_in(client)

    second = _refresh(client, first["refresh_token"]).json()

    assert decode_access_token(second["access_token"]).session_id == (
        decode_access_token(first["access_token"]).session_id
    )
    assert len(_sessions(client, second["access_token"]).json()) == 1


def test_refresh_can_be_repeated(client: TestClient) -> None:
    tokens = _sign_in(client)

    for _ in range(3):
        response = _refresh(client, tokens["refresh_token"])
        assert response.status_code == 200
        tokens = response.json()

    assert _me(client, tokens["access_token"]).status_code == 200


def test_refresh_needs_no_access_token(client: TestClient) -> None:
    # The whole reason to call it is that the access token has run out.
    tokens = _sign_in(client)

    assert _refresh(client, tokens["refresh_token"]).status_code == 200


def test_refresh_rejects_a_token_nobody_was_issued(client: TestClient) -> None:
    _sign_in(client)

    response = _refresh(client, "not a token anybody ever held")

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_refresh_token"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_refresh_rejects_an_access_token_in_its_place(client: TestClient) -> None:
    tokens = _sign_in(client)

    assert _refresh(client, tokens["access_token"]).status_code == 401


# --- reuse ----------------------------------------------------------------


def test_a_spent_refresh_token_cannot_be_used_again(client: TestClient) -> None:
    first = _sign_in(client)
    _refresh(client, first["refresh_token"])

    response = _refresh(client, first["refresh_token"])

    assert response.status_code == 401
    assert response.json()["code"] == "refresh_token_reused"


def test_reuse_ends_the_session_for_everybody_holding_it(
    client: TestClient,
) -> None:
    # The theft scenario, end to end. Somebody copies the refresh token;
    # the rightful client refreshes first; the copy is then presented.
    # Neither of them keeps the session, because neither can be told from
    # the other.
    first = _sign_in(client)
    second = _refresh(client, first["refresh_token"]).json()

    _refresh(client, first["refresh_token"])

    assert _refresh(client, second["refresh_token"]).status_code == 401
    assert _me(client, second["access_token"]).status_code == 401


def test_a_stolen_token_stops_working_after_one_use(client: TestClient) -> None:
    # And the other direction: the thief gets in first. What they bought
    # dies the moment the rightful client tries the token they still hold.
    first = _sign_in(client)
    stolen = _refresh(client, first["refresh_token"]).json()

    assert _refresh(client, first["refresh_token"]).status_code == 401
    assert _me(client, stolen["access_token"]).status_code == 401


# --- logout ---------------------------------------------------------------


def test_logout_invalidates_the_session(client: TestClient) -> None:
    tokens = _sign_in(client)

    assert _logout(client, tokens["refresh_token"]).status_code == 204

    assert _refresh(client, tokens["refresh_token"]).status_code == 401
    assert _me(client, tokens["access_token"]).status_code == 401


def test_logout_needs_no_access_token(client: TestClient) -> None:
    tokens = _sign_in(client)

    response = client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert response.status_code == 204


def test_logout_says_nothing_about_a_token_it_does_not_know(
    client: TestClient,
) -> None:
    assert _logout(client, "not a token anybody ever held").status_code == 204


def test_logout_is_idempotent(client: TestClient) -> None:
    tokens = _sign_in(client)

    _logout(client, tokens["refresh_token"])

    assert _logout(client, tokens["refresh_token"]).status_code == 204


def test_logout_leaves_the_other_devices_alone(client: TestClient) -> None:
    _register(client)
    laptop = _login(client)
    phone = _login(client)

    _logout(client, laptop["refresh_token"])

    assert _me(client, phone["access_token"]).status_code == 200


# --- the session list -----------------------------------------------------


def test_the_session_list_has_a_row_for_each_sign_in(client: TestClient) -> None:
    _register(client)
    _login(client)
    latest = _login(client)

    listed = _sessions(client, latest["access_token"]).json()

    assert len(listed) == 2


def test_the_session_list_marks_the_one_asking(client: TestClient) -> None:
    _register(client)
    _login(client)
    here = _login(client)

    listed = _sessions(client, here["access_token"]).json()

    here_id = decode_access_token(here["access_token"]).session_id

    current = [row for row in listed if row["current"]]
    assert len(current) == 1
    assert current[0]["id"] == str(here_id)


def test_the_session_list_shows_what_signed_in(client: TestClient) -> None:
    tokens = _sign_in(client, user_agent="Firefox on a Thinkpad")

    listed = _sessions(client, tokens["access_token"]).json()

    assert listed[0]["user_agent"] == "Firefox on a Thinkpad"
    assert listed[0]["created_at"]
    assert listed[0]["last_used_at"]
    assert listed[0]["expires_at"]


def test_the_session_list_carries_no_secrets(client: TestClient) -> None:
    tokens = _sign_in(client)

    response = _sessions(client, tokens["access_token"])

    assert tokens["refresh_token"] not in response.text
    assert "token" not in response.json()[0]
    assert "hash" not in response.text


def test_the_session_list_is_one_account_only(client: TestClient) -> None:
    _sign_in(client, "alan@example.com")
    mine = _sign_in(client)

    listed = _sessions(client, mine["access_token"]).json()

    assert len(listed) == 1


def test_a_session_that_has_ended_leaves_the_list(client: TestClient) -> None:
    _register(client)
    gone = _login(client)
    here = _login(client)

    _logout(client, gone["refresh_token"])

    listed = _sessions(client, here["access_token"]).json()
    assert len(listed) == 1
    assert listed[0]["current"] is True


# --- revoking -------------------------------------------------------------


def test_revoking_a_session_signs_that_device_out(client: TestClient) -> None:
    _register(client)
    phone = _login(client)
    laptop = _login(client)

    phone_id = str(decode_access_token(phone["access_token"]).session_id)
    response = client.delete(
        f"/api/v1/account/sessions/{phone_id}",
        headers=_bearer(laptop["access_token"]),
    )

    assert response.status_code == 204
    assert _me(client, phone["access_token"]).status_code == 401
    assert _refresh(client, phone["refresh_token"]).status_code == 401
    assert _me(client, laptop["access_token"]).status_code == 200


def test_revoking_somebody_elses_session_is_a_404(client: TestClient) -> None:
    theirs = _sign_in(client, "alan@example.com")
    mine = _sign_in(client)

    theirs_id = str(decode_access_token(theirs["access_token"]).session_id)
    response = client.delete(
        f"/api/v1/account/sessions/{theirs_id}",
        headers=_bearer(mine["access_token"]),
    )

    assert response.status_code == 404
    assert _me(client, theirs["access_token"]).status_code == 200


def test_revoking_a_session_that_never_existed_is_a_404(
    client: TestClient,
) -> None:
    tokens = _sign_in(client)

    response = client.delete(
        "/api/v1/account/sessions/3f2b0a6e-9c1d-4f8a-8f3e-2b6d5c4a1e70",
        headers=_bearer(tokens["access_token"]),
    )

    assert response.status_code == 404


def test_revoking_every_session_signs_out_everywhere(client: TestClient) -> None:
    _register(client)
    phone = _login(client)
    laptop = _login(client)

    response = client.delete(
        "/api/v1/account/sessions",
        headers=_bearer(laptop["access_token"]),
    )

    assert response.status_code == 204
    assert _refresh(client, phone["refresh_token"]).status_code == 401
    assert _refresh(client, laptop["refresh_token"]).status_code == 401
    assert _me(client, phone["access_token"]).status_code == 401
    assert _me(client, laptop["access_token"]).status_code == 401


def test_revoking_every_session_leaves_other_accounts_alone(
    client: TestClient,
) -> None:
    theirs = _sign_in(client, "alan@example.com")
    mine = _sign_in(client)

    client.delete("/api/v1/account/sessions", headers=_bearer(mine["access_token"]))

    assert _me(client, theirs["access_token"]).status_code == 200


# --- changing a password --------------------------------------------------


def test_changing_the_password_signs_the_other_devices_out(
    client: TestClient,
) -> None:
    _register(client)
    stolen = _login(client)
    here = _login(client)

    response = client.post(
        "/api/v1/account/change-password",
        json={"current_password": PASSWORD, "new_password": "a different one"},
        headers=_bearer(here["access_token"]),
    )

    assert response.status_code == 204
    assert _refresh(client, stolen["refresh_token"]).status_code == 401
    assert _me(client, stolen["access_token"]).status_code == 401


def test_changing_the_password_leaves_the_session_doing_it_alone(
    client: TestClient,
) -> None:
    tokens = _sign_in(client)

    client.post(
        "/api/v1/account/change-password",
        json={"current_password": PASSWORD, "new_password": "a different one"},
        headers=_bearer(tokens["access_token"]),
    )

    assert _me(client, tokens["access_token"]).status_code == 200
    assert _refresh(client, tokens["refresh_token"]).status_code == 200


def test_a_refused_password_change_signs_nobody_out(client: TestClient) -> None:
    _register(client)
    elsewhere = _login(client)
    here = _login(client)

    client.post(
        "/api/v1/account/change-password",
        json={"current_password": "not it", "new_password": "a different one"},
        headers=_bearer(here["access_token"]),
    )

    assert _me(client, elsewhere["access_token"]).status_code == 200


# --- expiry ---------------------------------------------------------------


def test_a_session_left_idle_for_too_long_stops_working(
    client: TestClient,
    db_session: Session,
    user_session_repository: UserSessionRepository,
) -> None:
    tokens = _sign_in(client)
    session_id = decode_access_token(tokens["access_token"]).session_id

    stored = user_session_repository.get(session_id)
    assert stored is not None
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    assert _me(client, tokens["access_token"]).status_code == 401
    assert _refresh(client, tokens["refresh_token"]).status_code == 401


def test_refreshing_pushes_the_deadline_out(
    client: TestClient,
    db_session: Session,
    user_session_repository: UserSessionRepository,
) -> None:
    tokens = _sign_in(client)
    session_id = decode_access_token(tokens["access_token"]).session_id

    stored = user_session_repository.get(session_id)
    assert stored is not None
    stored.expires_at = datetime.now(UTC) + timedelta(minutes=1)
    db_session.flush()
    before = stored.expires_at

    _refresh(client, tokens["refresh_token"])

    assert stored.expires_at > before


# --- authentication -------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/account/sessions"),
        ("delete", "/api/v1/account/sessions"),
        (
            "delete",
            "/api/v1/account/sessions/3f2b0a6e-9c1d-4f8a-8f3e-2b6d5c4a1e70",
        ),
    ],
)
def test_every_session_endpoint_requires_a_token(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    assert getattr(client, method)(path).status_code == 401
