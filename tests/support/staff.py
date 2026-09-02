"""A staff member, signed in, ready to call the platform surface.

The same idea as tests/support/tenants.py and the mirror image of it.
There, the setup is a business with an owner inside it; here it is a
person outside every business, which is the distinction the whole
surface rests on -- so the two helpers deliberately share the sign-up
step and nothing else.

Staff rows are written straight through the repository rather than
through the API, because the API cannot grant the first one: granting is
owner-only, and a platform with no owner has nobody to do it. That is
the same reason the real deployment has a command line.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.admin_approval import ApprovableAction
from app.models.admin_audit_log import AdminAction, AdminAuditLog
from app.models.staff_member import StaffMember, StaffRole
from app.repositories.staff_repository import StaffRepository
from app.repositories.user_repository import UserRepository
from tests.support.tenants import sign_up

ADMIN = "/api/v1/admin"


def operations() -> list[tuple[str, str]]:
    """Every operation the platform router publishes, as method and path.

    Read from the application rather than listed in a test, which is the
    point of the tests that use it: the day somebody adds a route and
    forgets to guard it, or forgets to audit it, this already contains
    it and the test already fails.
    """
    spec = create_app().openapi()

    found = sorted(
        (method.upper(), path)
        for path, published in spec["paths"].items()
        if path.startswith(ADMIN)
        for method in published
    )

    # An empty list would make pytest skip every test parametrised on
    # this, and a skipped guard reads exactly like a passing one in the
    # summary. Failing here is the only outcome somebody notices.
    assert found, "no admin routes found: this is looking in the wrong place"

    return found


class Console:
    """One staff member with a token, and the paths they can call."""

    def __init__(
        self,
        client: TestClient,
        session: Session,
        email: str,
        role: StaffRole = StaffRole.OWNER,
    ) -> None:
        self.client = client
        self._session = session

        self.headers = sign_up(client, email)

        user = UserRepository(session).get_by_email(email)
        assert user is not None
        self.user_id = user.id
        self.email = email

        self.staff = StaffRepository(session).create(
            user_id=user.id,
            role=role,
            granted_by_user_id=None,
        )

    def get(self, path: str = "", **params: Any) -> Any:
        return self.client.get(
            f"{ADMIN}{path}",
            headers=self.headers,
            params=params,
        )

    def post(self, path: str, json: dict[str, Any]) -> Any:
        return self.client.post(f"{ADMIN}{path}", json=json, headers=self.headers)

    def patch(self, path: str, json: dict[str, Any]) -> Any:
        return self.client.patch(f"{ADMIN}{path}", json=json, headers=self.headers)

    def delete(self, path: str) -> Any:
        return self.client.delete(f"{ADMIN}{path}", headers=self.headers)

    def revoked(self) -> StaffMember:
        """Take this staff member's own access away, out of band.

        Directly rather than through the API, so that a test about what a
        revoked staff member may do is not also a test of the route that
        revokes them.
        """
        return StaffRepository(self._session).revoke(self.staff, datetime.now(UTC))


def a_colleague(client: TestClient, session: Session, email: str) -> int:
    """An ordinary account with no platform access, and its id."""
    sign_up(client, email)

    user = UserRepository(session).get_by_email(email)
    assert user is not None

    return user.id


def seconded(
    requester: Console,
    approver: Console,
    *,
    action: ApprovableAction,
    subject: str,
    role: str | None = None,
) -> str:
    """One approval, raised by one console and agreed to by another.

    Three lines in every test that touches an erasure or an owner
    promotion, and worth a helper for a reason beyond brevity: the two
    consoles have to be different people, and a helper that takes both
    makes it impossible to write the test that accidentally uses one.
    """
    body: dict[str, Any] = {
        "action": action.value,
        "subject": subject,
        "reason": "Agreed in the incident channel before doing it",
    }

    if role is not None:
        body["role"] = role

    raised = requester.post("/approvals", body)
    assert raised.status_code == 201, raised.text

    approval_id = str(raised.json()["id"])
    agreed = approver.post(f"/approvals/{approval_id}/approve", {})
    assert agreed.status_code == 200, agreed.text

    return approval_id


def entries(
    session: Session,
    action: AdminAction | None = None,
) -> list[AdminAuditLog]:
    """The platform log as it stands, oldest first.

    Read from the table rather than through `/admin/audit`, because
    reading that endpoint writes a row of its own -- which is the point
    of the surface and would be noise in an assertion about something
    else.
    """
    query = select(AdminAuditLog).order_by(AdminAuditLog.sequence)

    if action is not None:
        query = query.where(AdminAuditLog.action == action)

    return list(session.scalars(query).all())
