"""Phase 4 acceptance: invitations end to end, over HTTP."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.workspace_invitation import WorkspaceInvitation
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


class Team:
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
        self.slug = slug

        self.owner_headers = _sign_up(client, f"owner-{slug}@example.com")
        self.workspace_id = client.post(
            "/api/v1/workspaces",
            json={"name": "Acme Fashion", "slug": slug},
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

    def path(self, invitation_id: str | None = None) -> str:
        base = f"/api/v1/workspaces/{self.workspace_id}/invitations"

        return base if invitation_id is None else f"{base}/{invitation_id}"

    def invite(
        self,
        email: str = "new@example.com",
        role: WorkspaceRole = AGENT,
        headers: dict[str, str] | None = None,
    ):
        return self._client.post(
            self.path(),
            json={"email": email, "role": role.value},
            headers=headers or self.owner_headers,
        )


@pytest.fixture
def team(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Team:
    return Team(client, user_repository, membership_repository)


@pytest.fixture
def rival(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Team:
    return Team(client, user_repository, membership_repository, slug="rival-store")


# --- sending ----------------------------------------------------------------


def test_inviting_returns_201_and_a_token(client: TestClient, team: Team) -> None:
    response = team.invite()

    assert response.status_code == 201

    body = response.json()
    assert body["email"] == "new@example.com"
    assert body["role"] == "agent"
    assert body["status"] == "pending"
    assert body["accepted_at"] is None
    assert body["token"]


def test_the_token_is_returned_once_and_never_again(
    client: TestClient,
    team: Team,
) -> None:
    # It is stored as a digest, so no later response could repeat it even
    # if one wanted to. This is what makes the create response the only
    # chance to put the link somewhere.
    created = team.invite().json()

    listed = client.get(team.path(), headers=team.owner_headers).json()

    assert created["token"] not in str(listed)
    assert "token" not in listed[0]


def test_an_admin_can_invite_below_their_rank(
    client: TestClient,
    team: Team,
) -> None:
    admin = team.member("admin@example.com", ADMIN)

    assert team.invite(role=VIEWER, headers=admin).status_code == 201


@pytest.mark.parametrize("role", [OWNER, ADMIN])
def test_an_admin_cannot_invite_at_or_above_their_rank(
    client: TestClient,
    team: Team,
    role: WorkspaceRole,
) -> None:
    admin = team.member("admin@example.com", ADMIN)

    response = team.invite(role=role, headers=admin)

    assert response.status_code == 403
    assert response.json()["code"] == "insufficient_workspace_role"


@pytest.mark.parametrize("role", [AGENT, VIEWER])
def test_a_member_without_administrative_rights_cannot_invite(
    client: TestClient,
    team: Team,
    role: WorkspaceRole,
) -> None:
    headers = team.member(f"{role.value}@example.com", role)

    assert team.invite(headers=headers).status_code == 403


def test_inviting_somebody_already_on_the_team_is_a_409(
    client: TestClient,
    team: Team,
) -> None:
    team.member("agent@example.com", AGENT)

    response = team.invite(email="agent@example.com")

    assert response.status_code == 409
    assert response.json()["code"] == "already_a_member"


def test_a_second_outstanding_invitation_is_a_409(
    client: TestClient,
    team: Team,
) -> None:
    team.invite()

    response = team.invite()

    assert response.status_code == 409
    assert response.json()["code"] == "invitation_already_pending"


def test_an_invalid_email_is_rejected(client: TestClient, team: Team) -> None:
    response = client.post(
        team.path(),
        json={"email": "not-an-email", "role": "agent"},
        headers=team.owner_headers,
    )

    assert response.status_code == 422


def test_an_invented_role_is_rejected(client: TestClient, team: Team) -> None:
    response = client.post(
        team.path(),
        json={"email": "new@example.com", "role": "superuser"},
        headers=team.owner_headers,
    )

    assert response.status_code == 422


# --- listing and revoking ---------------------------------------------------


def test_invitations_are_listed_for_the_workspace(
    client: TestClient,
    team: Team,
) -> None:
    team.invite(email="one@example.com")
    team.invite(email="two@example.com")

    listed = client.get(team.path(), headers=team.owner_headers).json()

    assert {row["email"] for row in listed} == {
        "one@example.com",
        "two@example.com",
    }


@pytest.mark.parametrize("role", [AGENT, VIEWER])
def test_the_invitation_list_is_not_everybodys_business(
    client: TestClient,
    team: Team,
    role: WorkspaceRole,
) -> None:
    # It is a list of the addresses of people being recruited.
    headers = team.member(f"{role.value}@example.com", role)

    assert client.get(team.path(), headers=headers).status_code == 403


def test_revoking_returns_204_and_stops_the_link_working(
    client: TestClient,
    team: Team,
) -> None:
    created = team.invite().json()

    response = client.delete(
        team.path(created["id"]),
        headers=team.owner_headers,
    )

    assert response.status_code == 204
    assert client.get(f"/api/v1/invitations/{created['token']}").status_code == 404


def test_revoking_an_unknown_invitation_is_a_404(
    client: TestClient,
    team: Team,
) -> None:
    response = client.delete(team.path(str(uuid.uuid4())), headers=team.owner_headers)

    assert response.status_code == 404
    assert response.json()["code"] == "invitation_not_found"


# --- the preview ------------------------------------------------------------


def test_the_preview_needs_no_account(client: TestClient, team: Team) -> None:
    # The person reading it may not have signed up yet, which is rather
    # the point of inviting them.
    created = team.invite(role=VIEWER).json()

    response = client.get(f"/api/v1/invitations/{created['token']}")

    assert response.status_code == 200

    body = response.json()
    assert body["workspace_name"] == "Acme Fashion"
    assert body["workspace_slug"] == "acme-fashion"
    assert body["role"] == "viewer"
    assert body["status"] == "pending"


def test_the_preview_of_an_unknown_token_is_a_404(client: TestClient) -> None:
    assert client.get("/api/v1/invitations/nothing-issued-this").status_code == 404


# --- accepting --------------------------------------------------------------


def test_accepting_joins_the_workspace(client: TestClient, team: Team) -> None:
    created = team.invite(email="new@example.com", role=ADMIN).json()
    invited = _sign_up(client, "new@example.com")

    response = client.post(
        f"/api/v1/invitations/{created['token']}/accept",
        headers=invited,
    )

    assert response.status_code == 200
    assert response.json()["id"] == team.workspace_id

    # And they are on the team, with the role the invitation offered.
    members = client.get(
        f"/api/v1/workspaces/{team.workspace_id}/members",
        headers=invited,
    ).json()
    assert "admin" in [member["role"] for member in members]


def test_a_new_member_can_immediately_use_their_role(
    client: TestClient,
    team: Team,
) -> None:
    created = team.invite(email="new@example.com", role=ADMIN).json()
    invited = _sign_up(client, "new@example.com")

    client.post(f"/api/v1/invitations/{created['token']}/accept", headers=invited)

    assert (
        client.patch(
            f"/api/v1/workspaces/{team.workspace_id}",
            json={"name": "Renamed"},
            headers=invited,
        ).status_code
        == 200
    )


def test_accepting_requires_an_account(client: TestClient, team: Team) -> None:
    created = team.invite().json()

    assert (
        client.post(f"/api/v1/invitations/{created['token']}/accept").status_code == 401
    )


def test_an_invitation_can_only_be_accepted_once(
    client: TestClient,
    team: Team,
) -> None:
    created = team.invite(email="new@example.com").json()
    invited = _sign_up(client, "new@example.com")
    path = f"/api/v1/invitations/{created['token']}/accept"

    assert client.post(path, headers=invited).status_code == 200

    second = client.post(path, headers=invited)
    assert second.status_code == 409
    assert second.json()["code"] == "invitation_already_accepted"


def test_a_forwarded_invitation_does_not_admit_whoever_received_it(
    client: TestClient,
    team: Team,
) -> None:
    created = team.invite(email="new@example.com").json()
    interloper = _sign_up(client, "interloper@example.com")

    response = client.post(
        f"/api/v1/invitations/{created['token']}/accept",
        headers=interloper,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "invitation_not_yours"


def test_an_expired_invitation_is_gone_rather_than_missing(
    client: TestClient,
    team: Team,
    db_session: Session,
) -> None:
    created = team.invite(email="new@example.com").json()
    invited = _sign_up(client, "new@example.com")

    invitation = db_session.get(WorkspaceInvitation, uuid.UUID(created["id"]))
    assert invitation is not None
    invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    response = client.post(
        f"/api/v1/invitations/{created['token']}/accept",
        headers=invited,
    )

    assert response.status_code == 410
    assert response.json()["code"] == "invitation_expired"


def test_an_expired_invitation_shows_as_expired_in_the_preview(
    client: TestClient,
    team: Team,
    db_session: Session,
) -> None:
    created = team.invite().json()

    invitation = db_session.get(WorkspaceInvitation, uuid.UUID(created["id"]))
    assert invitation is not None
    invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    body = client.get(f"/api/v1/invitations/{created['token']}").json()

    assert body["status"] == "expired"


# --- the tenant boundary ----------------------------------------------------


def test_another_business_cannot_list_or_send_your_invitations(
    client: TestClient,
    team: Team,
    rival: Team,
) -> None:
    response = client.get(team.path(), headers=rival.owner_headers)

    assert response.status_code == 404
    assert response.json()["code"] == "workspace_not_found"


def test_another_business_cannot_revoke_your_invitation(
    client: TestClient,
    team: Team,
    rival: Team,
) -> None:
    created = team.invite().json()

    # Aimed at their own workspace, with an id belonging to somebody
    # else's: the id alone must not be enough to reach it.
    response = client.delete(
        rival.path(created["id"]),
        headers=rival.owner_headers,
    )

    assert response.status_code == 404
    assert client.get(f"/api/v1/invitations/{created['token']}").status_code == 200


# --- what invitations unblock -----------------------------------------------


def test_an_owner_can_hand_over_and_then_close_their_account(
    client: TestClient,
    team: Team,
) -> None:
    # The gap Phases 2 and 3 left open: the sole owner could not delete
    # their account, and there was no way to appoint anybody else.
    created = team.invite(email="successor@example.com", role=OWNER).json()
    successor = _sign_up(client, "successor@example.com")

    client.post(f"/api/v1/invitations/{created['token']}/accept", headers=successor)

    assert (
        client.delete("/api/v1/account", headers=team.owner_headers).status_code == 204
    )
