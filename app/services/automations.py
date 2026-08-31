"""The predefined automations, and what each of them actually does.

The plan's instruction for this phase is not to build a visual workflow
builder first, and to start with a small set of predefined automations.
So an `automations` row is not a program: it is settings for one of the
three below, all of which are code. What a business chooses is whether it
runs, when, and what it says.

Each one declares the shape of its own settings, so a definition is
validated against the automation that will read it before it is ever
stored -- which is what stops a row existing that the code cannot make
sense of.

Nothing here commits. The engine owns the transaction, because a run's
outcome and the work it did have to land together: a message sent and no
run recorded is a message that will be sent again tomorrow.
"""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Protocol

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.automation import AutomationKind, AutomationTrigger
from app.models.conversation import Channel, Conversation, ConversationStatus
from app.models.conversation_event import EventType
from app.models.message import SenderType
from app.models.order import Order
from app.models.workspace import Workspace
from app.repositories.automation_repository import AutomationRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.conversation_event_repository import (
    ConversationEventRepository,
)
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.order_repository import OrderRepository
from app.schemas.message import MessageCreate
from app.services.message_service import MessageService

# How many dropped leads one sweep will follow up. A cap rather than a
# target: a workspace that switches this on after six quiet months should
# send a handful of messages and then some more tomorrow, not eight
# hundred at once to people who have long since bought elsewhere.
FOLLOWUP_BATCH = 25


@dataclass(frozen=True)
class Trigger:
    """What happened, in the engine's vocabulary rather than a caller's.

    One shape for every trigger, with the fields that do not apply left
    out. The alternative -- a class per trigger -- would put a match
    statement in the engine and buy nothing: an automation reads the two
    fields it cares about and the engine reads none of them.
    """

    type: AutomationTrigger
    workspace: Workspace
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None


@dataclass
class Tools:
    """Everything an automation is allowed to reach.

    A fixed set, handed over rather than constructed, for the reason
    ai_dispatch hands its providers over: work that outlives the request
    which scheduled it must keep a test's fakes in force. That it is a
    fixed set is also the point -- an automation cannot quietly acquire a
    new capability without this list growing, in one place, on purpose.
    """

    session: Session
    messages: MessageService
    message_repository: MessageRepository
    conversations: ConversationRepository
    events: ConversationEventRepository
    contacts: ContactRepository
    orders: OrderRepository
    automations: AutomationRepository


@dataclass(frozen=True)
class Outcome:
    """What one run did, or why it did nothing.

    `skipped` is not a failure and is the ordinary answer. An automation
    is considered on every matching event, and most events are not the
    one it is for.
    """

    ran: bool
    detail: dict[str, Any]

    @classmethod
    def did(cls, **detail: Any) -> "Outcome":
        return cls(ran=True, detail=detail)

    @classmethod
    def skipped(cls, why: str, **detail: Any) -> "Outcome":
        return cls(ran=False, detail={"skipped": why, **detail})


class Automation(Protocol):
    """One predefined automation.

    `dedupe_key` is what makes "duplicate execution prevented where
    required" a database constraint rather than an intention. An
    automation that returns one is saying that running twice for this
    thing would be wrong; one that returns None is saying the opposite,
    and both are decisions worth writing down per automation rather than
    guessing at centrally.
    """

    @property
    def kind(self) -> AutomationKind: ...

    @property
    def trigger(self) -> AutomationTrigger: ...

    @property
    def default_name(self) -> str: ...

    @property
    def settings_model(self) -> type[BaseModel]: ...

    @property
    def max_attempts(self) -> int: ...

    def dedupe_key(self, trigger: Trigger) -> str | None: ...

    def run(self, tools: Tools, trigger: Trigger, settings: Any) -> Outcome: ...


# --- order confirmation ----------------------------------------------------


class OrderConfirmationSettings(BaseModel):
    """What to say when an order arrives.

    The placeholders are a fixed list rather than an expression language,
    which is the same decision the phase makes about workflows: a
    business writes a sentence, not a program.
    """

    template: Annotated[str, Field(min_length=1, max_length=1000)] = (
        "Thanks for your order {order_number}! "
        "We have received it and will let you know when it ships."
    )


