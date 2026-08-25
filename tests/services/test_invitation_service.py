"""Phase 4 acceptance: offering a seat, and taking it exactly once."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.exceptions import (
    AlreadyAMemberError,
    InsufficientWorkspaceRoleError,
    InvitationAlreadyAcceptedError,
    InvitationExpiredError,
    InvitationNotFoundError,
    InvitationNotYoursError,
    PendingInvitationExistsError,
)
from app.core.security import hash_token
from app.models.user import User
from app.models.workspace_invitation import (
    InvitationStatus,
    WorkspaceInvitation,
)
from app.models.workspace_membership import MembershipStatus, WorkspaceRole
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_invitation_repository import (
    WorkspaceInvitationRepository,
)
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.workspace import WorkspaceCreate
from app.schemas.workspace_invitation import InvitationCreate
from app.services.invitation_service import InvitationService
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
    invitation_repository: WorkspaceInvitationRepository,
    membership_repository: WorkspaceMembershipRepository,
    workspace_repository: WorkspaceRepository,
    user_repository: UserRepository,
) -> InvitationService:
    return InvitationService(
        session=db_session,
        invitations=invitation_repository,
        memberships=membership_repository,
        workspaces=workspace_repository,
        users=user_repository,
    )


class Team:
    def __init__(
        self,
        session: Session,
        workspaces: WorkspaceService,
        memberships: WorkspaceMembershipRepository,
    ) -> None:
        self._session = session
        self._workspaces = workspaces
        self._memberships = memberships
        self._people = 0

        self.owner = self.user("owner@example.com")
        self.workspace = workspaces.create(
            WorkspaceCreate(name="Acme Fashion", slug="acme-fashion"),
            creator=self.owner,
        )

    def user(self, email: str) -> User:
        self._people += 1
        user = User(
            name=f"Person {self._people}",
            email=email,
            hashed_password="not a real hash",
        )
        self._session.add(user)
        self._session.flush()

        return user

    def member(self, email: str, role: WorkspaceRole) -> User:
        user = self.user(email)
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


def _invite(
    service: InvitationService,
    team: Team,
    actor: User | None = None,
    email: str = "new@example.com",
    role: WorkspaceRole = AGENT,
):
    return service.invite(
        team.access(actor or team.owner),
        InvitationCreate(email=email, role=role),
    )


# --- sending ----------------------------------------------------------------


def test_an_owner_can_invite_somebody(
    service: InvitationService,
    team: Team,
) -> None:
    invitation, token = _invite(service, team)

    assert invitation.email == "new@example.com"
    assert invitation.role == AGENT
    assert invitation.accepted_at is None
    assert token


def test_the_raw_token_is_never_stored(
    service: InvitationService,
    team: Team,
    db_session: Session,
) -> None:
    # The rule the plan states outright. Anyone reading this table -- a
    # backup, a support query, a leaked dump -- must not come away holding
    # a set of working invitation links.
    _, token = _invite(service, team)

    stored = db_session.scalars(select(WorkspaceInvitation)).all()
    assert [row.token_hash for row in stored] == [hash_token(token)]

    whole_table = db_session.execute(text("SELECT * FROM workspace_invitations")).all()
    assert token not in str(whole_table)


def test_an_invitation_expires_in_the_future(
    service: InvitationService,
    team: Team,
) -> None:
    invitation, _ = _invite(service, team)

    assert invitation.expires_at > datetime.now(UTC)
    assert invitation.status_at(datetime.now(UTC)) == InvitationStatus.PENDING


def test_an_email_address_is_stored_in_one_case(
    service: InvitationService,
    team: Team,
) -> None:
    invitation, _ = _invite(service, team, email="Mixed.Case@Example.COM")

    assert invitation.email == "mixed.case@example.com"


def test_an_admin_may_invite_below_their_own_rank(
    service: InvitationService,
    team: Team,
) -> None:
    admin = team.member("admin@example.com", ADMIN)

    invitation, _ = _invite(service, team, actor=admin, role=VIEWER)

    assert invitation.role == VIEWER


@pytest.mark.parametrize("role", [OWNER, ADMIN])
def test_an_admin_may_not_invite_at_or_above_their_own_rank(
    service: InvitationService,
    team: Team,
    role: WorkspaceRole,
) -> None:
    # Otherwise the rank ceiling is not a ceiling: an admin who cannot
    # promote a colleague could invite a second account instead.
    admin = team.member("admin@example.com", ADMIN)

    with pytest.raises(InsufficientWorkspaceRoleError):
        _invite(service, team, actor=admin, role=role)


def test_an_owner_may_invite_another_owner(
    service: InvitationService,
    team: Team,
) -> None:
    invitation, _ = _invite(service, team, role=OWNER)

    assert invitation.role == OWNER


def test_somebody_already_on_the_team_cannot_be_invited(
    service: InvitationService,
    team: Team,
) -> None:
    team.member("agent@example.com", AGENT)

    with pytest.raises(AlreadyAMemberError):
        _invite(service, team, email="agent@example.com")


def test_a_second_invitation_to_the_same_address_is_refused(
    service: InvitationService,
    team: Team,
) -> None:
    _invite(service, team)

    with pytest.raises(PendingInvitationExistsError):
        _invite(service, team)


def test_revoking_frees_the_address_to_be_invited_again(
    service: InvitationService,
    team: Team,
) -> None:
    invitation, _ = _invite(service, team)

    service.revoke(team.access(team.owner), invitation.id)

    assert _invite(service, team)[0].id != invitation.id


def test_a_revoked_invitation_stops_working(
    service: InvitationService,
    team: Team,
) -> None:
    invitation, token = _invite(service, team)

    service.revoke(team.access(team.owner), invitation.id)

    with pytest.raises(InvitationNotFoundError):
        service.preview(token)


def test_an_invitation_belonging_to_another_workspace_cannot_be_revoked(
    service: InvitationService,
    workspaces: WorkspaceService,
    team: Team,
    db_session: Session,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    invitation, _ = _invite(service, team)

    rival_owner = team.user("rival@example.com")
    rival = workspaces.create(
        WorkspaceCreate(name="Rival", slug="rival-store"),
        creator=rival_owner,
    )

    with pytest.raises(InvitationNotFoundError):
        service.revoke(
            workspaces.access(rival.id, rival_owner),
            invitation.id,
        )


# --- receiving --------------------------------------------------------------


def test_the_preview_names_the_workspace_and_the_role(
    service: InvitationService,
    team: Team,
) -> None:
    _, token = _invite(service, team, role=VIEWER)

    invitation, workspace = service.preview(token)

    assert workspace.slug == "acme-fashion"
    assert invitation.role == VIEWER


def test_an_unknown_token_is_not_found(service: InvitationService) -> None:
    with pytest.raises(InvitationNotFoundError):
        service.preview("not a token anybody issued")


def test_accepting_creates_the_membership_the_invitation_offered(
    service: InvitationService,
    team: Team,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    _, token = _invite(service, team, email="new@example.com", role=ADMIN)
    invited = team.user("new@example.com")

    membership, workspace = service.accept(token, invited)

    assert workspace.id == team.workspace.id
    assert membership.role == ADMIN
    assert membership.status == MembershipStatus.ACTIVE
    assert membership_repository.get_for_user(team.workspace.id, invited.id)


def test_an_invitation_can_only_be_accepted_once(
    service: InvitationService,
    team: Team,
) -> None:
    _, token = _invite(service, team)
    invited = team.user("new@example.com")

    service.accept(token, invited)

    with pytest.raises(InvitationAlreadyAcceptedError):
        service.accept(token, invited)


def test_accepting_marks_the_invitation_used(
    service: InvitationService,
    team: Team,
) -> None:
    invitation, token = _invite(service, team)
    invited = team.user("new@example.com")

    service.accept(token, invited)

    assert invitation.accepted_at is not None
    assert invitation.status_at(datetime.now(UTC)) == InvitationStatus.ACCEPTED


def test_an_expired_invitation_is_refused(
    service: InvitationService,
    team: Team,
    db_session: Session,
) -> None:
    invitation, token = _invite(service, team)
    invited = team.user("new@example.com")

    invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    with pytest.raises(InvitationExpiredError):
        service.accept(token, invited)


def test_an_expired_invitation_says_so_rather_than_hiding(
    service: InvitationService,
    team: Team,
    db_session: Session,
) -> None:
    # The holder had a valid link, so there is nothing to protect by
    # pretending it never existed -- and "ask for another" is a different
    # thing to tell somebody than "check the address".
    invitation, token = _invite(service, team)

    invitation.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    found, _ = service.preview(token)
    assert found.status_at(datetime.now(UTC)) == InvitationStatus.EXPIRED


def test_an_invitation_only_admits_the_address_it_names(
    service: InvitationService,
    team: Team,
) -> None:
    _, token = _invite(service, team, email="new@example.com")
    somebody_else = team.user("interloper@example.com")

    with pytest.raises(InvitationNotYoursError):
        service.accept(token, somebody_else)


def test_the_address_match_ignores_case(
    service: InvitationService,
    team: Team,
) -> None:
    _, token = _invite(service, team, email="new@example.com")
    invited = team.user("New@Example.com")

    membership, _ = service.accept(token, invited)

    assert membership.user_id == invited.id


def test_accepting_twice_over_cannot_produce_two_memberships(
    service: InvitationService,
    team: Team,
) -> None:
    _, first = _invite(service, team, email="new@example.com")
    invited = team.user("new@example.com")
    service.accept(first, invited)

    # A second, separate invitation to somebody already on the team.
    with pytest.raises(AlreadyAMemberError):
        _invite(service, team, email="new@example.com")


def test_a_returning_member_gets_their_row_back_rather_than_a_second(
    service: InvitationService,
    team: Team,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    # One membership per person per workspace is a database constraint, so
    # coming back has to restore the row rather than insert beside it.
    _, token = _invite(service, team, email="new@example.com", role=AGENT)
    invited = team.user("new@example.com")
    membership, _ = service.accept(token, invited)

    membership_repository.set_status(membership, MembershipStatus.REMOVED)

    _, again = _invite(service, team, email="new@example.com", role=VIEWER)
    restored, _ = service.accept(again, invited)

    assert restored.id == membership.id
    assert restored.role == VIEWER
    assert restored.status == MembershipStatus.ACTIVE


def test_an_invitation_to_a_closed_workspace_stops_working(
    service: InvitationService,
    workspaces: WorkspaceService,
    team: Team,
) -> None:
    _, token = _invite(service, team)
    invited = team.user("new@example.com")

    workspaces.cancel(team.access(team.owner))

    with pytest.raises(InvitationNotFoundError):
        service.accept(token, invited)


def test_an_invitation_is_listed_for_its_own_workspace_only(
    service: InvitationService,
    workspaces: WorkspaceService,
    team: Team,
) -> None:
    _invite(service, team)

    rival_owner = team.user("rival@example.com")
    rival = workspaces.create(
        WorkspaceCreate(name="Rival", slug="rival-store"),
        creator=rival_owner,
    )

    assert len(service.list_for(team.access(team.owner))) == 1
    assert service.list_for(workspaces.access(rival.id, rival_owner)) == []
