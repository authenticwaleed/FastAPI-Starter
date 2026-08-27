"""Phase 15 acceptance: rotation, reuse detection, and revocation.

The half of the phase that has nothing to do with HTTP. What a session is
worth comes down to four questions -- can this token still buy another
one, can a spent one, what happens when a spent one comes back, and what
does revoking actually destroy -- and all four are answered here.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import (
    InactiveUserError,
    InvalidRefreshTokenError,
    RefreshTokenReusedError,
    SessionNotFoundError,
)
from app.core.security import hash_token
from app.models.user import User
from app.models.user_session import SessionEndReason, UserSession
from app.repositories.user_repository import UserRepository
from app.repositories.user_session_repository import UserSessionRepository
from app.schemas.user import UserCreate
from app.services.session_service import SessionService
from app.services.user_service import UserService

PASSWORD = "correct horse battery staple"


@pytest.fixture
def sessions(
    db_session: Session,
    user_session_repository: UserSessionRepository,
) -> SessionService:
    return SessionService(session=db_session, repository=user_session_repository)


@pytest.fixture
def users(db_session: Session, user_repository: UserRepository) -> UserService:
    return UserService(session=db_session, repository=user_repository)


@pytest.fixture
def account(users: UserService) -> User:
    return users.create_user(
        UserCreate(name="Ada Lovelace", email="ada@example.com", password=PASSWORD)
    )


@pytest.fixture
def other(users: UserService) -> User:
    return users.create_user(
        UserCreate(name="Alan Turing", email="alan@example.com", password=PASSWORD)
    )


def _age(session: Session, user_session: UserSession) -> None:
    """Push a session's deadline into the past, as time would."""
    user_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.flush()


# --- starting -------------------------------------------------------------


def test_begin_opens_a_live_session(
    sessions: SessionService,
    account: User,
) -> None:
    issued = sessions.begin(account)

    assert issued.session.user_id == account.id
    assert issued.session.is_live_at(datetime.now(UTC))
    assert issued.refresh_token


def test_begin_records_who_was_asking(
    sessions: SessionService,
    account: User,
) -> None:
    issued = sessions.begin(
        account,
        user_agent="Mozilla/5.0",
        ip_address="203.0.113.7",
    )

    assert issued.session.user_agent == "Mozilla/5.0"
    assert issued.session.ip_address == "203.0.113.7"


def test_an_enormous_user_agent_is_trimmed_rather_than_refused(
    sessions: SessionService,
    account: User,
) -> None:
    # A header anybody can set must not be able to fail a sign-in.
    issued = sessions.begin(account, user_agent="x" * 5000)

    assert issued.session.user_agent is not None
    assert len(issued.session.user_agent) == 255


def test_the_token_itself_is_never_stored(
    sessions: SessionService,
    user_session_repository: UserSessionRepository,
    account: User,
) -> None:
    issued = sessions.begin(account)

    assert user_session_repository.get_refresh_token(issued.refresh_token) is None

    stored = user_session_repository.get_refresh_token(hash_token(issued.refresh_token))
    assert stored is not None
    assert stored.session_id == issued.session.id


def test_two_sign_ins_are_two_sessions(
    sessions: SessionService,
    account: User,
) -> None:
    first = sessions.begin(account)
    second = sessions.begin(account)

    assert first.session.id != second.session.id
    assert first.refresh_token != second.refresh_token


# --- rotating -------------------------------------------------------------


def test_rotate_hands_back_a_different_token_for_the_same_session(
    sessions: SessionService,
    account: User,
) -> None:
    first = sessions.begin(account)

    rotated, user = sessions.rotate(first.refresh_token)

    assert rotated.refresh_token != first.refresh_token
    assert rotated.session.id == first.session.id
    assert user is account


def test_rotate_pushes_the_deadline_out_and_records_the_activity(
    sessions: SessionService,
    db_session: Session,
    account: User,
) -> None:
    first = sessions.begin(account)

    # Wind the clock back rather than waiting for it to move.
    first.session.last_used_at = datetime.now(UTC) - timedelta(days=7)
    first.session.expires_at = datetime.now(UTC) + timedelta(days=1)
    db_session.flush()
    before = first.session.expires_at

    rotated, _ = sessions.rotate(first.refresh_token)

    assert rotated.session.expires_at > before
    assert rotated.session.last_used_at > datetime.now(UTC) - timedelta(minutes=1)


