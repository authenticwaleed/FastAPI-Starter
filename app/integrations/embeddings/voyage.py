import logging
from collections.abc import Sequence
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.exceptions import EmbeddingProviderError
from app.core.vectors import normalise
from app.integrations.embeddings.base import (
    EmbeddingPurpose,
    Embeddings,
)

logger = logging.getLogger(__name__)

_URL = "https://api.voyageai.com/v1/embeddings"
# Embedding a document is slower than sending a message and is not a
# customer waiting on a screen, so the read timeout is generous. Connect
# stays short: a provider that cannot be reached should be reported
# quickly rather than held onto.
_TIMEOUT = httpx.Timeout(60.0, connect=5.0)

# The provider's own cap on one request.
MAX_BATCH = 1000


class VoyageEmbeddingProvider:
    """Voyage AI's embeddings API.

    Everything Voyage-shaped lives here: the URL, the field names, the
    batch limit. Above this layer the application knows only that text
    goes in and unit vectors come out.

    Vectors are normalised on the way out rather than wherever they are
    stored, so there is one place that guarantees it and no caller that
    can forget. Similarity in the database is a dot product, and a dot
    product is only a cosine if both sides have unit length.
    """

    def embed(
        self,
        texts: Sequence[str],
        *,
        purpose: EmbeddingPurpose,
    ) -> Embeddings:
        if not texts:
            return Embeddings(vectors=[], model=get_settings().embedding_model)

        if len(texts) > MAX_BATCH:
            raise EmbeddingProviderError(
                f"{len(texts)} texts is more than the {MAX_BATCH} one request allows"
            )

        settings = get_settings()
        key = settings.voyage_api_key

        if key is None:
            raise EmbeddingProviderError("No embedding provider key is configured")

        try:
            response = httpx.post(
                _URL,
                headers={"Authorization": f"Bearer {key.get_secret_value()}"},
                json={
                    "model": settings.embedding_model,
                    "input": list(texts),
                    "input_type": purpose.value,
                    "output_dimension": settings.embedding_dimensions,
                    # Over-length input is cut rather than refused. A
                    # single oversized passage should not fail a whole
                    # document's ingestion, and the chunker has already
                    # made passages far shorter than any model's limit.
                    "truncation": True,
                },
                timeout=_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            logger.warning("The embedding provider could not be reached: %s", exc)
            raise EmbeddingProviderError(
                "The embedding provider could not be reached"
            ) from exc

        if response.status_code >= 400:
            # Logged, not raised onward: the provider's own words can name
            # account and quota details that belong in a log rather than
            # in an API response.
            logger.warning(
                "The embedding provider refused a request: %s %s",
                response.status_code,
                response.text[:500],
            )
            raise EmbeddingProviderError("The embedding provider refused the request")

        return self._parse(response.json(), expected=len(texts))

    @staticmethod
    def _parse(payload: dict[str, Any], *, expected: int) -> Embeddings:
        """Read the response, in the order the texts were sent.

        Voyage numbers each result, and this sorts by that number rather
        than trusting the order of the list. Getting this wrong attaches
        every vector to the wrong passage -- which does not fail, it just
        makes retrieval quietly meaningless.
        """
        data = payload.get("data") or []

        if len(data) != expected:
            raise EmbeddingProviderError(
                f"The embedding provider returned {len(data)} vectors for "
                f"{expected} texts"
            )

        ordered = sorted(data, key=lambda item: item.get("index", 0))
        vectors = [normalise(item["embedding"]) for item in ordered]

        if any(not vector for vector in vectors):
            raise EmbeddingProviderError("The embedding provider returned no vector")

        return Embeddings(
            vectors=vectors,
            model=str(payload.get("model") or get_settings().embedding_model),
            total_tokens=(payload.get("usage") or {}).get("total_tokens"),
        )
