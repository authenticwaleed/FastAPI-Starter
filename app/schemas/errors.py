from typing import Any

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """The shape every error response takes.

    One shape for all of them, so a client can parse a failure the same way
    whether it was a 401, a 409 or a 500.
    """

    detail: str
    # Stable and machine-readable, where `detail` is prose that may be
    # reworded. Clients should branch on this rather than on the message.
    code: str
    # Only populated for validation failures, which have per-field errors
    # that a single sentence cannot carry.
    errors: list[dict[str, Any]] | None = None