def test_a_token_that_was_never_issued_buys_nothing(
    sessions: SessionService,
    account: User,
) -> None:
    with pytest.raises(InvalidRefreshTokenError):
        sessions.rotate("not a token anybody ever held")


def test_a_spent_token_cannot_be_spent_again(
    sessions: SessionService,
    account: User,
) -> None:
    first = sessions.begin(account)
    sessions.rotate(first.refresh_token)

    with pytest.raises(RefreshTokenReusedError):
        sessions.rotate(first.refresh_token)


def test_reuse_ends_the_whole_session(
    sessions: SessionService,
    user_session_repository: UserSessionRepository,
    account: User,
) -> None:
    # The point of keeping spent links at all. The thief and the rightful
    # holder cannot be told apart, so neither of them keeps the session.
    first = sessions.begin(account)
    second, _ = sessions.rotate(first.refresh_token)

    with pytest.raises(RefreshTokenReusedError):
        sessions.rotate(first.refresh_token)

    ended = user_session_repository.get(first.session.id)
    assert ended is not None
    assert ended.revoked_at is not None
    assert ended.revoked_reason is SessionEndReason.TOKEN_REUSED

    # And the successor the rightful holder was using dies with it.
    with pytest.raises(InvalidRefreshTokenError):
        sessions.rotate(second.refresh_token)


def test_a_session_that_has_gone_idle_cannot_be_refreshed(
    sessions: SessionService,
    db_session: Session,
    account: User,
) -> None:
    issued = sessions.begin(account)
    _age(db_session, issued.session)

    with pytest.raises(InvalidRefreshTokenError):
        sessions.rotate(issued.refresh_token)


def test_a_revoked_session_cannot_be_refreshed(
    sessions: SessionService,
    account: User,
) -> None:
    issued = sessions.begin(account)
    sessions.revoke(account, issued.session.id)

    with pytest.raises(InvalidRefreshTokenError):
        sessions.rotate(issued.refresh_token)


def test_refreshing_a_deactivated_account_ends_its_session(
    sessions: SessionService,
    user_session_repository: UserSessionRepository,
    db_session: Session,
    account: User,
) -> None:
    issued = sessions.begin(account)

    account.is_active = False
    db_session.flush()

    with pytest.raises(InactiveUserError):
        sessions.rotate(issued.refresh_token)

    ended = user_session_repository.get(issued.session.id)
    assert ended is not None
    assert ended.revoked_at is not None


# --- resolving ------------------------------------------------------------


def test_resolve_returns_the_session_and_its_owner(
    sessions: SessionService,
    account: User,
) -> None:
    issued = sessions.begin(account)

    resolved = sessions.resolve(issued.session.id)

    assert resolved is not None
    assert resolved[0].id == issued.session.id
    assert resolved[1] is account


def test_resolve_refuses_a_session_that_has_ended(
    sessions: SessionService,
    account: User,
) -> None:
    issued = sessions.begin(account)
    sessions.revoke(account, issued.session.id)

    assert sessions.resolve(issued.session.id) is None


def test_resolve_refuses_a_session_that_has_gone_idle(
    sessions: SessionService,
    db_session: Session,
    account: User,
) -> None:
    issued = sessions.begin(account)
    _age(db_session, issued.session)

    assert sessions.resolve(issued.session.id) is None


def test_resolve_refuses_an_id_nobody_was_issued(
    sessions: SessionService,
) -> None:
    assert sessions.resolve(uuid.uuid4()) is None


# --- ending ---------------------------------------------------------------


def test_end_revokes_the_session_the_token_belongs_to(
    sessions: SessionService,
    user_session_repository: UserSessionRepository,
    account: User,
) -> None:
    issued = sessions.begin(account)

    sessions.end(issued.refresh_token)

    ended = user_session_repository.get(issued.session.id)
    assert ended is not None
    assert ended.revoked_reason is SessionEndReason.LOGGED_OUT
    assert sessions.resolve(issued.session.id) is None


