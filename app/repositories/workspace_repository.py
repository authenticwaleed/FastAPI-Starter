import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.models.workspace import Workspace, WorkspaceStatus
from app.models.workspace_membership import MembershipStatus, WorkspaceMembership


def _visible_to(user_id: int) -> tuple[ColumnElement[bool], ...]:
    """What makes a workspace one this user is allowed to be told exists.

    Written once and applied to both the page and its count, so the two can
    never disagree about what is there. Cancelled workspaces are excluded
    here rather than filtered afterwards: a cancelled workspace is gone as
    far as the API is concerned, and the rows only survive so that closing
    an account is recoverable.
    """
    return (
        WorkspaceMembership.user_id == user_id,
        WorkspaceMembership.status == MembershipStatus.ACTIVE,
        Workspace.status != WorkspaceStatus.CANCELLED,
    )


class WorkspaceRepository:
    """Every query against the workspaces table lives here.

    Methods flush rather than commit, so the caller decides where a
    transaction ends and a workspace and its first membership can be
    written as one.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        name: str,
        slug: str,
        timezone: str,
        default_currency: str,
        created_by_user_id: int,
    ) -> Workspace:
        workspace = Workspace(
            name=name,
            slug=slug,
            timezone=timezone,
            default_currency=default_currency,
            created_by_user_id=created_by_user_id,
        )

        self._session.add(workspace)
        # Flush so the id and the server-side defaults exist, while leaving
        # the transaction open for the membership that has to accompany it.
        self._session.flush()

        return workspace

    def get(self, workspace_id: uuid.UUID) -> Workspace | None:
        return self._session.get(Workspace, workspace_id)

    def due_for_erasure(self, *, now: datetime) -> Sequence[uuid.UUID]:
        """Workspaces whose retention period is over.

        Ids only, and not workspace-scoped -- one of the few queries here
        that is not, because what asks it is the sweep deciding what has
        come due. Everything it then does is one workspace at a time.
        """
        return self._session.scalars(
            select(Workspace.id)
            .where(Workspace.erase_after.is_not(None), Workspace.erase_after <= now)
            .order_by(Workspace.erase_after)
        ).all()

    def erase(self, workspace: Workspace) -> None:
        """Destroy a workspace and everything hanging off it.

        One DELETE, and that is not a shortcut: every table that belongs
        to a tenant references `workspaces.id` with ON DELETE CASCADE, and
        has since the tenant boundary was drawn. Deleting row by row here
        would be a second list of what a workspace owns, kept in step with
        the schema by hand, and the day it fell behind would be the day a
        deletion quietly left something.
        """
        self._session.delete(workspace)
        self._session.flush()

    def clear_erasure(self, workspace: Workspace) -> Workspace:
        """Take the erasure date off a workspace that is coming back.

        Its own method rather than a null passed to `set_status`, which
        reads there as "leave it alone" -- and the difference between
        leaving a date alone and removing it is a restored workspace that
        gets erased anyway on the day nobody expected.
        """
        workspace.erase_after = None
        self._session.flush()

        return workspace

    def get_by_slug(self, slug: str) -> Workspace | None:
        return self._session.scalar(select(Workspace).where(Workspace.slug == slug))

    def list_for_user(
        self,
        user_id: int,
        *,
        limit: int,
        offset: int,
    ) -> Sequence[Workspace]:
        """One page of the workspaces this user actually belongs to.

        The join is the authorization. There is no way to call this and get
        back a workspace the user has no membership of, which is what stops
        a listing endpoint from becoming a directory of every business on
        the platform.
        """
        return self._session.scalars(
            select(Workspace)
            .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
            .where(*_visible_to(user_id))
            # created_at alone is not a stable sort: every row written in
            # one transaction shares a now(), so the id breaks the tie and
            # keeps pages from overlapping or skipping.
            .order_by(Workspace.created_at, Workspace.id)
            .limit(limit)
            .offset(offset)
        ).all()

    def count_for_user(self, user_id: int) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(Workspace)
                .join(
                    WorkspaceMembership,
                    WorkspaceMembership.workspace_id == Workspace.id,
                )
                .where(*_visible_to(user_id))
            )
            or 0
        )

    def update(
        self,
        workspace: Workspace,
        *,
        name: str | None = None,
        timezone: str | None = None,
        default_currency: str | None = None,
    ) -> Workspace:
        """Apply the fields supplied and leave the rest alone.

        `None` means "no change" rather than "set to null": all three
        columns are NOT NULL, so there is nothing else it could mean.
        """
        if name is not None:
            workspace.name = name

        if timezone is not None:
            workspace.timezone = timezone

        if default_currency is not None:
            workspace.default_currency = default_currency

        self._session.flush()

        return workspace

    def set_status(
        self,
        workspace: Workspace,
        status: WorkspaceStatus,
        *,
        erase_after: datetime | None = None,
    ) -> Workspace:
        """Move the status, and set the erasure date when one is given.

        Together rather than as two calls, because they are one decision:
        a workspace that is closed without a date is one whose data nobody
        has decided anything about, and that is exactly the state a
        retention policy exists to prevent.
        """
        workspace.status = status

        if erase_after is not None:
            workspace.erase_after = erase_after

        self._session.flush()

        return workspace
