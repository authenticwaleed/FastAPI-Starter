import logging
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import Depends

from app.core import text as text_tools
from app.core.exceptions import EmbeddingProviderError
from app.integrations.embeddings.base import (
    EmbeddingProvider,
    EmbeddingPurpose,
)
from app.repositories.knowledge_repository import KnowledgeRepository
from app.services.knowledge_service import (
    EmbeddingProviderDep,
    KnowledgeRepositoryDep,
)

logger = logging.getLogger(__name__)

# How close a passage has to be before it counts as evidence. Cosine
# similarity, so 1.0 is identical and 0.0 is unrelated. 0.35 is a floor
# rather than a threshold of confidence: below it the passages returned are
# reliably about something else, and an assistant handed those will either
# say something wrong or say something irrelevant with conviction.
MIN_SCORE = 0.35

# Enough passages that an answer spread over two of them is whole, few
# enough that the model is not choosing between eleven near-duplicates.
DEFAULT_LIMIT = 5


@dataclass(frozen=True)
class Match:
    """One passage that came back, and how close it was."""

    document_id: uuid.UUID
    chunk_id: uuid.UUID
    score: float
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Retrieval:
    """What was searched for, and what was found.

    Empty matches is an ordinary outcome and not an error: a workspace
    with no knowledge base, a question about something nobody wrote down,
    a question in a language the documents are not in. What matters is
    that it comes back as an empty list rather than as an exception, so
    the caller decides what to do about knowing nothing.
    """

    query: str
    matches: list[Match] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.matches

    @property
    def best_score(self) -> float:
        return max((match.score for match in self.matches), default=0.0)


class RetrievalService:
    """Finding the passages that bear on a question.

    Deliberately separate from the thing that writes replies. Retrieval
    can be measured on its own -- did the right passage come back -- and
    keeping it apart is what lets that be tested without a language model
    in the loop.
    """

    def __init__(
        self,
        knowledge: KnowledgeRepository,
        embeddings: EmbeddingProvider,
    ) -> None:
        self._knowledge = knowledge
        self._embeddings = embeddings

    def retrieve(
        self,
        workspace_id: uuid.UUID,
        query: str,
        *,
        limit: int = DEFAULT_LIMIT,
        min_score: float = MIN_SCORE,
    ) -> Retrieval:
        """The passages this workspace has that bear on this question.

        `workspace_id` is the first argument and is passed to the search
        unconditionally. There is no overload without it and no default:
        the plan calls a cross-tenant knowledge leak a severe security
        failure, and the way to make one impossible is for the scoping not
        to be a decision any caller gets to make.
        """
        normalised = text_tools.normalise(query)

        if not normalised:
            return Retrieval(query=normalised)

        try:
            embedded = self._embeddings.embed(
                [normalised],
                purpose=EmbeddingPurpose.QUERY,
            )
        except EmbeddingProviderError:
            # Knowing nothing rather than failing. Retrieval is one input
            # to answering, and a provider being down should degrade the
            # assistant to "I will get somebody to help" rather than take
            # the endpoint that called it down with it.
            logger.warning("A question could not be embedded; retrieving nothing")

            return Retrieval(query=normalised)

        if not embedded.vectors:
            return Retrieval(query=normalised)

        scored = self._knowledge.search(
            workspace_id,
            embedding=embedded.vectors[0],
            limit=limit,
            min_score=min_score,
        )

        return Retrieval(
            query=normalised,
            matches=[
                Match(
                    document_id=item.chunk.document_id,
                    chunk_id=item.chunk.id,
                    score=item.score,
                    content=item.chunk.content,
                    metadata=item.chunk.meta,
                )
                for item in scored
            ],
        )


def get_retrieval_service(
    knowledge: KnowledgeRepositoryDep,
    embeddings: EmbeddingProviderDep,
) -> RetrievalService:
    return RetrievalService(knowledge=knowledge, embeddings=embeddings)


RetrievalServiceDep = Annotated[RetrievalService, Depends(get_retrieval_service)]
