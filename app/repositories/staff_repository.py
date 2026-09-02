from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.staff_member import StaffMember, StaffRole
from app.models.user import User


class StaffRepository:
    """Every query against the staff_members table lives here.

    Small, and unlike almost every other repository in this application
    none of it is scoped to a workspace. That is not an oversight: this
    table is about the business that operates the product rather than
    about any of the businesses using it, so there is no tenant to narrow
    by. It is also why nothing here may ever be reached from a tenant
    route -- the boundary these queries sit outside of is the whole
    reason the rest of them sit inside it.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_user(self, user_id: int) -> StaffMember | None:
        """This account's staff row, live or revoked.

        Both, deliberately. A caller checking whether somebody may open
        the console has to tell "was never staff" from "was staff until
        Tuesday", because those are two different answers to give and, on
        this surface, both of them are safe to give.
        """
        return self._session.scalar(
            select(StaffMember).where(StaffMember.user_id == user_id)
        )

    def create(
        self,
        *,
        user_id: int,
        role: StaffRole,
        granted_by_user_id: int | None,
    ) -> StaffMember:
        member = StaffMember(
            user_id=user_id,
            role=role,
            granted_by_user_id=granted_by_user_id,
        )

        self._session.add(member)
        self._session.flush()

        return member

    def list_all(self) -> list[tuple[StaffMember, User]]:
        """Everybody who has ever been staff, newest grant first.

        Revoked rows included, for the reason the API key list keeps
        revoked keys: after an incident the useful half of the screen is
        who used to have this and when it was taken away.

        Joined rather than looked up per row, and an inner join because a
        staff row cannot outlive its account -- the foreign key cascades,
        which is what makes the join provably lossless here.
        """
        rows = self._session.execute(
            select(StaffMember, User)
            .join(User, User.id == StaffMember.user_id)
            .order_by(StaffMember.granted_at.desc(), StaffMember.id)
        ).all()

        return [(member, user) for member, user in rows]

    def set_role(self, member: StaffMember, role: StaffRole) -> StaffMember:
        member.role = role
        self._session.flush()

        return member

    def revoke(self, member: StaffMember, at: datetime) -> StaffMember:
        member.revoked_at = at
        self._session.flush()

        return member

    def reinstate(
        self,
        member: StaffMember,
        *,
        role: StaffRole,
        granted_by_user_id: int | None,
        at: datetime,
    ) -> StaffMember:
        """Give a revoked row back its access.

        An update rather than a second row, because `user_id` is unique
        and that is the point of it: somebody who was staff last year and
        is again today has one history, not two rows that have to be read
        together to make sense.

        `granted_at` moves with it. The question the column answers is
        "since when has this person had this", and after a gap the honest
        answer is the new date rather than the old one.
        """
        member.role = role
        member.granted_by_user_id = granted_by_user_id
        member.granted_at = at
        member.revoked_at = None
        self._session.flush()

        return member

    def count_live_owners(self) -> int:
        """How many people can still grant access to this platform.

        The number the refuse-to-strand rule is built on. Only an owner
        may promote anyone, so a platform whose last owner is revoked is
        a console nobody can ever be added to again without a database
        client.
        """
        return (
            self._session.scalar(
                select(func.count())
                .select_from(StaffMember)
                .where(
                    StaffMember.role == StaffRole.OWNER,
                    StaffMember.revoked_at.is_(None),
                )
            )
            or 0
        )
