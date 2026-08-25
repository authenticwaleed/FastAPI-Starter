"""Phase 2 acceptance: workspace CRUD, and the tenant boundary over HTTP."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.models.workspace_membership import WorkspaceRole
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)

PASSWORD = "correct horse battery staple"


def _headers(client: TestClient, email: str) -> dict[str, str]:
    """Register a user and return headers that authenticate them."""
    client.post(
        "/api/v1/auth/register",
        json={"name": "Someone", "email": email, "password": PASSWORD},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    ).json()["access_token"]

    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ada(client: TestClient) -> dict[str, str]:
    return _headers(client, "ada@example.com")


@pytest.fixture
def alan(client: TestClient) -> dict[str, str]:
    return _headers(client, "alan@example.com")


def _body(slug: str = "acme-fashion", **overrides: object) -> dict:
    return {"name": "Acme Fashion", "slug": slug} | overrides


def _create(client: TestClient, headers: dict[str, str], slug: str = "acme-fashion"):
    return client.post("/api/v1/workspaces", json=_body(slug), headers=headers)


# --- creating ---------------------------------------------------------------


def test_creating_a_workspace_returns_201_and_the_workspace(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    response = _create(client, ada)

    assert response.status_code == 201

    body = response.json()
    assert body["name"] == "Acme Fashion"
    assert body["slug"] == "acme-fashion"
    assert body["status"] == "active"
    assert uuid.UUID(body["id"])


def test_a_new_workspace_defaults_to_utc_and_usd(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    body = _create(client, ada).json()

    assert body["timezone"] == "UTC"
    assert body["default_currency"] == "USD"


def test_a_workspace_can_be_created_with_a_timezone_and_currency(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    response = client.post(
        "/api/v1/workspaces",
        json=_body(timezone="Asia/Karachi", default_currency="pkr"),
        headers=ada,
    )

    assert response.status_code == 201
    assert response.json()["timezone"] == "Asia/Karachi"
    # Normalised on the way in, so a currency means one thing in storage.
    assert response.json()["default_currency"] == "PKR"


def test_the_creator_becomes_the_owner(
    client: TestClient,
    ada: dict[str, str],
    membership_repository: WorkspaceMembershipRepository,
    user_repository: UserRepository,
) -> None:
    workspace_id = uuid.UUID(_create(client, ada).json()["id"])

    user = user_repository.get_by_email("ada@example.com")
    assert user is not None

    membership = membership_repository.get_for_user(workspace_id, user.id)
    assert membership is not None
    assert membership.role == WorkspaceRole.OWNER


def test_a_duplicate_slug_returns_409(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    _create(client, ada)

    response = _create(client, ada)

    assert response.status_code == 409
    assert response.json()["code"] == "slug_already_exists"


def test_another_business_cannot_take_a_slug_already_in_use(
    client: TestClient,
    ada: dict[str, str],
    alan: dict[str, str],
) -> None:
    _create(client, ada)

    assert _create(client, alan).status_code == 409


@pytest.mark.parametrize(
    "slug",
    ["", "ab", "Acme", "acme fashion", "acme_fashion", "-acme", "acme-", "acme--x"],
)
def test_a_malformed_slug_is_rejected(
    client: TestClient,
    ada: dict[str, str],
    slug: str,
) -> None:
    response = client.post("/api/v1/workspaces", json=_body(slug), headers=ada)

    assert response.status_code == 422


def test_an_unknown_timezone_is_rejected(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    # Every analytics bucket is reported in this zone. A typo here is wrong
    # numbers on a dashboard months later, not an error anyone can trace.
    response = client.post(
        "/api/v1/workspaces",
        json=_body(timezone="Mars/Olympus_Mons"),
        headers=ada,
    )

    assert response.status_code == 422


def test_a_malformed_currency_is_rejected(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    response = client.post(
        "/api/v1/workspaces",
        json=_body(default_currency="dollars"),
        headers=ada,
    )

    assert response.status_code == 422


# --- listing ----------------------------------------------------------------


def test_listing_starts_empty(client: TestClient, ada: dict[str, str]) -> None:
    response = client.get("/api/v1/workspaces", headers=ada)

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


def test_listing_returns_the_workspaces_you_belong_to(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    _create(client, ada, "first-store")
    _create(client, ada, "second-store")

    body = client.get("/api/v1/workspaces", headers=ada).json()

    assert body["total"] == 2
    assert {item["slug"] for item in body["items"]} == {
        "first-store",
        "second-store",
    }


def test_listing_is_paginated(client: TestClient, ada: dict[str, str]) -> None:
    for index in range(3):
        _create(client, ada, f"store-{index}")

    body = client.get(
        "/api/v1/workspaces",
        params={"page": 1, "page_size": 2},
        headers=ada,
    ).json()

    assert len(body["items"]) == 2
    assert body["total"] == 3


def test_listing_rejects_an_oversized_page(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    response = client.get(
        "/api/v1/workspaces",
        params={"page_size": 101},
        headers=ada,
    )

    assert response.status_code == 422


# --- reading, updating, closing ---------------------------------------------


def test_a_member_can_read_their_workspace(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    created = _create(client, ada).json()

    response = client.get(f"/api/v1/workspaces/{created['id']}", headers=ada)

    assert response.status_code == 200
    assert response.json() == created


def test_an_owner_can_rename_their_workspace(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    created = _create(client, ada).json()

    response = client.patch(
        f"/api/v1/workspaces/{created['id']}",
        json={"name": "Acme Apparel"},
        headers=ada,
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Acme Apparel"
    assert response.json()["slug"] == "acme-fashion"


def test_the_slug_cannot_be_changed_by_a_patch(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    # It is a public identifier that ends up in customers' bookmarks, so
    # moving it is a deliberate operation rather than a field in a PATCH.
    created = _create(client, ada).json()

    client.patch(
        f"/api/v1/workspaces/{created['id']}",
        json={"slug": "something-else"},
        headers=ada,
    )

    read = client.get(f"/api/v1/workspaces/{created['id']}", headers=ada).json()
    assert read["slug"] == "acme-fashion"


def test_an_empty_patch_changes_nothing(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    created = _create(client, ada).json()

    response = client.patch(
        f"/api/v1/workspaces/{created['id']}",
        json={},
        headers=ada,
    )

    assert response.status_code == 200
    assert response.json()["name"] == created["name"]


def test_closing_a_workspace_returns_204(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    created = _create(client, ada).json()

    response = client.delete(f"/api/v1/workspaces/{created['id']}", headers=ada)

    assert response.status_code == 204
    assert not response.content


def test_a_closed_workspace_disappears_completely(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    created = _create(client, ada).json()

    client.delete(f"/api/v1/workspaces/{created['id']}", headers=ada)

    assert (
        client.get(f"/api/v1/workspaces/{created['id']}", headers=ada).status_code
        == 404
    )
    assert client.get("/api/v1/workspaces", headers=ada).json()["total"] == 0


# --- the tenant boundary ----------------------------------------------------


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_naming_a_workspace_without_a_token_is_refused(
    client: TestClient,
    ada: dict[str, str],
    method: str,
) -> None:
    created = _create(client, ada).json()

    response = client.request(
        method,
        f"/api/v1/workspaces/{created['id']}",
        json={"name": "Renamed"},
    )

    assert response.status_code == 401


@pytest.mark.parametrize("method", ["get", "post"])
def test_the_collection_needs_a_token_too(client: TestClient, method: str) -> None:
    response = client.request(method, "/api/v1/workspaces", json=_body())

    assert response.status_code == 401


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_another_business_is_not_reachable_at_all(
    client: TestClient,
    ada: dict[str, str],
    alan: dict[str, str],
    method: str,
) -> None:
    # The isolation rule from the plan's checklist: workspace A must not be
    # reachable by anyone who belongs to workspace B.
    created = _create(client, ada).json()

    response = client.request(
        method,
        f"/api/v1/workspaces/{created['id']}",
        json={"name": "Taken Over"},
        headers=alan,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "workspace_not_found"


def test_someone_elses_workspace_looks_exactly_like_one_that_never_existed(
    client: TestClient,
    ada: dict[str, str],
    alan: dict[str, str],
) -> None:
    # If these two differed, the id in the URL would become a way of asking
    # which businesses have accounts here.
    created = _create(client, ada).json()

    theirs = client.get(f"/api/v1/workspaces/{created['id']}", headers=alan)
    imaginary = client.get(f"/api/v1/workspaces/{uuid.uuid4()}", headers=alan)

    assert theirs.status_code == imaginary.status_code == 404
    assert theirs.json() == imaginary.json()


def test_a_refused_update_leaves_the_workspace_untouched(
    client: TestClient,
    ada: dict[str, str],
    alan: dict[str, str],
) -> None:
    created = _create(client, ada).json()

    client.patch(
        f"/api/v1/workspaces/{created['id']}",
        json={"name": "Taken Over"},
        headers=alan,
    )

    read = client.get(f"/api/v1/workspaces/{created['id']}", headers=ada).json()
    assert read["name"] == "Acme Fashion"


def test_another_business_cannot_close_yours(
    client: TestClient,
    ada: dict[str, str],
    alan: dict[str, str],
) -> None:
    created = _create(client, ada).json()

    client.delete(f"/api/v1/workspaces/{created['id']}", headers=alan)

    assert (
        client.get(f"/api/v1/workspaces/{created['id']}", headers=ada).status_code
        == 200
    )


def test_a_workspace_id_that_is_not_a_uuid_is_rejected(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    response = client.get("/api/v1/workspaces/not-a-uuid", headers=ada)

    assert response.status_code == 422


# --- roles over HTTP --------------------------------------------------------


def _add_member(
    client: TestClient,
    memberships: WorkspaceMembershipRepository,
    users: UserRepository,
    workspace_id: str,
    email: str,
    role: WorkspaceRole,
) -> None:
    """Put somebody in a workspace directly.

    There is no invitation endpoint yet -- that is a later phase -- so the
    only way to exercise a role other than owner is to write the membership.
    """
    user = users.get_by_email(email)
    assert user is not None
    memberships.create(
        workspace_id=uuid.UUID(workspace_id),
        user_id=user.id,
        role=role,
    )


@pytest.mark.parametrize("role", [WorkspaceRole.AGENT, WorkspaceRole.VIEWER])
def test_a_member_without_administrative_rights_is_told_403_not_404(
    client: TestClient,
    ada: dict[str, str],
    alan: dict[str, str],
    membership_repository: WorkspaceMembershipRepository,
    user_repository: UserRepository,
    role: WorkspaceRole,
) -> None:
    # A member has already proved they belong, so confirming the workspace
    # exists tells them nothing. A stranger still gets a 404.
    created = _create(client, ada).json()
    _add_member(
        client,
        membership_repository,
        user_repository,
        created["id"],
        "alan@example.com",
        role,
    )

    response = client.patch(
        f"/api/v1/workspaces/{created['id']}",
        json={"name": "Renamed"},
        headers=alan,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "insufficient_workspace_role"


def test_a_viewer_can_still_read_the_workspace(
    client: TestClient,
    ada: dict[str, str],
    alan: dict[str, str],
    membership_repository: WorkspaceMembershipRepository,
    user_repository: UserRepository,
) -> None:
    created = _create(client, ada).json()
    _add_member(
        client,
        membership_repository,
        user_repository,
        created["id"],
        "alan@example.com",
        WorkspaceRole.VIEWER,
    )

    assert (
        client.get(f"/api/v1/workspaces/{created['id']}", headers=alan).status_code
        == 200
    )
    assert client.get("/api/v1/workspaces", headers=alan).json()["total"] == 1


def test_an_admin_may_rename_but_not_close(
    client: TestClient,
    ada: dict[str, str],
    alan: dict[str, str],
    membership_repository: WorkspaceMembershipRepository,
    user_repository: UserRepository,
) -> None:
    created = _create(client, ada).json()
    _add_member(
        client,
        membership_repository,
        user_repository,
        created["id"],
        "alan@example.com",
        WorkspaceRole.ADMIN,
    )

    assert (
        client.patch(
            f"/api/v1/workspaces/{created['id']}",
            json={"name": "Renamed"},
            headers=alan,
        ).status_code
        == 200
    )
    assert (
        client.delete(f"/api/v1/workspaces/{created['id']}", headers=alan).status_code
        == 403
    )


# --- what Phase 2 does to account deletion ----------------------------------


def test_the_only_owner_cannot_delete_their_account(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    # Letting them go would strand a business nobody can administer.
    _create(client, ada)

    response = client.delete("/api/v1/account", headers=ada)

    assert response.status_code == 409
    assert response.json()["code"] == "workspace_ownership_required"


def test_the_refused_account_deletion_leaves_the_account_working(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    _create(client, ada)

    client.delete("/api/v1/account", headers=ada)

    assert client.get("/api/v1/account", headers=ada).status_code == 200


def test_closing_the_workspace_frees_the_account(
    client: TestClient,
    ada: dict[str, str],
) -> None:
    created = _create(client, ada).json()

    client.delete(f"/api/v1/workspaces/{created['id']}", headers=ada)

    assert client.delete("/api/v1/account", headers=ada).status_code == 204


def test_a_user_who_owns_nothing_can_still_delete_their_account(
    client: TestClient,
    ada: dict[str, str],
    alan: dict[str, str],
    membership_repository: WorkspaceMembershipRepository,
    user_repository: UserRepository,
) -> None:
    created = _create(client, ada).json()
    _add_member(
        client,
        membership_repository,
        user_repository,
        created["id"],
        "alan@example.com",
        WorkspaceRole.ADMIN,
    )

    assert client.delete("/api/v1/account", headers=alan).status_code == 204
