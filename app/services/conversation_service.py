import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated

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
from app.models.conversation import Conversation, ConversationStatus
from app.models.workspace_membership import MembershipStatus
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.schemas.conversation import ConversationCreate, ConversationUpdate
from app.services.contact_service import ContactRepositoryDep
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
    ) -> None:
        self._session = session
        self._conversations = conversations
        self._contacts = contacts
        self._memberships = memberships

    def create(
        self,
        access: WorkspaceAccess,
        payload: ConversationCreate,
    ) -> Conversation:
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

        return conversation

    def get(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
    ) -> Conversation:
        conversation = self._conversations.get(access.workspace.id, conversation_id)

        if conversation is None:
            raise ConversationNotFoundError(access.workspace.id, conversation_id)

        return conversation

    def list_for(
        self,
        access: WorkspaceAccess,
        *,
        page: int = 1,
        page_size: int = 20,
        status: ConversationStatus | None = None,
        assigned_user_id: int | None = None,
        contact_id: uuid.UUID | None = None,
        unassigned: bool = False,
    ) -> tuple[Sequence[Conversation], int]:
        workspace_id = access.workspace.id
        filters = {
            "status": status,
            "assigned_user_id": assigned_user_id,
            "contact_id": contact_id,
            "unassigned": unassigned,
        }

        conversations = self._conversations.list_for_workspace(
            workspace_id,
            limit=page_size,
            offset=(page - 1) * page_size,
            **filters,  # type: ignore[arg-type]
        )
        total = self._conversations.count_for_workspace(
            workspace_id,
            **filters,  # type: ignore[arg-type]
        )

        return conversations, total

    def update(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
        payload: ConversationUpdate,
    ) -> Conversation:
        """Apply a partial update, routing a status change through the
        same code the close and reopen endpoints use."""
        conversation = self.get(access, conversation_id)

        if payload.ai_mode is not None:
            self._conversations.set_ai_mode(conversation, payload.ai_mode)

        if payload.status is not None and payload.status != conversation.status:
            self._apply_status(conversation, payload.status)

        self._session.commit()

        return conversation

    def assign(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
        user_id: int | None,
    ) -> Conversation:
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
        self._session.commit()

        return conversation

    def close(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
    ) -> Conversation:
        conversation = self.get(access, conversation_id)

        if not conversation.is_closed:
            self._apply_status(conversation, ConversationStatus.CLOSED)
            self._session.commit()

        return conversation

    def reopen(
        self,
        access: WorkspaceAccess,
        conversation_id: uuid.UUID,
    ) -> Conversation:
        conversation = self.get(access, conversation_id)

        if conversation.is_closed:
            self._apply_status(conversation, ConversationStatus.OPEN)
            self._session.commit()

        return conversation

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


def get_conversation_repository(session: SessionDep) -> ConversationRepository:
    return ConversationRepository(session)


ConversationRepositoryDep = Annotated[
    ConversationRepository,
    Depends(get_conversation_repository),
]


def get_conversation_service(
    session: SessionDep,
    conversations: ConversationRepositoryDep,
    contacts: ContactRepositoryDep,
    memberships: WorkspaceMembershipRepositoryDep,
) -> ConversationService:
    return ConversationService(
        session=session,
        conversations=conversations,
        contacts=contacts,
        memberships=memberships,
    )


ConversationServiceDep = Annotated[
    ConversationService,
    Depends(get_conversation_service),
]
