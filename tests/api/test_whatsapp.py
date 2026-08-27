"""Phase 7 acceptance: connecting a number, and the token nobody sees."""

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text as sql
from sqlalchemy.orm import Session

from app.models.workspace_membership import WorkspaceRole
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from tests.support.whatsapp import PHONE_NUMBER_ID

PASSWORD = "correct horse battery staple"
TOKEN = "EAAG-a-provider-access-token-nobody-should-see"

OWNER = WorkspaceRole.OWNER
ADMIN = WorkspaceRole.ADMIN
AGENT = WorkspaceRole.AGENT
VIEWER = WorkspaceRole.VIEWER


def _sign_up(client: TestClient, email: str) -> dict[str, str]:
    client.post(
        "/api/v1/auth/register",
        json={"name": "Someone", "email": email, "password": PASSWORD},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    ).json()["access_token"]

    return {"Authorization": f"Bearer {token}"}


class Business:
    def __init__(
        self,
        client: TestClient,
        users: UserRepository,
        memberships: WorkspaceMembershipRepository,
        slug: str,
    ) -> None:
        self._client = client
        self._users = users
        self._memberships = memberships

        self.owner_headers = _sign_up(client, f"owner-{slug}@example.com")
        self.workspace_id = client.post(
            "/api/v1/workspaces",
            json={"name": slug.title(), "slug": slug},
            headers=self.owner_headers,
        ).json()["id"]

    def member(self, email: str, role: WorkspaceRole) -> dict[str, str]:
        headers = _sign_up(self._client, email)
        user = self._users.get_by_email(email)
        assert user is not None
        self._memberships.create(
            workspace_id=uuid.UUID(self.workspace_id),
            user_id=user.id,
            role=role,
        )

        return headers

    def path(self, suffix: str = "") -> str:
        return f"/api/v1/workspaces/{self.workspace_id}/integrations/whatsapp{suffix}"

    def connect(
        self,
        headers: dict[str, str] | None = None,
        phone_number_id: str = PHONE_NUMBER_ID,
        **fields: object,
    ):
        body = {
            "phone_number": "+15550001111",
            "external_phone_number_id": phone_number_id,
            "access_token": TOKEN,
        } | fields

        return self._client.post(
            self.path("/connect"),
            json=body,
            headers=headers or self.owner_headers,
        )


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Business:
    return Business(client, user_repository, membership_repository, "acme-fashion")


@pytest.fixture
def rival(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Business:
    return Business(client, user_repository, membership_repository, "rival-store")


@contextmanager
def capture(level: int = logging.DEBUG) -> Iterator[list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collect(level=level)
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(level)

    try:
        yield records
    finally:
        root.setLevel(previous)
        root.removeHandler(handler)


# --- connecting -------------------------------------------------------------


def test_connecting_returns_201(client: TestClient, acme: Business) -> None:
    response = acme.connect()

    assert response.status_code == 201

    body = response.json()
    assert body["phone_number"] == "+15550001111"
    assert body["external_phone_number_id"] == PHONE_NUMBER_ID
    assert body["provider"] == "meta_cloud"
    assert body["status"] == "connected"


def test_no_response_ever_carries_the_access_token(
    client: TestClient,
    acme: Business,
) -> None:
    connected = acme.connect()
    read = client.get(acme.path(), headers=acme.owner_headers)

    for response in (connected, read):
        assert TOKEN not in response.text
        assert "access_token" not in response.json()
        assert "access_token_encrypted" not in response.json()


def test_the_token_is_not_stored_in_plain_text(
    client: TestClient,
    acme: Business,
    db_session: Session,
) -> None:
    acme.connect()

    stored = db_session.execute(sql("SELECT * FROM whatsapp_accounts")).all()

    assert TOKEN not in str(stored)


def test_the_token_never_reaches_the_log(
    client: TestClient,
    acme: Business,
) -> None:
    with capture() as records:
        acme.connect()
        client.get(acme.path(), headers=acme.owner_headers)

    written = "\n".join(record.getMessage() for record in records)

    assert TOKEN not in written


def test_connecting_twice_is_a_409(client: TestClient, acme: Business) -> None:
    acme.connect()

    response = acme.connect()

    assert response.status_code == 409
    assert response.json()["code"] == "whatsapp_already_connected"


def test_a_number_connected_elsewhere_cannot_be_taken(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    # Answered the same way as connecting twice, deliberately: saying
    # which would confirm that a given business number is in use here, to
    # somebody who only had to guess it.
    acme.connect()

    response = rival.connect()

    assert response.status_code == 409
    assert response.json()["code"] == "whatsapp_already_connected"


def test_a_bad_phone_number_is_rejected(client: TestClient, acme: Business) -> None:
    assert acme.connect(phone_number="0300 1234567").status_code == 422


def test_an_empty_token_is_rejected(client: TestClient, acme: Business) -> None:
    assert acme.connect(access_token="").status_code == 422


# --- reading and disconnecting ----------------------------------------------


def test_reading_before_connecting_is_a_404(
    client: TestClient,
    acme: Business,
) -> None:
    response = client.get(acme.path(), headers=acme.owner_headers)

    assert response.status_code == 404
    assert response.json()["code"] == "whatsapp_not_connected"


def test_disconnecting_removes_the_credential(
    client: TestClient,
    acme: Business,
    db_session: Session,
) -> None:
    acme.connect()

    response = client.delete(acme.path(), headers=acme.owner_headers)

    assert response.status_code == 204
    assert db_session.execute(sql("SELECT * FROM whatsapp_accounts")).all() == []


def test_disconnecting_frees_the_number(client: TestClient, acme: Business) -> None:
    acme.connect()
    client.delete(acme.path(), headers=acme.owner_headers)

    assert acme.connect().status_code == 201


# --- who may do what --------------------------------------------------------


@pytest.mark.parametrize("role", [OWNER, ADMIN])
def test_an_administrator_may_connect_and_disconnect(
    client: TestClient,
    acme: Business,
    role: WorkspaceRole,
) -> None:
    headers = acme.member(f"{role.value}@example.com", role)

    assert acme.connect(headers=headers).status_code == 201
    assert client.delete(acme.path(), headers=headers).status_code == 204


@pytest.mark.parametrize("role", [AGENT, VIEWER])
def test_handing_over_a_credential_is_not_an_agents_job(
    client: TestClient,
    acme: Business,
    role: WorkspaceRole,
) -> None:
    headers = acme.member(f"{role.value}@example.com", role)

    assert acme.connect(headers=headers).status_code == 403
    acme.connect()
    assert client.delete(acme.path(), headers=headers).status_code == 403


@pytest.mark.parametrize("role", [OWNER, ADMIN, AGENT, VIEWER])
def test_every_member_may_see_what_is_connected(
    client: TestClient,
    acme: Business,
    role: WorkspaceRole,
) -> None:
    headers = acme.member(f"{role.value}@example.com", role)
    acme.connect()

    assert client.get(acme.path(), headers=headers).status_code == 200


# --- the tenant boundary ----------------------------------------------------


def test_another_business_cannot_see_your_connection(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    acme.connect()

    response = client.get(acme.path(), headers=rival.owner_headers)

    assert response.status_code == 404
    assert response.json()["code"] == "workspace_not_found"


def test_connecting_requires_a_token(client: TestClient, acme: Business) -> None:
    response = client.post(
        acme.path("/connect"),
        json={
            "phone_number": "+15550001111",
            "external_phone_number_id": PHONE_NUMBER_ID,
            "access_token": TOKEN,
        },
    )

    assert response.status_code == 401
