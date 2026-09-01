"""Measuring the things that go wrong slowly.

The plan's metrics list is mostly latency and failure rates, and the ones
that matter are not about this application's own code -- they are about
what it waits for: WhatsApp, a language model, an embedding provider, a
database. So what this module offers is one way to time an outbound call
and say how it went.

Emitted as log lines rather than kept in a counter, and that is the
phase's decision. Every line already carries the request it belongs to and
the workspace it is for, so one query over the log stream answers "how
slow is WhatsApp" and "how slow was WhatsApp for this customer at four
o'clock on Tuesday" -- and the second question is the one somebody
actually asks. A counter answers only the first, and needs a scrape
endpoint, a dependency and a second place to look.

What would change that is a dashboard nobody can build from logs, or a
volume where logging every call is itself the cost. Both are visible
problems when they arrive.
"""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

from app.core import context

logger = logging.getLogger(__name__)


@contextmanager
def observed(integration: str, operation: str) -> Iterator[None]:
    """Time one call to something outside, and record how it ended.

    Binds the integration and the operation for the length of the call, so
    that anything logged inside it -- including by the library making the
    call -- says what it was doing. Restored afterwards, because the lines
    that follow are not about it any more.

    Never swallows. What is being observed is the call, not whether the
    caller wanted the exception.
    """
    with context.bound(integration=integration, operation=operation):
        started = time.perf_counter()

        try:
            yield
        except Exception as exc:
            # The class name, never the message. A provider's own words
            # can carry a phone number, a prompt, or a URL with a token in
            # the query string, and this line exists to say that something
            # failed and how long it took to fail.
            logger.warning(
                "Outbound call failed",
                extra={
                    "duration_ms": _since(started),
                    "outcome": "error",
                    "error": type(exc).__name__,
                },
            )
            raise
        else:
            logger.info(
                "Outbound call",
                extra={"duration_ms": _since(started), "outcome": "ok"},
            )


def _since(started: float) -> int:
    """Milliseconds, as an integer.

    perf_counter rather than the wall clock, because this is a duration
    and the wall clock is allowed to move sideways. Rounded, because
    nobody is chasing microseconds across a network call and a whole
    number is what a dashboard groups on.
    """
    return int((time.perf_counter() - started) * 1000)
