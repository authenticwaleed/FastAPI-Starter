"""Phase 5 acceptance: one number, one spelling."""

import pytest

from app.core.phone import normalise_phone_number


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        ("+923001234567", "+923001234567"),
        # The ways a person makes a number readable.
        ("+92 300 1234567", "+923001234567"),
        ("+92-300-1234567", "+923001234567"),
        ("+1 (415) 555-2671", "+14155552671"),
        ("+44.20.7946.0958", "+442079460958"),
        ("  +923001234567  ", "+923001234567"),
        # A no-break space, which is what a browser or a word processor
        # pastes in where a person typed an ordinary one.
        ("+92\u00a0300\u00a01234567", "+923001234567"),
        # 00 is how much of the world dials internationally, and people
        # type what they dial.
        ("00923001234567", "+923001234567"),
        ("00 92 300 1234567", "+923001234567"),
    ],
)
def test_a_readable_number_becomes_one_canonical_form(
    typed: str,
    stored: str,
) -> None:
    assert normalise_phone_number(typed) == stored


def test_normalising_is_idempotent() -> None:
    # It has to be: the same value goes through this on the way in from
    # the dashboard and again on the way in from a provider.
    once = normalise_phone_number("+92 300 1234567")

    assert normalise_phone_number(once) == once


@pytest.mark.parametrize(
    "rejected",
    [
        "",
        "   ",
        "not a number",
        # National form. Resolving this needs a country, and nothing in
        # the product records one yet.
        "0300 1234567",
        "3001234567",
        # A country code cannot start with zero.
        "+0923001234567",
        # Too short to be anybody, and too long to be a phone number.
        "+123",
        "+1234567890123456",
        # Digits with something in them that is not a digit.
        "+92300123456a",
        "+92300*234567",
    ],
)
def test_what_is_not_a_number_is_refused(rejected: str) -> None:
    with pytest.raises(ValueError):
        normalise_phone_number(rejected)


def test_the_refusal_explains_itself() -> None:
    # It reaches a client as a 422 field error, so it has to say what
    # would have been acceptable.
    with pytest.raises(ValueError, match="international"):
        normalise_phone_number("0300 1234567")
