"""The one arithmetic decision the retrieval layer rests on.

Every vector is stored at unit length. That is what lets similarity be a
dot product -- arithmetic PostgreSQL already does over an array -- instead
of a cosine, which would need the magnitudes recomputed on every row of
every search.
"""

import math
from collections.abc import Sequence


def normalise(vector: Sequence[float]) -> list[float]:
    """Scale a vector to unit length.

    A zero vector is returned unchanged rather than divided by zero. It
    should not happen -- an embedding provider given real text does not
    produce one -- and if it does, a row that matches nothing is a better
    outcome than an ingestion that raises.
    """
    magnitude = math.sqrt(sum(value * value for value in vector))

    if magnitude == 0.0:
        return list(vector)

    return [value / magnitude for value in vector]


def similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity, for the callers not going through the database.

    Normalises both sides rather than assuming it: this is used to check
    what the database computed, and a check that shares an assumption with
    the thing it is checking is not a check.
    """
    if len(left) != len(right):
        raise ValueError(
            f"vectors of different lengths cannot be compared: "
            f"{len(left)} and {len(right)}"
        )

    a = normalise(left)
    b = normalise(right)

    return sum(x * y for x, y in zip(a, b, strict=True))