def test_ending_destroys_the_chain_rather_than_marking_it(
    sessions: SessionService,
    user_session_repository: UserSessionRepository,
    account: User,
) -> None:
    issued = sessions.begin(account)
    digest = hash_token(issued.refresh_token)

    sessions.end(issued.refresh_token)

    assert user_session_repository.get_refresh_token(digest) is None


def test_end_is_silent_about_a_token_that_means_nothing(
    sessions: SessionService,
) -> None:
    # No exception and no answer. Whoever is guessing learns nothing.
    sessions.end("not a token anybody ever held")


def test_end_is_idempotent(sessions: SessionService, account: User) -> None:
    issued = sessions.begin(account)

    sessions.end(issued.refresh_token)
    sessions.end(issued.refresh_token)


def test_a_spent_token_can_still_log_out(
    sessions: SessionService,
    account: User,
) -> None:
    # A nuisance rather than a compromise, and the same conclusion
    # rotation already reaches when a spent token comes back.
    first = sessions.begin(account)
    sessions.rotate(first.refresh_token)

    sessions.end(first.refresh_token)

    assert sessions.resolve(first.session.id) is None


# --- listing and revoking -------------------------------------------------


def test_the_list_holds_one_row_per_sign_in(
    sessions: SessionService,
    account: User,
) -> None:
    first = sessions.begin(account)
    second = sessions.begin(account)

    listed = {session.id for session in sessions.list_for(account)}

    assert listed == {first.session.id, second.session.id}


def test_the_list_leaves_out_what_has_already_ended(
    sessions: SessionService,
    db_session: Session,
    account: User,
) -> None:
    live = sessions.begin(account)
    revoked = sessions.begin(account)
    idle = sessions.begin(account)

    sessions.revoke(account, revoked.session.id)
    _age(db_session, idle.session)

    assert [session.id for session in sessions.list_for(account)] == [live.session.id]


def test_the_list_is_one_account_only(
    sessions: SessionService,
    account: User,
    other: User,
) -> None:
    mine = sessions.begin(account)
    sessions.begin(other)

    assert [session.id for session in sessions.list_for(account)] == [mine.session.id]


def test_revoking_refuses_a_session_belonging_to_somebody_else(
    sessions: SessionService,
    account: User,
    other: User,
) -> None:
    theirs = sessions.begin(other)

    with pytest.raises(SessionNotFoundError):
        sessions.revoke(account, theirs.session.id)

    assert sessions.resolve(theirs.session.id) is not None


def test_revoking_refuses_an_id_that_names_nothing(
    sessions: SessionService,
    account: User,
) -> None:
    with pytest.raises(SessionNotFoundError):
        sessions.revoke(account, uuid.uuid4())


def test_revoking_the_same_session_twice_is_refused(
    sessions: SessionService,
    account: User,
) -> None:
    issued = sessions.begin(account)
    sessions.revoke(account, issued.session.id)

    with pytest.raises(SessionNotFoundError):
        sessions.revoke(account, issued.session.id)


def test_revoke_all_ends_every_session_the_account_has(
    sessions: SessionService,
    account: User,
) -> None:
    first = sessions.begin(account)
    second = sessions.begin(account)

    assert sessions.revoke_all(account) == 2
    assert sessions.resolve(first.session.id) is None
    assert sessions.resolve(second.session.id) is None


def test_revoke_all_can_spare_the_one_asking(
    sessions: SessionService,
    account: User,
) -> None:
    here = sessions.begin(account)
    elsewhere = sessions.begin(account)

    assert sessions.revoke_all(account, keep=here.session.id) == 1
    assert sessions.resolve(here.session.id) is not None
    assert sessions.resolve(elsewhere.session.id) is None


def test_revoke_all_leaves_other_accounts_alone(
    sessions: SessionService,
    account: User,
    other: User,
) -> None:
    theirs = sessions.begin(other)
    sessions.begin(account)

    sessions.revoke_all(account)

    assert sessions.resolve(theirs.session.id) is not None


def test_revoke_all_records_why(
    sessions: SessionService,
    user_session_repository: UserSessionRepository,
    account: User,
) -> None:
    issued = sessions.begin(account)

    sessions.revoke_all(account, reason=SessionEndReason.PASSWORD_CHANGED)

    ended = user_session_repository.get(issued.session.id)
    assert ended is not None
    assert ended.revoked_reason is SessionEndReason.PASSWORD_CHANGED
