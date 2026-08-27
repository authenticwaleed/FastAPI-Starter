from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class EmbeddingPurpose(StrEnum):
    """What a piece of text is being embedded for.

    Not decoration. Embedding providers ask for it because a question and
    the passage that answers it are not the same kind of text -- "do you
    deliver to Karachi?" and "Delivery is available nationwide" are close
    in meaning and far apart in shape. Telling the provider which is which
    measurably improves what comes back.
    """

    DOCUMENT = "document"
    QUERY = "query"


@dataclass(frozen=True)
class Embeddings:
    """Vectors for a batch of texts, in the order they were given.

    The order is the contract: nothing here carries the text back, so a
    provider that returned results out of order would silently attach
    every vector to the wrong passage.
    """

    vectors: list[list[float]]
    model: str
    total_tokens: int | None = None


class EmbeddingProvider(Protocol):
    """What the application needs an embedding provider to do.

    One method. A Protocol rather than a base class, for the reason the
    messaging one is: the fake used in tests is not this with pieces
    removed, it is a different object answering the same question.
    """

    def embed(
        self,
        texts: Sequence[str],
        *,
        purpose: EmbeddingPurpose,
    ) -> Embeddings:
        """Vectors for these texts, or raise EmbeddingProviderError."""
        ...
