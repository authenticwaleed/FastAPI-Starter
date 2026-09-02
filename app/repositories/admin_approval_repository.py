import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models.admin_approval import AdminApproval, ApprovableAction
from app.models.user import User


class AdminApprovalRepository:
    """Every query against the admin_approvals table lives here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        action: ApprovableAction,
        subject: str,
        reason: str,
        requested_by_user_id: int,
        expires_at: datetime,
        meta: dict[str, Any],
    ) -> AdminApproval:
        approval = AdminApproval(
            action=action,
            subject=subject,
            reason=reason,
            requested_by_user_id=requested_by_user_id,
            expires_at=expires_at,
            meta=meta,
        )

        self._session.add(approval)
        self._session.flush()

        return approval

    def get(self, approval_id: uuid.UUID) -> AdminApproval | None:
        return self._session.get(AdminApproval, approval_id)

    def approve(
        self,
        approval: AdminApproval,
        *,
        by_user_id: int,
        at: datetime,
    ) -> AdminApproval:
        approval.approved_by_user_id = by_user_id
        approval.approved_at = at
        self._session.flush()

        return approval

    def consume(self, approval: AdminApproval, *, at: datetime) -> AdminApproval:
        """Spend it, once.

        Without this an approval to erase one workspace would be reusable
        every time somebody wanted to erase it again -- which sounds
        harmless until the workspace is restored and erased twice.
        """
        approval.consumed_at = at
        self._session.flush()

        return approval

    def list_recent(
        self,
        *,
        limit: int,
        offset: int,
    ) -> list[tuple[AdminApproval, User | None, User | None]]:
        """Approvals, newest first, with both people named.

        Two outer joins rather than an inner one, because either account
        can be gone: the foreign keys are SET NULL so that a colleague
        leaving does not delete the record of what they agreed to.

        Spent and expired ones included, which is most of the value: this
        is the review surface for the two most serious acts on the
        platform, and a list of only what is pending would be a list that
        is almost always empty.
        """
        requester = aliased(User)
        approver = aliased(User)

        rows = self._session.execute(
            select(AdminApproval, requester, approver)
            .outerjoin(requester, requester.id == AdminApproval.requested_by_user_id)
            .outerjoin(approver, approver.id == AdminApproval.approved_by_user_id)
            .order_by(AdminApproval.created_at.desc(), AdminApproval.id)
            .limit(limit)
            .offset(offset)
        ).all()

        return [(approval, asked, agreed) for approval, asked, agreed in rows]

    def count(self) -> int:
        return (
            self._session.scalar(select(func.count()).select_from(AdminApproval)) or 0
        )

    def pending_for(
        self,
        action: ApprovableAction,
        subject: str,
    ) -> Sequence[AdminApproval]:
        """Approvals raised for this exact act, spent or not.

        By action *and* subject, which is the property that stops an
        approval being general. Used by the console rather than by the
        check: spending one names it by id, so there is never a guess
        about which approval was meant.
        """
        return self._session.scalars(
            select(AdminApproval)
            .where(
                AdminApproval.action == action,
                AdminApproval.subject == subject,
            )
            .order_by(AdminApproval.created_at.desc())
        ).all()
