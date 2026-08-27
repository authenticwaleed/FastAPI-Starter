from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Turn:
    """One thing that was said, and who said it.

    Deliberately not the provider's message shape. What the assistant
    needs to know about a conversation is who spoke and what they said;
    everything else in a Message row -- delivery status, provider ids,
    channel -- is bookkeeping that would only make the prompt longer.
    """

    from_customer: bool
    text: str


@dataclass(frozen=True)
class Passage:
    """One piece of the business's own knowledge, offered as evidence.

    Carries its id because the model is asked to say which passages it
    used, and an answer that cannot be traced to a source is exactly what
    the plan says not to ship.
    """

    id: str
    content: str
    title: str | None = None


@dataclass(frozen=True)
class ReplyDraft:
    """What the model came back with.

    `can_answer` is separate from `text` on purpose. A model asked to
    answer will nearly always produce something; asking it to say whether
    the evidence actually supported an answer is what turns "it wrote
    something" into a decision the pipeline can act on.
    """

    text: str
    can_answer: bool
    confidence: float
    used_passage_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Completion:
    """A draft, and what producing it cost."""

    draft: ReplyDraft
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class ReplyWriter(Protocol):
    """What the application needs a language model to do.

    One method, taking this application's vocabulary and returning it. The
    prompt, the model id, the response format and the retry behaviour all
    live behind it.
    """

    def write(
        self,
        *,
        instructions: str,
        turns: Sequence[Turn],
        passages: Sequence[Passage],
    ) -> Completion:
        """Draft a reply, or raise ReplyProviderError."""
        ...
