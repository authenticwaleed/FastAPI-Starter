"""Phase 5 acceptance: the contacts API, and the wall around each tenant."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.models.workspace_membership import WorkspaceRole
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)

PASSWORD = "correct horse battery staple"
NUMBER = "+923001234567"
OTHER_NUMBER = "+923009876543"

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

    def path(self, contact_id: str | None = None) -> str:
        base = f"/api/v1/workspaces/{self.workspace_id}/contacts"

        return base if contact_id is None else f"{base}/{contact_id}"

    def add(
        self,
        phone_number: str = NUMBER,
        headers: dict[str, str] | None = None,
        **fields: object,
    ):
        return self._client.post(
            self.path(),
            json={"phone_number": phone_number} | fields,
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


# --- creating ---------------------------------------------------------------


def test_adding_a_contact_returns_201(client: TestClient, acme: Business) -> None:
    response = acme.add()

    assert response.status_code == 201

    body = response.json()
    assert body["phone_number"] == NUMBER
    assert body["status"] == "lead"
    assert body["metadata"] == {}
    assert uuid.UUID(body["id"])


def test_a_number_is_normalised_on_the_way_in(
    client: TestClient,
    acme: Business,
) -> None:
    assert acme.add("+92 300 1234567").json()["phone_number"] == NUMBER
    assert acme.add("0092 300 987 6543").json()["phone_number"] == OTHER_NUMBER


@pytest.mark.parametrize(
    "rejected",
    ["0300 1234567", "not a number", "+0923001234567", "+123", ""],
)
def test_a_number_that_is_not_a_number_is_a_422(
    client: TestClient,
    acme: Business,
    rejected: str,
) -> None:
    assert acme.add(rejected).status_code == 422


def test_a_contact_needs_a_phone_number(client: TestClient, acme: Business) -> None:
    response = client.post(
        acme.path(),
        json={"name": "Ayesha"},
        headers=acme.owner_headers,
    )

    assert response.status_code == 422


def test_a_duplicate_number_is_a_409(client: TestClient, acme: Business) -> None:
    acme.add()

    response = acme.add()

    assert response.status_code == 409
    assert response.json()["code"] == "contact_already_exists"


def test_the_same_customer_can_belong_to_two_businesses(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    assert acme.add().status_code == 201
    assert rival.add().status_code == 201


def test_an_invented_status_is_rejected(client: TestClient, acme: Business) -> None:
    assert acme.add(status="vip").status_code == 422


# --- reading and filtering --------------------------------------------------


def test_listing_starts_empty(client: TestClient, acme: Business) -> None:
    body = client.get(acme.path(), headers=acme.owner_headers).json()

    assert body == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_a_contact_can_be_read_back(client: TestClient, acme: Business) -> None:
    created = acme.add().json()

    response = client.get(acme.path(created["id"]), headers=acme.owner_headers)

    assert response.status_code == 200
    assert response.json() == created


def test_listing_is_paginated(client: TestClient, acme: Business) -> None:
    for index in range(3):
        acme.add(f"+92300123456{index}")

    body = client.get(
        acme.path(),
        params={"page": 1, "page_size": 2},
        headers=acme.owner_headers,
    ).json()

    assert len(body["items"]) == 2
    assert body["total"] == 3


def test_listing_rejects_an_oversized_page(
    client: TestClient,
    acme: Business,
) -> None:
    response = client.get(
        acme.path(),
        params={"page_size": 101},
        headers=acme.owner_headers,
    )

    assert response.status_code == 422


def test_contacts_can_be_searched(client: TestClient, acme: Business) -> None:
    acme.add(NUMBER, name="Ayesha")
    acme.add(OTHER_NUMBER, name="Bilal")

    body = client.get(
        acme.path(),
        params={"search": "ayesha"},
        headers=acme.owner_headers,
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["name"] == "Ayesha"


def test_contacts_can_be_filtered_by_status_and_source(
    client: TestClient,
    acme: Business,
) -> None:
    acme.add(NUMBER, status="customer", source="whatsapp")
    acme.add(OTHER_NUMBER, source="manual")

    by_status = client.get(
        acme.path(), params={"status": "customer"}, headers=acme.owner_headers
    ).json()
    by_source = client.get(
        acme.path(), params={"source": "manual"}, headers=acme.owner_headers
    ).json()

    assert by_status["total"] == 1
    assert by_status["items"][0]["phone_number"] == NUMBER
    assert by_source["total"] == 1
    assert by_source["items"][0]["phone_number"] == OTHER_NUMBER


def test_an_unknown_contact_is_a_404(client: TestClient, acme: Business) -> None:
    response = client.get(acme.path(str(uuid.uuid4())), headers=acme.owner_headers)

    assert response.status_code == 404
    assert response.json()["code"] == "contact_not_found"


# --- updating ---------------------------------------------------------------


def test_updating_changes_only_what_was_sent(
    client: TestClient,
    acme: Business,
) -> None:
    created = acme.add(NUMBER, name="Ayesha").json()

    response = client.patch(
        acme.path(created["id"]),
        json={"status": "customer"},
        headers=acme.owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "customer"
    assert response.json()["name"] == "Ayesha"


def test_a_number_cannot_be_moved_onto_another_contact(
    client: TestClient,
    acme: Business,
) -> None:
    acme.add(NUMBER)
    second = acme.add(OTHER_NUMBER).json()

    response = client.patch(
        acme.path(second["id"]),
        json={"phone_number": NUMBER},
        headers=acme.owner_headers,
    )

    assert response.status_code == 409


def test_metadata_round_trips(client: TestClient, acme: Business) -> None:
    created = acme.add(NUMBER, metadata={"size": "M"}).json()

    assert created["metadata"] == {"size": "M"}

    updated = client.patch(
        acme.path(created["id"]),
        json={"metadata": {"size": "L", "colour": "black"}},
        headers=acme.owner_headers,
    ).json()

    assert updated["metadata"] == {"size": "L", "colour": "black"}


# --- who may do what --------------------------------------------------------


@pytest.mark.parametrize("role", [OWNER, ADMIN, AGENT, VIEWER])
def test_every_member_may_read_contacts(
    client: TestClient,
    acme: Business,
    role: WorkspaceRole,
) -> None:
    headers = acme.member(f"{role.value}@example.com", role)
    created = acme.add().json()

    assert client.get(acme.path(), headers=headers).status_code == 200
    assert client.get(acme.path(created["id"]), headers=headers).status_code == 200


@pytest.mark.parametrize("role", [OWNER, ADMIN, AGENT])
def test_anyone_who_handles_customers_may_add_one(
    client: TestClient,
    acme: Business,
    role: WorkspaceRole,
) -> None:
    headers = acme.member(f"{role.value}@example.com", role)

    assert acme.add(OTHER_NUMBER, headers=headers).status_code == 201


def test_a_viewer_may_not_add_or_change_a_contact(
    client: TestClient,
    acme: Business,
) -> None:
    headers = acme.member("viewer@example.com", VIEWER)
    created = acme.add().json()

    assert acme.add(OTHER_NUMBER, headers=headers).status_code == 403
    assert (
        client.patch(
            acme.path(created["id"]),
            json={"name": "Renamed"},
            headers=headers,
        ).status_code
        == 403
    )


# --- the tenant boundary ----------------------------------------------------


@pytest.mark.parametrize("method", ["get", "post"])
def test_the_collection_requires_a_token(
    client: TestClient,
    acme: Business,
    method: str,
) -> None:
    response = client.request(method, acme.path(), json={"phone_number": OTHER_NUMBER})

    assert response.status_code == 401


@pytest.mark.parametrize("method", ["get", "patch"])
def test_another_business_cannot_reach_your_contact(
    client: TestClient,
    acme: Business,
    rival: Business,
    method: str,
) -> None:
    # A contact id is a UUID, but unguessable is not an access control.
    created = acme.add().json()

    response = client.request(
        method,
        f"/api/v1/workspaces/{rival.workspace_id}/contacts/{created['id']}",
        json={"name": "Taken Over"},
        headers=rival.owner_headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "contact_not_found"


def test_aiming_at_the_owning_workspace_from_outside_is_also_refused(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    # The other half of the same attempt: the right workspace in the path,
    # somebody else's token. That is stopped a step earlier, by the
    # workspace dependency, and must not leak that the workspace exists.
    created = acme.add().json()

    response = client.get(acme.path(created["id"]), headers=rival.owner_headers)

    assert response.status_code == 404
    assert response.json()["code"] == "workspace_not_found"


def test_another_businesss_contacts_never_appear_in_your_list(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    acme.add(NUMBER, name="Ayesha")
    rival.add(OTHER_NUMBER, name="Bilal")

    body = client.get(acme.path(), headers=acme.owner_headers).json()

    assert body["total"] == 1
    assert [item["name"] for item in body["items"]] == ["Ayesha"]


def test_search_cannot_be_used_to_probe_another_business(
    client: TestClient,
    acme: Business,
    rival: Business,
) -> None:
    rival.add(NUMBER, name="Ayesha")

    body = client.get(
        acme.path(),
        params={"search": "Ayesha"},
        headers=acme.owner_headers,
    ).json()

    assert body == {"items": [], "total": 0, "page": 1, "page_size": 20}
