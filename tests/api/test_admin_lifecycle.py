"""Phase A4 acceptance: what the platform may do to an account.

The phase where `SUSPENDED` stopped being a word. It was declared by the
status enum, set by nothing and checked by nothing, so a workspace marked
suspended kept working normally -- and half this file is about the
behaviour that now sits behind it.

The other half is about the calls that cannot be undone, and what stands
in front of them: a rank, the slug typed back, and an entry written
before the delete rather than after.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.encryption import encrypt
from app.models.admin_approval import ApprovableAction
from app.models.admin_audit_log import AdminAction, AdminAuditLog
from app.models.audit_log import AuditEvent, AuditLog
from app.models.message import Direction, Message
from app.models.staff_member import StaffRole
from app.models.user import User
from app.models.user_session import UserSession
from app.models.workspace import Workspace, WorkspaceStatus
from app.repositories.user_repository import UserRepository
from app.repositories.whatsapp_account_repository import WhatsAppAccountRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.repositories.workspace_repository import WorkspaceRepository
from app.schemas.workspace import WorkspaceCreate
from app.services.plans import PlanTier
from app.services.workspace_service import WorkspaceService
from tests.support.services import audit_service
from tests.support.staff import Console, entries, seconded
from tests.support.tenants import PASSWORD, Tenant, sign_up
from tests.support.whatsapp import PHONE_NUMBER_ID, inbound_payload, sign

REASON = "The invoice of 3 March is sixty days overdue"


@pytest.fixture
def admin(client: TestClient, db_session: Session) -> Console:
    """The rank that suspends and closes, but does not erase."""
    return Console(client, db_session, "platform-admin@example.com", StaffRole.ADMIN)


@pytest.fixture
def owner(client: TestClient, db_session: Session) -> Console:
    return Console(client, db_session, "platform-owner@example.com", StaffRole.OWNER)


@pytest.fixture
def colleague(client: TestClient, db_session: Session) -> Console:
    """A second staff member, because erasing now needs one.

    Phase A8 put a two-person approval in front of the erasure, so every
    test of it involves two people -- which is the control working rather
    than test noise.
    """
    return Console(client, db_session, "platform-second@example.com", StaffRole.ADMIN)


def _approved_erasure(owner: Console, colleague: Console, workspace_id: str) -> str:
    return seconded(
        owner,
        colleague,
        action=ApprovableAction.ERASE_WORKSPACE,
        subject=workspace_id,
    )


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> Tenant:
    return Tenant(client, user_repository, membership_repository, "acme-fashion")


def _suspend(console: Console, tenant: Tenant, **body: Any) -> Any:
    return console.post(
        f"/workspaces/{tenant.workspace_id}/suspend",
        {"reason": REASON} | body,
    )


def _status(session: Session, tenant: Tenant) -> WorkspaceStatus:
    workspace = session.get(Workspace, uuid.UUID(tenant.workspace_id))
    assert workspace is not None
    session.refresh(workspace)

    return workspace.status


def _tenant_log(session: Session, event: AuditEvent) -> list[AuditLog]:
    return list(
        session.scalars(
            select(AuditLog).where(AuditLog.event == event).order_by(AuditLog.sequence)
        ).all()
    )


# --- a suspension is reachable and frozen -----------------------------------


def test_a_suspended_workspace_can_still_be_read(
    admin: Console,
    acme: Tenant,
) -> None:
    """The useful reading, and the one the status enum's comment promises.

    A business that has not paid should be able to look at its history,
    see what it owes and settle it. Taking their records away over an
    invoice punishes them for the thing you want them to fix.
    """
    assert _suspend(admin, acme).status_code == 200

    for path in ("", "contacts", "conversations", "members"):
        response = acme.client.get(acme.path(path), headers=acme.owner_headers)

        assert response.status_code == 200, path


def test_a_suspended_workspace_refuses_every_write(
    admin: Console,
    acme: Tenant,
) -> None:
    _suspend(admin, acme)

    refused = acme.client.patch(
        acme.path(),
        json={"name": "Renamed While Frozen"},
        headers=acme.owner_headers,
    )

    assert refused.status_code == 403
    assert refused.json()["code"] == "workspace_suspended"


def test_the_freeze_is_by_method_rather_than_by_role(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """Which is why an administrator's *reads* still work.

    Refusing by role would freeze the audit log and the API key list too,
    and a suspended business unable to read its own audit log is the
    opposite of what a suspension is for.
    """
    acme.on_plan(db_session, PlanTier.BUSINESS)
    _suspend(admin, acme)

    readable = acme.client.get(acme.path("audit-logs"), headers=acme.owner_headers)
    writable = acme.client.post(
        acme.path("contacts"),
        json={"phone_number": "+923001234567"},
        headers=acme.owner_headers,
    )

    assert readable.status_code == 200
    assert writable.status_code == 403


def test_a_suspension_is_lifted_cleanly(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    _suspend(admin, acme)

    assert (
        admin.post(f"/workspaces/{acme.workspace_id}/unsuspend", {}).status_code == 200
    )
    assert _status(db_session, acme) == WorkspaceStatus.ACTIVE
    assert (
        acme.client.patch(
            acme.path(), json={"name": "Renamed"}, headers=acme.owner_headers
        ).status_code
        == 200
    )


def test_unsuspending_what_was_never_frozen_changes_nothing(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # The safest request on this surface. Refusing it would be a
    # confusing answer to somebody trying to put things right.
    response = admin.post(f"/workspaces/{acme.workspace_id}/unsuspend", {})

    assert response.status_code == 200
    assert _tenant_log(db_session, AuditEvent.WORKSPACE_UNSUSPENDED) == []


def test_suspending_twice_is_refused_rather_than_restamped(
    admin: Console,
    acme: Tenant,
) -> None:
    # The reason and the state were recorded together, and a second
    # reason would describe a freeze already in force.
    _suspend(admin, acme)

    again = _suspend(admin, acme, reason="A different reason entirely")

    assert again.status_code == 409


def test_a_reason_is_required_to_freeze_an_account(
    admin: Console,
    acme: Tenant,
) -> None:
    assert admin.post(f"/workspaces/{acme.workspace_id}/suspend", {}).status_code == 422


def test_the_customer_sees_the_freeze_in_their_own_log(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    _suspend(admin, acme)

    (entry,) = _tenant_log(db_session, AuditEvent.WORKSPACE_SUSPENDED)

    assert entry.meta["reason"] == REASON
    # By staff, and never looking like one of their own people.
    assert entry.meta["by_staff"] == "platform-admin@example.com"
    assert entry.actor_user_id is None


# --- closing, restoring, erasing --------------------------------------------


def test_closing_needs_the_slug_typed_back(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    wrong = admin.post(
        f"/workspaces/{acme.workspace_id}/cancel",
        {"confirm_slug": "acme-fashions"},
    )

    assert wrong.status_code == 422
    assert wrong.json()["code"] == "confirmation_mismatch"
    assert _status(db_session, acme) == WorkspaceStatus.ACTIVE


def test_closing_schedules_erasure_the_way_a_customer_closing_does(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """Through the same service method, so the two cannot drift.

    A second closing path that set the date differently is how a business
    ends up erased on a day nobody told them about.
    """
    response = admin.post(
        f"/workspaces/{acme.workspace_id}/cancel",
        {"confirm_slug": "acme-fashion"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["erase_after"] is not None
    assert _status(db_session, acme) == WorkspaceStatus.CANCELLED

    (closed,) = _tenant_log(db_session, AuditEvent.WORKSPACE_CLOSED)
    assert closed.meta["by_staff"] == "platform-admin@example.com"


def test_a_closed_workspace_comes_back_intact(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    contact_id = acme.contact("+923001234567")
    admin.post(
        f"/workspaces/{acme.workspace_id}/cancel", {"confirm_slug": "acme-fashion"}
    )

    restored = admin.post(f"/workspaces/{acme.workspace_id}/restore", {})

    assert restored.status_code == 200
    assert restored.json()["status"] == "active"
    # And with no date left on it, or the next sweep erases it anyway.
    assert restored.json()["erase_after"] is None

    still_there = acme.client.get(
        acme.path("contacts", contact_id), headers=acme.owner_headers
    )
    assert still_there.status_code == 200


def test_restore_after_the_date_refuses_rather_than_pretending(
    admin: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """By then the erasure job may have run, may be running, or may run in
    the next minute -- and "restored" would be a promise this cannot keep.
    """
    admin.post(
        f"/workspaces/{acme.workspace_id}/cancel", {"confirm_slug": "acme-fashion"}
    )
    workspace = db_session.get(Workspace, uuid.UUID(acme.workspace_id))
    assert workspace is not None
    workspace.erase_after = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    refused = admin.post(f"/workspaces/{acme.workspace_id}/restore", {})

    assert refused.status_code == 409


def test_the_erasure_date_moves_both_ways(
    admin: Console,
    acme: Tenant,
) -> None:
    admin.post(
        f"/workspaces/{acme.workspace_id}/cancel", {"confirm_slug": "acme-fashion"}
    )
    sooner = (datetime.now(UTC) + timedelta(days=2)).isoformat()

    response = admin.patch(
        f"/workspaces/{acme.workspace_id}/erase-after",
        {"erase_after": sooner},
    )

    assert response.status_code == 200
    assert datetime.fromisoformat(
        response.json()["erase_after"]
    ) == datetime.fromisoformat(sooner)


def test_only_an_owner_may_erase(admin: Console, acme: Tenant) -> None:
    # Refused on the rank before the approval is even looked at, which is
    # the order that keeps an admin from discovering whether one exists.
    response = admin.post(
        f"/workspaces/{acme.workspace_id}/erase-now",
        {"confirm_slug": "acme-fashion", "approval_id": str(uuid.uuid4())},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "insufficient_staff_role"


def test_erasing_with_the_wrong_slug_is_refused_and_recorded(
    owner: Console,
    colleague: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """The one entry in this table written for something that did not
    happen, which the plan asks for by name.

    Somebody typing the wrong name into an erasure is either tired or in
    the wrong window, and both are worth a row.
    """
    approval_id = _approved_erasure(owner, colleague, acme.workspace_id)
    refused = owner.post(
        f"/workspaces/{acme.workspace_id}/erase-now",
        {"confirm_slug": "acme", "approval_id": approval_id},
    )

    assert refused.status_code == 422
    assert db_session.get(Workspace, uuid.UUID(acme.workspace_id)) is not None

    (attempt,) = entries(db_session, AdminAction.WORKSPACE_ERASE_REFUSED)

    assert attempt.meta["typed"] == "acme"
    assert attempt.workspace_slug == "acme-fashion"


def test_erasing_destroys_the_workspace_and_leaves_the_record(
    owner: Console,
    colleague: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    """The whole arrangement, in one test.

    The workspace and everything hanging off it goes. The entry saying so
    does not, because this table's workspace reference is nullable and
    does not cascade -- and it still names the account, by slug.
    """
    acme.contact("+923001234567")
    workspace_id = uuid.UUID(acme.workspace_id)

    approval_id = _approved_erasure(owner, colleague, acme.workspace_id)
    response = owner.post(
        f"/workspaces/{acme.workspace_id}/erase-now",
        {"confirm_slug": "acme-fashion", "approval_id": approval_id},
    )

    assert response.status_code == 204

    db_session.expire_all()

    assert db_session.get(Workspace, workspace_id) is None

    (erased,) = entries(db_session, AdminAction.WORKSPACE_ERASED)

    assert erased.workspace_id is None
    assert erased.workspace_slug == "acme-fashion"
    assert erased.actor_email == "platform-owner@example.com"


def test_the_erasure_entry_is_written_before_the_delete(
    owner: Console,
    colleague: Console,
    acme: Tenant,
    db_session: Session,
) -> None:
    # Not an ordering detail: afterwards there is no workspace to write
    # about. If the entry were written after, a crash in between would
    # destroy an account with nothing saying who did it.
    approval_id = _approved_erasure(owner, colleague, acme.workspace_id)
    owner.post(
        f"/workspaces/{acme.workspace_id}/erase-now",
        {"confirm_slug": "acme-fashion", "approval_id": approval_id},
    )

    db_session.expire_all()
    written = db_session.scalars(
        select(AdminAuditLog).order_by(AdminAuditLog.sequence)
    ).all()

    assert written[-1].action == AdminAction.WORKSPACE_ERASED


# --- a person ---------------------------------------------------------------


def test_deactivating_signs_the_account_out(
    admin: Console,
    client: TestClient,
    db_session: Session,
    user_repository: UserRepository,
) -> None:
    """Both halves or neither.

    A deactivated account that stays signed in is not deactivated: the
    access token in a browser keeps working until it expires, and the
    refresh behind it would mint another.
    """
    headers = sign_up(client, "customer@example.com")
    user = user_repository.get_by_email("customer@example.com")
    assert user is not None

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    response = admin.post(f"/users/{user.id}/deactivate", {})

    assert response.status_code == 200
    assert response.json()["is_active"] is False

    db_session.expire_all()
    live = db_session.scalars(
        select(UserSession).where(
            UserSession.user_id == user.id, UserSession.revoked_at.is_(None)
        )
    ).all()

    assert live == []
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_an_account_can_be_turned_back_on(
    admin: Console,
    client: TestClient,
    user_repository: UserRepository,
) -> None:
    sign_up(client, "customer@example.com")
    user = user_repository.get_by_email("customer@example.com")
    assert user is not None
    admin.post(f"/users/{user.id}/deactivate", {})

    assert admin.post(f"/users/{user.id}/activate", {}).json()["is_active"] is True

    # Coming back means signing in, which is also what proves the account
    # is theirs again.
    signed_in = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@example.com", "password": PASSWORD},
    )
    assert signed_in.status_code == 200


def test_sessions_can_be_ended_without_turning_the_account_off(
    admin: Console,
    client: TestClient,
    user_repository: UserRepository,
) -> None:
    # The answer to "somebody has my laptop" from a customer who cannot
    # reach their own session list.
    headers = sign_up(client, "customer@example.com")
    user = user_repository.get_by_email("customer@example.com")
    assert user is not None

    response = admin.post(f"/users/{user.id}/sessions/revoke", {})

    assert response.json()["sessions_ended"] == 1
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    # And they can sign straight back in, which is the difference between
    # this and deactivating.
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "customer@example.com", "password": PASSWORD},
        ).status_code
        == 200
    )


def test_an_address_can_be_confirmed_when_the_mail_will_not_arrive(
    admin: Console,
    client: TestClient,
    user_repository: UserRepository,
    db_session: Session,
) -> None:
    sign_up(client, "customer@example.com")
    user = user_repository.get_by_email("customer@example.com")
    assert user is not None
    assert user.email_verified_at is None

    response = admin.post(f"/users/{user.id}/verify-email", {})

    assert response.status_code == 200
    assert response.json()["email_verified_at"] is not None

    # And it records whose word it was, because that is the whole of the
    # proof here.
    (entry,) = entries(db_session, AdminAction.USER_EMAIL_VERIFIED)
    assert entry.actor_email == "platform-admin@example.com"
    assert entry.target_user_id == user.id


def test_confirming_an_address_twice_keeps_the_first_date(
    admin: Console,
    client: TestClient,
    user_repository: UserRepository,
) -> None:
    # The question the column answers is when it was *first* proved.
    sign_up(client, "customer@example.com")
    user = user_repository.get_by_email("customer@example.com")
    assert user is not None

    first = admin.post(f"/users/{user.id}/verify-email", {}).json()
    second = admin.post(f"/users/{user.id}/verify-email", {}).json()

    assert first["email_verified_at"] == second["email_verified_at"]


def test_support_may_not_change_anybodys_account(
    client: TestClient,
    db_session: Session,
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    # Reading an account is any rank; changing one is `admin`.
    console = Console(client, db_session, "support@example.com", StaffRole.SUPPORT)
    user = user_repository.get_by_email("owner-acme-fashion@example.com")
    assert user is not None

    assert console.post(f"/users/{user.id}/deactivate", {}).status_code == 403
    assert (
        console.post(
            f"/workspaces/{acme.workspace_id}/suspend", {"reason": REASON}
        ).status_code
        == 403
    )


# --- a frozen account still hears from its customers ------------------------


def test_a_suspended_workspace_still_ingests_inbound_messages(
    admin: Console,
    db_session: Session,
    workspace_repository: WorkspaceRepository,
    membership_repository: WorkspaceMembershipRepository,
    whatsapp_account_repository: WhatsAppAccountRepository,
    client: TestClient,
) -> None:
    """The acceptance criterion, and the decision behind it.

    Refusing to ingest would lose a customer's question over their
    supplier's unpaid invoice -- the worst thing a suspension could do to
    somebody who is not party to it. So the delivery is accepted and
    stored, and the assistant simply does not answer it: the message sits
    unanswered in an inbox the business can still read, which is exactly
    where a person would find it.
    """
    user = User(
        name="Owner",
        email="frozen-owner@example.com",
        hashed_password="not a real hash",
    )
    db_session.add(user)
    db_session.flush()

    workspaces = WorkspaceService(
        session=db_session,
        workspaces=workspace_repository,
        memberships=membership_repository,
        audit=audit_service(db_session),
    )
    workspace = workspaces.create(
        WorkspaceCreate(name="Frozen Goods", slug="frozen-goods"),
        creator=user,
    )
    whatsapp_account_repository.create(
        workspace_id=workspace.id,
        provider="meta_cloud",  # type: ignore[arg-type]
        phone_number="+15550001111",
        external_phone_number_id=PHONE_NUMBER_ID,
        external_business_account_id=None,
        access_token_encrypted=encrypt("a-provider-token"),
    )

    admin.post(f"/workspaces/{workspace.id}/suspend", {"reason": REASON})

    secret = get_settings().whatsapp_app_secret
    assert secret is not None
    body, header = sign(inbound_payload(), secret.get_secret_value())
    delivered = client.post(
        "/api/v1/webhooks/whatsapp",
        content=body,
        headers={
            "X-Hub-Signature-256": header,
            "Content-Type": "application/json",
        },
    )

    assert delivered.status_code == 200

    stored = db_session.scalars(
        select(Message).where(Message.workspace_id == workspace.id)
    ).all()

    # The customer's message is there, and nothing was sent back.
    assert [message.direction for message in stored] == [Direction.INBOUND]
