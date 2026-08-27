import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.conversation_event import ConversationEvent, EventType


class ConversationEventRepository:
    """Every query against the handoff audit trail lives here.

    Workspace-scoped like the rest. This table records who took which of a
    business's conversations and when, which is exactly the sort of thing
    a query without a workspace would show to the wrong business.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        workspace_id: uuid.UUID,
        conversation_id: uuid.UUID,
        event_type: EventType,
        actor_user_id: int | None = None,
        reason: str | None = None,
    ) -> ConversationEvent:
        event = ConversationEvent(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            reason=reason,
        )

        self._session.add(event)
        self._session.flush()

        return event

    def list_for_conversation(
        self,
        workspace_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> Sequence[ConversationEvent]:
        """One thread's history, most recent first."""
        return self._session.scalars(
            select(ConversationEvent)
            .where(
                ConversationEvent.workspace_id == workspace_id,
                ConversationEvent.conversation_id == conversation_id,
            )
            .order_by(ConversationEvent.sequence.desc())
            .limit(limit)
            .offset(offset)
        ).all()

    def count_for_conversation(
        self,
        workspace_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(ConversationEvent)
                .where(
                    ConversationEvent.workspace_id == workspace_id,
                    ConversationEvent.conversation_id == conversation_id,
                )
            )
            or 0
        )
