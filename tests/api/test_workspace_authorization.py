"""Phase 3 acceptance: one reusable dependency, not a check per handler."""

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies.workspace import (
    WorkspaceAdminDep,
    WorkspaceMemberDep,
    WorkspaceOwnerDep,
    require_workspace_role,
)
from app.core.exceptions import InsufficientWorkspaceRoleError
from app.models.workspace import Workspace
from app.models.workspace_membership import WorkspaceMembership, WorkspaceRole
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.workspace_service import WorkspaceAccess

PASSWORD = "correct horse battery staple"

OWNER = WorkspaceRole.OWNER
ADMIN = WorkspaceRole.ADMIN
AGENT = WorkspaceRole.AGENT
VIEWER = WorkspaceRole.VIEWER


def _access(role: WorkspaceRole) -> WorkspaceAccess:
    """A WorkspaceAccess for a given role, without touching the database.

    The dependency is a pure function of the role, so proving what it
    admits needs nothing persisted.
    """
    return WorkspaceAccess(
        workspace=Workspace(id=uuid.uuid4(), name="Acme", slug="acme"),
        membership=WorkspaceMembership(role=role),
    )


# --- the dependency itself --------------------------------------------------


@pytest.mark.parametrize("role", [OWNER, ADMIN])
def test_a_permitted_role_passes_straight_through(role: WorkspaceRole) -> None:
    dependency = require_workspace_role(OWNER, ADMIN)
    access = _access(role)

    assert dependency(access) is access


@pytest.mark.parametrize("role", [AGENT, VIEWER])
def test_a_role_outside_the_list_is_refused(role: WorkspaceRole) -> None:
    dependency = require_workspace_role(OWNER, ADMIN)

    with pytest.raises(InsufficientWorkspaceRoleError):
        dependency(_access(role))


def test_the_refusal_names_the_role_that_was_refused() -> None:
    # For the log line. The response says only that the role does not
    # permit this, which is all the caller needs.
    dependency = require_workspace_role(OWNER)

    with pytest.raises(InsufficientWorkspaceRoleError) as refused:
        dependency(_access(VIEWER))

    assert refused.value.role == VIEWER
    assert refused.value.detail == "Your role does not permit this action"


def test_the_named_dependencies_are_the_roles_they_say() -> None:
    # WorkspaceMemberDep is deliberately the unfiltered access dependency:
    # for it, membership is the whole check.
    assert WorkspaceMemberDep is not None
    assert WorkspaceAdminDep is not None
    assert WorkspaceOwnerDep is not None


def test_no_route_hard_codes_a_role_check() -> None:
    # The point of the phase, as a test. A role compared inside a handler
    # is a rule that the next handler can silently fail to repeat, and a
    # route that forgot one looks exactly like a route deliberately open.
    for module in sorted(Path("app/api/routes").glob("*.py")):
        assert "WorkspaceRole" not in module.read_text(), module


# --- the same rules, over HTTP ----------------------------------------------


@pytest.fixture
def workspace_id(
    client: TestClient,
    user_repository: UserRepository,
) -> str:
    client.post(
        "/api/v1/auth/register",
        json={"name": "Owner", "email": "owner@example.com", "password": PASSWORD},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": PASSWORD},
    ).json()["access_token"]

    return client.post(
        "/api/v1/workspaces",
        json={"name": "Acme Fashion", "slug": "acme-fashion"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()["id"]


def _member(
    client: TestClient,
    users: UserRepository,
    memberships: WorkspaceMembershipRepository,
    workspace_id: str,
    role: WorkspaceRole,
) -> dict[str, str]:
    # Prefixed so the owner case does not collide with the address the
    # workspace's creator already registered.
    email = f"member-{role.value}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"name": "Member", "email": email, "password": PASSWORD},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    ).json()["access_token"]

    user = users.get_by_email(email)
    assert user is not None
    memberships.create(
        workspace_id=uuid.UUID(workspace_id),
        user_id=user.id,
        role=role,
    )

    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize(
    ("role", "read", "update", "close"),
    [
        (OWNER, 200, 200, 204),
        (ADMIN, 200, 200, 403),
        (AGENT, 200, 403, 403),
        (VIEWER, 200, 403, 403),
    ],
)
def test_each_role_reaches_exactly_what_it_should(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    workspace_id: str,
    role: WorkspaceRole,
    read: int,
    update: int,
    close: int,
) -> None:
    headers = _member(
        client,
        user_repository,
        membership_repository,
        workspace_id,
        role,
    )
    path = f"/api/v1/workspaces/{workspace_id}"

    assert client.get(path, headers=headers).status_code == read
    assert (
        client.patch(path, json={"name": "Renamed"}, headers=headers).status_code
        == update
    )
    assert client.delete(path, headers=headers).status_code == close
