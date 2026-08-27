from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.user_token import UserToken, UserTokenPurpose


class UserTokenRepository:
    """Every query against the user_tokens table lives here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        user_id: int,
        purpose: UserTokenPurpose,
        email: str,
        token_hash: str,
        expires_at: datetime,
    ) -> UserToken:
        token = UserToken(
            user_id=user_id,
            purpose=purpose,
            email=email,
            token_hash=token_hash,
            expires_at=expires_at,
        )

        self._session.add(token)
        self._session.flush()

        return token

    def get_by_token_hash(self, token_hash: str) -> UserToken | None:
        """The one indexed lookup following a link costs.

        Possible because the digest is unsalted -- see `hash_token`.
        """
        return self._session.scalar(
            select(UserToken).where(UserToken.token_hash == token_hash)
        )

    def discard_outstanding(self, user_id: int, purpose: UserTokenPurpose) -> None:
        """Delete the account's unused links of one kind.

        Called before a new one is issued, so that "send me another"
        leaves one live link rather than a growing set of them. Somebody
        clicking yesterday's link out of their inbox is told to ask for a
        fresh one, which is a smaller surprise than five working keys to
        an account sitting in a mailbox.

        Only that purpose: asking to reset a password says nothing about
        an outstanding request to confirm the address.
        """
        self._session.execute(
            delete(UserToken)
            .where(
                UserToken.user_id == user_id,
                UserToken.purpose == purpose,
                UserToken.used_at.is_(None),
            )
            .execution_options(synchronize_session=False)
        )
        self._session.flush()

    def mark_used(self, token: UserToken, at: datetime) -> UserToken:
        token.used_at = at
        self._session.flush()

        return token
