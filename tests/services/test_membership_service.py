"""Phase 3 acceptance: rank, and the last owner."""

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import (
    InsufficientWorkspaceRoleError,
    LastOwnerError,
    MembershipNotFoundError,
    WorkspaceNotFoundError,
)
from app.models.user import User
from app.models.workspace_membership import (
    MembershipStatus,
    WorkspaceRole,
    outranks,
)
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.workspace import WorkspaceCreate
from app.services.membership_service import MembershipService, may_manage
from app.services.workspace_service import WorkspaceService

OWNER = WorkspaceRole.OWNER
ADMIN = WorkspaceRole.ADMIN
AGENT = WorkspaceRole.AGENT
VIEWER = WorkspaceRole.VIEWER


@pytest.fixture
def workspaces(
    db_session: Session,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> WorkspaceService:
    return WorkspaceService(
        session=db_session,
        workspaces=workspace_repository,
        memberships=membership_repository,
    )


@pytest.fixture
def service(
    db_session: Session,
    membership_repository: WorkspaceMembershipRepository,
) -> MembershipService:
    return MembershipService(
        session=db_session,
        memberships=membership_repository,
    )


class Team:
    """A workspace with one owner, plus whoever a test needs in it."""

    def __init__(
        self,
        session: Session,
        workspaces: WorkspaceService,
        memberships: WorkspaceMembershipRepository,
    ) -> None:
        self._session = session
        self._workspaces = workspaces
        self._memberships = memberships
        self._users = 0

        self.owner = self.user()
        self.workspace = workspaces.create(
            WorkspaceCreate(name="Acme Fashion", slug="acme-fashion"),
            creator=self.owner,
        )

    def user(self) -> User:
        self._users += 1
        user = User(
            name=f"Person {self._users}",
            email=f"person{self._users}@example.com",
            hashed_password="not a real hash",
        )
        self._session.add(user)
        self._session.flush()

        return user

    def member(self, role: WorkspaceRole) -> User:
        user = self.user()
        self._memberships.create(
            workspace_id=self.workspace.id,
            user_id=user.id,
            role=role,
        )

        return user

    def access(self, user: User):
        return self._workspaces.access(self.workspace.id, user)


@pytest.fixture
def team(
    db_session: Session,
    workspaces: WorkspaceService,
    membership_repository: WorkspaceMembershipRepository,
) -> Team:
    return Team(db_session, workspaces, membership_repository)


# --- the rule itself --------------------------------------------------------


@pytest.mark.parametrize(
    ("actor", "target", "permitted"),
    [
        (OWNER, OWNER, True),
        (OWNER, ADMIN, True),
        (OWNER, AGENT, True),
        (OWNER, VIEWER, True),
        (ADMIN, OWNER, False),
        (ADMIN, ADMIN, False),
        (ADMIN, AGENT, True),
        (ADMIN, VIEWER, True),
        (AGENT, ADMIN, False),
        (AGENT, AGENT, False),
        (VIEWER, VIEWER, False),
    ],
)
def test_who_may_act_on_whom(
    actor: WorkspaceRole,
    target: WorkspaceRole,
    permitted: bool,
) -> None:
    # The plan's "owner manages admins, admin manages agents", as one rule
    # in one place rather than a table of who may touch whom.
    assert may_manage(actor, target) is permitted


def test_rank_is_strict(_unused: None = None) -> None:
    assert outranks(OWNER, ADMIN)
    assert outranks(ADMIN, AGENT)
    assert outranks(AGENT, VIEWER)
    assert not outranks(ADMIN, ADMIN)
    assert not outranks(VIEWER, OWNER)


# --- changing a role --------------------------------------------------------


def test_an_owner_can_promote_an_agent_to_admin(
    service: MembershipService,
    team: Team,
) -> None:
    agent = team.member(AGENT)

    membership, user = service.change_role(team.access(team.owner), agent.id, ADMIN)

    assert membership.role == ADMIN
    assert user.id == agent.id


def test_an_admin_can_manage_an_agent(
    service: MembershipService,
    team: Team,
) -> None:
    admin = team.member(ADMIN)
    agent = team.member(AGENT)

    membership, _ = service.change_role(team.access(admin), agent.id, VIEWER)

    assert membership.role == VIEWER


def test_an_admin_cannot_promote_anyone_to_their_own_rank(
    service: MembershipService,
    team: Team,
) -> None:
    # Otherwise `admin` reaches `owner` in two moves: make an ally an
    # admin, have them make you an owner.
    admin = team.member(ADMIN)
    agent = team.member(AGENT)

    with pytest.raises(InsufficientWorkspaceRoleError):
        service.change_role(team.access(admin), agent.id, ADMIN)


def test_an_admin_cannot_promote_anyone_to_owner(
    service: MembershipService,
    team: Team,
) -> None:
    admin = team.member(ADMIN)
    agent = team.member(AGENT)

    with pytest.raises(InsufficientWorkspaceRoleError):
        service.change_role(team.access(admin), agent.id, OWNER)


def test_an_admin_cannot_demote_an_owner(
    service: MembershipService,
    team: Team,
) -> None:
    admin = team.member(ADMIN)

    with pytest.raises(InsufficientWorkspaceRoleError):
        service.change_role(team.access(admin), team.owner.id, VIEWER)


def test_an_admin_cannot_demote_another_admin(
    service: MembershipService,
    team: Team,
) -> None:
    admin = team.member(ADMIN)
    colleague = team.member(ADMIN)

    with pytest.raises(InsufficientWorkspaceRoleError):
        service.change_role(team.access(admin), colleague.id, AGENT)


def test_the_last_owner_cannot_be_demoted(
    service: MembershipService,
    team: Team,
) -> None:
    with pytest.raises(LastOwnerError):
        service.change_role(team.access(team.owner), team.owner.id, ADMIN)


def test_an_owner_can_step_down_once_there_is_another(
    service: MembershipService,
    team: Team,
) -> None:
    successor = team.member(OWNER)

    membership, _ = service.change_role(
        team.access(successor),
        team.owner.id,
        ADMIN,
    )

    assert membership.role == ADMIN


def test_setting_the_role_somebody_already_has_is_a_no_op(
    service: MembershipService,
    team: Team,
) -> None:
    # Notably including the last owner: this must not trip the last-owner
    # rule, because nothing is actually changing.
    membership, _ = service.change_role(
        team.access(team.owner),
        team.owner.id,
        OWNER,
    )

    assert membership.role == OWNER


def test_a_stranger_is_not_a_member(
    service: MembershipService,
    team: Team,
) -> None:
    stranger = team.user()

    with pytest.raises(MembershipNotFoundError):
        service.change_role(team.access(team.owner), stranger.id, AGENT)


def test_a_removed_member_is_no_longer_a_member(
    service: MembershipService,
    team: Team,
) -> None:
    agent = team.member(AGENT)
    service.remove(team.access(team.owner), agent.id)

    with pytest.raises(MembershipNotFoundError):
        service.change_role(team.access(team.owner), agent.id, ADMIN)


# --- removing ---------------------------------------------------------------


def test_an_owner_can_remove_an_agent(
    service: MembershipService,
    team: Team,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    agent = team.member(AGENT)

    service.remove(team.access(team.owner), agent.id)

    membership = membership_repository.get_for_user(team.workspace.id, agent.id)
    assert membership is not None
    assert membership.status == MembershipStatus.REMOVED


def test_an_admin_cannot_remove_an_owner(
    service: MembershipService,
    team: Team,
) -> None:
    admin = team.member(ADMIN)

    with pytest.raises(InsufficientWorkspaceRoleError):
        service.remove(team.access(admin), team.owner.id)


def test_an_admin_cannot_remove_another_admin(
    service: MembershipService,
    team: Team,
) -> None:
    admin = team.member(ADMIN)
    colleague = team.member(ADMIN)

    with pytest.raises(InsufficientWorkspaceRoleError):
        service.remove(team.access(admin), colleague.id)


def test_an_agent_cannot_remove_a_viewer(
    service: MembershipService,
    team: Team,
) -> None:
    # Rank alone is not enough: removing somebody is administration, and
    # an agent does not administer anything.
    agent = team.member(AGENT)
    viewer = team.member(VIEWER)

    with pytest.raises(InsufficientWorkspaceRoleError):
        service.remove(team.access(agent), viewer.id)


def test_anyone_may_leave_a_workspace_themselves(
    service: MembershipService,
    team: Team,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    viewer = team.member(VIEWER)

    service.remove(team.access(viewer), viewer.id)

    membership = membership_repository.get_for_user(team.workspace.id, viewer.id)
    assert membership is not None
    assert membership.status == MembershipStatus.REMOVED


def test_the_last_owner_cannot_walk_out(
    service: MembershipService,
    team: Team,
) -> None:
    with pytest.raises(LastOwnerError):
        service.remove(team.access(team.owner), team.owner.id)


def test_an_owner_can_leave_once_there_is_another(
    service: MembershipService,
    team: Team,
) -> None:
    successor = team.member(OWNER)

    service.remove(team.access(team.owner), team.owner.id)

    # Asked as the successor, because having left, the former owner can no
    # longer reach the workspace to ask anything about it.
    remaining = service.list_members(team.access(successor))
    assert [user.id for _, user in remaining] == [successor.id]


def test_leaving_a_workspace_closes_the_door_behind_you(
    service: MembershipService,
    workspaces: WorkspaceService,
    team: Team,
) -> None:
    agent = team.member(AGENT)

    service.remove(team.access(agent), agent.id)

    with pytest.raises(WorkspaceNotFoundError):
        workspaces.access(team.workspace.id, agent)


def test_a_removed_member_leaves_the_team_list(
    service: MembershipService,
    team: Team,
) -> None:
    agent = team.member(AGENT)

    service.remove(team.access(team.owner), agent.id)

    members = service.list_members(team.access(team.owner))
    assert agent.id not in [user.id for _, user in members]


def test_the_team_list_shows_everyone_with_their_role(
    service: MembershipService,
    team: Team,
) -> None:
    admin = team.member(ADMIN)
    viewer = team.member(VIEWER)

    members = service.list_members(team.access(viewer))

    assert {user.id: membership.role for membership, user in members} == {
        team.owner.id: OWNER,
        admin.id: ADMIN,
        viewer.id: VIEWER,
    }
