import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import Session

from app.models.conversation import (
    AiMode,
    Channel,
    Conversation,
    ConversationStatus,
)


class ConversationRepository:
    """Every query against the conversations table lives here.

    Workspace-scoped throughout, for the reason the contacts repository
    is: an id is not a permission, and a method that will answer without
    a workspace makes the tenant boundary a thing every caller has to
    remember.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        contact_id: uuid.UUID,
        channel: Channel,
    ) -> Conversation:
        conversation = Conversation(
            workspace_id=workspace_id,
            contact_id=contact_id,
            channel=channel,
        )

        self._session.add(conversation)
        self._session.flush()

        return conversation

    def get(
        self,
        workspace_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> Conversation | None:
        return self._session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == workspace_id,
            )
        )

    def get_live_for_contact(
        self,
        workspace_id: uuid.UUID,
        contact_id: uuid.UUID,
        channel: Channel,
    ) -> Conversation | None:
        """The contact's thread that is not closed, if they have one.

        There is at most one, enforced by a partial unique index rather
        than by this query being careful. The webhook will reach for this
        on every inbound message.
        """
        return self._session.scalar(
            select(Conversation).where(
                Conversation.workspace_id == workspace_id,
                Conversation.contact_id == contact_id,
                Conversation.channel == channel,
                Conversation.status != ConversationStatus.CLOSED,
            )
        )

    def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        status: ConversationStatus | None = None,
        assigned_user_id: int | None = None,
        contact_id: uuid.UUID | None = None,
        unassigned: bool = False,
    ) -> Sequence[Conversation]:
        return self._session.scalars(
            self._filtered(
                select(Conversation),
                workspace_id,
                status,
                assigned_user_id,
                contact_id,
                unassigned,
            )
            # Most recently active first, which is what an inbox is. A
            # thread with no messages yet sorts last rather than
            # disappearing, and the id breaks ties so pages cannot
            # overlap.
            .order_by(
                Conversation.last_message_at.desc().nullslast(),
                Conversation.created_at.desc(),
                Conversation.id,
            )
            .limit(limit)
            .offset(offset)
        ).all()

    def count_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        status: ConversationStatus | None = None,
        assigned_user_id: int | None = None,
        contact_id: uuid.UUID | None = None,
        unassigned: bool = False,
    ) -> int:
        return (
            self._session.scalar(
                self._filtered(
                    select(func.count()).select_from(Conversation),
                    workspace_id,
                    status,
                    assigned_user_id,
                    contact_id,
                    unassigned,
                )
            )
            or 0
        )

    @staticmethod
    def _filtered(
        statement: Select[Any],
        workspace_id: uuid.UUID,
        status: ConversationStatus | None,
        assigned_user_id: int | None,
        contact_id: uuid.UUID | None,
        unassigned: bool,
    ) -> Select[Any]:
        criteria: list[ColumnElement[bool]] = [
            Conversation.workspace_id == workspace_id
        ]

        if status is not None:
            criteria.append(Conversation.status == status)

        if unassigned:
            criteria.append(Conversation.assigned_user_id.is_(None))
        elif assigned_user_id is not None:
            criteria.append(Conversation.assigned_user_id == assigned_user_id)

        if contact_id is not None:
            criteria.append(Conversation.contact_id == contact_id)

        return statement.where(*criteria)

    def set_status(
        self,
        conversation: Conversation,
        status: ConversationStatus,
        *,
        closed_at: datetime | None = None,
        opened_at: datetime | None = None,
    ) -> Conversation:
        conversation.status = status

        # Written together with the status rather than by a separate call,
        # so a conversation cannot be closed without a closing time.
        if closed_at is not None or status != ConversationStatus.CLOSED:
            conversation.closed_at = closed_at

        if opened_at is not None:
            conversation.opened_at = opened_at

        self._session.flush()

        return conversation

    def set_assignee(
        self,
        conversation: Conversation,
        user_id: int | None,
    ) -> Conversation:
        conversation.assigned_user_id = user_id
        self._session.flush()

        return conversation

    def set_ai_mode(self, conversation: Conversation, mode: AiMode) -> Conversation:
        conversation.ai_mode = mode
        self._session.flush()

        return conversation

    def record_activity(self, conversation: Conversation, at: datetime) -> Conversation:
        """Move the conversation to the top of the inbox.

        Denormalised from messages deliberately: the alternative is a
        correlated subquery on every row of every inbox request.
        """
        conversation.last_message_at = at
        self._session.flush()

        return conversation
