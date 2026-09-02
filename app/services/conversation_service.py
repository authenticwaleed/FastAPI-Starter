import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ContactNotFoundError,
    ConversationAlreadyOpenError,
    ConversationNotFoundError,
    MembershipNotFoundError,
)
from app.db.session import SessionDep
from app.models.audit_log import AuditEvent
from app.models.contact import Contact
from app.models.conversation import AiMode, Conversation, ConversationStatus
from app.models.conversation_event import ConversationEvent, EventType
from app.models.notification import NotificationKind
from app.models.workspace_membership import MembershipStatus
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_event_repository import (
    ConversationEventRepository,
)
from app.repositories.conversation_repository import (
    ConversationRepository,
    InboxRow,
)
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.schemas.conversation import ConversationCreate, ConversationUpdate
from app.services.audit_service import AuditService, AuditServiceDep
from app.services.contact_service import ContactRepositoryDep
from app.services.notification_service import (
    NotificationService,
    NotificationServiceDep,
)
from app.services.workspace_service import (
    WorkspaceAccess,
    WorkspaceMembershipRepositoryDep,
)


class ConversationService:
    """The threads a workspace has with its customers.

    Owns the lifecycle -- opened, assigned, closed, reopened -- and the
    two invariants that go with it: a conversation belongs to a contact in
    the same workspace, and a contact has at most one live thread.
    """

    def __init__(
        self,
        session: Session,
        conversations: ConversationRepository,
        contacts: ContactRepository,
        memberships: WorkspaceMembershipRepository,
        events: ConversationEventRepository,
        notifications: NotificationService,
        audit: AuditService,
    ) -> None:
        self._session = session
        self._conversations = conversations
        self._contacts = contacts
        self._memberships = memberships
        self._events = events
        self._notifications = notifications
        self._audit = audit

    def create(
        self,
        access: WorkspaceAccess,
        payload: ConversationCreate,
    ) -> InboxRow:
        workspace_id = access.workspace.id

        # Checked here so the answer is "no such contact" rather than a
        # foreign key violation. The database refuses it too -- the key is
        # composite, over workspace and contact together -- but that is
        # the backstop, not the message.
        if self._contacts.get(workspace_id, payload.contact_id) is None:
            raise ContactNotFoundError(workspace_id, payload.contact_id)

        existing = self._conversations.get_live_for_contact(
            workspace_id,
            payload.contact_id,
            payload.channel,
        )

        if existing is not None:
            raise ConversationAlreadyOpenError(payload.contact_id)

        try:
            conversation = self._conversations.create(
                workspace_id=workspace_id,
                contact_id=payload.contact_id,
                channel=payload.channel,
            )
            self._session.commit()
        except IntegrityError as exc:
            # Two agents can open a thread with the same customer at the
            # same moment. The partial unique index is what settles it.
            self._session.rollback()
            raise ConversationAlreadyOpenError(payload.contact_id) from exc

        return self._row(access, conversation)

    def get(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
    ) -> Conversation:
        conversation = self._conversations.get(access.workspace.id, conversation_id)

        if conversation is None:
            raise ConversationNotFoundError(access.workspace.id, conversation_id)

        return conversation

    def detail(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
    ) -> InboxRow:
        """One conversation with its contact, assignee and last message."""
        row = self._conversations.get_row(access.workspace.id, conversation_id)

        if row is None:
            raise ConversationNotFoundError(access.workspace.id, conversation_id)

        return row

    def list_for(
        self,
        access: WorkspaceAccess,
        *,
        page: int = 1,
        page_size: int = 20,
        statuses: Sequence[ConversationStatus] | None = None,
        assigned_user_id: int | None = None,
        contact_id: uuid.UUID | None = None,
        unassigned: bool = False,
        search: str | None = None,
    ) -> tuple[Sequence[InboxRow], int]:
        """The inbox: one page, and the total behind it.

        Two queries whatever the page holds -- the rows and their count --
        because everything a row displays is fetched with the row.
        """
        workspace_id = access.workspace.id
        filters: dict[str, Any] = {
            "statuses": statuses,
            "assigned_user_id": assigned_user_id,
            "contact_id": contact_id,
            "unassigned": unassigned,
            "search": search,
        }

        rows = self._conversations.list_for_workspace(
            workspace_id,
            limit=page_size,
            offset=(page - 1) * page_size,
            **filters,
        )
        total = self._conversations.count_for_workspace(workspace_id, **filters)

        return rows, total

    def update(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
        payload: ConversationUpdate,
    ) -> InboxRow:
        """Apply a partial update, routing a status change through the
        same code the close and reopen endpoints use."""
        conversation = self.get(access, conversation_id)

        if payload.ai_mode is not None:
            was = conversation.ai_mode
            self._conversations.set_ai_mode(conversation, payload.ai_mode)
            self._audit_ai_mode(access, conversation, was)

        if payload.status is not None and payload.status != conversation.status:
            self._apply_status(conversation, payload.status)
            self._audit_status(access, conversation, payload.status)

        self._session.commit()

        return self._row(access, conversation)

    def assign(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
        user_id: int | None,
    ) -> InboxRow:
        """Hand a thread to a colleague, or to nobody.

        The assignee has to be an active member of this workspace. A
        conversation assigned to somebody outside it would put a
        customer's history on a screen that should not have it, and would
        do so through a field that looks like bookkeeping.
        """
        conversation = self.get(access, conversation_id)

        if user_id is not None:
            membership = self._memberships.get_for_user(access.workspace.id, user_id)

            if membership is None or membership.status != MembershipStatus.ACTIVE:
                raise MembershipNotFoundError(access.workspace.id, user_id)

        self._conversations.set_assignee(conversation, user_id)
        # Recorded whether a thread was handed to somebody or taken off
        # them: `assigned_to` is null for the second, which is the same
        # act and the one somebody asks about later.
        self._audit.did(
            access.workspace.id,
            AuditEvent.CONVERSATION_ASSIGNED,
            actor_user_id=access.actor_user_id,
            meta={
                "conversation_id": str(conversation.id),
                "assigned_to": user_id,
            },
        )

        if user_id is not None and user_id != access.actor_user_id:
            # Told in the same transaction as the assignment, so the two
            # cannot disagree -- and not told to whoever did it, who
            # already knows and does not need a badge for their own click.
            contact = self._contacts.get(access.workspace.id, conversation.contact_id)
            self._notifications.tell(
                user_id=user_id,
                workspace_id=access.workspace.id,
                kind=NotificationKind.CONVERSATION_ASSIGNED,
                title="A conversation was assigned to you",
                body=_about(contact),
                meta={"conversation_id": str(conversation.id)},
            )

        self._session.commit()

        return self._row(access, conversation)

    def close(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
    ) -> InboxRow:
        conversation = self.get(access, conversation_id)

        if not conversation.is_closed:
            self._apply_status(conversation, ConversationStatus.CLOSED)
            self._audit_status(access, conversation, ConversationStatus.CLOSED)
            self._session.commit()

        return self._row(access, conversation)

    def reopen(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
    ) -> InboxRow:
        conversation = self.get(access, conversation_id)

        if conversation.is_closed:
            self._apply_status(conversation, ConversationStatus.OPEN)
            self._session.commit()

        return self._row(access, conversation)

    def take_over(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
        reason: str | None = None,
    ) -> InboxRow:
        """Put a thread in the caller's hands and stop the assistant.

        The plan's business rule, and the reason it is a rule: once a
        person is talking to a customer, an assistant continuing to answer
        alongside them is two voices contradicting each other in one
        thread. Nothing releases it but somebody deciding to.

        Assigning to the caller as well, because taking over without
        picking it up is how a thread ends up with the assistant switched
        off and nobody looking at it -- worse for the customer than either
        alternative.
        """
        conversation = self.get(access, conversation_id)
        actor = access.actor_user_id

        self._conversations.take_over(
            conversation,
            at=datetime.now(UTC),
            reason=reason,
            user_id=actor,
        )
        self._conversations.set_assignee(conversation, actor)
        self._events.record(
            workspace_id=access.workspace.id,
            conversation_id=conversation.id,
            event_type=EventType.HUMAN_TAKEOVER,
            actor_user_id=actor,
            reason=reason,
        )
        self._session.commit()

        return self._row(access, conversation)

    def release_to_ai(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
        mode: AiMode = AiMode.SUGGEST_ONLY,
    ) -> InboxRow:
        """Hand a thread back to the assistant.

        Back to drafting rather than to answering unless the caller says
        otherwise: a thread a person had to take over is not the one to
        return to full automation without somebody choosing to.

        The assignment is left alone. Releasing the assistant and dropping
        the thread are two decisions, and the agent who did the first is
        usually still the right person to see the customer's reply.
        """
        conversation = self.get(access, conversation_id)

        self._conversations.release(conversation, mode)
        self._events.record(
            workspace_id=access.workspace.id,
            conversation_id=conversation.id,
            event_type=EventType.AI_RELEASED,
            actor_user_id=access.actor_user_id,
        )
        self._session.commit()

        return self._row(access, conversation)

    def history(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[Sequence[ConversationEvent], int]:
        """Who has had this thread, and why."""
        self.get(access, conversation_id)
        workspace_id = access.workspace.id

        return (
            self._events.list_for_conversation(
                workspace_id,
                conversation_id,
                limit=page_size,
                offset=(page - 1) * page_size,
            ),
            self._events.count_for_conversation(workspace_id, conversation_id),
        )

    def mark_read(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
    ) -> InboxRow:
        """Clear the thread's unread count for the whole team.

        For the whole team because the count is the team's: this is a
        shared inbox, and a badge that stays lit on four other screens
        after somebody has dealt with a customer is a queue that gets
        worked four times.

        Idempotent, and reachable when there was nothing unread, so a
        client can call it whenever a thread is opened without first
        checking whether it needs to.
        """
        conversation = self.get(access, conversation_id)

        self._conversations.mark_read(conversation, datetime.now(UTC))
        self._session.commit()

        return self._row(access, conversation)

    def _audit_status(
        self,
        access: WorkspaceAccess,
        conversation: Conversation,
        status: ConversationStatus,
    ) -> None:
        """Record a thread being closed, and only that.

        Reopening is not audited, because the plan names one direction and
        it is the right one: closing is what takes a customer's thread out
        of the queue everybody is working from, and a thread closed by
        mistake is invisible until somebody goes looking for it.
        """
        if status != ConversationStatus.CLOSED:
            return

        self._audit.did(
            access.workspace.id,
            AuditEvent.CONVERSATION_CLOSED,
            actor_user_id=access.actor_user_id,
            meta={"conversation_id": str(conversation.id)},
        )

    def _audit_ai_mode(
        self,
        access: WorkspaceAccess,
        conversation: Conversation,
        was: AiMode,
    ) -> None:
        """Record the assistant being switched off on a thread.

        One direction, which is the plan's vocabulary and defensible on
        its own: switching the assistant off is what silently changes what
        a customer gets back, and it is the state a business finds itself
        in without remembering choosing it. What it was before is in the
        entry, so the other direction is at least legible when the
        vocabulary grows.
        """
        if conversation.ai_mode != AiMode.DISABLED or was == AiMode.DISABLED:
            return

        self._audit.did(
            access.workspace.id,
            AuditEvent.CONVERSATION_AI_DISABLED,
            actor_user_id=access.actor_user_id,
            meta={"conversation_id": str(conversation.id), "from": was.value},
        )

    def _apply_status(
        self,
        conversation: Conversation,
        status: ConversationStatus,
    ) -> None:
        """The one place a conversation's status and its timestamps move.

        Closing stamps closed_at; reopening clears it and restarts
        opened_at, so "how long has this been open" measures the current
        spell rather than the first one.
        """
        now = datetime.now(UTC)

        if status == ConversationStatus.CLOSED:
            self._conversations.set_status(conversation, status, closed_at=now)
            return

        reopening = conversation.is_closed

        try:
            self._conversations.set_status(
                conversation,
                status,
                opened_at=now if reopening else None,
            )
        except IntegrityError as exc:
            # Reopening runs into the same partial unique index that stops
            # two live threads with one contact: somebody started a new
            # conversation while this one was closed.
            self._session.rollback()
            raise ConversationAlreadyOpenError(conversation.contact_id) from exc

    def _row(self, access: WorkspaceAccess, conversation: Conversation) -> InboxRow:
        """Read back what was just written, in the shape the API answers in.

        One more query after a change that has already been committed.
        Worth it: the alternative is that a client which has just assigned
        a thread cannot redraw the row from the response, and has to ask
        for the conversation again anyway -- the same query, one round
        trip further away.
        """
        return self.detail(access, conversation.id)


def get_conversation_repository(session: SessionDep) -> ConversationRepository:
    return ConversationRepository(session)


ConversationRepositoryDep = Annotated[
    ConversationRepository,
    Depends(get_conversation_repository),
]


def get_conversation_event_repository(
    session: SessionDep,
) -> ConversationEventRepository:
    return ConversationEventRepository(session)


ConversationEventRepositoryDep = Annotated[
    ConversationEventRepository,
    Depends(get_conversation_event_repository),
]


def get_conversation_service(
    session: SessionDep,
    conversations: ConversationRepositoryDep,
    contacts: ContactRepositoryDep,
    memberships: WorkspaceMembershipRepositoryDep,
    events: ConversationEventRepositoryDep,
    notifications: NotificationServiceDep,
    audit: AuditServiceDep,
) -> ConversationService:
    return ConversationService(
        session=session,
        conversations=conversations,
        contacts=contacts,
        memberships=memberships,
        events=events,
        notifications=notifications,
        audit=audit,
    )


ConversationServiceDep = Annotated[
    ConversationService,
    Depends(get_conversation_service),
]


def _about(contact: Contact | None) -> str | None:
    """Who the thread is with, as one line, written down now.

    Composed here rather than looked up when the notification is read,
    because a notification is a record of a moment: a contact renamed
    next month should not silently rewrite what somebody was told today.
    """
    if contact is None:
        return None

    return f"With {contact.name or contact.phone_number}"