class OrderConfirmation:
    """Message the customer when an order is recorded.

    Keyed on the order, so a Shopify webhook redelivered an hour later
    cannot thank somebody twice for the same purchase.

    Deliberately does not fire during a storefront's first sync. That is
    enforced by the caller rather than here -- see
    EcommerceSyncService.upsert_order -- because it is a property of how
    the order arrived rather than of the order, and getting it wrong
    means messaging every customer a shop has ever had the moment it
    connects.
    """

    kind = AutomationKind.ORDER_CONFIRMATION
    trigger = AutomationTrigger.ORDER_CREATED
    default_name = "Order confirmation"
    settings_model = OrderConfirmationSettings
    # A send that fails is usually the provider being briefly unavailable,
    # and the message is worth a second go. Three, and then it is a failed
    # run somebody can see rather than a message nobody knows was lost.
    max_attempts = 3

    def dedupe_key(self, trigger: Trigger) -> str | None:
        return f"order:{trigger.order_id}"

    def run(
        self,
        tools: Tools,
        trigger: Trigger,
        settings: OrderConfirmationSettings,
    ) -> Outcome:
        workspace = trigger.workspace

        if trigger.order_id is None:
            return Outcome.skipped("no_order")

        order = tools.orders.get(workspace.id, trigger.order_id)

        if order is None:
            return Outcome.skipped("order_gone")

        contact = tools.contacts.get(workspace.id, order.contact_id)

        if contact is None:
            return Outcome.skipped("contact_gone")

        conversation = _thread_for(tools, workspace.id, contact.id)
        text = _fill(settings.template, _order_fields(order))

        message = tools.messages.send(
            workspace,
            conversation.id,
            MessageCreate(text=text),
            # Not `agent`: nobody typed this. A thread where an automated
            # message is attributed to a person is a thread where the
            # person is asked why they said it.
            sender_type=SenderType.SYSTEM,
        )

        return Outcome.did(message_id=str(message.id), order_id=str(order.id))


# --- human handoff ---------------------------------------------------------


class HumanHandoffSettings(BaseModel):
    """When to stop answering and fetch somebody.

    Keywords rather than a model, and that is not a shortcut. The
    assistant already hands over when it cannot answer, judged on the
    evidence it was given; this is for the customer who is not asking a
    question at all -- who is angry, or has said the word "refund" -- and
    for that a business wants a list it can read and edit, not a
    confidence score.
    """

    keywords: list[Annotated[str, Field(min_length=2, max_length=40)]] = Field(
        default_factory=lambda: [
            "agent",
            "human",
            "person",
            "manager",
            "complaint",
            "refund",
            "cancel my order",
            "speak to someone",
        ]
    )

    # Sent before the handoff, so the customer is not left with silence
    # while somebody is found. Optional: a business whose agents answer
    # within a minute may prefer to say nothing.
    acknowledgement: Annotated[str, Field(max_length=1000)] | None = (
        "One moment -- I am getting a colleague to help you."
    )


class HumanHandoff:
    """Hand a thread to a person when the customer asks for one.

    Keyed on the message, so a redelivered webhook cannot acknowledge the
    same request twice.
    """

    kind = AutomationKind.HUMAN_HANDOFF
    trigger = AutomationTrigger.MESSAGE_RECEIVED
    default_name = "Hand over to a person"
    settings_model = HumanHandoffSettings
    max_attempts = 3

    def dedupe_key(self, trigger: Trigger) -> str | None:
        return f"message:{trigger.message_id}"

    def run(
        self,
        tools: Tools,
        trigger: Trigger,
        settings: HumanHandoffSettings,
    ) -> Outcome:
        workspace = trigger.workspace

        if trigger.conversation_id is None or trigger.message_id is None:
            return Outcome.skipped("no_message")

        conversation = tools.conversations.get(workspace.id, trigger.conversation_id)
        message = tools.message_repository.get(workspace.id, trigger.message_id)

        if conversation is None or message is None:
            return Outcome.skipped("gone")

        if conversation.is_with_a_human:
            # Somebody is already on it. Handing over again would move
            # nothing and acknowledging again would be a second promise.
            return Outcome.skipped("already_with_a_human")

        matched = _first_keyword(message.text_body or "", settings.keywords)

        if matched is None:
            return Outcome.skipped("no_keyword")

        detail: dict[str, Any] = {"keyword": matched}

        if settings.acknowledgement:
            sent = tools.messages.send(
                workspace,
                conversation.id,
                MessageCreate(text=settings.acknowledgement),
                sender_type=SenderType.SYSTEM,
            )
            detail["message_id"] = str(sent.id)

        # `hand_over` rather than `take_over`: nobody has claimed this, so
        # it belongs in the unassigned queue where the next free agent
        # will see it, not quietly on somebody's list.
        tools.conversations.hand_over(
            conversation,
            at=datetime.now(UTC),
            reason=f"customer asked for a person: {matched}",
        )
        tools.events.record(
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            event_type=EventType.AI_HANDOFF,
            reason=f"automation: {matched}",
        )

        return Outcome.did(**detail)


# --- follow-up after an unanswered lead ------------------------------------


class UnansweredLeadSettings(BaseModel):
    after_hours: Annotated[int, Field(ge=1, le=168)] = 24
    template: Annotated[str, Field(min_length=1, max_length=1000)] = (
        "Hi{name}, sorry for the wait -- are you still looking for help? "
        "We are here whenever you need us."
    )


