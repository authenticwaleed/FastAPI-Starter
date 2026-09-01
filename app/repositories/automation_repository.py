import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.automation import (
    Automation,
    AutomationKind,
    AutomationRun,
    AutomationStatus,
    AutomationTrigger,
    RunStatus,
)
from app.models.conversation import Channel, Conversation, ConversationStatus
from app.models.message import Direction, Message


class AutomationRepository:
    """Every query against the automation tables lives here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- automations -------------------------------------------------------

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        kind: AutomationKind,
        name: str,
        trigger_type: AutomationTrigger,
        status: AutomationStatus,
        definition: dict[str, Any],
    ) -> Automation:
        automation = Automation(
            workspace_id=workspace_id,
            kind=kind,
            name=name,
            trigger_type=trigger_type,
            status=status,
            definition=definition,
        )

        self._session.add(automation)
        self._session.flush()

        return automation

    def get(
        self,
        workspace_id: uuid.UUID,
        automation_id: uuid.UUID,
    ) -> Automation | None:
        return self._session.scalar(
            select(Automation).where(
                Automation.id == automation_id,
                Automation.workspace_id == workspace_id,
            )
        )

    def get_by_kind(
        self,
        workspace_id: uuid.UUID,
        kind: AutomationKind,
    ) -> Automation | None:
        return self._session.scalar(
            select(Automation).where(
                Automation.workspace_id == workspace_id,
                Automation.kind == kind,
            )
        )

    def list_for_workspace(self, workspace_id: uuid.UUID) -> Sequence[Automation]:
        """All of them, enabled or not.

        Unpaged, deliberately: there are as many rows here as there are
        predefined automations, and a page control over a list of three
        would be furniture.
        """
        return self._session.scalars(
            select(Automation)
            .where(Automation.workspace_id == workspace_id)
            .order_by(Automation.kind)
        ).all()

    def list_enabled_for(
        self,
        workspace_id: uuid.UUID,
        trigger: AutomationTrigger,
    ) -> Sequence[Automation]:
        """What the engine asks on every event."""
        return self._session.scalars(
            select(Automation)
            .where(
                Automation.workspace_id == workspace_id,
                Automation.trigger_type == trigger,
                Automation.status == AutomationStatus.ENABLED,
            )
            .order_by(Automation.kind)
        ).all()

    def workspace_ids_with_enabled(
        self,
        trigger: AutomationTrigger,
    ) -> Sequence[uuid.UUID]:
        """Which businesses have this kind of automation switched on.

        The one query in this file that is not workspace-scoped, and it is
        deliberately narrow: it returns ids and nothing else, because what
        asks it is the sweep deciding whom to plan work for. Everything it
        then does is scoped to one of those ids at a time.

        Distinct, because a workspace with two scheduled automations is
        still one workspace to sweep -- the sweep looks at all of them.
        """
        return self._session.scalars(
            select(Automation.workspace_id)
            .where(
                Automation.trigger_type == trigger,
                Automation.status == AutomationStatus.ENABLED,
            )
            .distinct()
            .order_by(Automation.workspace_id)
        ).all()

    def update(
        self,
        automation: Automation,
        *,
        name: str | None = None,
        status: AutomationStatus | None = None,
        definition: dict[str, Any] | None = None,
    ) -> Automation:
        if name is not None:
            automation.name = name

        if status is not None:
            automation.status = status

        if definition is not None:
            automation.definition = definition

        self._session.flush()

        return automation

    def delete(self, automation: Automation) -> None:
        self._session.delete(automation)
        self._session.flush()

    # --- runs --------------------------------------------------------------

    def start_run(
        self,
        *,
        workspace_id: uuid.UUID,
        automation_id: uuid.UUID,
        dedupe_key: str | None,
    ) -> AutomationRun:
        """Claim the right to run, by writing the row that says so.

        Written before the work rather than after it. The unique index on
        (automation_id, dedupe_key) is what prevents a duplicate, and an
        index only prevents anything if the row exists before the second
        attempt looks -- which means the claim has to come first and the
        outcome afterwards.
        """
        run = AutomationRun(
            workspace_id=workspace_id,
            automation_id=automation_id,
            dedupe_key=dedupe_key,
            status=RunStatus.RUNNING,
        )

        self._session.add(run)
        self._session.flush()

        return run

    def finish_run(
        self,
        run: AutomationRun,
        *,
        status: RunStatus,
        at: datetime,
        attempts: int = 1,
        error: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AutomationRun:
        run.status = status
        run.completed_at = at
        run.attempts = attempts
        run.error = error
        run.meta = meta or {}
        self._session.flush()

        return run

    def list_runs(
        self,
        workspace_id: uuid.UUID,
        automation_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        status: RunStatus | None = None,
    ) -> Sequence[AutomationRun]:
        """One page of history, most recent first."""
        statement = select(AutomationRun).where(
            AutomationRun.workspace_id == workspace_id,
            AutomationRun.automation_id == automation_id,
        )

        if status is not None:
            statement = statement.where(AutomationRun.status == status)

        return self._session.scalars(
            statement.order_by(AutomationRun.started_at.desc(), AutomationRun.id)
            .limit(limit)
            .offset(offset)
        ).all()

    def count_runs(
        self,
        workspace_id: uuid.UUID,
        automation_id: uuid.UUID,
        *,
        status: RunStatus | None = None,
    ) -> int:
        statement = (
            select(func.count())
            .select_from(AutomationRun)
            .where(
                AutomationRun.workspace_id == workspace_id,
                AutomationRun.automation_id == automation_id,
            )
        )

        if status is not None:
            statement = statement.where(AutomationRun.status == status)

        return self._session.scalar(statement) or 0

    # --- what a scheduled automation looks for -----------------------------

    def unanswered_conversations(
        self,
        workspace_id: uuid.UUID,
        *,
        before: datetime,
        limit: int,
    ) -> Sequence[Conversation]:
        """Threads a customer opened that nobody has ever replied to.

        "Never replied to" rather than "not replied to recently", and the
        difference is the whole point: a conversation somebody answered
        last week and has since gone quiet is a conversation with a
        history, and a stranger's automated nudge is the wrong thing to
        put in it. What this finds is a lead that was dropped.

        Closed threads are left out. Somebody closed it, which is an
        answer of a kind.
        """
        answered = select(Message.id).where(
            Message.workspace_id == Conversation.workspace_id,
            Message.conversation_id == Conversation.id,
            Message.direction == Direction.OUTBOUND,
        )

        return self._session.scalars(
            select(Conversation)
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.status != ConversationStatus.CLOSED,
                Conversation.channel == Channel.WHATSAPP,
                Conversation.last_message_at.is_not(None),
                Conversation.last_message_at < before,
                ~answered.exists(),
            )
            .order_by(Conversation.last_message_at)
            .limit(limit)
        ).all()
