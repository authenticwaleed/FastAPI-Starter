import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.support_grant import SupportGrant
from app.models.user import User


class SupportGrantRepository:
    """Every query against the support_grants table lives here.

    Small, and one of its four methods runs on every request that reaches
    a customer's messages -- so the shape of `live_for` is what decides
    whether time-boxing costs anything. It is a single indexed lookup on
    the pair a grant is about, with the expiry compared in the database
    rather than in Python, which is the same reason sessions are resolved
    that way: a clock in the application is one more thing that can be
    wrong.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        staff_user_id: int,
        reason: str,
        expires_at: datetime,
    ) -> SupportGrant:
        grant = SupportGrant(
            workspace_id=workspace_id,
            staff_user_id=staff_user_id,
            reason=reason,
            expires_at=expires_at,
        )

        self._session.add(grant)
        self._session.flush()

        return grant

    def live_for(
        self,
        workspace_id: uuid.UUID,
        staff_user_id: int,
        now: datetime,
    ) -> SupportGrant | None:
        """The grant, if any, that lets this person read this workspace now.

        Not revoked and not expired, both settled here rather than by the
        caller. There is no status column to consult and nothing has to
        run for a grant to lapse -- it simply stops matching, which is
        what makes expiry a property of the data rather than of a job
        somebody has to remember to schedule.

        Newest first, because re-granting after one expires leaves two
        rows and the live one is the later.
        """
        return self._session.scalar(
            select(SupportGrant)
            .where(
                SupportGrant.workspace_id == workspace_id,
                SupportGrant.staff_user_id == staff_user_id,
                SupportGrant.revoked_at.is_(None),
                SupportGrant.expires_at > now,
            )
            .order_by(SupportGrant.created_at.desc())
            .limit(1)
        )

    def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
    ) -> list[tuple[SupportGrant, User]]:
        """Every grant over this business, live and historical, newest first.

        History included, and that is most of the value: "who has been in
        this account, when, and why" is the question an administrator
        asks and the one a customer would ask if they wrote in about it.
        A list of only the live ones would be a list that is almost
        always empty.

        Joined to the account rather than looked up per row, so the
        answer names people rather than ids.
        """
        rows = self._session.execute(
            select(SupportGrant, User)
            .join(User, User.id == SupportGrant.staff_user_id)
            .where(SupportGrant.workspace_id == workspace_id)
            .order_by(SupportGrant.created_at.desc(), SupportGrant.id)
        ).all()

        return [(grant, user) for grant, user in rows]

    def lapsed(self, now: datetime) -> Sequence[SupportGrant]:
        """Grants whose hour has passed and which nobody ended by hand.

        Not what makes them stop working: an expired grant already fails
        the lookup in `live_for`, with nothing having to run. What this
        finds is the grants nobody has told the *customer* about ending
        -- their audit log shows access granted and, without a sweep,
        never shows it end.
        """
        return self._session.scalars(
            select(SupportGrant)
            .where(
                SupportGrant.revoked_at.is_(None),
                SupportGrant.expires_at <= now,
            )
            .order_by(SupportGrant.expires_at)
        ).all()

    def revoke(self, grant: SupportGrant, at: datetime) -> SupportGrant:
        """End a grant early, keeping the row that says it existed."""
        grant.revoked_at = at
        self._session.flush()

        return grant
