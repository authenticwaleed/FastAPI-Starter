import re

# Everything a person might type to make a number readable, and nothing
# that carries meaning: spaces, hyphens, dots, brackets. `\s` is Unicode
# here, so it also catches the no-break space a browser or a word
# processor will happily paste in.
_DECORATION = re.compile(r"[\s\-.()]")

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalise_phone_number(value: str) -> str:
    """Reduce a typed phone number to one canonical form, or refuse it.

    E.164: a plus, a country code that does not start with zero, and up to
    fifteen digits in total. That is the form WhatsApp identifies a person
    by, and storing anything else means the same customer arriving twice --
    once as they were typed into the dashboard and once as the provider
    spells them.

    Deliberately not a full libphonenumber parse. That would let somebody
    type a local number and have it resolved against a country, which is
    genuinely better, and it needs a default region per workspace that
    nothing yet records. Numbers reaching this product arrive either from
    WhatsApp, already international, or typed by a business that knows its
    own customers' country codes. When neither is true any more, the fix
    is a `country` on the workspace and this function calling out to
    libphonenumber -- not loosening what counts as valid here.

    Raises ValueError, so a pydantic validator turns a bad number into an
    ordinary 422 alongside every other field error.
    """
    if not isinstance(value, str):
        raise TypeError("phone number must be a string")

    stripped = _DECORATION.sub("", value)

    # 00 is how much of the world dials internationally, and people type
    # what they dial.
    if stripped.startswith("00"):
        stripped = f"+{stripped[2:]}"

    if not stripped.startswith("+"):
        raise ValueError(
            "phone number must be in international form, starting with + or 00"
        )

    if not _E164.match(stripped):
        raise ValueError(
            "phone number must be 8 to 15 digits in international form, "
            "with a country code that does not start with zero"
        )

    return stripped
