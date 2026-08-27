from datetime import date

from pydantic import BaseModel


class DayPoint(BaseModel):
    """One day of a chart. Days with nothing in them are present as zero."""

    day: date
    count: int


class ConversationTotals(BaseModel):
    total: int
    open: int
    pending: int
    closed: int
    # How many are in a person's hands, or waiting for one.
    with_a_human: int
    unassigned: int


class MessageTotals(BaseModel):
    total: int
    received: int
    sent: int
    by_ai: int
    by_agents: int


class HandledTotals(BaseModel):
    """Conversations somebody replied in, split by who.

    A thread both the assistant and an agent spoke in counts in both, which
    is right -- it was handled by both -- and is why these do not sum to
    `answered`.
    """

    answered: int
    by_ai: int
    by_agents: int


class Overview(BaseModel):
    """The headline row of a dashboard, in one response."""

    conversations: ConversationTotals
    messages: MessageTotals
    handled: HandledTotals
    handoffs: int
    ai_decisions: int
    # Of the conversations somebody answered, the share the assistant
    # spoke in. Zero when nothing has been answered at all.
    ai_response_rate: float
    # Null when nothing in the period has been answered yet, which is an
    # honest "no data" rather than a zero that reads as instant.
    average_first_response_seconds: float | None


class ConversationAnalytics(BaseModel):
    totals: ConversationTotals
    by_day: list[DayPoint]
    average_first_response_seconds: float | None


class AiDecisionTotals(BaseModel):
    total: int
    answered: int
    suggested: int
    handoff: int
    blocked: int
    failed: int


class HandoffTotals(BaseModel):
    total: int
    ai_handoff: int
    human_takeover: int
    ai_released: int


class AiCost(BaseModel):
    """What the assistant spent. Null where nothing was recorded."""

    input_tokens: int | None
    output_tokens: int | None
    average_latency_ms: float | None
    average_confidence: float | None


class AiAnalytics(BaseModel):
    decisions: AiDecisionTotals
    handoffs: HandoffTotals
    cost: AiCost
    by_day: list[DayPoint]
    # Of the conversations somebody answered, the share the assistant
    # spoke in: what a business is buying.
    response_rate: float
    # Of the times it was asked, how often it produced something to send:
    # whether the knowledge base is good enough yet. A different question.
    answer_rate: float
