"""Phase 2 acceptance: the tenant tables, and what the database enforces."""

import uuid

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.workspace import Workspace, WorkspaceStatus
from app.models.workspace_membership import (
    MembershipStatus,
    WorkspaceMembership,
    WorkspaceRole,
)


@pytest.fixture
def user(db_session: Session) -> User:
    user = User(
        name="Ada Lovelace",
        email="ada@example.com",
        hashed_password="not a real hash",
    )
    db_session.add(user)
    db_session.flush()

    return user


def _workspace(user: User, slug: str = "acme-fashion") -> Workspace:
    return Workspace(
        name="Acme Fashion",
        slug=slug,
        created_by_user_id=user.id,
    )


def test_a_workspace_gets_a_uuid_primary_key(
    db_session: Session,
    user: User,
) -> None:
    workspace = _workspace(user)
    db_session.add(workspace)
    db_session.flush()

    assert isinstance(workspace.id, uuid.UUID)


def test_two_workspaces_do_not_get_guessable_neighbouring_ids(
    db_session: Session,
    user: User,
) -> None:
    # The reason for the UUID: a sequential id in a URL would say how many
    # businesses exist and let anyone walk the range.
    first = _workspace(user, slug="first-store")
    second = _workspace(user, slug="second-store")
    db_session.add_all([first, second])
    db_session.flush()

    assert first.id != second.id


def test_a_new_workspace_is_active(db_session: Session, user: User) -> None:
    workspace = _workspace(user)
    db_session.add(workspace)
    db_session.flush()
    db_session.refresh(workspace)

    assert workspace.status == WorkspaceStatus.ACTIVE


def test_a_workspace_defaults_to_utc_and_usd(
    db_session: Session,
    user: User,
) -> None:
    workspace = _workspace(user)
    db_session.add(workspace)
    db_session.flush()
    db_session.refresh(workspace)

    assert workspace.timezone == "UTC"
    assert workspace.default_currency == "USD"


def test_the_slug_is_unique(db_session: Session, user: User) -> None:
    db_session.add(_workspace(user))
    db_session.flush()

    db_session.add(_workspace(user))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_the_database_refuses_an_invented_status(
    db_session: Session,
    user: User,
) -> None:
    # The status vocabulary is a CHECK constraint, not just a Python enum,
    # so a statement issued outside the ORM cannot introduce a fourth one.
    workspace = _workspace(user)
    workspace.status = "deleted"  # type: ignore[assignment]
    db_session.add(workspace)

    with pytest.raises((IntegrityError, DBAPIError)):
        db_session.flush()


def test_the_database_refuses_an_invented_role(
    db_session: Session,
    user: User,
) -> None:
    workspace = _workspace(user)
    db_session.add(workspace)
    db_session.flush()

    db_session.add(
        WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=user.id,
            role="superuser",  # type: ignore[arg-type]
        )
    )

    with pytest.raises((IntegrityError, DBAPIError)):
        db_session.flush()


def test_a_user_cannot_hold_two_memberships_of_one_workspace(
    db_session: Session,
    user: User,
) -> None:
    workspace = _workspace(user)
    db_session.add(workspace)
    db_session.flush()

    db_session.add(
        WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=user.id,
            role=WorkspaceRole.OWNER,
        )
    )
    db_session.flush()

    db_session.add(
        WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=user.id,
            role=WorkspaceRole.VIEWER,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_new_membership_is_active(db_session: Session, user: User) -> None:
    workspace = _workspace(user)
    db_session.add(workspace)
    db_session.flush()

    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
    )
    db_session.add(membership)
    db_session.flush()
    db_session.refresh(membership)

    assert membership.status == MembershipStatus.ACTIVE


def test_deleting_a_user_leaves_the_workspace_standing(
    db_session: Session,
    user: User,
) -> None:
    # The business outlives whoever happened to create it. created_by is an
    # audit field, not the thing that keeps a workspace alive.
    workspace = _workspace(user)
    db_session.add(workspace)
    db_session.flush()

    db_session.delete(user)
    db_session.flush()
    db_session.expire(workspace)

    assert db_session.get(Workspace, workspace.id) is not None
    assert workspace.created_by_user_id is None


def test_deleting_a_user_takes_their_memberships_with_them(
    db_session: Session,
    user: User,
) -> None:
    workspace = _workspace(user)
    db_session.add(workspace)
    db_session.flush()

    membership = WorkspaceMembership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
    )
    db_session.add(membership)
    db_session.flush()
    membership_id = membership.id

    db_session.delete(user)
    db_session.flush()
    db_session.expunge_all()

    assert db_session.get(WorkspaceMembership, membership_id) is None
