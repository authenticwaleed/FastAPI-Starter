from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.ai_response_log import AiDecision


class AiReplyRead(BaseModel):
    """What the assistant decided about one customer message.

    `decision` is the field to branch on, not `text`. A reply with no text
    is the normal shape of a handoff, and a client that checks the text
    first will treat "a person should take this" as an empty answer.
    """

    decision: AiDecision
    text: str | None
    confidence: float | None
    # Why, in a word, when there is one: `no_knowledge`, `low_confidence`,
    # `cannot_answer`, `ai_disabled`, `provider_error`.
    reason: str | None
    # The chunks the answer was grounded in. Returned so a pilot can check
    # an answer against its evidence, which is the only way to find out
    # whether a knowledge base is good enough to switch on.
    sources: list[UUID]
    # Present when the decision was `answered` and the reply went out.
    message_id: UUID | None = None


class AiResponseLogRead(BaseModel):
    """One entry in the assistant's history for a conversation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    message_id: UUID | None
    decision: AiDecision
    reply_text: str | None
    # The reply that went out, when one did. What ties a decision to the
    # message a customer actually received.
    sent_message_id: UUID | None
    reason: str | None
    model: str | None
    prompt_version: str
    confidence: float | None
    retrieved_chunk_ids: list[UUID]
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime


class AiResponseLogPage(BaseModel):
    items: list[AiResponseLogRead]
    total: int
    page: int
    page_size: int
