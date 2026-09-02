"""Time-boxed permission to read one customer's data, and the reads it opens.

The most dangerous thing in this plan, and the shape of it is the whole
safeguard. Nobody on the platform has standing access to a customer's
messages. Somebody who needs it says which workspace, why, and for how
long; the grant expires on its own; and three separate records exist of
what happened -- the grant row, the customer's own audit log, and the
platform's.

Four properties are worth stating together, because each is uninteresting
alone and they only work as a set:

**It ends by itself.** `expires_at` is not nullable and nothing has to run
for a grant to lapse. It simply stops matching the query that opens the
door.

**The customer sees it.** Starting and ending a grant each write an entry
to the business's own audit log, naming the staff member and their stated
reason. One caveat worth knowing: reading that log is a paid feature, so a
business on the free plan holds the entry without being able to read it
today. Ungating it is a customer-facing change and belongs to whoever
decides the plan's shape, not here.

**It reads and nothing else.** Two things hold that up, and it is worth
being exact about which, because a comment that overstates this is worse
than none. The access handed out carries a staff actor rather than a
membership, so its role is `viewer` -- which every role check on a
tenant route refuses. And nothing on the platform surface calls a method
that writes: the only two that take this access are the inbox and the
thread below, both read-only, and a test asserts by introspection that
no admin route publishes a verb that could reach tenant data.

Where a service does write and record who did it, `actor_user_id`
raises rather than naming a staff member among the customer's own people
-- so the failure mode of a mistake here is a refusal, not a forged
entry.

**It is invisible to the team.** No membership row is written, so a grant
never appears in the customer's member list, in their seat count, or in
what they are billed for.
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    SupportAccessAlreadyGrantedError,
    SupportAccessRequiredError,
    SupportGrantTooLongError,
    WorkspaceNotFoundError,
)
from app.db.session import SessionDep
from app.models.admin_audit_log import AdminAction
from app.models.audit_log import AuditEvent
from app.models.conversation import ConversationStatus
from app.models.message import Message
from app.models.support_grant import SupportGrant
from app.models.user import User
from app.repositories.admin_console_repository import (
    AdminConsoleRepository,
    WorkspaceRow,
)
from app.repositories.conversation_repository import InboxRow
from app.repositories.support_grant_repository import SupportGrantRepository
from app.services.admin_audit_service import AdminAuditService, AdminAuditServiceDep
from app.services.admin_workspace_service import AdminConsoleRepositoryDep
from app.services.audit_service import AuditService, AuditServiceDep
from app.services.conversation_service import (
    ConversationService,
    ConversationServiceDep,
)
from app.services.message_service import MessageService, MessageServiceDep
from app.services.staff_service import StaffActor
from app.services.workspace_service import WorkspaceAccess

logger = logging.getLogger(__name__)


class SupportAccessService:
    """Granting the access, ending it, and using it.

    All three together because they are one rule seen from three sides,
    and splitting them would let the third exist without the first: a
    service that could read a customer's conversations without consulting
    the grant is the failure this phase is about.
    """

    def __init__(
        self,
        session: Session,
        grants: SupportGrantRepository,
        console: AdminConsoleRepository,
        admin_audit: AdminAuditService,
        tenant_audit: AuditService,
        conversations: ConversationService,
        messages: MessageService,
    ) -> None:
        self._session = session
        self._grants = grants
        self._console = console
        self._admin_audit = admin_audit
        self._tenant_audit = tenant_audit
        self._conversations = conversations
        self._messages = messages

    # --- granting ----------------------------------------------------------

    def grant(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
        *,
        reason: str,
        hours: int | None = None,
    ) -> SupportGrant:
        """Open a window on one customer's data, for a stated reason.

        The duration is refused rather than clamped when it is too long.
        Somebody who asks for two days and is quietly given four hours
        believes they have two days, and finds out otherwise in the
        middle of whatever they were investigating.

        A second grant while one is live is refused too, for a subtler
        reason: a grant carries a reason and an expiry that were recorded
        together, and pushing the expiry out on a later request would
        leave the recorded reason describing a window it no longer covers.
        """
        row = self._workspace(workspace_id)
        settings = get_settings()
        wanted = hours if hours is not None else settings.admin_support_grant_hours

        if wanted > settings.admin_support_grant_max_hours:
            raise SupportGrantTooLongError(
                wanted,
                settings.admin_support_grant_max_hours,
            )

        now = datetime.now(UTC)

        if self._grants.live_for(workspace_id, actor.user.id, now) is not None:
            raise SupportAccessAlreadyGrantedError(workspace_id)

        grant = self._grants.create(
            workspace_id=workspace_id,
            staff_user_id=actor.user.id,
            reason=reason,
            expires_at=now + timedelta(hours=wanted),
        )

        # The customer's own log first, because it is the half of this
        # that somebody outside the company will read. No actor id: the
        # entry belongs to no member of their team, and the event name is
        # what says a staff member did it.
        self._tenant_audit.did(
            row.workspace.id,
            AuditEvent.SUPPORT_ACCESS_GRANTED,
            by_staff=actor.user.email,
            meta=_told_to_the_customer(grant),
        )
        self._admin_audit.did(
            actor.logged,
            AdminAction.SUPPORT_ACCESS_GRANTED,
            workspace_id=row.workspace.id,
            workspace_slug=row.workspace.slug,
            meta={
                "reason": grant.reason,
                "hours": wanted,
                "expires_at": grant.expires_at.isoformat(),
            },
        )
        self._session.commit()

        _notice_the_hour(actor, row, grant)

        return grant

    def revoke(self, actor: StaffActor, workspace_id: uuid.UUID) -> SupportGrant | None:
        """End your own grant before it runs out.

        Ending access you no longer hold is not an error, and answers the
        same way as ending access you do. Somebody closing a window they
        are finished with should not have to know whether it had already
        expired -- and refusing would be a confusing answer to the safest
        request on this surface.

        Nothing is recorded when there was nothing to end, so a client
        that calls this twice leaves one entry rather than two.
        """
        row = self._workspace(workspace_id)
        now = datetime.now(UTC)
        grant = self._grants.live_for(workspace_id, actor.user.id, now)

        if grant is None:
            return None

        self._grants.revoke(grant, now)

        self._tenant_audit.did(
            row.workspace.id,
            AuditEvent.SUPPORT_ACCESS_ENDED,
            by_staff=actor.user.email,
            meta=_told_to_the_customer(grant),
        )
        self._admin_audit.did(
            actor.logged,
            AdminAction.SUPPORT_ACCESS_REVOKED,
            workspace_id=row.workspace.id,
            workspace_slug=row.workspace.slug,
            meta={"reason": grant.reason},
        )
        self._session.commit()

        return grant

    def list_grants(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
    ) -> list[tuple[SupportGrant, User]]:
        """Who has been in this account, when, and why.

        History as well as what is live, because a list of only the live
        ones is a list that is almost always empty -- and the question
        being asked is about the past.
        """
        row = self._workspace(workspace_id)
        listed = self._grants.list_for_workspace(workspace_id)

        self._admin_audit.did(
            actor.logged,
            AdminAction.SUPPORT_ACCESS_LISTED,
            workspace_id=row.workspace.id,
            workspace_slug=row.workspace.slug,
            meta={"grants": len(listed)},
        )
        self._session.commit()

        return listed

    # --- the door ----------------------------------------------------------

    def access_for(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
    ) -> tuple[WorkspaceAccess, WorkspaceRow]:
        """Turn a live grant into access the tenant services will accept.

        The one place a staff member becomes able to reach a customer's
        own data, and it is one lookup: a grant that is not revoked and
        has not expired. Unknown, revoked and expired are one refusal --
        unusual on this surface, where everything else is exact, and right
        here because all three mean the same thing to the person asking
        and lead to the same next step.

        What comes back carries a staff actor and no membership, so its
        role is `viewer`. Nothing downstream has to know that staff exist
        for every write in the application to refuse it.
        """
        row = self._workspace(workspace_id)

        if (
            self._grants.live_for(workspace_id, actor.user.id, datetime.now(UTC))
            is None
        ):
            raise SupportAccessRequiredError(workspace_id)

        return (
            WorkspaceAccess(workspace=row.workspace, staff_actor=actor.staff),
            row,
        )

    # --- what the grant opens ----------------------------------------------

    def conversations(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 20,
        statuses: Sequence[ConversationStatus] | None = None,
    ) -> tuple[Sequence[InboxRow], int]:
        """The customer's inbox, through the service they use themselves.

        The same query, the same shape, the same order. A second way of
        reading an inbox would eventually show support something the
        customer cannot see, which is the opposite of what a grant is
        for.
        """
        access, row = self.access_for(actor, workspace_id)
        found, total = self._conversations.list_for(
            access,
            page=page,
            page_size=page_size,
            statuses=statuses,
        )

        self._read(actor, row, AdminAction.CONVERSATIONS_READ, {"results": total})

        return found, total

    def messages(
        self,
        actor: StaffActor,
        workspace_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 30,
    ) -> tuple[Sequence[Message], int]:
        """One thread, in full.

        The deepest this surface reaches into a customer's account, and
        the entry it writes names the conversation -- because "they read
        the inbox" and "they read this customer's thread with this
        person" are different answers to give afterwards.
        """
        access, row = self.access_for(actor, workspace_id)
        found, total = self._messages.list_for(
            access.workspace,
            conversation_id,
            page=page,
            page_size=page_size,
        )

        self._read(
            actor,
            row,
            AdminAction.MESSAGES_READ,
            {"conversation_id": str(conversation_id), "messages": total},
        )

        return found, total

    # --- the steps they share ---------------------------------------------

    def _workspace(self, workspace_id: uuid.UUID) -> WorkspaceRow:
        """Resolve the id honestly, as everything on this surface does.

        404 only when nothing exists. A cancelled workspace is reachable
        here, which matters more for this phase than for the console: a
        business that closed its account and then wrote in about
        something is exactly when somebody needs to look.
        """
        row = self._console.get_workspace(workspace_id)

        if row is None:
            raise WorkspaceNotFoundError(workspace_id)

        return row

    def _read(
        self,
        actor: StaffActor,
        row: WorkspaceRow,
        action: AdminAction,
        meta: dict[str, object],
    ) -> None:
        """Record a read of a customer's own data, per request.

        Per request rather than once per grant, and that distinction is
        the value of the entry: the grant says somebody was allowed to
        look, and these say what they actually opened.
        """
        self._admin_audit.did(
            actor.logged,
            action,
            workspace_id=row.workspace.id,
            workspace_slug=row.workspace.slug,
            meta=dict(meta),
        )
        self._session.commit()


def _notice_the_hour(
    actor: StaffActor,
    row: WorkspaceRow,
    grant: SupportGrant,
) -> None:
    """Say something when a grant is asked for outside working hours.

    Not a refusal. Incidents do not keep office hours, and a console that
    could not be used at three in the morning would be a console somebody
    works around by keeping a standing grant -- which is the thing this
    whole design replaces.

    A warning line instead, in the stream operations already watches.
    That is what "alert on unusual patterns" comes to in a system whose
    alerting channel is its log: the pattern is noticed, a person
    decides, and nobody is blocked at the moment they are most needed.
    """
    hour = datetime.now(UTC).hour

    if hour in get_settings().admin_working_hours_utc:
        return

    logger.warning(
        "Support access granted outside working hours",
        extra={
            "admin_actor": actor.user.email,
            "admin_workspace": row.workspace.slug,
            "admin_hour_utc": hour,
            "admin_grant_hours": round(
                (grant.expires_at - grant.created_at).total_seconds() / 3600, 1
            )
            if grant.created_at
            else None,
        },
    )


def _told_to_the_customer(grant: SupportGrant) -> dict[str, object]:
    """What the business's own log says about a support grant.

    Enough to be an answer rather than an alarm: why, and until when. Who
    is not in here -- it is `by_staff`, alongside every other entry this
    application writes on a staff member's behalf, so a customer reading
    their history has one place to look rather than two conventions.

    "A staff member read your account" is frightening on its own; with
    the reason they gave and the hour it ends, it is something a customer
    can hold somebody to.
    """
    return {
        "reason": grant.reason,
        "expires_at": grant.expires_at.isoformat(),
    }


def get_support_grant_repository(session: SessionDep) -> SupportGrantRepository:
    return SupportGrantRepository(session)


SupportGrantRepositoryDep = Annotated[
    SupportGrantRepository,
    Depends(get_support_grant_repository),
]


def get_support_access_service(
    session: SessionDep,
    grants: SupportGrantRepositoryDep,
    console: AdminConsoleRepositoryDep,
    admin_audit: AdminAuditServiceDep,
    tenant_audit: AuditServiceDep,
    conversations: ConversationServiceDep,
    messages: MessageServiceDep,
) -> SupportAccessService:
    return SupportAccessService(
        session=session,
        grants=grants,
        console=console,
        admin_audit=admin_audit,
        tenant_audit=tenant_audit,
        conversations=conversations,
        messages=messages,
    )


SupportAccessServiceDep = Annotated[
    SupportAccessService,
    Depends(get_support_access_service),
]
