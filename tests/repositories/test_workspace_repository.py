"""Phase 2 acceptance: tenant queries, and the isolation they enforce."""

import pytest
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.workspace import WorkspaceStatus
from app.models.workspace_membership import (
    MembershipStatus,
    WorkspaceRole,
)
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository


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


def _workspace(
    workspaces: WorkspaceRepository,
    memberships: WorkspaceMembershipRepository,
    owner: User,
    slug: str = "acme-fashion",
):
    workspace = workspaces.create(
        name="Acme Fashion",
        slug=slug,
        timezone="UTC",
        default_currency="USD",
        created_by_user_id=owner.id,
    )
    memberships.create(
        workspace_id=workspace.id,
        user_id=owner.id,
        role=WorkspaceRole.OWNER,
    )

    return workspace


def test_a_created_workspace_can_be_read_back(
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
) -> None:
    workspace = _workspace(workspace_repository, membership_repository, ada)

    assert workspace_repository.get(workspace.id) is workspace
    assert workspace_repository.get_by_slug("acme-fashion") is workspace


def test_listing_returns_only_the_users_own_workspaces(
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
    alan: User,
) -> None:
    # The isolation rule, at the layer that enforces it: the join to
    # memberships is what makes another business unreachable, not a filter
    # somebody remembers to apply upstream.
    mine = _workspace(workspace_repository, membership_repository, ada, "mine")
    _workspace(workspace_repository, membership_repository, alan, "theirs")

    listed = workspace_repository.list_for_user(ada.id, limit=20, offset=0)

    assert [workspace.id for workspace in listed] == [mine.id]
    assert workspace_repository.count_for_user(ada.id) == 1


def test_a_user_with_no_workspaces_sees_none(
    workspace_repository: WorkspaceRepository,
    ada: User,
) -> None:
    assert workspace_repository.list_for_user(ada.id, limit=20, offset=0) == []
    assert workspace_repository.count_for_user(ada.id) == 0


def test_a_user_can_belong_to_several_workspaces(
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
) -> None:
    _workspace(workspace_repository, membership_repository, ada, "first-store")
    _workspace(workspace_repository, membership_repository, ada, "second-store")

    assert workspace_repository.count_for_user(ada.id) == 2


def test_a_member_who_is_not_the_owner_still_sees_the_workspace(
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
    alan: User,
) -> None:
    workspace = _workspace(workspace_repository, membership_repository, ada)
    membership_repository.create(
        workspace_id=workspace.id,
        user_id=alan.id,
        role=WorkspaceRole.VIEWER,
    )

    assert workspace_repository.count_for_user(alan.id) == 1


def test_a_cancelled_workspace_leaves_the_listing(
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
) -> None:
    workspace = _workspace(workspace_repository, membership_repository, ada)

    workspace_repository.set_status(workspace, WorkspaceStatus.CANCELLED)

    assert workspace_repository.list_for_user(ada.id, limit=20, offset=0) == []
    assert workspace_repository.count_for_user(ada.id) == 0


def test_a_cancelled_workspace_is_still_there(
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
) -> None:
    # Cancelling is not deleting. The rows survive so support can undo it.
    workspace = _workspace(workspace_repository, membership_repository, ada)

    workspace_repository.set_status(workspace, WorkspaceStatus.CANCELLED)

    assert workspace_repository.get(workspace.id) is not None
    assert membership_repository.list_for_workspace(workspace.id)


def test_a_removed_member_stops_seeing_the_workspace(
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
    alan: User,
    db_session: Session,
) -> None:
    workspace = _workspace(workspace_repository, membership_repository, ada)
    membership = membership_repository.create(
        workspace_id=workspace.id,
        user_id=alan.id,
        role=WorkspaceRole.AGENT,
    )

    membership.status = MembershipStatus.REMOVED
    db_session.flush()

    assert workspace_repository.count_for_user(alan.id) == 0
    assert workspace_repository.count_for_user(ada.id) == 1


def test_listing_is_paginated_and_deterministic(
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
) -> None:
    # Every row here shares one created_at, because now() is fixed for the
    # transaction. Without the id as a tiebreak the two pages could overlap.
    for index in range(5):
        _workspace(workspace_repository, membership_repository, ada, f"store-{index}")

    first = workspace_repository.list_for_user(ada.id, limit=2, offset=0)
    second = workspace_repository.list_for_user(ada.id, limit=2, offset=2)

    assert len(first) == len(second) == 2
    assert not {workspace.id for workspace in first} & {
        workspace.id for workspace in second
    }
    assert workspace_repository.list_for_user(ada.id, limit=2, offset=0) == first


def test_update_changes_only_what_was_supplied(
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
) -> None:
    workspace = _workspace(workspace_repository, membership_repository, ada)

    workspace_repository.update(workspace, name="Renamed")

    assert workspace.name == "Renamed"
    assert workspace.slug == "acme-fashion"
    assert workspace.timezone == "UTC"


def test_a_membership_is_found_for_its_own_user_only(
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
    alan: User,
) -> None:
    workspace = _workspace(workspace_repository, membership_repository, ada)

    assert membership_repository.get_for_user(workspace.id, ada.id) is not None
    assert membership_repository.get_for_user(workspace.id, alan.id) is None


def test_the_only_owner_is_reported_as_such(
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
) -> None:
    workspace = _workspace(workspace_repository, membership_repository, ada)

    assert membership_repository.sole_owned_workspace_ids(ada.id) == [workspace.id]


def test_a_second_owner_means_neither_is_the_only_one(
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
    alan: User,
) -> None:
    workspace = _workspace(workspace_repository, membership_repository, ada)
    membership_repository.create(
        workspace_id=workspace.id,
        user_id=alan.id,
        role=WorkspaceRole.OWNER,
    )

    assert membership_repository.sole_owned_workspace_ids(ada.id) == []
    assert membership_repository.sole_owned_workspace_ids(alan.id) == []


def test_an_admin_does_not_count_as_an_owner(
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
    alan: User,
) -> None:
    workspace = _workspace(workspace_repository, membership_repository, ada)
    membership_repository.create(
        workspace_id=workspace.id,
        user_id=alan.id,
        role=WorkspaceRole.ADMIN,
    )

    assert membership_repository.sole_owned_workspace_ids(ada.id) == [workspace.id]
    assert membership_repository.sole_owned_workspace_ids(alan.id) == []


def test_a_cancelled_workspace_no_longer_needs_an_owner(
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    ada: User,
) -> None:
    workspace = _workspace(workspace_repository, membership_repository, ada)

    workspace_repository.set_status(workspace, WorkspaceStatus.CANCELLED)

    assert membership_repository.sole_owned_workspace_ids(ada.id) == []
