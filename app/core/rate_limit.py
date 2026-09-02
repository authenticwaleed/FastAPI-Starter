"""Counting requests, in this process's memory and nowhere else.

Deliberately not Redis. The plan says not to introduce it until it is
needed, and what that costs is stated plainly rather than hidden: each
worker keeps its own counters, so a deployment running four of them
allows four times each limit. That is the right trade while the limits
are there to stop abuse and runaway loops rather than to sell quota, and
the day they are there to sell quota is the day this grows a shared
backing store. Nothing above this module would change.

Token buckets rather than fixed windows. A fixed window lets twice the
limit through in the two seconds either side of a boundary, and it also
gives a client no useful answer to "when may I try again?" beyond the top
of the next minute. A bucket refills continuously, so the answer is
exactly how long one token takes.
"""

import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from app.core.exceptions import RateLimitExceededError

# Above this many live buckets, the full ones are swept. A full bucket
# carries no information -- it is indistinguishable from a key that has
# never been seen -- so dropping it forgets nothing. The number is a
# guard against the limiter itself becoming the way to exhaust memory:
# every distinct key is an entry, and keys come from request data.
_SWEEP_ABOVE = 10_000


class RateLimited(StrEnum):
    """The things worth counting, each with its own allowance.

    A closed set rather than free strings, so that a route naming a scope
    and the settings configuring one cannot drift apart -- and so that
    two endpoints sharing a bucket is a decision visible in one place.
    Refreshing a token shares AUTH with logging in on purpose: both are
    somebody presenting a credential, and both are worth guessing at.
    """

    AUTH = "auth"
    EMAIL = "email"
    INVITATIONS = "invitations"
    AI = "ai"
    SEARCH = "search"
    UPLOADS = "uploads"
    WEBHOOK_REJECTIONS = "webhook_rejections"
    # The platform console, keyed on the staff member rather than the
    # workspace: this surface belongs to no workspace, and what a runaway
    # console costs is rows in the platform's own audit log, which is
    # written on reads as well as writes.
    ADMIN = "admin"


@dataclass(frozen=True)
class Limit:
    """How much of something is allowed, and over what.

    `times` is both the allowance over a whole window and the largest
    burst permitted at once, which is what a token bucket makes the same
    number. Ten a minute means ten immediately and then one every six
    seconds, not ten spaced evenly.
    """

    times: int
    seconds: float

    def __post_init__(self) -> None:
        if self.times < 1 or self.seconds <= 0:
            raise ValueError("a limit must allow at least one request over a window")

    @property
    def refill_per_second(self) -> float:
        return self.times / self.seconds


@dataclass
class _Bucket:
    tokens: float
    at: float

    def filled_to(self, limit: Limit, now: float) -> float:
        """How many tokens are in it now, having refilled since `at`."""
        earned = (now - self.at) * limit.refill_per_second

        return min(float(limit.times), self.tokens + earned)


@dataclass
class RateLimiter:
    """Token buckets, one per scope per client.

    Holds its own allowances rather than being told one per call. That is
    what lets a route say only *what kind* of thing it is doing, and what
    lets a test hand over a limiter with tiny numbers instead of
    rewriting the process-wide settings for the length of one assertion.

    Thread-safe, because sync routes run in a threadpool and two requests
    for the same key really do arrive at once.

    `enabled` is off in most of the suite. A limiter that counted through
    every test would make an unrelated test fail the moment somebody added
    a sixth login to it, and the tests that are about limits turn it on
    for themselves.
    """

    limits: Mapping[RateLimited, Limit]
    enabled: bool = True
    _buckets: dict[str, _Bucket] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def spend(self, scope: RateLimited, key: str) -> None:
        """Count one request against `key`, or refuse it.

        Raises RateLimitExceededError, carrying how long until a token is
        available, which becomes the Retry-After header.
        """
        self._take(scope, key, spending=True)

    def check(self, scope: RateLimited, key: str) -> None:
        """Refuse if `key` has nothing left, but do not count this request.

        For the webhook, where the thing worth counting is a delivery that
        failed to authenticate rather than a delivery. A caller that is
        behaving is never charged for arriving.
        """
        self._take(scope, key, spending=False)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def tracked(self) -> int:
        """How many clients this limiter is currently remembering.

        For the tests that are about the memory this keeps rather than
        about who gets refused, so that they need not reach past the
        public surface to ask.
        """
        with self._lock:
            return len(self._buckets)

    def _take(self, scope: RateLimited, key: str, *, spending: bool) -> None:
        if not self.enabled:
            return

        limit = self.limits[scope]
        key = f"{scope}:{key}"
        now = time.monotonic()

        with self._lock:
            bucket = self._buckets.get(key)
            tokens = (
                float(limit.times) if bucket is None else bucket.filled_to(limit, now)
            )

            if tokens < 1:
                # Written with the bucket left as it was: a refused request
                # must not push the deadline out, or a client polling
                # steadily would never be let back in.
                raise RateLimitExceededError(_seconds_until_a_token(tokens, limit))

            if spending:
                tokens -= 1

            if tokens >= limit.times:
                # Full again, which is the same as never having been
                # seen, so the entry is dropped rather than kept saying
                # nothing. Only reachable from `check`, which takes
                # nothing: a spend always leaves the bucket short.
                self._buckets.pop(key, None)
            else:
                self._buckets[key] = _Bucket(tokens=tokens, at=now)

            if len(self._buckets) > _SWEEP_ABOVE:
                self._sweep(limit, now)

    def _sweep(self, limit: Limit, now: float) -> None:
        """Drop the buckets that have refilled, under the caller's lock.

        Approximate on purpose: `limit` is whichever one is being checked,
        and different keys are checked against different limits. Refilling
        the wrong one only means a bucket is kept slightly too long or
        dropped slightly early, and dropping it early is the same as
        forgiving one client one request.
        """
        self._buckets = {
            key: bucket
            for key, bucket in self._buckets.items()
            if bucket.filled_to(limit, now) < limit.times
        }


def _seconds_until_a_token(tokens: float, limit: Limit) -> int:
    """Rounded up, and never zero: a Retry-After of 0 invites a hot loop."""
    needed = 1 - tokens

    return max(1, int(needed / limit.refill_per_second) + 1)
