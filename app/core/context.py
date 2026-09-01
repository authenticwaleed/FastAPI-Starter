"""The identifiers every log line should carry, wherever it is written.

The plan names five, and this module offers exactly those five and nothing
else. That is the design rather than a starting point: "avoid sensitive
contents by default" is a rule somebody breaks the first time it is
convenient, and a function whose parameters are `request_id`,
`workspace_id`, `conversation_id`, `integration` and `operation` cannot be
handed a message body or an access token in the first place.

Held in a context variable rather than passed down, because the code that
knows the workspace and the code that writes the log line are usually far
apart -- a retrieval failure deep in the assistant should say which
business it happened to without every function between here and there
carrying an argument for it.
"""

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token

# Empty rather than absent, so nothing has to check whether the context
# exists before reading it. The default is shared and never mutated: every
# bind replaces the mapping rather than editing it, which is what keeps
# one request's identifiers out of another's.
_EMPTY: Mapping[str, str] = {}

_context: ContextVar[Mapping[str, str]] = ContextVar("log_context", default=_EMPTY)


def current() -> Mapping[str, str]:
    """Whatever is bound right now. Never None, possibly empty."""
    return _context.get()


def new_request_id() -> str:
    """An identifier for one request through this system.

    A hex UUID rather than a readable name: it is only ever compared for
    equality and pasted into a search box, and 32 characters of hex is the
    shape people already recognise as an id when they see one in a log.
    """
    return uuid.uuid4().hex


def bind(
    *,
    request_id: str | None = None,
    workspace_id: uuid.UUID | str | None = None,
    conversation_id: uuid.UUID | str | None = None,
    integration: str | None = None,
    operation: str | None = None,
) -> Token[Mapping[str, str]]:
    """Add identifiers to everything logged from here on.

    Keyword-only and exhaustively named, which is the whole point: this
    signature is the list of what may be logged, and widening it is an
    edit somebody has to make deliberately in a file about logging rather
    than a dictionary key they add in a hurry somewhere else.

    Returns a token to hand back to `reset`. `bound` below is the usual
    way in; this exists for the one caller that cannot use a context
    manager, which is a middleware that has to outlive its own frame.
    """
    supplied = {
        "request_id": request_id,
        "workspace_id": workspace_id,
        "conversation_id": conversation_id,
        "integration": integration,
        "operation": operation,
    }

    return _context.set(
        {
            **current(),
            **{key: str(value) for key, value in supplied.items() if value is not None},
        }
    )


def reset(token: Token[Mapping[str, str]]) -> None:
    _context.reset(token)


@contextmanager
def bound(
    *,
    request_id: str | None = None,
    workspace_id: uuid.UUID | str | None = None,
    conversation_id: uuid.UUID | str | None = None,
    integration: str | None = None,
    operation: str | None = None,
) -> Iterator[None]:
    """Bind for the length of a block, and put back what was there before.

    Restoring matters for the nested case: an outbound call binds an
    integration and an operation, and the lines written after it returns
    are not about that call any more.
    """
    token = bind(
        request_id=request_id,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        integration=integration,
        operation=operation,
    )

    try:
        yield
    finally:
        reset(token)
