"""Providers that answer without reaching anybody.

The suite's rule is that nothing in it makes a real call, which for the
knowledge base and the assistant means two fakes. Both are deterministic
on purpose: a test that asserts a passage was retrieved has to fail when
retrieval breaks, not when a provider happens to embed two sentences
slightly differently this week.
"""

import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.core.exceptions import EmbeddingProviderError, ReplyProviderError
from app.core.vectors import normalise
from app.integrations.embeddings.base import EmbeddingPurpose, Embeddings
from app.integrations.llm.base import (
    Completion,
    Passage,
    ReplyDraft,
    Turn,
)

# Small enough to read in a failure message, large enough that two
# unrelated sentences do not collide into the same vector.
DIMENSIONS = 64

_WORD = re.compile(r"[a-z0-9']+")


@dataclass
class FakeEmbeddingProvider:
    """Embeds by hashing words into buckets.

    A bag of words, not a language model: two texts that share words come
    out close together and two that share none come out far apart, which
    is the only property the retrieval tests actually rest on. Deliberately
    not a stand-in for real semantics -- a test that needed "returns" to
    match "send it back" would be testing the provider, and this suite
    cannot test the provider.
    """

    calls: list[tuple[list[str], EmbeddingPurpose]] = field(default_factory=list)
    fail_with: str | None = None

    def embed(
        self,
        texts: Sequence[str],
        *,
        purpose: EmbeddingPurpose,
    ) -> Embeddings:
        self.calls.append((list(texts), purpose))

        if self.fail_with is not None:
            raise EmbeddingProviderError(self.fail_with)

        return Embeddings(
            vectors=[vector_for(text) for text in texts],
            model="fake-embeddings",
            total_tokens=sum(len(text.split()) for text in texts),
        )


def vector_for(text: str) -> list[float]:
    """The same vector for the same words, every time.

    Normalised here as well as in the real provider, because the database
    computes a dot product and calls it a cosine -- an unnormalised vector
    from a fake would make every similarity in the suite meaningless
    without failing anything.
    """
    vector = [0.0] * DIMENSIONS

    for word in _WORD.findall(text.lower()):
        digest = hashlib.sha256(word.encode()).digest()
        bucket = int.from_bytes(digest[:4], "big") % DIMENSIONS
        # Term frequency, dampened. Without the log, a word repeated
        # twenty times in one passage swamps every other word in it.
        vector[bucket] += 1.0

    vector = [math.log1p(value) for value in vector]

    if not any(vector):
        # A text with no words in it at all. A vector of zeros would be
        # normalised to zeros and match nothing, which is correct, but a
        # tiny constant keeps it comparable rather than degenerate.
        vector[0] = 1e-6

    return normalise(vector)


@dataclass
class FakeReplyWriter:
    """Answers however the test told it to.

    Records what it was given, because half of what is worth asserting
    about the AI pipeline is what reached the model: that the passages
    were the workspace's own, that the instructions named the right
    business, that the thread arrived oldest-first.
    """

    reply: str = "Returns are accepted within 14 days."
    can_answer: bool = True
    confidence: float = 0.9
    fail_with: str | None = None

    calls: list[tuple[str, list[Turn], list[Passage]]] = field(default_factory=list)

    def write(
        self,
        *,
        instructions: str,
        turns: Sequence[Turn],
        passages: Sequence[Passage],
    ) -> Completion:
        self.calls.append((instructions, list(turns), list(passages)))

        if self.fail_with is not None:
            raise ReplyProviderError(self.fail_with)

        return Completion(
            draft=ReplyDraft(
                text=self.reply,
                can_answer=self.can_answer,
                confidence=self.confidence,
                used_passage_ids=[passage.id for passage in passages],
            ),
            model="fake-model",
            input_tokens=100,
            output_tokens=20,
        )

    @property
    def last_passages(self) -> list[Passage]:
        return self.calls[-1][2] if self.calls else []

    @property
    def last_turns(self) -> list[Turn]:
        return self.calls[-1][1] if self.calls else []
