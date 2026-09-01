import uuid
from datetime import datetime

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.message import Message
from app.models.subscription import Subscription
from app.models.usage_record import UsageMetric, UsageRecord
from app.models.whatsapp_account import WhatsAppAccount
from app.models.workspace_membership import (
    MembershipStatus,
    WorkspaceMembership,
)


class UsageRepository:
    """Every query metering needs, whichever table the answer is in.

    Two kinds of query, and the split is the point of the phase. The
    ledger below is written where usage happens and summed back per
    period; the counts after it are levels, read from the rows that
    define them at the moment somebody asks.

    Reaching across tables rather than owning one, like the analytics
    repository and for the same reason: metering is a question about a
    workspace, not about a table, and answering it through five other
    repositories would put the aggregate in Python.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- the ledger --------------------------------------------------------

    def record(
        self,
        *,
        workspace_id: uuid.UUID,
        metric: UsageMetric,
        quantity: int,
        period_start: datetime,
        period_end: datetime,
        source_id: uuid.UUID,
    ) -> UsageRecord:
        """Append one event.

        Flushed and not committed. A usage record belongs in the same
        transaction as the thing it meters -- the log row for an answer,
        the message for a send -- so that neither can exist without the
        other. Committing here would make them two writes, and a crash
        between them would be either an answer nobody was charged for or
        a charge for an answer that was rolled back.
        """
        record = UsageRecord(
            workspace_id=workspace_id,
            metric=metric,
            quantity=quantity,
            period_start=period_start,
            period_end=period_end,
            source_id=source_id,
        )

        self._session.add(record)
        self._session.flush()

        return record

    def total(
        self,
        workspace_id: uuid.UUID,
        metric: UsageMetric,
        *,
        period_start: datetime,
    ) -> int:
        """What one metric came to in one period."""
        return (
            self._session.scalar(
                select(func.coalesce(func.sum(UsageRecord.quantity), 0)).where(
                    UsageRecord.workspace_id == workspace_id,
                    UsageRecord.metric == metric,
                    UsageRecord.period_start == period_start,
                )
            )
            or 0
        )

    def totals(
        self,
        workspace_id: uuid.UUID,
        *,
        period_start: datetime,
    ) -> dict[UsageMetric, int]:
        """Every metered metric's total for one period, in one query.

        One query because it is one screen. A dashboard row per metric,
        each its own round trip, is the shape that makes a page slow for
        no reason -- and these all come from the same index on the same
        rows.
        """
        rows = self._session.execute(
            select(UsageRecord.metric, func.sum(UsageRecord.quantity))
            .where(
                UsageRecord.workspace_id == workspace_id,
                UsageRecord.period_start == period_start,
            )
            .group_by(UsageRecord.metric)
        ).all()

        return {metric: int(total or 0) for metric, total in rows}

    # --- the period --------------------------------------------------------

    def subscription_period(
        self,
        workspace_id: uuid.UUID,
    ) -> tuple[datetime | None, datetime | None]:
        """The dates the provider says this workspace is being billed for.

        Read here rather than through the subscription service, so that
        metering does not depend on the thing that depends on metering.
        Either date can be missing: a checkout that was started and never
        finished leaves a row with neither.
        """
        row = self._session.execute(
            select(
                Subscription.current_period_start,
                Subscription.current_period_end,
            ).where(Subscription.workspace_id == workspace_id)
        ).first()

        return (None, None) if row is None else (row[0], row[1])

    # --- the levels --------------------------------------------------------

    def team_members(self, workspace_id: uuid.UUID) -> int:
        """How many people are actually in the workspace.

        Active memberships only. An invitation is not a seat until
        somebody uses it, and a removed colleague is not one afterwards.
        """
        return (
            self._session.scalar(
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.status == MembershipStatus.ACTIVE,
                )
            )
            or 0
        )

    def whatsapp_numbers(self, workspace_id: uuid.UUID) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(WhatsAppAccount)
                .where(WhatsAppAccount.workspace_id == workspace_id)
            )
            or 0
        )

    def knowledge_documents(self, workspace_id: uuid.UUID) -> int:
        return (
            self._session.scalar(
                select(func.count())
                .select_from(KnowledgeDocument)
                .where(KnowledgeDocument.workspace_id == workspace_id)
            )
            or 0
        )

    def knowledge_tokens(self, workspace_id: uuid.UUID) -> int:
        """How much text the knowledge base holds, in what it cost to embed.

        Tokens rather than characters, because tokens are the unit the
        embedding provider charges in and the unit a retrieval budget is
        written in -- and because the number is already on the chunk, so
        this is an integer sum rather than a scan of every stored passage.

        A chunk whose provider did not report a count contributes nothing.
        That understates rather than invents, which is the same trade the
        ingestion pipeline already makes when a batch comes back silent.
        """
        return (
            self._session.scalar(
                select(func.coalesce(func.sum(KnowledgeChunk.token_count), 0)).where(
                    KnowledgeChunk.workspace_id == workspace_id
                )
            )
            or 0
        )

    def active_contacts(
        self,
        workspace_id: uuid.UUID,
        *,
        start: datetime,
        end: datetime,
    ) -> int:
        """How many of a business's customers it was actually talking to.

        Counted distinctly over the period rather than accumulated as
        events, which is the only way to get it right: a customer who
        sends twenty messages is one active contact, and a ledger of
        message events would say twenty.

        Either direction counts. A business that opened a conversation is
        as much in touch with that customer as one that answered.
        """
        return (
            self._session.scalar(
                select(func.count(distinct(Conversation.contact_id)))
                .select_from(Message)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Message.workspace_id == workspace_id,
                    Message.created_at >= start,
                    Message.created_at < end,
                )
            )
            or 0
        )
