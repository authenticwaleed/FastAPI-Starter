"""Requiring a second person for the two acts that deserve one.

The rule, stated once so the checks below read as consequences of it:
**the person who performs an act may not be the person who approved it.**

Not "two staff members were involved at some point". Somebody who could
approve their own erasure and then perform it has not been through a
two-person process, they have been through a form. So the check is on the
performer, at the moment of performing, against the approver.

What is deliberately *not* required is that the requester and the
performer differ. Asking a colleague to agree and then doing it yourself
is the ordinary shape of this: one person is acting and another has
looked at it, which is what the control is for.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ApprovalRequiredError
from app.db.session import SessionDep
from app.models.admin_approval import AdminApproval, ApprovableAction
from app.models.admin_audit_log import AdminAction
from app.models.user import User
from app.repositories.admin_approval_repository import AdminApprovalRepository
from app.services.admin_audit_service import AdminAuditService, AdminAuditServiceDep
from app.services.staff_service import StaffActor


class AdminApprovalService:
    """Raising an approval, agreeing to one, and spending it."""

    def __init__(
        self,
        session: Session,
        approvals: AdminApprovalRepository,
        admin_audit: AdminAuditService,
    ) -> None:
        self._session = session
        self._approvals = approvals
        self._admin_audit = admin_audit

    def request(
        self,
        actor: StaffActor,
        *,
        action: ApprovableAction,
        subject: str,
        reason: str,
        meta: dict[str, Any] | None = None,
    ) -> AdminApproval:
        """Ask for a colleague's agreement to one specific act.

        The window is short by configuration, because the point of the
        second person is that they are looking at the same situation --
        an approval collected in the morning and spent in the evening is
        one signature on a decision rather than two.
        """
        approval = self._approvals.create(
            action=action,
            subject=subject,
            reason=reason,
            requested_by_user_id=actor.user.id,
            expires_at=datetime.now(UTC)
            + timedelta(minutes=get_settings().admin_approval_expire_minutes),
            meta=meta or {},
        )

        self._record(actor, AdminAction.APPROVAL_REQUESTED, approval)

        return approval

    def approve(self, actor: StaffActor, approval_id: uuid.UUID) -> AdminApproval:
        """Agree to somebody else's request.

        Refused on your own request, which is the whole control: an
        approval you raised and agreed to yourself is a form, not a
        second person.
        """
        approval = self._approval(approval_id)

        if approval.requested_by_user_id == actor.user.id:
            raise ApprovalRequiredError("you cannot approve your own request")

        if approval.approved_at is not None:
            raise ApprovalRequiredError("that request has already been approved")

        if approval.expires_at <= datetime.now(UTC):
            raise ApprovalRequiredError("that request has expired")

        self._approvals.approve(
            approval,
            by_user_id=actor.user.id,
            at=datetime.now(UTC),
        )
        self._record(actor, AdminAction.APPROVAL_GRANTED, approval)

        return approval

    def spend(
        self,
        actor: StaffActor,
        approval_id: uuid.UUID | None,
        *,
        action: ApprovableAction,
        subject: str,
        matching: dict[str, Any] | None = None,
    ) -> AdminApproval:
        """Check an approval covers this act, and mark it spent.

        Every refusal here is the same answer, because every one of them
        means the same thing to the person asking: find a colleague. What
        differs is the sentence, which goes in the detail so somebody can
        tell "expired" from "already used" without reading the log.

        The subject is checked, not just the action. A colleague agreeing
        to erase a test workspace has not agreed to erase any of them,
        and `matching` carries the rest of what they saw -- the rank in a
        promotion, so a request approved for `support` cannot be spent
        granting `owner`.
        """
        if approval_id is None:
            raise ApprovalRequiredError("no approval was supplied")

        approval = self._approval(approval_id)
        now = datetime.now(UTC)

        if approval.action is not action or approval.subject != subject:
            raise ApprovalRequiredError("that approval is for something else")

        if not approval.usable_at(now):
            raise ApprovalRequiredError(_why(approval, now))

        if approval.approved_by_user_id == actor.user.id:
            # The rule this whole module exists for.
            raise ApprovalRequiredError("it was approved by you")

        for key, value in (matching or {}).items():
            if approval.meta.get(key) != value:
                raise ApprovalRequiredError(f"that approval was for a different {key}")

        self._approvals.consume(approval, at=now)
        self._record(actor, AdminAction.APPROVAL_SPENT, approval)

        return approval

    def listed(
        self,
        actor: StaffActor,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[tuple[AdminApproval, User | None, User | None]], int]:
        """The review surface for the two most serious acts on the platform.

        Spent and expired ones included, which is most of the value: a
        list of only what is pending is a list that is almost always
        empty, and the question is about what has been agreed to.
        """
        found = self._approvals.list_recent(
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        total = self._approvals.count()

        self._admin_audit.did(
            actor.logged,
            AdminAction.APPROVALS_READ,
            meta={"results": total},
        )
        self._session.commit()

        return found, total

    def _approval(self, approval_id: uuid.UUID) -> AdminApproval:
        approval = self._approvals.get(approval_id)

        if approval is None:
            raise ApprovalRequiredError("no approval with that id")

        return approval

    def _record(
        self,
        actor: StaffActor,
        action: AdminAction,
        approval: AdminApproval,
    ) -> None:
        self._admin_audit.did(
            actor.logged,
            action,
            meta={
                "approval_id": str(approval.id),
                "action": approval.action.value,
                "subject": approval.subject,
                "reason": approval.reason,
            },
        )
        self._session.commit()


def _why(approval: AdminApproval, now: datetime) -> str:
    """Which of the three unusable states this approval is in.

    Told apart in the sentence, not in the status code. Somebody who
    reaches for an approval they already spent and somebody who reaches
    for one that lapsed both need a colleague -- but they need to be told
    different things about what to do next.
    """
    if approval.approved_at is None:
        return "nobody has approved it yet"

    if approval.consumed_at is not None:
        return "it has already been used"

    if approval.expires_at <= now:
        return "it has expired"

    return "it cannot be used"


def get_admin_approval_repository(session: SessionDep) -> AdminApprovalRepository:
    return AdminApprovalRepository(session)


AdminApprovalRepositoryDep = Annotated[
    AdminApprovalRepository,
    Depends(get_admin_approval_repository),
]


def get_admin_approval_service(
    session: SessionDep,
    approvals: AdminApprovalRepositoryDep,
    admin_audit: AdminAuditServiceDep,
) -> AdminApprovalService:
    return AdminApprovalService(
        session=session,
        approvals=approvals,
        admin_audit=admin_audit,
    )


AdminApprovalServiceDep = Annotated[
    AdminApprovalService,
    Depends(get_admin_approval_service),
]
