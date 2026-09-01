"""Phase 26 acceptance: what a business's own people did to it.

The plan asks for two things and the second is the harder one: an endpoint,
and a log that is append-only from the application's perspective. Most of
this file is about the first; the tests near the end are about what makes
the second worth having -- that an administrator cannot quietly remove
themselves from the record, and that nothing anywhere can edit an entry.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditEvent, AuditLog
from app.models.user import User
from app.models.workspace_membership import WorkspaceRole
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.plans import PlanTier
from tests.support.services import put_on_plan
from tests.support.tenants import PASSWORD, Tenant, sign_up


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    db_session: Session,
) -> Tenant:
    """A business on the plan that includes an audit log.

    Business, because that is the only plan whose features include this --
    which is the plan document's own reading of who audit logs are for.
    """
    tenant = Tenant(client, user_repository, membership_repository, "acme-fashion")
    tenant.on_plan(db_session, PlanTier.BUSINESS)

    return tenant


def _page(tenant: Tenant, **params: Any) -> dict[str, Any]:
    response = tenant.client.get(
        tenant.path("audit-logs"),
        headers=tenant.owner_headers,
        params=params,
    )
    assert response.status_code == 200, response.text

    return dict(response.json())


def _events(tenant: Tenant, **params: Any) -> list[str]:
    return [item["event"] for item in _page(tenant, **params)["items"]]


def _entry(tenant: Tenant, event: AuditEvent) -> dict[str, Any]:
    items = _page(tenant, event=event.value)["items"]
    assert items, f"no {event.value} entry"

    return dict(items[0])


def _connect(tenant: Tenant, phone_number: str = "+15550001111") -> None:
    response = tenant.client.post(
        tenant.path("integrations", "whatsapp", "connect"),
        json={
            "phone_number": phone_number,
            "external_phone_number_id": "109876543210987",
            "access_token": "a-provider-token",
        },
        headers=tenant.owner_headers,
    )
    assert response.status_code == 201, response.text


def _upload(tenant: Tenant, title: str = "Returns policy") -> str:
    source = tenant.client.post(
        tenant.path("knowledge", "sources"),
        json={"name": "Policies", "source_type": "text"},
        headers=tenant.owner_headers,
    ).json()["id"]
    response = tenant.client.post(
        tenant.path("knowledge", "documents"),
        json={
            "knowledge_source_id": source,
            "title": title,
            "content": "Returns are accepted within 14 days of delivery.",
        },
        headers=tenant.owner_headers,
    )
    assert response.status_code == 201, response.text

    return str(response.json()["id"])


def _thread(tenant: Tenant) -> str:
    contact = tenant.contact()
    response = tenant.client.post(
        tenant.path("conversations"),
        json={"contact_id": contact},
        headers=tenant.owner_headers,
    )
    assert response.status_code == 201, response.text

    return str(response.json()["id"])


# --- what gets recorded -----------------------------------------------------


def test_a_workspace_begins_with_the_record_of_its_creation(acme: Tenant) -> None:
    # Written in the transaction that created it, so there is no workspace
    # whose history starts anywhere else.
    entry = _entry(acme, AuditEvent.WORKSPACE_CREATED)

    assert entry["metadata"]["slug"] == "acme-fashion"
    assert entry["actor"]["email"] == "owner-acme-fashion@example.com"


def test_renaming_records_what_it_was_and_what_it_became(acme: Tenant) -> None:
    acme.client.patch(
        acme.path(),
        json={"name": "Acme Couture"},
        headers=acme.owner_headers,
    )

    changed = _entry(acme, AuditEvent.WORKSPACE_UPDATED)["metadata"]["changed"]

    assert changed["name"] == {"from": "Acme-Fashion", "to": "Acme Couture"}
    # Only the field that moved. A PATCH carrying one key should not leave
    # an entry claiming the other two were set to what they already were.
    assert list(changed) == ["name"]


def test_saving_a_form_without_changing_anything_records_nothing(
    acme: Tenant,
) -> None:
    acme.client.patch(
        acme.path(),
        json={"name": "Acme-Fashion"},
        headers=acme.owner_headers,
    )

    assert AuditEvent.WORKSPACE_UPDATED.value not in _events(acme)


def test_inviting_and_joining_are_two_entries_by_two_people(
    acme: Tenant,
    client: TestClient,
) -> None:
    invitation = acme.client.post(
        acme.path("invitations"),
        json={"email": "colleague@example.com", "role": "agent"},
        headers=acme.owner_headers,
    ).json()

    headers = sign_up(client, "colleague@example.com")
    response = client.post(
        f"/api/v1/invitations/{invitation['token']}/accept",
        headers=headers,
    )
    assert response.status_code == 200, response.text

    invited = _entry(acme, AuditEvent.MEMBER_INVITED)
    joined = _entry(acme, AuditEvent.MEMBER_JOINED)

    assert invited["actor"]["email"] == "owner-acme-fashion@example.com"
    # The one entry in the product whose actor was not already a member.
    assert joined["actor"]["email"] == "colleague@example.com"
    assert joined["metadata"]["role"] == "agent"


def test_an_invitation_token_never_reaches_the_audit_log(acme: Tenant) -> None:
    """The log is read by more people than the invitation was sent to."""
    invitation = acme.client.post(
        acme.path("invitations"),
        json={"email": "colleague@example.com", "role": "agent"},
        headers=acme.owner_headers,
    ).json()

    entry = _entry(acme, AuditEvent.MEMBER_INVITED)

    assert invitation["token"] not in str(entry)


def test_a_role_change_records_both_ranks(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    acme.member("colleague@example.com", WorkspaceRole.AGENT)
    colleague = user_repository.get_by_email("colleague@example.com")
    assert colleague is not None

    response = acme.client.patch(
        acme.path("members", str(colleague.id)),
        json={"role": "admin"},
        headers=acme.owner_headers,
    )
    assert response.status_code == 200, response.text

    meta = _entry(acme, AuditEvent.MEMBER_ROLE_CHANGED)["metadata"]

    # Both, because "was promoted to admin" without the rank they held is
    # half an answer to the question somebody is actually asking.
    assert (meta["from"], meta["to"]) == ("agent", "admin")
    assert meta["user_id"] == colleague.id


def test_removing_a_colleague_is_recorded(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    acme.member("colleague@example.com", WorkspaceRole.AGENT)
    colleague = user_repository.get_by_email("colleague@example.com")
    assert colleague is not None

    response = acme.client.delete(
        acme.path("members", str(colleague.id)),
        headers=acme.owner_headers,
    )
    assert response.status_code == 204

    entry = _entry(acme, AuditEvent.MEMBER_REMOVED)

    assert entry["metadata"]["user_id"] == colleague.id
    assert entry["actor"]["email"] == "owner-acme-fashion@example.com"


def test_connecting_and_disconnecting_the_number_records_which_number(
    acme: Tenant,
) -> None:
    _connect(acme)
    response = acme.client.delete(
        acme.path("integrations", "whatsapp"),
        headers=acme.owner_headers,
    )
    assert response.status_code == 204

    connected = _entry(acme, AuditEvent.WHATSAPP_CONNECTED)
    disconnected = _entry(acme, AuditEvent.WHATSAPP_DISCONNECTED)

    assert connected["metadata"]["phone_number"] == "+15550001111"
    # Read off the row before it was deleted. Afterwards there is nothing
    # left to say which line went quiet.
    assert disconnected["metadata"]["phone_number"] == "+15550001111"


def test_the_provider_token_never_reaches_the_audit_log(acme: Tenant) -> None:
    _connect(acme)

    assert "a-provider-token" not in str(_page(acme))


def test_a_document_and_its_deletion_are_recorded_with_its_title(
    acme: Tenant,
) -> None:
    document_id = _upload(acme, title="Returns policy")
    response = acme.client.delete(
        acme.path("knowledge", "documents", document_id),
        headers=acme.owner_headers,
    )
    assert response.status_code == 204

    uploaded = _entry(acme, AuditEvent.KNOWLEDGE_DOCUMENT_UPLOADED)
    deleted = _entry(acme, AuditEvent.KNOWLEDGE_DOCUMENT_DELETED)

    assert uploaded["metadata"]["title"] == "Returns policy"
    # The title, not only the id: this is the entry somebody reads when
    # the assistant stops answering a question it used to answer.
    assert deleted["metadata"]["title"] == "Returns policy"
    assert deleted["metadata"]["document_id"] == document_id


def test_assigning_a_thread_and_taking_it_back_are_both_recorded(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    acme.member("colleague@example.com", WorkspaceRole.AGENT)
    colleague = user_repository.get_by_email("colleague@example.com")
    assert colleague is not None
    conversation = _thread(acme)

    for assignee in (colleague.id, None):
        response = acme.client.post(
            acme.path("conversations", conversation, "assign"),
            json={"user_id": assignee},
            headers=acme.owner_headers,
        )
        assert response.status_code == 200, response.text

    assigned = [
        item["metadata"]["assigned_to"]
        for item in _page(acme, event=AuditEvent.CONVERSATION_ASSIGNED.value)["items"]
    ]

    # Newest first, so unassigning comes back before the assignment.
    assert assigned == [None, colleague.id]


def test_closing_a_thread_is_recorded_and_reopening_it_is_not(
    acme: Tenant,
) -> None:
    """One direction, which is the plan's vocabulary and the useful one.

    Closing takes a customer's thread out of the queue everybody works
    from; a thread closed by mistake is invisible until somebody goes
    looking for it. Reopening puts it back where people can see it.
    """
    conversation = _thread(acme)

    acme.client.post(
        acme.path("conversations", conversation, "close"),
        headers=acme.owner_headers,
    )
    acme.client.post(
        acme.path("conversations", conversation, "reopen"),
        headers=acme.owner_headers,
    )

    assert _events(acme).count(AuditEvent.CONVERSATION_CLOSED.value) == 1


def test_switching_the_assistant_off_is_recorded_with_what_it_was(
    acme: Tenant,
) -> None:
    conversation = _thread(acme)

    response = acme.client.patch(
        acme.path("conversations", conversation),
        json={"ai_mode": "disabled"},
        headers=acme.owner_headers,
    )
    assert response.status_code == 200, response.text

    meta = _entry(acme, AuditEvent.CONVERSATION_AI_DISABLED)["metadata"]

    assert meta["from"] == "suggest_only"
    assert meta["conversation_id"] == conversation


def test_switching_the_assistant_on_is_not_recorded_as_switching_it_off(
    acme: Tenant,
) -> None:
    conversation = _thread(acme)

    acme.client.patch(
        acme.path("conversations", conversation),
        json={"ai_mode": "automatic"},
        headers=acme.owner_headers,
    )

    assert AuditEvent.CONVERSATION_AI_DISABLED.value not in _events(acme)


def test_a_cancellation_names_the_person_who_asked_for_it(acme: Tenant) -> None:
    """Which the payment provider's own webhook cannot answer.

    "Who stopped paying for this" is a question a business asks about
    itself, and the delivery that follows a cancellation knows only that
    the subscription changed.
    """
    response = acme.client.post(
        acme.path("subscription", "cancel"),
        headers=acme.owner_headers,
    )
    assert response.status_code == 200, response.text

    entry = _entry(acme, AuditEvent.SUBSCRIPTION_CHANGED)

    assert entry["actor"]["email"] == "owner-acme-fashion@example.com"
    assert entry["metadata"]["cancel_at_period_end"] is True


def test_an_entry_with_nobody_behind_it_says_so(
    acme: Tenant,
    db_session: Session,
) -> None:
    """The third state of an actor, and the reason the join is an outer one.

    A payment provider changing a subscription has no person behind it, and
    naming one would put an accusation in the record.
    """
    AuditLogRepository(db_session).record(
        workspace_id=uuid.UUID(acme.workspace_id),
        event=AuditEvent.SUBSCRIPTION_CHANGED,
        actor_user_id=None,
        meta={"event_type": "invoice.payment_failed"},
    )
    db_session.flush()

    assert _entry(acme, AuditEvent.SUBSCRIPTION_CHANGED)["actor"] is None


# --- who may read it --------------------------------------------------------


def test_the_log_is_for_administrators(acme: Tenant) -> None:
    headers = acme.member("agent@example.com", WorkspaceRole.AGENT)

    response = acme.client.get(acme.path("audit-logs"), headers=headers)

    assert response.status_code == 403


def test_the_log_needs_a_plan_that_includes_it(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    db_session: Session,
) -> None:
    """Business only, which is what the plan catalogue already says.

    Growth is checked as well as the free plan, because "a paid plan" and
    "the plan that includes this" are different things and a gate that
    admitted the first would be no gate at all.
    """
    tenant = Tenant(client, user_repository, membership_repository, "on-starter")

    assert (
        client.get(tenant.path("audit-logs"), headers=tenant.owner_headers).status_code
        == 402
    )

    put_on_plan(db_session, tenant.workspace_id, PlanTier.GROWTH)

    assert (
        client.get(tenant.path("audit-logs"), headers=tenant.owner_headers).status_code
        == 402
    )


def test_reading_the_log_needs_a_token(client: TestClient, acme: Tenant) -> None:
    assert client.get(acme.path("audit-logs")).status_code == 401


def test_one_businesss_history_is_not_anothers(
    acme: Tenant,
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    db_session: Session,
) -> None:
    rival = Tenant(client, user_repository, membership_repository, "rival-store")
    rival.on_plan(db_session, PlanTier.BUSINESS)

    _connect(acme)

    assert AuditEvent.WHATSAPP_CONNECTED.value in _events(acme)
    assert AuditEvent.WHATSAPP_CONNECTED.value not in _events(rival)
    # Its own creation and nothing else.
    assert _events(rival) == [AuditEvent.WORKSPACE_CREATED.value]


def test_a_stranger_is_told_the_workspace_does_not_exist(
    acme: Tenant,
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    # Membership is established before the plan and the role are consulted,
    # so a stranger guessing at an id learns nothing about the workspace.
    rival = Tenant(client, user_repository, membership_repository, "rival-store")

    response = client.get(acme.path("audit-logs"), headers=rival.owner_headers)

    assert response.status_code == 404


# --- reading it -------------------------------------------------------------


def test_the_newest_entry_comes_first(acme: Tenant) -> None:
    _connect(acme)

    assert _events(acme) == [
        AuditEvent.WHATSAPP_CONNECTED.value,
        AuditEvent.WORKSPACE_CREATED.value,
    ]


def test_entries_written_in_one_transaction_keep_their_order(
    acme: Tenant,
    db_session: Session,
) -> None:
    """The reason the table has a sequence at all.

    now() is fixed for the length of a transaction, so entries written in
    one share a created_at to the microsecond -- and ordering on the id
    after that would shuffle them, because it is a UUID.
    """
    logs = AuditLogRepository(db_session)
    workspace_id = uuid.UUID(acme.workspace_id)

    for index in range(5):
        logs.record(
            workspace_id=workspace_id,
            event=AuditEvent.WORKSPACE_UPDATED,
            actor_user_id=None,
            meta={"index": index},
        )
    db_session.flush()

    written = _page(acme, event=AuditEvent.WORKSPACE_UPDATED.value)["items"]

    assert [item["metadata"]["index"] for item in written] == [4, 3, 2, 1, 0]


def test_filtering_by_event(acme: Tenant) -> None:
    _connect(acme)
    _upload(acme)

    assert _events(acme, event=AuditEvent.WHATSAPP_CONNECTED.value) == [
        AuditEvent.WHATSAPP_CONNECTED.value
    ]
    assert _page(acme, event=AuditEvent.WHATSAPP_CONNECTED.value)["total"] == 1


def test_filtering_by_actor(
    acme: Tenant,
    user_repository: UserRepository,
) -> None:
    """The question an investigation actually starts from."""
    headers = acme.member("colleague@example.com", WorkspaceRole.ADMIN)
    colleague = user_repository.get_by_email("colleague@example.com")
    assert colleague is not None

    acme.client.patch(
        acme.path(),
        json={"name": "Acme Couture"},
        headers=headers,
    )

    theirs = _page(acme, actor_user_id=colleague.id)

    assert [item["event"] for item in theirs["items"]] == [
        AuditEvent.WORKSPACE_UPDATED.value
    ]
    assert theirs["total"] == 1


def test_filtering_by_date_range(acme: Tenant, db_session: Session) -> None:
    now = datetime.now(UTC)

    # Everything so far is inside a window that ends before it happened.
    assert _page(acme, until=(now - timedelta(days=1)).isoformat())["total"] == 0
    assert _page(acme, since=(now - timedelta(days=1)).isoformat())["total"] == 1


def test_paging(acme: Tenant) -> None:
    _connect(acme)
    _upload(acme)

    first = _page(acme, page=1, page_size=2)
    second = _page(acme, page=2, page_size=2)

    assert first["total"] == 3
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert second["items"][0]["event"] == AuditEvent.WORKSPACE_CREATED.value


# --- append-only ------------------------------------------------------------


def test_nothing_edits_or_deletes_an_entry(acme: Tenant) -> None:
    """Append-only from the application's perspective, as the plan asks.

    Enforced by omission rather than by a rule: there is no route to reach
    and no repository method to call, which is the version of this that a
    handler written next month cannot get wrong.
    """
    path = acme.path("audit-logs")

    assert (
        acme.client.patch(path, json={}, headers=acme.owner_headers).status_code == 405
    )
    assert acme.client.delete(path, headers=acme.owner_headers).status_code == 405

    assert not hasattr(AuditLogRepository, "update")
    assert not hasattr(AuditLogRepository, "delete")


def test_closing_an_account_does_not_erase_what_it_did(
    acme: Tenant,
    client: TestClient,
    db_session: Session,
    user_repository: UserRepository,
) -> None:
    """The move an audit log exists to defeat.

    Accounts here are deleted rather than retired, and the foreign key is
    ON DELETE SET NULL -- so without the address copied onto the entry, an
    administrator could remove themselves from the record of what they did
    by closing their own account.
    """
    headers = acme.member("colleague@example.com", WorkspaceRole.ADMIN)
    acme.client.patch(
        acme.path(),
        json={"name": "Acme Couture"},
        headers=headers,
    )

    response = client.request(
        "DELETE",
        "/api/v1/account",
        json={"password": PASSWORD},
        headers=headers,
    )
    assert response.status_code == 204, response.text
    assert user_repository.get_by_email("colleague@example.com") is None

    entry = _entry(acme, AuditEvent.WORKSPACE_UPDATED)

    # The account is gone, so the id went with it. What they did, and the
    # address that did it, did not.
    assert entry["actor"]["user_id"] is None
    assert entry["actor"]["email"] == "colleague@example.com"
    assert entry["metadata"]["changed"]["name"]["to"] == "Acme Couture"


def test_an_entry_is_never_rewritten_by_a_later_one(
    acme: Tenant,
    db_session: Session,
) -> None:
    """Two changes to one thing are two rows, not one row twice."""
    for name in ("Acme Couture", "Acme Atelier"):
        acme.client.patch(
            acme.path(),
            json={"name": name},
            headers=acme.owner_headers,
        )

    stored = db_session.scalars(
        select(AuditLog)
        .where(AuditLog.event == AuditEvent.WORKSPACE_UPDATED)
        .order_by(AuditLog.sequence)
    ).all()

    assert [entry.meta["changed"]["name"]["to"] for entry in stored] == [
        "Acme Couture",
        "Acme Atelier",
    ]


def test_the_actor_name_is_read_live_rather_than_frozen(
    acme: Tenant,
    db_session: Session,
    user_repository: UserRepository,
) -> None:
    """The half of an actor that should not be a copy.

    A colleague who changes their name should read as the person they are
    now; the address is stored only because it has to outlive the account.
    """
    owner = user_repository.get_by_email("owner-acme-fashion@example.com")
    assert owner is not None
    owner.name = "Ayesha Khan"
    db_session.flush()

    assert _entry(acme, AuditEvent.WORKSPACE_CREATED)["actor"]["name"] == "Ayesha Khan"


def test_every_recorded_event_is_one_the_vocabulary_allows(
    acme: Tenant,
    db_session: Session,
) -> None:
    """The CHECK constraint is the vocabulary, not a comment about it."""
    _connect(acme)
    _upload(acme)

    stored = db_session.scalars(
        select(AuditLog).where(AuditLog.workspace_id == uuid.UUID(acme.workspace_id))
    ).all()

    assert stored
    assert all(entry.event in set(AuditEvent) for entry in stored)


def test_an_actor_is_a_real_person_in_this_workspace(
    acme: Tenant,
    db_session: Session,
) -> None:
    """Nothing invents an actor to fill the column in."""
    _connect(acme)

    actors = db_session.scalars(
        select(AuditLog.actor_user_id).where(
            AuditLog.workspace_id == uuid.UUID(acme.workspace_id)
        )
    ).all()
    owner = db_session.scalars(
        select(User).where(User.email == "owner-acme-fashion@example.com")
    ).one()

    assert set(actors) == {owner.id}
