"""The door to the platform, and who is allowed to hold a key.

Everything in this module is about the business that operates Baton
rather than about any business using it, which is why nothing here takes
a WorkspaceAccess and nothing here can be reached from a tenant route.

Two responsibilities, and they are together because they are the same
subject seen twice: `access` decides whether somebody may open the
console at all, and the rest decides who gets that privilege. Both write
to the platform's own log, because on this surface being here is itself
worth recording.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import (
    AdminSessionExpiredError,
    AlreadyStaffError,
    InsufficientStaffRoleError,
    LastStaffOwnerError,
    NotStaffError,
    StaffMemberNotFoundError,
    UserNotFoundError,
)
from app.db.session import SessionDep
from app.models.admin_audit_log import AdminAction
from app.models.staff_member import StaffMember, StaffRole, permits
from app.models.user import User
from app.models.user_session import UserSession
from app.repositories.staff_repository import StaffRepository
from app.repositories.user_repository import UserRepository
from app.services.admin_audit_service import (
    AdminActor,
    AdminAuditService,
    AdminAuditServiceDep,
)
from app.services.user_service import UserRepositoryDep

# What each part of this surface asks for, named here rather than spelled
# into every method, so that "what does an admin get?" is one place to
# read and one place to change.
#
# Granting is owner-only and stays that way. It is the one act on this
# surface that creates more of this surface, and an admin who could
# promote themselves to owner would make the distinction decorative.
MAY_ADMINISTER = StaffRole.ADMIN
MAY_GRANT = StaffRole.OWNER


@dataclass(frozen=True)
class StaffActor:
    """A staff member, proved, together with where they are acting from.

    The platform's answer to WorkspaceAccess, and shaped the same way:
    nothing hands out a StaffMember on its own, so every later decision
    is answered from a role that has already been established rather than
    from a second lookup somebody could forget.

    It carries the request's address and user agent because every act on
    this surface is logged with them. Both are best effort and neither
    decides anything -- they are here to be read by a person asking
    whether an entry looks like the colleague it names.
    """

    staff: StaffMember
    user: User
    ip_address: str | None = None
    user_agent: str | None = None

    @property
    def role(self) -> StaffRole:
        return self.staff.role

    @property
    def logged(self) -> AdminActor:
        """This actor as the audit log needs them: ids and strings."""
        return AdminActor(
            user_id=self.user.id,
            email=self.user.email,
            ip_address=self.ip_address,
            user_agent=self.user_agent,
        )


class StaffService:
    """Who may run this platform, and the record of every change to that.

    Every method here writes to `admin_audit_logs`, reads included. That
    is not zeal: on the tenant surface, looking at your own data is the
    work and only changes are worth recording, while here the whole point
    of the log is to be able to say afterwards who was in the console and
    what they looked at.
    """

    def __init__(
        self,
        session: Session,
        staff: StaffRepository,
        users: UserRepository,
        audit: AdminAuditService,
    ) -> None:
        self._session = session
        self._staff = staff
        self._users = users
        self._audit = audit

    # --- the door ----------------------------------------------------------

    def access(
        self,
        user: User,
        user_session: UserSession,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> StaffActor:
        """Turn an authenticated account into proved platform access.

        Two refusals, and they are different on purpose. Not being staff
        is a 403 and says so: everybody who gets here is signed in
        already, and hiding the console from a colleague whose access was
        withdrawn this morning would only waste their afternoon.

        An idle session is a 401, because signing in again fixes it. That
        check is the whole of "staff do not reuse ordinary sessions":
        they sign in through the ordinary login and get an ordinary
        session, and this surface simply refuses to accept one that has
        been sitting unused. The tenant surface is untouched -- the same
        session keeps working there, which is what makes this a policy
        about the console rather than about the person.
        """
        member = self._staff.get_for_user(user.id)

        if member is None or not member.is_live:
            raise NotStaffError(user.id)

        idle_limit = timedelta(minutes=get_settings().admin_session_idle_minutes)

        # `last_used_at` moves on every token rotation, which is roughly
        # every time the access token runs out -- so this is accurate to
        # about that, and deliberately not to the request. Recording
        # activity per request would turn every console read into a write
        # to the session row.
        if datetime.now(UTC) - user_session.last_used_at > idle_limit:
            raise AdminSessionExpiredError(user_session.id)

        return StaffActor(
            staff=member,
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
        )

    # --- reading -----------------------------------------------------------

    def whoami(self, actor: StaffActor) -> StaffMember:
        """The caller's own staff row, and a note that they were here.

        The console's first call, and the reason it is recorded: "who was
        in the console on Tuesday" is a question this log has to answer
        even about a visit where nothing else was opened.
        """
        self._audit.did(actor.logged, AdminAction.CONSOLE_OPENED)
        self._session.commit()

        return actor.staff

    def list_staff(self, actor: StaffActor) -> list[tuple[StaffMember, User]]:
        """Everybody who runs this platform, revoked rows included.

        Unpaginated, like a workspace's member list and for the same
        reason: this is people, and there are not going to be thousands
        of them. Revoked rows stay because they are the useful half of
        the screen after an incident.
        """
        self._require(actor, MAY_ADMINISTER)

        listed = self._staff.list_all()

        self._audit.did(
            actor.logged,
            AdminAction.STAFF_LISTED,
            meta={"count": len(listed)},
        )
        self._session.commit()

        return listed

    # --- granting and taking away ------------------------------------------

    def grant(
        self,
        actor: StaffActor,
        user_id: int,
        role: StaffRole,
    ) -> tuple[StaffMember, User]:
        """Give an existing account access to the platform.

        Existing, and there is no way to create one here. Staff are
        ordinary accounts that have been promoted, so somebody joining
        the team registers the way a customer does and is granted after
        -- which means their password, their sessions and their password
        reset all work the way everyone else's do, rather than through a
        second implementation nobody exercises.

        Re-granting to a colleague whose access was revoked updates that
        row rather than starting a second one. Their history is one
        history.
        """
        self._require(actor, MAY_GRANT)

        user = self._users.get(user_id)

        if user is None:
            raise UserNotFoundError(user_id)

        existing = self._staff.get_for_user(user_id)

        if existing is not None and existing.is_live:
            # Changing what somebody may do is a PATCH, and it is the
            # request that gets recorded as a change of rank. Quietly
            # accepting a POST here would lose that distinction.
            raise AlreadyStaffError(user_id)

        if existing is None:
            member = self._staff.create(
                user_id=user_id,
                role=role,
                granted_by_user_id=actor.user.id,
            )
        else:
            member = self._staff.reinstate(
                existing,
                role=role,
                granted_by_user_id=actor.user.id,
                at=datetime.now(UTC),
            )

        self._audit.did(
            actor.logged,
            AdminAction.STAFF_GRANTED,
            target_user_id=user_id,
            # Both the address and the role, because this entry is read
            # by somebody asking who let a person in, and an id alone
            # sends them to another table to find out who it was.
            meta={
                "email": user.email,
                "role": role.value,
                "reinstated": existing is not None,
            },
        )
        self._session.commit()

        return member, user

    def change_role(
        self,
        actor: StaffActor,
        user_id: int,
        role: StaffRole,
    ) -> tuple[StaffMember, User]:
        """Move a colleague up or down the ladder."""
        self._require(actor, MAY_GRANT)

        member, user = self._live_member(user_id)

        if member.role == role:
            # Nothing happened, so nothing is recorded. A log full of
            # entries saying somebody saved a form without changing it is
            # one nobody reads.
            return member, user

        self._refuse_to_strand(member, leaving=role != StaffRole.OWNER)

        was = member.role

        self._staff.set_role(member, role)
        self._audit.did(
            actor.logged,
            AdminAction.STAFF_ROLE_CHANGED,
            target_user_id=user_id,
            # Both ranks. "Promoted to owner" without saying what they
            # were before is half an answer, and this is the entry an
            # investigation actually comes looking for.
            meta={"email": user.email, "from": was.value, "to": role.value},
        )
        self._session.commit()

        return member, user

    def revoke(self, actor: StaffActor, user_id: int) -> tuple[StaffMember, User]:
        """Take somebody's platform access away, and keep their row.

        Revoking twice is not an error, for the reason revoking an API
        key twice is not: two people turning off the same access should
        get the same answer whichever of them was first, and the
        timestamp stays the one from when it actually stopped working.

        Their sessions are left alone. A staff member is an ordinary
        account with an ordinary workspace or two, and signing them out
        of a customer's inbox because they no longer run the platform
        would be this surface reaching into the tenant one.
        """
        self._require(actor, MAY_GRANT)

        member, user = self._member(user_id)

        if not member.is_live:
            return member, user

        self._refuse_to_strand(member, leaving=True)

        was = member.role

        self._staff.revoke(member, datetime.now(UTC))
        self._audit.did(
            actor.logged,
            AdminAction.STAFF_REVOKED,
            target_user_id=user_id,
            meta={"email": user.email, "role": was.value},
        )
        self._session.commit()

        return member, user

    # --- the rules everything above shares ---------------------------------

    def _require(self, actor: StaffActor, needed: StaffRole) -> None:
        """Enforce the rank, again, where the work happens.

        The route says the same thing in its signature, which is the
        declaration; this is the enforcement. The difference matters the
        first time one of these is called by something that is not a
        route -- a command line, a job -- which on this surface has
        already happened: the first owner is granted from a terminal.
        """
        if not permits(actor.role, needed):
            raise InsufficientStaffRoleError(actor.role, needed)

    def _member(self, user_id: int) -> tuple[StaffMember, User]:
        member = self._staff.get_for_user(user_id)

        if member is None:
            raise StaffMemberNotFoundError(user_id)

        user = self._users.get(user_id)

        if user is None:
            # Unreachable while the foreign key cascades, and checked
            # rather than asserted because "unreachable" is a claim about
            # a schema that somebody may change.
            raise UserNotFoundError(user_id)

        return member, user

    def _live_member(self, user_id: int) -> tuple[StaffMember, User]:
        member, user = self._member(user_id)

        if not member.is_live:
            # A revoked row is history, not a colleague whose rank can be
            # adjusted. Granting is the way back in, and it is the act
            # that gets recorded.
            raise StaffMemberNotFoundError(user_id)

        return member, user

    def _refuse_to_strand(self, member: StaffMember, *, leaving: bool) -> None:
        """Stop the last owner being demoted or revoked.

        The tenant side refuses to leave a workspace without an owner,
        and the same rule bites harder here: only an owner may grant
        access, so a platform with no live owner is a console nobody can
        ever be added to again without a database client and a
        deployment.
        """
        if not leaving or member.role != StaffRole.OWNER:
            return

        if self._staff.count_live_owners() <= 1:
            raise LastStaffOwnerError(member.user_id)


def get_staff_repository(session: SessionDep) -> StaffRepository:
    return StaffRepository(session)


StaffRepositoryDep = Annotated[StaffRepository, Depends(get_staff_repository)]


def get_staff_service(
    session: SessionDep,
    staff: StaffRepositoryDep,
    users: UserRepositoryDep,
    audit: AdminAuditServiceDep,
) -> StaffService:
    return StaffService(session=session, staff=staff, users=users, audit=audit)


StaffServiceDep = Annotated[StaffService, Depends(get_staff_service)]
