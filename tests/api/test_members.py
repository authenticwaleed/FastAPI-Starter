"""Phase 3 acceptance: role-gated endpoints, declared by dependency."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.models.workspace_membership import WorkspaceRole
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)

PASSWORD = "correct horse battery staple"

OWNER = WorkspaceRole.OWNER
ADMIN = WorkspaceRole.ADMIN
AGENT = WorkspaceRole.AGENT
VIEWER = WorkspaceRole.VIEWER


class Team:
    """A workspace over HTTP, plus a way to put people in it.

    Members are written directly because there is no invitation endpoint
    yet -- that is the next phase. Everything else here goes through the
    API, so what is being tested is the API.
    """

    def __init__(
        self,
        client: TestClient,
        users: UserRepository,
        memberships: WorkspaceMembershipRepository,
        slug: str = "acme-fashion",
    ) -> None:
        self._client = client
        self._users = users
        self._memberships = memberships
        self._people = 0

        self.owner_headers, self.owner_id = self._person()
        self.workspace_id = client.post(
            "/api/v1/workspaces",
            json={"name": "Acme Fashion", "slug": slug},
            headers=self.owner_headers,
        ).json()["id"]

    def _person(self) -> tuple[dict[str, str], int]:
        self._people += 1
        email = f"{self._people}-{id(self)}@example.com"

        self._client.post(
            "/api/v1/auth/register",
            json={"name": "Someone", "email": email, "password": PASSWORD},
        )
        token = self._client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": PASSWORD},
        ).json()["access_token"]

        user = self._users.get_by_email(email)
        assert user is not None

        return {"Authorization": f"Bearer {token}"}, user.id

    def member(self, role: WorkspaceRole) -> tuple[dict[str, str], int]:
        headers, user_id = self._person()
        self._memberships.create(
            workspace_id=uuid.UUID(self.workspace_id),
            user_id=user_id,
            role=role,
        )

        return headers, user_id

    def path(self, user_id: int | None = None) -> str:
        base = f"/api/v1/workspaces/{self.workspace_id}/members"

        return base if user_id is None else f"{base}/{user_id}"


def _role_of(client: TestClient, team: "Team", user_id: int) -> str:
    """Look a member up by who they are, not by where they sit in the list."""
    members = client.get(team.path(), headers=team.owner_headers).json()

    return next(member["role"] for member in members if member["user_id"] == user_id)


@pytest.fixture
def team(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Team:
    return Team(client, user_repository, membership_repository)


@pytest.fixture
def other_team(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Team:
    return Team(client, user_repository, membership_repository, slug="rival-store")


# --- listing the team -------------------------------------------------------


def test_a_new_workspace_has_exactly_one_member(
    client: TestClient,
    team: Team,
) -> None:
    response = client.get(team.path(), headers=team.owner_headers)

    assert response.status_code == 200

    body = response.json()
    assert len(body) == 1
    assert body[0]["user_id"] == team.owner_id
    assert body[0]["role"] == "owner"
    assert body[0]["status"] == "active"


def test_the_team_list_carries_names_and_addresses(
    client: TestClient,
    team: Team,
) -> None:
    # A team list of bare user ids would force the client into a second
    # request per row just to render one screen.
    body = client.get(team.path(), headers=team.owner_headers).json()

    assert body[0]["name"] == "Someone"
    assert "@example.com" in body[0]["email"]


def test_the_team_list_never_carries_a_password_or_its_hash(
    client: TestClient,
    team: Team,
    user_repository: UserRepository,
) -> None:
    response = client.get(team.path(), headers=team.owner_headers)

    owner = user_repository.get(team.owner_id)
    assert owner is not None
    assert PASSWORD not in response.text
    assert owner.hashed_password not in response.text


@pytest.mark.parametrize("role", [OWNER, ADMIN, AGENT, VIEWER])
def test_every_member_may_see_who_they_work_with(
    client: TestClient,
    team: Team,
    role: WorkspaceRole,
) -> None:
    headers, _ = team.member(role)

    assert client.get(team.path(), headers=headers).status_code == 200


# --- changing a role --------------------------------------------------------


def test_an_owner_can_change_a_role(client: TestClient, team: Team) -> None:
    _, agent_id = team.member(AGENT)

    response = client.patch(
        team.path(agent_id),
        json={"role": "admin"},
        headers=team.owner_headers,
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert response.json()["user_id"] == agent_id


def test_a_changed_role_takes_effect_immediately(
    client: TestClient,
    team: Team,
) -> None:
    viewer_headers, viewer_id = team.member(VIEWER)

    assert (
        client.patch(
            f"/api/v1/workspaces/{team.workspace_id}",
            json={"name": "Renamed"},
            headers=viewer_headers,
        ).status_code
        == 403
    )

    client.patch(
        team.path(viewer_id),
        json={"role": "admin"},
        headers=team.owner_headers,
    )

    assert (
        client.patch(
            f"/api/v1/workspaces/{team.workspace_id}",
            json={"name": "Renamed"},
            headers=viewer_headers,
        ).status_code
        == 200
    )


@pytest.mark.parametrize("role", [AGENT, VIEWER])
def test_a_member_without_administrative_rights_cannot_change_roles(
    client: TestClient,
    team: Team,
    role: WorkspaceRole,
) -> None:
    headers, _ = team.member(role)
    _, target_id = team.member(VIEWER)

    response = client.patch(
        team.path(target_id),
        json={"role": "admin"},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "insufficient_workspace_role"


def test_an_admin_cannot_promote_anyone_to_their_own_rank(
    client: TestClient,
    team: Team,
) -> None:
    admin_headers, _ = team.member(ADMIN)
    _, agent_id = team.member(AGENT)

    response = client.patch(
        team.path(agent_id),
        json={"role": "admin"},
        headers=admin_headers,
    )

    assert response.status_code == 403


def test_an_admin_cannot_demote_the_owner(client: TestClient, team: Team) -> None:
    admin_headers, _ = team.member(ADMIN)

    response = client.patch(
        team.path(team.owner_id),
        json={"role": "viewer"},
        headers=admin_headers,
    )

    assert response.status_code == 403
    assert (
        client.get(team.path(), headers=team.owner_headers).json()[0]["role"] == "owner"
    )


def test_the_last_owner_cannot_be_demoted(client: TestClient, team: Team) -> None:
    response = client.patch(
        team.path(team.owner_id),
        json={"role": "admin"},
        headers=team.owner_headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "last_owner"


def test_an_invented_role_is_rejected(client: TestClient, team: Team) -> None:
    _, agent_id = team.member(AGENT)

    response = client.patch(
        team.path(agent_id),
        json={"role": "superuser"},
        headers=team.owner_headers,
    )

    assert response.status_code == 422


def test_changing_the_role_of_someone_who_is_not_a_member_is_a_404(
    client: TestClient,
    team: Team,
) -> None:
    response = client.patch(
        team.path(999_999),
        json={"role": "admin"},
        headers=team.owner_headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "membership_not_found"


# --- removing ---------------------------------------------------------------


def test_an_owner_can_remove_a_member(client: TestClient, team: Team) -> None:
    agent_headers, agent_id = team.member(AGENT)

    response = client.delete(team.path(agent_id), headers=team.owner_headers)

    assert response.status_code == 204
    assert not response.content

    remaining = client.get(team.path(), headers=team.owner_headers).json()
    assert agent_id not in [member["user_id"] for member in remaining]
    # And the workspace is closed to them from that moment.
    assert (
        client.get(
            f"/api/v1/workspaces/{team.workspace_id}", headers=agent_headers
        ).status_code
        == 404
    )


def test_an_admin_cannot_remove_the_owner(client: TestClient, team: Team) -> None:
    admin_headers, _ = team.member(ADMIN)

    response = client.delete(team.path(team.owner_id), headers=admin_headers)

    assert response.status_code == 403
    assert (
        client.get(
            f"/api/v1/workspaces/{team.workspace_id}", headers=team.owner_headers
        ).status_code
        == 200
    )


def test_an_agent_cannot_remove_a_viewer(client: TestClient, team: Team) -> None:
    agent_headers, _ = team.member(AGENT)
    _, viewer_id = team.member(VIEWER)

    assert client.delete(team.path(viewer_id), headers=agent_headers).status_code == 403


@pytest.mark.parametrize("role", [ADMIN, AGENT, VIEWER])
def test_any_member_may_leave(
    client: TestClient,
    team: Team,
    role: WorkspaceRole,
) -> None:
    headers, user_id = team.member(role)

    assert client.delete(team.path(user_id), headers=headers).status_code == 204
    assert (
        client.get(
            f"/api/v1/workspaces/{team.workspace_id}", headers=headers
        ).status_code
        == 404
    )


def test_the_last_owner_cannot_walk_out(client: TestClient, team: Team) -> None:
    response = client.delete(team.path(team.owner_id), headers=team.owner_headers)

    assert response.status_code == 409
    assert response.json()["code"] == "last_owner"


def test_an_owner_can_leave_once_there_is_another(
    client: TestClient,
    team: Team,
) -> None:
    successor_headers, _ = team.member(OWNER)

    assert (
        client.delete(team.path(team.owner_id), headers=team.owner_headers).status_code
        == 204
    )
    assert len(client.get(team.path(), headers=successor_headers).json()) == 1


# --- the tenant boundary ----------------------------------------------------


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_the_member_endpoints_require_a_token(
    client: TestClient,
    team: Team,
    method: str,
) -> None:
    path = team.path() if method == "get" else team.path(team.owner_id)

    assert client.request(method, path, json={"role": "viewer"}).status_code == 401


@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_another_business_cannot_see_or_touch_your_team(
    client: TestClient,
    team: Team,
    other_team: Team,
    method: str,
) -> None:
    path = team.path() if method == "get" else team.path(team.owner_id)

    response = client.request(
        method,
        path,
        json={"role": "viewer"},
        headers=other_team.owner_headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "workspace_not_found"


def test_a_member_of_another_workspace_is_not_a_member_of_this_one(
    client: TestClient,
    team: Team,
    other_team: Team,
) -> None:
    # The subtle one. The target holds a real, active membership -- of a
    # different business. Looking them up by user id alone would edit the
    # wrong workspace's row.
    response = client.patch(
        team.path(other_team.owner_id),
        json={"role": "viewer"},
        headers=team.owner_headers,
    )

    assert response.status_code == 404
    assert response.json()["code"] == "membership_not_found"


def test_a_refused_cross_tenant_change_leaves_the_other_team_alone(
    client: TestClient,
    team: Team,
    other_team: Team,
) -> None:
    client.patch(
        team.path(other_team.owner_id),
        json={"role": "viewer"},
        headers=team.owner_headers,
    )

    assert _role_of(client, other_team, other_team.owner_id) == "owner"
