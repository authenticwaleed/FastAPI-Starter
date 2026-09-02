"""Phase A1 acceptance: how the first platform owner comes to exist.

Granting is owner-only, so a platform with no owner cannot produce one
through its own console. The way out is a command on the deployment, and
these tests are about the two properties that makes it safe to have: it
promotes an account that already exists rather than creating one, and it
writes an entry saying nobody granted it -- which is true, and is the
honest alternative to an entry naming somebody who was not there.

The functions are called with the test's own session rather than through
`main`, which opens one of its own: a command that committed outside the
test's transaction would leave rows behind for the next test to find.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin_audit_log import AdminAction, AdminAuditLog
from app.models.staff_member import StaffMember, StaffRole
from app.repositories.user_repository import UserRepository
from app.staff_cli import _grant, _list, _parser


@pytest.fixture
def account(user_repository: UserRepository) -> int:
    user = user_repository.create(
        name="Ada Lovelace",
        email="ada@example.com",
        hashed_password="not a real hash",
    )

    return user.id


def _staff(session: Session) -> StaffMember | None:
    return session.scalar(select(StaffMember))


def _entries(session: Session) -> list[AdminAuditLog]:
    return list(session.scalars(select(AdminAuditLog).order_by(AdminAuditLog.sequence)))


def test_granting_promotes_an_account_that_already_exists(
    db_session: Session,
    account: int,
) -> None:
    code = _grant(db_session, "ada@example.com", StaffRole.OWNER)

    assert code == 0

    member = _staff(db_session)
    assert member is not None
    assert member.user_id == account
    assert member.role == StaffRole.OWNER
    assert member.is_live
    # Nobody granted it, because nobody could: this is the row that makes
    # every later grant possible.
    assert member.granted_by_user_id is None


def test_the_first_grant_is_recorded_with_no_actor(
    db_session: Session,
    account: int,
) -> None:
    _grant(db_session, "ada@example.com", StaffRole.OWNER)

    (entry,) = _entries(db_session)

    assert entry.action == AdminAction.STAFF_GRANTED
    # An entry naming a person would be an accusation; no entry at all
    # would mean the platform's history began with somebody already
    # holding the keys.
    assert entry.actor_user_id is None
    assert entry.actor_email is None
    assert entry.target_user_id == account
    # So a reader can tell this from a colleague being promoted, which is
    # the difference between a deployment being set up and a decision
    # somebody made.
    assert entry.meta["via"] == "cli"


def test_an_address_with_no_account_is_refused_and_changes_nothing(
    db_session: Session,
) -> None:
    # There is no way to create a user here, on purpose: staff are
    # ordinary accounts that have been promoted, which is what keeps one
    # password and one way back in for everybody.
    code = _grant(db_session, "nobody@example.com", StaffRole.OWNER)

    assert code == 2
    assert _staff(db_session) is None
    assert _entries(db_session) == []


def test_granting_twice_is_refused_and_records_nothing_further(
    db_session: Session,
    account: int,
) -> None:
    _grant(db_session, "ada@example.com", StaffRole.OWNER)

    code = _grant(db_session, "ada@example.com", StaffRole.SUPPORT)

    assert code == 3
    assert len(_entries(db_session)) == 1

    member = _staff(db_session)
    assert member is not None
    # And the refusal changed nothing, rather than half-applying: the
    # rank they hold is still the one they were granted.
    assert member.role == StaffRole.OWNER


def test_the_command_defaults_to_owner(db_session: Session) -> None:
    # The case this exists for is the first one, and the first staff
    # member has to be able to grant the rest. A lesser rank by default
    # would produce a console nobody can be added to.
    arguments = _parser().parse_args(["grant", "ada@example.com"])

    assert arguments.role == StaffRole.OWNER.value


def test_the_command_can_only_grant(db_session: Session) -> None:
    """Everything else goes through the console, where there is an actor.

    A shell can always grant itself an owner row and then revoke somebody
    properly, which is the version of that power that leaves a trail.
    """
    with pytest.raises(SystemExit):
        _parser().parse_args(["revoke", "ada@example.com"])


def test_listing_shows_who_has_access_and_who_used_to(
    db_session: Session,
    account: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _grant(db_session, "ada@example.com", StaffRole.OWNER)

    assert _list(db_session) == 0

    printed = capsys.readouterr().out

    assert "ada@example.com" in printed
    assert "owner" in printed
    assert "live" in printed
