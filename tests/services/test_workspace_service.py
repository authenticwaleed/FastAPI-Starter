"""Phase 2 acceptance: the tenant boundary, and the roles that guard it."""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import (
    InsufficientWorkspaceRoleError,
    SlugAlreadyExistsError,
    WorkspaceNotFoundError,
)
from app.models.user import User
from app.models.workspace import WorkspaceStatus
from app.models.workspace_membership import MembershipStatus, WorkspaceRole
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.workspace import WorkspaceCreate, WorkspaceUpdate
from app.services.workspace_service import WorkspaceService
from tests.support.services import audit_service


@pytest.fixture
def service(
    db_session: Session,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> WorkspaceService:
    return WorkspaceService(
        session=db_session,
        workspaces=workspace_repository,
        memberships=membership_repository,
        audit=audit_service(db_session),
    )


@pytest.fixture
def ada(db_session: Session) -> User:
    return _user(db_session, "ada@example.com")


@pytest.fixture
def alan(db_session: Session) -> User:
    return _user(db_session, "alan@example.com")


def _user(session: Session, email: str) -> User:
    user = User(name="Someone", email=email, hashed_password="not a real hash")
    session.add(user)
    session.flush()

    return user


def _payload(slug: str = "acme-fashion") -> WorkspaceCreate:
    return WorkspaceCreate(name="Acme Fashion", slug=slug)


def test_creating_a_workspace_makes_the_creator_its_owner(
    service: WorkspaceService,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
) -> None:
    workspace = service.create(_payload(), creator=ada)

    membership = membership_repository.get_for_user(workspace.id, ada.id)

    assert membership is not None
    assert membership.role == WorkspaceRole.OWNER
    assert membership.status == MembershipStatus.ACTIVE


def test_a_new_workspace_is_active_and_records_its_creator(
    service: WorkspaceService,
    ada: User,
) -> None:
    workspace = service.create(_payload(), creator=ada)

    assert workspace.status == WorkspaceStatus.ACTIVE
    assert workspace.created_by_user_id == ada.id


def test_a_duplicate_slug_is_refused(service: WorkspaceService, ada: User) -> None:
    service.create(_payload(), creator=ada)

    with pytest.raises(SlugAlreadyExistsError):
        service.create(_payload(), creator=ada)


def test_a_slug_is_taken_across_the_whole_platform(
    service: WorkspaceService,
    ada: User,
    alan: User,
) -> None:
    service.create(_payload(), creator=ada)

    with pytest.raises(SlugAlreadyExistsError):
        service.create(_payload(), creator=alan)


def test_a_cancelled_workspace_keeps_its_slug(
    service: WorkspaceService,
    ada: User,
) -> None:
    # The slug may already be in a customer's bookmarks. Handing it to
    # somebody else would let them inherit that.
    workspace = service.create(_payload(), creator=ada)
    service.cancel(service.access(workspace.id, ada))

    with pytest.raises(SlugAlreadyExistsError):
        service.create(_payload(), creator=ada)


def test_a_member_can_reach_their_own_workspace(
    service: WorkspaceService,
    ada: User,
) -> None:
    workspace = service.create(_payload(), creator=ada)

    access = service.access(workspace.id, ada)

    assert access.workspace.id == workspace.id
    assert access.role == WorkspaceRole.OWNER


def test_an_unrelated_user_cannot_reach_a_workspace(
    service: WorkspaceService,
    ada: User,
    alan: User,
) -> None:
    workspace = service.create(_payload(), creator=ada)

    with pytest.raises(WorkspaceNotFoundError):
        service.access(workspace.id, alan)


def test_a_workspace_that_does_not_exist_fails_the_same_way(
    service: WorkspaceService,
    ada: User,
    alan: User,
) -> None:
    # The point of the phase, as a test. A stranger must not be able to
    # tell "no such workspace" from "one exists and you are not in it",
    # because the difference is a way of discovering who has an account.
    workspace = service.create(_payload(), creator=ada)

    with pytest.raises(WorkspaceNotFoundError) as belonging_to_someone_else:
        service.access(workspace.id, alan)

    with pytest.raises(WorkspaceNotFoundError) as never_existed:
        service.access(uuid.uuid4(), alan)

    assert belonging_to_someone_else.value.detail == never_existed.value.detail


def test_a_removed_member_can_no_longer_reach_it(
    service: WorkspaceService,
    membership_repository: WorkspaceMembershipRepository,
    db_session: Session,
    ada: User,
    alan: User,
) -> None:
    workspace = service.create(_payload(), creator=ada)
    membership = membership_repository.create(
        workspace_id=workspace.id,
        user_id=alan.id,
        role=WorkspaceRole.AGENT,
    )

    membership.status = MembershipStatus.REMOVED
    db_session.flush()

    with pytest.raises(WorkspaceNotFoundError):
        service.access(workspace.id, alan)


def test_listing_never_crosses_into_another_business(
    service: WorkspaceService,
    ada: User,
    alan: User,
) -> None:
    mine = service.create(_payload("mine"), creator=ada)
    service.create(_payload("theirs"), creator=alan)

    workspaces, total = service.list_for(ada)

    assert [workspace.id for workspace in workspaces] == [mine.id]
    assert total == 1


# --- who may do what --------------------------------------------------------


@pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
def test_an_administrator_may_rename_the_workspace(
    service: WorkspaceService,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
    alan: User,
    role: WorkspaceRole,
) -> None:
    workspace = service.create(_payload(), creator=ada)
    membership_repository.create(
        workspace_id=workspace.id,
        user_id=alan.id,
        role=role,
    )

    updated = service.update(
        service.access(workspace.id, alan),
        WorkspaceUpdate(name="Renamed"),
    )

    assert updated.name == "Renamed"


@pytest.mark.parametrize("role", [WorkspaceRole.AGENT, WorkspaceRole.VIEWER])
def test_an_agent_or_viewer_may_not_rename_the_workspace(
    service: WorkspaceService,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
    alan: User,
    role: WorkspaceRole,
) -> None:
    workspace = service.create(_payload(), creator=ada)
    membership_repository.create(
        workspace_id=workspace.id,
        user_id=alan.id,
        role=role,
    )

    with pytest.raises(InsufficientWorkspaceRoleError):
        service.update(
            service.access(workspace.id, alan),
            WorkspaceUpdate(name="Renamed"),
        )


@pytest.mark.parametrize(
    "role",
    [WorkspaceRole.ADMIN, WorkspaceRole.AGENT, WorkspaceRole.VIEWER],
)
def test_only_an_owner_may_close_the_workspace(
    service: WorkspaceService,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
    alan: User,
    role: WorkspaceRole,
) -> None:
    workspace = service.create(_payload(), creator=ada)
    membership_repository.create(
        workspace_id=workspace.id,
        user_id=alan.id,
        role=role,
    )

    with pytest.raises(InsufficientWorkspaceRoleError):
        service.cancel(service.access(workspace.id, alan))


def test_a_refused_update_changes_nothing(
    service: WorkspaceService,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
    alan: User,
) -> None:
    workspace = service.create(_payload(), creator=ada)
    membership_repository.create(
        workspace_id=workspace.id,
        user_id=alan.id,
        role=WorkspaceRole.VIEWER,
    )

    with pytest.raises(InsufficientWorkspaceRoleError):
        service.update(
            service.access(workspace.id, alan),
            WorkspaceUpdate(name="Renamed"),
        )

    assert service.access(workspace.id, ada).workspace.name == "Acme Fashion"


# --- closing ----------------------------------------------------------------


def test_closing_a_workspace_cancels_it_rather_than_deleting_it(
    service: WorkspaceService,
    workspace_repository: WorkspaceRepository,
    ada: User,
) -> None:
    workspace = service.create(_payload(), creator=ada)

    service.cancel(service.access(workspace.id, ada))

    stored = workspace_repository.get(workspace.id)
    assert stored is not None
    assert stored.status == WorkspaceStatus.CANCELLED


def test_a_closed_workspace_is_unreachable_even_to_its_owner(
    service: WorkspaceService,
    ada: User,
) -> None:
    workspace = service.create(_payload(), creator=ada)

    service.cancel(service.access(workspace.id, ada))

    with pytest.raises(WorkspaceNotFoundError):
        service.access(workspace.id, ada)


def test_closing_one_workspace_leaves_the_others_alone(
    service: WorkspaceService,
    ada: User,
) -> None:
    doomed = service.create(_payload("doomed"), creator=ada)
    kept = service.create(_payload("kept"), creator=ada)

    service.cancel(service.access(doomed.id, ada))

    workspaces, total = service.list_for(ada)

    assert [workspace.id for workspace in workspaces] == [kept.id]
    assert total == 1
