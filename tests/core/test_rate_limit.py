"""Phase 17: the token bucket itself, without a request anywhere near it."""

import threading

import pytest

from app.core import rate_limit
from app.core.exceptions import RateLimitExceededError
from app.core.rate_limit import Limit, RateLimited, RateLimiter

SCOPE = RateLimited.AUTH
OTHER = RateLimited.EMAIL


def _limiter(times: int = 3, seconds: float = 60, **kwargs: object) -> RateLimiter:
    limits = dict.fromkeys(RateLimited, Limit(times=times, seconds=seconds))

    return RateLimiter(limits=limits, **kwargs)  # type: ignore[arg-type]


def test_requests_within_the_allowance_pass() -> None:
    limiter = _limiter(times=3)

    for _ in range(3):
        limiter.spend(SCOPE, "someone")


def test_one_too_many_is_refused() -> None:
    limiter = _limiter(times=3)

    for _ in range(3):
        limiter.spend(SCOPE, "someone")

    with pytest.raises(RateLimitExceededError):
        limiter.spend(SCOPE, "someone")


def test_the_refusal_says_how_long_to_wait() -> None:
    # A 429 without Retry-After tells a client to guess, and what clients
    # guess is "immediately".
    limiter = _limiter(times=1, seconds=60)
    limiter.spend(SCOPE, "someone")

    with pytest.raises(RateLimitExceededError) as refused:
        limiter.spend(SCOPE, "someone")

    assert refused.value.retry_after > 0
    assert refused.value.headers() == {"Retry-After": str(refused.value.retry_after)}


def test_two_clients_do_not_share_an_allowance() -> None:
    limiter = _limiter(times=1)
    limiter.spend(SCOPE, "someone")

    limiter.spend(SCOPE, "somebody else")


def test_two_scopes_do_not_share_an_allowance() -> None:
    # Spending the login allowance must not also spend the one for asking
    # to reset a password.
    limiter = _limiter(times=1)
    limiter.spend(SCOPE, "someone")

    limiter.spend(OTHER, "someone")


def test_the_bucket_refills() -> None:
    # A whole window in a hundredth of a second, so this asserts the
    # refill rather than the patience of whoever runs the suite.
    limiter = _limiter(times=2, seconds=0.01)
    limiter.spend(SCOPE, "someone")
    limiter.spend(SCOPE, "someone")

    with pytest.raises(RateLimitExceededError):
        limiter.spend(SCOPE, "someone")

    _wait(0.02)

    limiter.spend(SCOPE, "someone")


def test_a_refusal_does_not_push_the_deadline_out() -> None:
    # Otherwise a client polling steadily would never be let back in.
    limiter = _limiter(times=1, seconds=0.01)
    limiter.spend(SCOPE, "someone")

    for _ in range(5):
        with pytest.raises(RateLimitExceededError):
            limiter.spend(SCOPE, "someone")

    _wait(0.02)

    limiter.spend(SCOPE, "someone")


def test_checking_refuses_without_counting() -> None:
    # What the webhook uses: arriving is free, and only a delivery that
    # failed to authenticate is charged for.
    limiter = _limiter(times=1)

    for _ in range(10):
        limiter.check(SCOPE, "someone")

    limiter.spend(SCOPE, "someone")

    with pytest.raises(RateLimitExceededError):
        limiter.check(SCOPE, "someone")


def test_a_disabled_limiter_counts_nothing() -> None:
    limiter = _limiter(times=1, enabled=False)

    for _ in range(100):
        limiter.spend(SCOPE, "someone")


def test_resetting_forgets_everybody() -> None:
    limiter = _limiter(times=1)
    limiter.spend(SCOPE, "someone")

    limiter.reset()

    limiter.spend(SCOPE, "someone")


def test_a_refilled_bucket_is_forgotten() -> None:
    # A full bucket says the same thing as a key nobody has ever seen, so
    # keeping it would only be a way to run this process out of memory
    # one distinct key at a time.
    limiter = _limiter(times=1, seconds=0.01)
    limiter.spend(SCOPE, "someone")
    assert limiter.tracked() == 1

    _wait(0.02)
    limiter.check(SCOPE, "someone")

    assert limiter.tracked() == 0


def test_the_sweep_reclaims_keys_that_have_gone_quiet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Every distinct key is an entry, and keys come from request data, so
    # without this the limiter is itself a way to exhaust memory.
    monkeypatch.setattr(rate_limit, "_SWEEP_ABOVE", 20)
    limiter = _limiter(times=2, seconds=0.01)

    for number in range(21):
        limiter.spend(SCOPE, f"client-{number}")

    _wait(0.02)
    limiter.spend(SCOPE, "one more")

    # Everything before the wait has refilled, so only the last is left.
    assert limiter.tracked() == 1


def test_a_limit_must_allow_something() -> None:
    with pytest.raises(ValueError):
        Limit(times=0, seconds=60)

    with pytest.raises(ValueError):
        Limit(times=1, seconds=0)


def test_concurrent_callers_cannot_overspend() -> None:
    # Sync routes run in a threadpool, so two requests for one key really
    # do arrive at once. Without the lock, both read the same count.
    limiter = _limiter(times=50)
    allowed = []
    barrier = threading.Barrier(20)

    def attempt() -> None:
        barrier.wait()

        try:
            limiter.spend(SCOPE, "someone")
            allowed.append(1)
        except RateLimitExceededError:
            pass

    threads = [threading.Thread(target=attempt) for _ in range(20)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    assert len(allowed) == 20


def test_concurrent_callers_are_not_let_past_the_allowance() -> None:
    limiter = _limiter(times=5)
    allowed = []
    barrier = threading.Barrier(20)

    def attempt() -> None:
        barrier.wait()

        try:
            limiter.spend(SCOPE, "someone")
            allowed.append(1)
        except RateLimitExceededError:
            pass

    threads = [threading.Thread(target=attempt) for _ in range(20)]

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

    assert len(allowed) == 5


def _wait(seconds: float) -> None:
    """Busy-wait on the same clock the limiter reads.

    `time.sleep` would do, and this makes the dependency explicit: what
    has to advance is `time.monotonic`, which is what the bucket refills
    against.
    """
    import time

    deadline = time.monotonic() + seconds

    while time.monotonic() < deadline:
        time.sleep(0.001)
