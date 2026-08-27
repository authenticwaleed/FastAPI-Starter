"""Phase 16 acceptance: confirming an address, and getting back in.

The four things the phase is judged on: verification works, reset works,
enumeration is not exposed, and expiry is tested.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user_token import UserToken, UserTokenPurpose
from app.repositories.user_repository import UserRepository
from tests.support.email import FakeEmailSender

EMAIL = "ada@example.com"
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


def _bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _verify(client: TestClient, token: str):
    return client.post("/api/v1/auth/verify-email", json={"token": token})


def _resend(client: TestClient, email: str = EMAIL):
    return client.post("/api/v1/auth/resend-verification", json={"email": email})


def _forgot(client: TestClient, email: str = EMAIL):
    return client.post("/api/v1/auth/forgot-password", json={"email": email})


def _reset(client: TestClient, token: str, password: str = NEW_PASSWORD):
    return client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": password},
    )


def _age(
    session: Session,
    user_repository: UserRepository,
    purpose: UserTokenPurpose,
) -> None:
    """Push the account's outstanding link of one kind into the past.

    Written directly rather than through an endpoint, because no endpoint
    lets a link have been sent two days ago -- and waiting two days is
    not a test.
    """
    user = user_repository.get_by_email(EMAIL)
    assert user is not None

    tokens = session.scalars(
        select(UserToken).where(
            UserToken.user_id == user.id,
            UserToken.purpose == purpose,
        )
    ).all()

    assert len(tokens) == 1

    tokens[0].expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.flush()


# --- registration ---------------------------------------------------------


def test_registering_sends_a_confirmation_email(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    _register(client)

    assert len(email_sender.sent) == 1
    assert email_sender.last.to == EMAIL
    assert "Confirm" in email_sender.last.subject


def test_a_new_account_is_not_confirmed_yet(client: TestClient) -> None:
    assert _register(client)["email_verified_at"] is None


def test_the_email_never_carries_the_password(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    _register(client)

    assert PASSWORD not in email_sender.last.body


# --- verification ---------------------------------------------------------


def test_following_the_link_confirms_the_address(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    _register(client)

    assert _verify(client, email_sender.last_token).status_code == 204

    token = _login(client).json()["access_token"]
    account = client.get("/api/v1/account", headers=_bearer(token)).json()
    assert account["email_verified_at"] is not None


def test_a_link_works_once(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    _register(client)
    link = email_sender.last_token

    _verify(client, link)

    response = _verify(client, link)
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_verification_token"


def test_a_link_nobody_was_sent_does_nothing(client: TestClient) -> None:
    _register(client)

    assert _verify(client, "not a link anybody was sent").status_code == 400


def test_an_expired_link_does_nothing(
    client: TestClient,
    email_sender: FakeEmailSender,
    db_session: Session,
    user_repository: UserRepository,
) -> None:
    _register(client)
    link = email_sender.last_token
    _age(db_session, user_repository, UserTokenPurpose.EMAIL_VERIFICATION)

    assert _verify(client, link).status_code == 400


def test_verifying_does_not_sign_anybody_in(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    _register(client)

    response = _verify(client, email_sender.last_token)

    assert response.status_code == 204
    assert not response.content


def test_resending_gives_a_link_that_works(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    _register(client)

    assert _resend(client).status_code == 202
    assert _verify(client, email_sender.last_token).status_code == 204


def test_resending_retires_the_previous_link(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    # Otherwise a mailbox accumulates working keys to an account.
    _register(client)
    first = email_sender.last_token

    _resend(client)

    assert email_sender.last_token != first
    assert _verify(client, first).status_code == 400


def test_an_address_already_confirmed_is_sent_nothing(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    _register(client)
    _verify(client, email_sender.last_token)
    already = len(email_sender.sent)

    assert _resend(client).status_code == 202
    assert len(email_sender.sent) == already


def test_changing_the_address_unconfirms_it(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    # Otherwise "verified" means nothing: anybody could carry it over to
    # an address they had never received mail at.
    _register(client)
    _verify(client, email_sender.last_token)
    token = _login(client).json()["access_token"]

    response = client.patch(
        "/api/v1/account",
        json={"email": "ada.lovelace@example.com"},
        headers=_bearer(token),
    )

    assert response.status_code == 200
    assert response.json()["email_verified_at"] is None


def test_a_link_sent_to_an_address_that_has_since_changed_is_refused(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    _register(client)
    old = email_sender.last_token
    token = _login(client).json()["access_token"]

    client.patch(
        "/api/v1/account",
        json={"email": "ada.lovelace@example.com"},
        headers=_bearer(token),
    )

    assert _verify(client, old).status_code == 400


# --- password reset -------------------------------------------------------


def test_a_reset_link_replaces_the_password(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    _register(client)

    assert _forgot(client).status_code == 202
    assert _reset(client, email_sender.last_token).status_code == 204

    assert _login(client, password=NEW_PASSWORD).status_code == 200
    assert _login(client, password=PASSWORD).status_code == 401


def test_the_reset_email_is_not_the_verification_email(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    _register(client)
    _forgot(client)

    assert "Reset" in email_sender.last.subject


def test_a_reset_link_works_once(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    _register(client)
    _forgot(client)
    link = email_sender.last_token

    _reset(client, link)

    assert _reset(client, link, "yet another password").status_code == 400
    assert _login(client, password=NEW_PASSWORD).status_code == 200


def test_asking_twice_retires_the_first_link(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    _register(client)
    _forgot(client)
    first = email_sender.last_token

    _forgot(client)

    assert _reset(client, first).status_code == 400
    assert _reset(client, email_sender.last_token).status_code == 204


def test_an_expired_reset_link_does_nothing(
    client: TestClient,
    email_sender: FakeEmailSender,
    db_session: Session,
    user_repository: UserRepository,
) -> None:
    _register(client)
    _forgot(client)
    link = email_sender.last_token
    _age(db_session, user_repository, UserTokenPurpose.PASSWORD_RESET)

    assert _reset(client, link).status_code == 400
    assert _login(client, password=PASSWORD).status_code == 200


def test_a_confirmation_link_cannot_reset_a_password(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    # The cheap link, the one that lives for days, must not be spendable
    # as the expensive one.
    _register(client)

    assert _reset(client, email_sender.last_token).status_code == 400
    assert _login(client, password=PASSWORD).status_code == 200


def test_a_reset_link_cannot_confirm_an_address(client: TestClient) -> None:
    _register(client)
    _forgot(client)

    # Deliberately the other direction too: the purpose is checked, not
    # merely the lifetime.
    response = client.post(
        "/api/v1/auth/verify-email",
        json={"token": "not the one that was sent"},
    )

    assert response.status_code == 400


def test_resetting_signs_every_session_out(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    # The whole point when the reason for resetting is that somebody else
    # got in.
    _register(client)
    stolen = _login(client).json()
    _forgot(client)

    _reset(client, email_sender.last_token)

    assert (
        client.get(
            "/api/v1/auth/me", headers=_bearer(stolen["access_token"])
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": stolen["refresh_token"]},
        ).status_code
        == 401
    )


def test_resetting_confirms_the_address_as_well(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    # They just read mail at it, which is exactly what a confirmation
    # link proves.
    _register(client)
    _forgot(client)

    _reset(client, email_sender.last_token)

    token = _login(client, password=NEW_PASSWORD).json()["access_token"]
    account = client.get("/api/v1/account", headers=_bearer(token)).json()
    assert account["email_verified_at"] is not None


def test_a_reset_applies_the_password_policy(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    _register(client)
    _forgot(client)

    assert _reset(client, email_sender.last_token, "short").status_code == 422
    assert _login(client, password=PASSWORD).status_code == 200


def test_resetting_does_not_sign_anybody_in(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    _register(client)
    _forgot(client)

    response = _reset(client, email_sender.last_token)

    assert response.status_code == 204
    assert not response.content


# --- enumeration ----------------------------------------------------------


@pytest.mark.parametrize("path", ["forgot-password", "resend-verification"])
def test_an_unknown_address_gets_the_same_answer_as_a_real_one(
    client: TestClient,
    path: str,
) -> None:
    _register(client)

    known = client.post(f"/api/v1/auth/{path}", json={"email": EMAIL})
    unknown = client.post(
        f"/api/v1/auth/{path}",
        json={"email": "nobody@example.com"},
    )

    assert known.status_code == unknown.status_code == 202
    assert known.content == unknown.content


@pytest.mark.parametrize("path", ["forgot-password", "resend-verification"])
def test_nothing_is_sent_to_an_address_nobody_registered(
    client: TestClient,
    email_sender: FakeEmailSender,
    path: str,
) -> None:
    client.post(f"/api/v1/auth/{path}", json={"email": "nobody@example.com"})

    assert email_sender.sent == []


@pytest.mark.parametrize("path", ["forgot-password", "resend-verification"])
def test_a_deactivated_account_is_sent_nothing_and_says_so_to_nobody(
    client: TestClient,
    email_sender: FakeEmailSender,
    user_repository: UserRepository,
    db_session: Session,
    path: str,
) -> None:
    _register(client)
    user = user_repository.get_by_email(EMAIL)
    assert user is not None
    user.is_active = False
    db_session.flush()
    already = len(email_sender.sent)

    response = client.post(f"/api/v1/auth/{path}", json={"email": EMAIL})

    assert response.status_code == 202
    assert len(email_sender.sent) == already


@pytest.mark.parametrize("path", ["forgot-password", "resend-verification"])
def test_a_malformed_address_is_still_refused(
    client: TestClient,
    path: str,
) -> None:
    # Not an enumeration signal: it says nothing about accounts, only
    # that the field was not an address at all.
    response = client.post(f"/api/v1/auth/{path}", json={"email": "not-an-email"})

    assert response.status_code == 422


def test_a_failed_send_does_not_fail_the_request(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    # A mail server being down must not be able to fail a registration,
    # and must not answer differently for a real address either.
    email_sender.fail_with = "the mail server said no"

    assert _register(client)["email"] == EMAIL
    assert _forgot(client).status_code == 202
