from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.automation import (
    AutomationKind,
    AutomationStatus,
    AutomationTrigger,
    RunStatus,
)


class AutomationCreate(BaseModel):
    """Switch one of the predefined automations on.

    `kind` names one of the ones that exist rather than describing a new
    one, which is the plan's instruction for this phase as a schema: this
    is a settings form, not a workflow builder.
    """

    kind: AutomationKind

    # Defaulted from the kind when it is left out, because "Order
    # confirmation" is what most businesses will call it.
    name: Annotated[str, Field(min_length=1, max_length=120)] | None = None

    status: AutomationStatus = AutomationStatus.ENABLED

    # Free-shaped here and validated against the schema the named
    # automation declares, which is the only place that knows what a
    # setting means. An empty object takes every default.
    definition: dict[str, Any] = Field(default_factory=dict)


class AutomationUpdate(BaseModel):
    """A partial update. An omitted field means "leave this alone".

    The kind is not here. Changing what an automation *is* would leave
    its history describing something else, and switching one off and
    another on says the same thing without that.
    """

    name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    status: AutomationStatus | None = None
    definition: dict[str, Any] | None = None


class AutomationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: AutomationKind
    name: str
    trigger_type: AutomationTrigger
    status: AutomationStatus
    definition: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RunRead(BaseModel):
    """One attempt, and what became of it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    automation_id: UUID
    status: RunStatus
    # What this run was about, when it was about something: an order, a
    # message, a conversation. Null for a run that may happen again.
    dedupe_key: str | None
    attempts: int
    started_at: datetime
    completed_at: datetime | None
    error: str | None
    # Reads the model's `meta`, which carries the column the plan calls
    # `metadata`: the name is taken on a declarative class.
    metadata: dict[str, Any] = Field(validation_alias="meta")


class RunPage(BaseModel):
    items: list[RunRead]
    total: int
    page: int
    page_size: int


class SweepReport(BaseModel):
    """What one due-run sweep did.

    `ran` counts the automations that actually did something; `considered`
    counts every run recorded, most of which are skips. The gap between
    them is the useful number -- it is how much work the sweep looked at
    and correctly left alone.
    """

    considered: int
    ran: int
