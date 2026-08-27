from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class SessionRead(BaseModel):
    """One sign-in, as the person who owns the account sees it.

    Everything here is either an identifier or something they told us
    themselves. No token and no hash: the whole point of the session list
    is that it can be shown to somebody, and a list that carried the
    secrets would be a list nobody could safely render.
    """

    id: UUID

    created_at: datetime
    # Accurate to about the access token's lifetime -- it moves when the
    # session refreshes, not on every request. Close enough to answer
    # "was that me an hour ago?", which is the question being asked.
    last_used_at: datetime
    # When it lapses if nobody touches it again. Moves forward every time
    # it is used, so it is a deadline rather than a date.
    expires_at: datetime

    # Both best effort, and both here to be recognised rather than
    # trusted: a browser sends whatever User-Agent it likes, and an
    # address can belong to a phone network's proxy. Null where the
    # request did not carry one.
    user_agent: str | None
    ip_address: str | None

    # Whether this is the session the request asking the question came
    # from -- the row a client should label "this device" and think twice
    # before ending.
    current: bool
