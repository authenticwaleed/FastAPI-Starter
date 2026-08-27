import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.user_session import RefreshToken, SessionEndReason, UserSession


class UserSessionRepository:
    """Every query against the session tables lives here.

    Two tables, one repository, because they are one thing: a session and
    the chain of refresh secrets that keeps it alive are never usefully
    read apart, and splitting them would put the rule that a token
    belongs to a session in two places.

    Methods flush rather than commit, like every other repository here, so
    the caller decides where the transaction ends.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # --- sessions ----------------------------------------------------------

    def create(
        self,
        *,
        user_id: int,
        expires_at: datetime,
        user_agent: str | None,
        ip_address: str | None,
    ) -> UserSession:
        session = UserSession(
            user_id=user_id,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )

        self._session.add(session)
        self._session.flush()

        return session

    def get(self, session_id: uuid.UUID) -> UserSession | None:
        """By id alone, live or not.

        Unscoped, so nothing that takes an id from a request may use it.
        The one caller is logging out, which has already been vouched for
        by a token from the chain that belongs to this very session.
        """
        return self._session.get(UserSession, session_id)

    def get_live_with_user(
        self,
        session_id: uuid.UUID,
        now: datetime,
    ) -> tuple[UserSession, User] | None:
        """The session and its owner, in one query, if it is still live.

        One query rather than two because this runs on every
        authenticated request. Note it does not filter on `is_active`:
        a deactivated account has to be told apart from an unknown
        session, since one is a 403 and the other a 401.
        """
        row = self._session.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(
                UserSession.id == session_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
        ).first()

        if row is None:
            return None

        return row[0], row[1]

    def get_live_for_user(
        self,
        user_id: int,
        session_id: uuid.UUID,
        now: datetime,
    ) -> UserSession | None:
        """Scoped by user, not looked up by id alone.

        An id is a guess anybody can make. Requiring it to belong to the
        account already holding the token is what stops one person
        signing another out.
        """
        return self._session.scalar(
            select(UserSession).where(
                UserSession.id == session_id,
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
        )

    def list_live_for_user(
        self,
        user_id: int,
        now: datetime,
    ) -> Sequence[UserSession]:
        """The sessions a person would recognise as "where I am signed in".

        Revoked and expired rows are left out: a list of things that no
        longer work is not what the question was, and the row a user
        wants to act on is always a live one. Most recently used first,
        because the session being looked for is usually the odd one out
        at the bottom.
        """
        return self._session.scalars(
            select(UserSession)
            .where(
                UserSession.user_id == user_id,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            )
            .order_by(UserSession.last_used_at.desc(), UserSession.id)
        ).all()

    def touch(
        self,
        session: UserSession,
        *,
        at: datetime,
        expires_at: datetime,
    ) -> UserSession:
        """Record activity and push the idle deadline out again."""
        session.last_used_at = at
        session.expires_at = expires_at
        self._session.flush()

        return session

    def revoke(
        self,
        session: UserSession,
        *,
        at: datetime,
        reason: SessionEndReason,
    ) -> UserSession:
        """End a session, and destroy the chain that could revive it.

        The tokens go rather than being marked: none of them can do
        anything once the session is dead, so keeping them would only be
        keeping secrets for no reason.
        """
        self._discard_chains([session.id])

        session.revoked_at = at
        session.revoked_reason = reason
        self._session.flush()

        return session

    def revoke_live_for_user(
        self,
        user_id: int,
        *,
        at: datetime,
        reason: SessionEndReason,
        keep: uuid.UUID | None = None,
    ) -> int:
        """Sign an account out, optionally sparing one session.

        `keep` is how changing a password signs out every other device
        without signing out the person doing it. `at` is both the clock
        that decides which sessions are still live and the moment they
        stopped being so -- one instant, not two.

        Returns how many were ended.
        """
        targets = [
            session
            for session in self.list_live_for_user(user_id, at)
            if keep is None or session.id != keep
        ]

        if not targets:
            return 0

        # Loaded and mutated one by one rather than updated in bulk. An
        # UPDATE ... WHERE id IN (subquery) would be one statement, and it
        # would also leave any copy of these rows already loaded in this
        # request claiming to be live -- which is exactly the copy the
        # caller is holding. A person has a handful of sessions, not a
        # table's worth, so the cheaper statement is not worth the trap.
        self._discard_chains([session.id for session in targets])

        for session in targets:
            session.revoked_at = at
            session.revoked_reason = reason

        self._session.flush()

        return len(targets)

    # --- refresh tokens ----------------------------------------------------

    def issue(self, *, session_id: uuid.UUID, token_hash: str) -> RefreshToken:
        token = RefreshToken(session_id=session_id, token_hash=token_hash)

        self._session.add(token)
        self._session.flush()

        return token

    def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        """Resolve a presented token, spent or not.

        Deliberately not filtered on `rotated_at`: a spent token is the
        one case worth knowing about, and a query that hid it would make
        reuse indistinguishable from a token that never existed.
        """
        return self._session.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )

    def claim(self, token: RefreshToken, *, at: datetime) -> bool:
        """Spend a token, and say whether this call is the one that did.

        A conditional UPDATE rather than a read-then-write. Two requests
        arriving with the same token would both pass an `if rotated_at is
        None` check and both mint a successor, leaving one session with
        two live chains. Here the second statement blocks on the first,
        re-evaluates its WHERE against the committed row, matches nothing
        and returns False -- which the caller treats as reuse, because
        from the outside that is exactly what it looks like.
        """
        claimed = self._session.scalar(
            update(RefreshToken)
            .where(
                RefreshToken.id == token.id,
                RefreshToken.rotated_at.is_(None),
            )
            .values(rotated_at=at)
            .returning(RefreshToken.id)
            .execution_options(synchronize_session=False)
        )

        return claimed is not None

    def _discard_chains(self, session_ids: Sequence[uuid.UUID]) -> None:
        self._session.execute(
            delete(RefreshToken)
            .where(RefreshToken.session_id.in_(session_ids))
            .execution_options(synchronize_session=False)
        )
