import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai_response_log import AiDecision, AiResponseLog


class AiResponseLogRepository:
    """Every query against the assistant's own record lives here.

    Workspace-scoped like the rest, and for a sharper reason than usual:
    this table records what was asked and what was answered, so a query
    that would answer without a workspace is a query that would show one
    business how another's assistant behaves.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID | None,
        decision: AiDecision,
        prompt_version: str,
        reply_text: str | None = None,
        sent_message_id: uuid.UUID | None = None,
        reason: str | None = None,
        model: str | None = None,
        retrieval_query: str | None = None,
        retrieved_chunk_ids: Sequence[uuid.UUID] = (),
        confidence: float | None = None,
        latency_ms: int | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> AiResponseLog:
        log = AiResponseLog(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            message_id=message_id,
            decision=decision,
            prompt_version=prompt_version,
            reply_text=reply_text,
            sent_message_id=sent_message_id,
            reason=reason,
            model=model,
            retrieval_query=retrieval_query,
            retrieved_chunk_ids=list(retrieved_chunk_ids),
            confidence=confidence,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        self._session.add(log)
        self._session.flush()

        return log

    def record_sent(self, log: AiResponseLog, message_id: uuid.UUID) -> AiResponseLog:
        """Tie the decision to the reply it produced."""
        log.sent_message_id = message_id
        self._session.flush()

        return log

    def list_for_conversation(
        self,
        workspace_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> Sequence[AiResponseLog]:
        """One thread's decisions, most recent first.

        The order somebody asking "why did it hand this over" wants: the
        thing that just happened, then what led to it.
        """
        return self._session.scalars(
            select(AiResponseLog)
            .where(
                AiResponseLog.workspace_id == workspace_id,
                AiResponseLog.conversation_id == conversation_id,
            )
            .order_by(AiResponseLog.sequence.desc())
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
                .select_from(AiResponseLog)
                .where(
                    AiResponseLog.workspace_id == workspace_id,
                    AiResponseLog.conversation_id == conversation_id,
                )
            )
            or 0
        )

    def get_for_message(
        self,
        workspace_id: uuid.UUID,
        message_id: uuid.UUID,
    ) -> AiResponseLog | None:
        """The latest thing the assistant decided about this message.

        What keeps it from replying twice when a webhook is delivered
        again. Newest first because a message can be looked at more than
        once -- a run that failed and a person who then pressed the button
        are two rows, and the one that matters is the last.
        """
        return self._session.scalar(
            select(AiResponseLog)
            .where(
                AiResponseLog.workspace_id == workspace_id,
                AiResponseLog.message_id == message_id,
            )
            .order_by(AiResponseLog.sequence.desc())
            .limit(1)
        )
