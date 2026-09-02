"""Grant the first platform owner, from a terminal on the deployment.

    uv run python -m app.staff_cli grant colleague@example.com
    uv run python -m app.staff_cli list

Run once per deployment, and then almost never. Granting is owner-only,
so a platform with no owner cannot produce one through its own console --
somebody with shell access has to start the chain, and this is that
somebody.

A command rather than a migration, which was a real choice. A migration
is reproducible and runs itself, and both of those are exactly the
problem here: it would put a privileged account in version control,
identical in every deployment, granted to an address chosen by whoever
wrote the file rather than by whoever runs it.

Two commands and no more. Changing a rank and taking access away belong
to the console, where there is a named actor to record; a shell can
always grant itself an owner row and do those properly, and that route
leaves a trail where this one would not.
"""

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.core.exceptions import AlreadyStaffError
from app.core.logging import configure_logging
from app.db.session import get_session_factory
from app.models.staff_member import StaffRole
from app.repositories.staff_repository import StaffRepository
from app.repositories.user_repository import UserRepository
from app.services.staff_service import build_staff_service


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()

    arguments = _parser().parse_args(argv)

    with get_session_factory()() as session:
        if arguments.command == "list":
            return _list(session)

        return _grant(session, arguments.email, StaffRole(arguments.role))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.staff_cli",
        description="Grant platform access to an account that already exists.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    grant = commands.add_parser(
        "grant",
        help="give an existing account platform access",
    )
    grant.add_argument("email", help="the address of an account that already exists")
    grant.add_argument(
        "--role",
        choices=[role.value for role in StaffRole],
        # Owner, because the case this command exists for is the first
        # one, and the first staff member has to be able to grant the
        # rest. A lesser rank by default would produce a console nobody
        # can be added to, which is the failure this command answers.
        default=StaffRole.OWNER.value,
        help="the rank to grant (default: owner)",
    )

    commands.add_parser("list", help="show everybody who has platform access")

    return parser


def _grant(session: Session, email: str, role: StaffRole) -> int:
    """Promote an account that already exists, or explain why not.

    An account, not a person: there is no way to create a user here, for
    the reason there is none on the API surface either. Staff are
    ordinary accounts that have been promoted, so a colleague joining the
    team registers the way a customer does and keeps one password, one
    session list, and one way back in when they forget it.

    Each refusal gets its own exit code, so this can be a step in a
    provisioning script rather than something a person has to read.
    """
    user = UserRepository(session).get_by_email(email)

    if user is None:
        sys.stderr.write(
            f"No account with the address {email}. Register it first, then grant it.\n"
        )

        return 2

    try:
        member = build_staff_service(session).seed(user, role)
    except AlreadyStaffError:
        sys.stderr.write(f"{email} already has platform access.\n")

        return 3

    sys.stdout.write(f"Granted {member.role.value} to {user.email}\n")

    return 0


def _list(session: Session) -> int:
    """Everybody who has ever had access, revoked rows included.

    Not written to the platform log, unlike the same read through the
    API, and the difference is that there is nobody to write down.
    Whoever runs this holds the database credentials and could read the
    table directly; an entry naming no actor would say only that somebody
    with shell access looked, which the shell's own history says better.
    """
    for member, user in StaffRepository(session).list_all():
        state = "live" if member.is_live else "revoked"
        sys.stdout.write(f"{user.email}\t{member.role.value}\t{state}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