class UnansweredLeadFollowup:
    """Nudge a customer nobody ever replied to.

    The one automation nothing fires. It is not about an event; it is
    about an event failing to happen, so it is found by a sweep -- which
    is why the engine has a due-run entry point and why that entry point
    is what a scheduler will eventually call.

    Keyed on the conversation, so a lead is nudged once ever rather than
    once per sweep. That is a stronger rule than it looks: without it,
    every sweep would find the same dropped thread and send the same
    message again, for as long as it stayed dropped.
    """

    kind = AutomationKind.UNANSWERED_LEAD_FOLLOWUP
    trigger = AutomationTrigger.SCHEDULE
    default_name = "Follow up an unanswered lead"
    settings_model = UnansweredLeadSettings
    max_attempts = 2

    def dedupe_key(self, trigger: Trigger) -> str | None:
        return f"conversation:{trigger.conversation_id}"

    def due(
        self,
        tools: Tools,
        workspace: Workspace,
        settings: UnansweredLeadSettings,
    ) -> Sequence[Conversation]:
        """The threads this sweep should consider, oldest first."""
        return tools.automations.unanswered_conversations(
            workspace.id,
            before=datetime.now(UTC) - timedelta(hours=settings.after_hours),
            limit=FOLLOWUP_BATCH,
        )

    def run(
        self,
        tools: Tools,
        trigger: Trigger,
        settings: UnansweredLeadSettings,
    ) -> Outcome:
        workspace = trigger.workspace

        if trigger.conversation_id is None:
            return Outcome.skipped("no_conversation")

        conversation = tools.conversations.get(workspace.id, trigger.conversation_id)

        if conversation is None or conversation.status == ConversationStatus.CLOSED:
            return Outcome.skipped("gone_or_closed")

        contact = tools.contacts.get(workspace.id, conversation.contact_id)
        greeting = f" {contact.name}" if contact and contact.name else ""

        message = tools.messages.send(
            workspace,
            conversation.id,
            MessageCreate(text=_fill(settings.template, {"name": greeting})),
            sender_type=SenderType.SYSTEM,
        )

        return Outcome.did(
            message_id=str(message.id),
            conversation_id=str(conversation.id),
        )


CATALOGUE: dict[AutomationKind, Automation] = {
    AutomationKind.ORDER_CONFIRMATION: OrderConfirmation(),
    AutomationKind.HUMAN_HANDOFF: HumanHandoff(),
    AutomationKind.UNANSWERED_LEAD_FOLLOWUP: UnansweredLeadFollowup(),
}


def _thread_for(
    tools: Tools,
    workspace_id: uuid.UUID,
    contact_id: uuid.UUID,
) -> Conversation:
    """The thread to say this in, opening one if there is none.

    The same rule inbound messages follow: a live thread if there is one,
    the most recent closed one reopened if there is not, and a new one
    only when this customer has never been spoken to. A business
    confirming an order should not open a second thread beside the one
    where the customer asked about it.
    """
    live = tools.conversations.get_live_for_contact(
        workspace_id,
        contact_id,
        Channel.WHATSAPP,
    )

    if live is not None:
        return live

    closed = tools.conversations.get_latest_closed_for_contact(
        workspace_id,
        contact_id,
        Channel.WHATSAPP,
    )

    if closed is not None:
        return tools.conversations.set_status(
            closed,
            ConversationStatus.OPEN,
            opened_at=datetime.now(UTC),
        )

    return tools.conversations.create(
        workspace_id=workspace_id,
        contact_id=contact_id,
        channel=Channel.WHATSAPP,
    )


def _order_fields(order: Order) -> dict[str, str]:
    return {
        "order_number": order.order_number or "",
        "status": order.status.value,
        "total": _money(order.total, order.currency),
        "tracking_number": order.tracking_number or "",
        "tracking_url": order.tracking_url or "",
    }


def _money(amount: Decimal | None, currency: str | None) -> str:
    if amount is None:
        return ""

    return f"{amount.normalize():f} {currency or ''}".strip()


def _fill(template: str, fields: dict[str, str]) -> str:
    """Substitute the placeholders this automation offers, and no others.

    `str.format` would evaluate whatever somebody put in the template,
    including attribute access on the values -- which is how a message
    template becomes a way to read the inside of the process that renders
    it. This replaces a fixed set of names and leaves everything else
    exactly as it was written.
    """
    for name, value in fields.items():
        template = template.replace("{" + name + "}", value)

    return template


def _first_keyword(text: str, keywords: Sequence[str]) -> str | None:
    """The first configured phrase this message contains, if any.

    Matched on word boundaries so that "cancel" does not fire on
    "cancellation policy", and lowercased on both sides because nobody
    types consistently. A phrase with a space in it is matched whole,
    which is why this is a regex rather than a set of tokens.
    """
    haystack = text.lower()

    for keyword in keywords:
        needle = keyword.strip().lower()

        if needle and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack):
            return keyword

    return None
