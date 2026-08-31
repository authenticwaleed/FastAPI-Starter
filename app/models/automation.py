import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import enum_column


class AutomationKind(StrEnum):
    """Which of the predefined automations this row configures.

    The plan is explicit that a visual workflow builder is not what to
    build first, so `definition` below holds *settings for a known
    automation* rather than a program. What each one does is code, in
    app/services/automations.py; what a business chooses is when it runs
    and what it says.

    Three, of the plan's six. The other three are not missing so much as
    already here or not yet possible, and both are worth saying:

    FAQ auto-response and order status response are what the assistant
    already does, driven by a conversation's `ai_mode` -- retrieval, the
    catalogue lookup and this customer's orders, all of it since Phase 11.
    Building them again here would be a second path to the same reply
    with a second set of bugs, which is the one thing this phase's plan
    tells us not to do.

    Abandoned cart follow-up needs a cart, and nothing in this product has
    one: a cart is a thing a storefront holds until it becomes an order,
    and neither the schema nor the Shopify subscription has ever seen one.
    That is a table and a webhook topic, not a setting.
    """

    ORDER_CONFIRMATION = "order_confirmation"
    HUMAN_HANDOFF = "human_handoff"
    UNANSWERED_LEAD_FOLLOWUP = "unanswered_lead_followup"


class AutomationTrigger(StrEnum):
    """What has to happen for an automation to be considered.

    Stored on the row as well as being a property of the kind, because the
    plan's `automations` names it and because it is what a list endpoint
    groups by -- "what runs when a customer writes in" is the question a
    person asks of this screen.
    """

    MESSAGE_RECEIVED = "message_received"
    ORDER_CREATED = "order_created"
    # Not an event: something has failed to happen for long enough. Found
    # by a sweep rather than fired by anything, which is why the engine
    # has a due-run entry point at all.
    SCHEDULE = "schedule"


class AutomationStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"


class RunStatus(StrEnum):
    """How one attempt at one automation ended.

    `skipped` is not a failure and is the most common outcome by far: an
    automation is considered on every matching event, and most events are
    not the one it is for. A message with none of the handoff keywords in
    it is a skip, and a table where those were errors would be a table
    nobody reads.
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class Automation(Base):
    """One predefined automation, as one business has configured it."""

    __tablename__ = "automations"

    __table_args__ = (
        # One configuration per kind per workspace. Two "order
        # confirmation" rows would be two messages to the same customer
        # about the same order, and no screen would explain why.
        UniqueConstraint(
            "workspace_id",
            "kind",
            name="uq_automations_workspace_id_kind",
        ),
        # The target of the composite foreign key on runs, so a run cannot
        # point at another workspace's automation.
        UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_automations_workspace_id_id",
        ),
        # What the engine asks on every event: this workspace's enabled
        # automations for this trigger.
        Index(
            "ix_automations_workspace_id_trigger_type",
            "workspace_id",
            "trigger_type",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )

    kind: Mapped[AutomationKind] = mapped_column(
        enum_column(AutomationKind, name="automation_kind"),
    )

    # What a person calls it. Defaulted from the kind and editable,
    # because "Order confirmation" is what most businesses will leave it
    # as and "Ali's follow-up" is what one of them will want.
    name: Mapped[str] = mapped_column(String(120))

    trigger_type: Mapped[AutomationTrigger] = mapped_column(
        enum_column(AutomationTrigger, name="automation_trigger"),
    )

    status: Mapped[AutomationStatus] = mapped_column(
        enum_column(AutomationStatus, name="automation_status"),
        default=AutomationStatus.ENABLED,
        server_default=text("'enabled'"),
    )

    # Settings for a known automation, not a program. Validated against
    # the schema its kind declares before it is ever written, so a row
    # here cannot carry something the code that reads it will not
    # understand.
    definition: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"Automation(id={self.id!r}, kind={self.kind!r})"


class AutomationRun(Base):
    """One attempt at one automation, and what became of it.

    The run history the plan asks for, and the thing that makes an
    automation debuggable at all: an automation that quietly does nothing
    is indistinguishable from one that is switched off, and this table is
    the difference.
    """

    __tablename__ = "automation_runs"

    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "automation_id"],
            ["automations.workspace_id", "automations.id"],
            ondelete="CASCADE",
            name="fk_automation_runs_automation_in_same_workspace",
        ),
        # "Duplicate execution prevented where required", as a constraint
        # rather than as a check somebody remembers. An order confirmation
        # is keyed on the order and a handoff on the message, so a
        # redelivered webhook cannot produce a second message to the same
        # customer. NULLs are distinct in PostgreSQL, so the runs with
        # nothing to be keyed on -- a scheduled sweep -- do not collide.
        UniqueConstraint(
            "automation_id",
            "dedupe_key",
            name="uq_automation_runs_automation_id_dedupe_key",
        ),
        Index(
            "ix_automation_runs_workspace_id_started_at",
            "workspace_id",
            text("started_at DESC"),
        ),
        Index(
            "ix_automation_runs_automation_id_started_at",
            "automation_id",
            text("started_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid)

    automation_id: Mapped[uuid.UUID]

    status: Mapped[RunStatus] = mapped_column(
        enum_column(RunStatus, name="automation_run_status"),
        default=RunStatus.RUNNING,
    )

    # What this run is *about*, when it is about something: an order id,
    # a message id. Null for a run that could happen again tomorrow and
    # should be allowed to.
    dedupe_key: Mapped[str | None] = mapped_column(String(120), default=None)

    # How many times this was tried. The retry policy is the kind's, and
    # the count is here because "it worked on the third go" and "it worked
    # first time" are different things to know about an integration.
    attempts: Mapped[int] = mapped_column(default=1, server_default=text("1"))

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )

    # What went wrong, for a person reading the history. Text rather than
    # a code: what is useful here is the provider's own complaint, and the
    # set of things that can go wrong is not one anybody can enumerate.
    error: Mapped[str | None] = mapped_column(Text, default=None)

    meta: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    def __repr__(self) -> str:
        return f"AutomationRun(id={self.id!r}, status={self.status!r})"
