"""Phase 17 acceptance: which endpoints are limited, and what a 429 says.

The suite runs with limiting off, for the reason the `rate_limiter`
fixture gives. These tests turn it on with numbers small enough to reach
in a few lines.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.rate_limit import limits_from
from app.core.config import get_settings
from app.core.rate_limit import Limit, RateLimited, RateLimiter
from tests.support.whatsapp import inbound_payload, sign

EMAIL = "ada@example.com"
PASSWORD = "correct horse battery staple"


@pytest.fixture
def rate_limiter() -> RateLimiter:
    """Overrides the suite-wide fixture: here the counters are real.

    Two a window, which is enough to show the third being refused and
    short enough to read.
    """
    limits = dict(limits_from(get_settings()))
    limits.update(dict.fromkeys(RateLimited, Limit(times=2, seconds=60)))

    return RateLimiter(limits=limits, enabled=True)


def _register(client: TestClient, email: str = EMAIL) -> dict[str, Any]:
    return client.post(
        "/api/v1/auth/register",
        json={"name": "Ada Lovelace", "email": email, "password": PASSWORD},
    ).json()


def _login(client: TestClient, email: str = EMAIL, password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _deliver(client: TestClient, *, secret: str | None = None):
    """One WhatsApp delivery, signed with the right secret or a wrong one."""
    configured = get_settings().whatsapp_app_secret
    assert configured is not None
    body, header = sign(
        inbound_payload(),
        secret if secret is not None else configured.get_secret_value(),
    )

    return client.post(
        "/api/v1/webhooks/whatsapp",
        content=body,
        headers={
            "X-Hub-Signature-256": header,
            "Content-Type": "application/json",
        },
    )


def _workspace(client: TestClient, token: str) -> str:
    return client.post(
        "/api/v1/workspaces",
        json={"name": "Ada's Shop", "slug": "adas-shop"},
        headers=_bearer(token),
    ).json()["id"]


# --- what a refusal looks like --------------------------------------------


def test_the_third_login_is_refused(client: TestClient) -> None:
    _register(client)

    assert _login(client).status_code == 200
    assert _login(client).status_code == 200
    assert _login(client).status_code == 429


def test_the_refusal_is_shaped_like_every_other_error(
    client: TestClient,
) -> None:
    _register(client)
    _login(client)
    _login(client)

    response = _login(client)

    assert response.status_code == 429
    assert response.json()["code"] == "rate_limit_exceeded"
    assert response.json()["detail"]


def test_the_refusal_says_how_long_to_wait(client: TestClient) -> None:
    _register(client)
    _login(client)
    _login(client)

    response = _login(client)

    assert int(response.headers["Retry-After"]) > 0


def test_a_wrong_password_is_counted_too(client: TestClient) -> None:
    # Otherwise the limit protects nothing: guessing is exactly the thing
    # being limited, and every guess is a wrong password.
    _register(client)

    assert _login(client, password="not it").status_code == 401
    assert _login(client, password="not it").status_code == 401
    assert _login(client, password="not it").status_code == 429


def test_the_limit_does_not_depend_on_the_address_submitted(
    client: TestClient,
) -> None:
    # Keyed on the caller, never on the account named. Keying on somebody
    # else's address is how a limiter becomes a way to lock one person
    # out of their own account.
    _register(client)
    _login(client, email="nobody@example.com")
    _login(client, email="somebody-else@example.com")

    assert _login(client).status_code == 429


# --- which endpoints ------------------------------------------------------


def test_refreshing_shares_the_login_allowance(client: TestClient) -> None:
    # A refresh token is a credential, and the same argument applies to
    # guessing at one.
    _register(client)
    tokens = _login(client).json()
    _login(client)

    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )

    assert response.status_code == 429


def test_the_endpoints_that_send_mail_are_limited(
    client: TestClient,
    rate_limiter: RateLimiter,
) -> None:
    # An unauthenticated way to make this service email a stranger, which
    # is why this is the tightest limit here.
    _register(client)
    rate_limiter.reset()

    for _ in range(3):
        last = client.post("/api/v1/auth/forgot-password", json={"email": EMAIL})

    assert last.status_code == 429


def test_asking_to_confirm_shares_that_allowance(
    client: TestClient,
    rate_limiter: RateLimiter,
) -> None:
    _register(client)
    rate_limiter.reset()

    client.post("/api/v1/auth/forgot-password", json={"email": EMAIL})
    client.post("/api/v1/auth/resend-verification", json={"email": EMAIL})

    response = client.post("/api/v1/auth/resend-verification", json={"email": EMAIL})

    assert response.status_code == 429


def test_registering_shares_the_mail_allowance(client: TestClient) -> None:
    # Registering sends a confirmation email, so it is the same amplifier.
    _register(client, "one@example.com")
    _register(client, "two@example.com")

    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Ada", "email": "three@example.com", "password": PASSWORD},
    )

    assert response.status_code == 429


def test_asking_the_assistant_is_limited_per_workspace(
    client: TestClient,
    rate_limiter: RateLimiter,
) -> None:
    _register(client)
    token = _login(client).json()["access_token"]
    workspace = _workspace(client, token)

    # Registering and logging in already spent from other scopes; only
    # the AI bucket matters here.
    rate_limiter.reset()

    contact = client.post(
        f"/api/v1/workspaces/{workspace}/contacts",
        json={"phone_number": "+923001234567"},
        headers=_bearer(token),
    ).json()
    conversation = client.post(
        f"/api/v1/workspaces/{workspace}/conversations",
        json={"contact_id": contact["id"]},
        headers=_bearer(token),
    ).json()

    path = f"/api/v1/workspaces/{workspace}/conversations/{conversation['id']}/ai-reply"

    for _ in range(3):
        last = client.post(path, headers=_bearer(token))

    assert last.status_code == 429


def test_searching_the_knowledge_base_is_limited(
    client: TestClient,
    rate_limiter: RateLimiter,
) -> None:
    _register(client)
    token = _login(client).json()["access_token"]
    workspace = _workspace(client, token)
    rate_limiter.reset()

    path = f"/api/v1/workspaces/{workspace}/knowledge/search"

    for _ in range(3):
        last = client.post(path, json={"query": "do you ship"}, headers=_bearer(token))

    assert last.status_code == 429


def test_inviting_is_limited(
    client: TestClient,
    rate_limiter: RateLimiter,
) -> None:
    _register(client)
    token = _login(client).json()["access_token"]
    workspace = _workspace(client, token)
    rate_limiter.reset()

    path = f"/api/v1/workspaces/{workspace}/invitations"

    for number in range(3):
        last = client.post(
            path,
            json={"email": f"colleague{number}@example.com", "role": "agent"},
            headers=_bearer(token),
        )

    assert last.status_code == 429


def test_one_workspace_cannot_spend_anothers_allowance(
    client: TestClient,
    rate_limiter: RateLimiter,
) -> None:
    _register(client)
    token = _login(client).json()["access_token"]
    mine = _workspace(client, token)
    theirs = client.post(
        "/api/v1/workspaces",
        json={"name": "Other", "slug": "other"},
        headers=_bearer(token),
    ).json()["id"]
    rate_limiter.reset()

    for _ in range(3):
        client.post(
            f"/api/v1/workspaces/{mine}/knowledge/search",
            json={"query": "anything"},
            headers=_bearer(token),
        )

    response = client.post(
        f"/api/v1/workspaces/{theirs}/knowledge/search",
        json={"query": "anything"},
        headers=_bearer(token),
    )

    assert response.status_code == 200


# --- the webhook ----------------------------------------------------------


def test_an_honest_delivery_is_never_charged(client: TestClient) -> None:
    # Meta sends real traffic in volume from a handful of addresses.
    # Counting every delivery would mean either a limit high enough to be
    # no limit or one that throttles the provider itself.
    for _ in range(10):
        assert _deliver(client).status_code == 200


def test_forgeries_stop_being_answered(client: TestClient) -> None:
    for _ in range(3):
        last = _deliver(client, secret="not the app secret")

    assert last.status_code == 429
    assert last.json()["code"] == "rate_limit_exceeded"


def test_only_a_forgery_is_charged_for(client: TestClient) -> None:
    # One forgery of the two allowed, and then any number of honest
    # deliveries: none of them touches the rejection bucket, so none of
    # them brings the address closer to being shut out.
    assert _deliver(client, secret="not the app secret").status_code == 403

    for _ in range(10):
        assert _deliver(client).status_code == 200

    # The second forgery is what empties it, and only then does the
    # address stop being answered at all.
    assert _deliver(client, secret="not the app secret").status_code == 403
    assert _deliver(client).status_code == 429
