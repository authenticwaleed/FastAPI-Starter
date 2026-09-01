"""Phase 27 acceptance: credentials a customer's own software holds.

Three endpoints, one storage rule, and the storage rule is the one worth
reading the tests for: return the plaintext key only once. Everything
after that follows from it -- the digest is what is stored, the fragment
is what a list can show, and a customer who loses the key issues another
because nothing here can produce it a second time.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.api_key import API_KEY_HEADER
from app.core.security import API_KEY_PREFIX, hash_token
from app.models.api_key import ApiKey
from app.models.audit_log import AuditEvent
from app.models.subscription import Subscription
from app.models.workspace_membership import WorkspaceRole
from app.repositories.api_key_repository import ApiKeyRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)
from app.services.plans import PlanTier
from tests.support.services import put_on_plan
from tests.support.tenants import Tenant

CURRENT = "/api/v1/api-keys/current"


@pytest.fixture
def acme(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    db_session: Session,
) -> Tenant:
    """A business on the plan whose features include API access."""
    tenant = Tenant(client, user_repository, membership_repository, "acme-fashion")
    tenant.on_plan(db_session, PlanTier.BUSINESS)

    return tenant


def _issue(
    tenant: Tenant,
    name: str = "Staging server",
    **fields: Any,
) -> dict[str, Any]:
    response = tenant.client.post(
        tenant.path("api-keys"),
        json={"name": name} | fields,
        headers=tenant.owner_headers,
    )
    assert response.status_code == 201, response.text

    return dict(response.json())


def _list(tenant: Tenant) -> list[dict[str, Any]]:
    response = tenant.client.get(tenant.path("api-keys"), headers=tenant.owner_headers)
    assert response.status_code == 200, response.text

    return list(response.json())


def _stored(session: Session, key_id: str) -> ApiKey:
    return session.scalars(select(ApiKey).where(ApiKey.id == uuid.UUID(key_id))).one()


# --- issuing ----------------------------------------------------------------


def test_a_new_key_comes_back_once_and_looks_like_one(acme: Tenant) -> None:
    issued = _issue(acme)

    assert issued["key"].startswith(API_KEY_PREFIX)
    assert issued["name"] == "Staging server"
    # The readable fragment is the start of the key itself, so a customer
    # can match the two up without holding the whole thing.
    assert issued["key"].startswith(issued["key_prefix"])
    assert issued["revoked_at"] is None
    assert issued["last_used_at"] is None


def test_the_key_itself_is_never_stored(acme: Tenant, db_session: Session) -> None:
    """The plan's one storage instruction, from the database's side."""
    issued = _issue(acme)
    stored = _stored(db_session, issued["id"])

    assert issued["key"] not in (stored.key_hash, stored.key_prefix, stored.name)
    # What is stored is the digest, which is what makes the lookup on it a
    # single indexed query rather than a scan.
    assert stored.key_hash == hash_token(issued["key"])


def test_the_key_is_never_shown_again(acme: Tenant) -> None:
    issued = _issue(acme)

    listed = _list(acme)

    assert [item["id"] for item in listed] == [issued["id"]]
    assert "key" not in listed[0]
    assert issued["key"] not in str(listed)


def test_two_keys_are_two_different_secrets(acme: Tenant) -> None:
    first = _issue(acme, "Staging server")
    second = _issue(acme, "Production")

    assert first["key"] != second["key"]
    assert first["key_prefix"] != second["key_prefix"]


def test_a_key_does_not_expire_unless_asked_to(acme: Tenant) -> None:
    """Offered rather than imposed.

    A key that stops working on a date nobody remembers choosing is an
    outage in a customer's system.
    """
    assert _issue(acme)["expires_at"] is None


def test_an_expiry_is_set_from_the_days_asked_for(acme: Tenant) -> None:
    issued = _issue(acme, expires_in_days=30)

    expires_at = datetime.fromisoformat(issued["expires_at"])
    expected = datetime.now(UTC) + timedelta(days=30)

    assert abs((expires_at - expected).total_seconds()) < 60


def test_an_absurd_expiry_is_refused(acme: Tenant) -> None:
    response = acme.client.post(
        acme.path("api-keys"),
        json={"name": "Forever", "expires_in_days": 10_000},
        headers=acme.owner_headers,
    )

    assert response.status_code == 422


# --- using ------------------------------------------------------------------


def test_a_key_says_which_workspace_it_addresses(
    acme: Tenant,
    client: TestClient,
) -> None:
    """The call an integration makes first.

    It turns "the key points at the other business" into a failure at
    setup rather than into messages arriving in somebody else's inbox.
    """
    issued = _issue(acme)

    response = client.get(CURRENT, headers={API_KEY_HEADER: issued["key"]})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "workspace_id": acme.workspace_id,
        "name": "Staging server",
        "key_prefix": issued["key_prefix"],
        "expires_at": None,
    }


def test_using_a_key_records_that_it_was_used(
    acme: Tenant,
    client: TestClient,
) -> None:
    issued = _issue(acme)
    assert issued["last_used_at"] is None

    client.get(CURRENT, headers={API_KEY_HEADER: issued["key"]})

    assert _list(acme)[0]["last_used_at"] is not None


def test_a_second_call_does_not_write_again(
    acme: Tenant,
    client: TestClient,
    db_session: Session,
) -> None:
    """Stamped when it has gone stale, not on every request.

    A write per call, to the row that call just read, serialises every
    client sharing one key onto the same row -- for a column whose only
    reader asks whether the key is still in use.
    """
    issued = _issue(acme)

    client.get(CURRENT, headers={API_KEY_HEADER: issued["key"]})
    first = _stored(db_session, issued["id"]).last_used_at

    client.get(CURRENT, headers={API_KEY_HEADER: issued["key"]})

    assert _stored(db_session, issued["id"]).last_used_at == first


def test_a_stale_key_is_stamped_again(
    acme: Tenant,
    client: TestClient,
    db_session: Session,
) -> None:
    issued = _issue(acme)
    key = _stored(db_session, issued["id"])
    key.last_used_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.flush()

    client.get(CURRENT, headers={API_KEY_HEADER: issued["key"]})

    refreshed = _stored(db_session, issued["id"]).last_used_at
    assert refreshed is not None
    assert datetime.now(UTC) - refreshed < timedelta(minutes=1)


def test_a_request_with_no_key_is_refused(client: TestClient) -> None:
    response = client.get(CURRENT)

    assert response.status_code == 401
    # RFC 9110 wants a scheme named, and it is not Bearer: naming Bearer
    # would send a client to retry with a header that will never work.
    assert "ApiKey" in response.headers["WWW-Authenticate"]


def test_an_unknown_key_is_refused(client: TestClient) -> None:
    response = client.get(
        CURRENT,
        headers={API_KEY_HEADER: f"{API_KEY_PREFIX}not-a-key-anybody-issued"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_api_key"


def test_a_revoked_key_is_refused_exactly_like_an_unknown_one(
    acme: Tenant,
    client: TestClient,
) -> None:
    """One refusal for both, deliberately.

    Telling a caller that their key is real but revoked, rather than
    simply wrong, confirms it was once valid -- which is what somebody who
    found it in a log file is trying to establish.
    """
    issued = _issue(acme)
    acme.client.delete(
        acme.path("api-keys", issued["id"]),
        headers=acme.owner_headers,
    )

    revoked = client.get(CURRENT, headers={API_KEY_HEADER: issued["key"]})
    unknown = client.get(CURRENT, headers={API_KEY_HEADER: "lp_nothing"})

    assert revoked.status_code == unknown.status_code == 401
    assert revoked.json() == unknown.json()


def test_an_expired_key_is_refused(
    acme: Tenant,
    client: TestClient,
    db_session: Session,
) -> None:
    issued = _issue(acme, expires_in_days=1)
    key = _stored(db_session, issued["id"])
    key.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()

    response = client.get(CURRENT, headers={API_KEY_HEADER: issued["key"]})

    assert response.status_code == 401


def test_a_key_from_one_business_never_names_another(
    acme: Tenant,
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    db_session: Session,
) -> None:
    rival = Tenant(client, user_repository, membership_repository, "rival-store")
    rival.on_plan(db_session, PlanTier.BUSINESS)

    theirs = _issue(rival)

    identity = client.get(CURRENT, headers={API_KEY_HEADER: theirs["key"]}).json()

    assert identity["workspace_id"] == rival.workspace_id
    assert identity["workspace_id"] != acme.workspace_id


# --- revoking ---------------------------------------------------------------


def test_revoking_stops_the_key_and_keeps_the_row(
    acme: Tenant,
    db_session: Session,
) -> None:
    """Revoked rather than deleted.

    What would be left behind is a digest, not a credential -- and keeping
    the row keeps last_used_at, which is the first thing anybody wants
    after revoking a key in a hurry.
    """
    issued = _issue(acme)

    response = acme.client.delete(
        acme.path("api-keys", issued["id"]),
        headers=acme.owner_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["revoked_at"] is not None
    assert _stored(db_session, issued["id"]).revoked_at is not None


def test_a_revoked_key_stays_in_the_list(acme: Tenant) -> None:
    issued = _issue(acme)
    acme.client.delete(
        acme.path("api-keys", issued["id"]),
        headers=acme.owner_headers,
    )

    listed = _list(acme)

    assert [item["id"] for item in listed] == [issued["id"]]
    assert listed[0]["revoked_at"] is not None


def test_revoking_twice_keeps_the_first_answer(acme: Tenant) -> None:
    """Somebody turning off a key they think is leaked should get the same
    answer whether or not a colleague got there first."""
    issued = _issue(acme)
    path = acme.path("api-keys", issued["id"])

    first = acme.client.delete(path, headers=acme.owner_headers).json()
    second = acme.client.delete(path, headers=acme.owner_headers).json()

    # Compared as instants rather than as strings. The first answer comes
    # from the row this request wrote and the second from one read back
    # through the driver, so the same moment arrives spelled two ways.
    assert datetime.fromisoformat(first["revoked_at"]) == datetime.fromisoformat(
        second["revoked_at"]
    )


def test_a_key_belonging_to_another_business_cannot_be_revoked(
    acme: Tenant,
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    db_session: Session,
) -> None:
    rival = Tenant(client, user_repository, membership_repository, "rival-store")
    rival.on_plan(db_session, PlanTier.BUSINESS)
    theirs = _issue(rival)

    response = acme.client.delete(
        acme.path("api-keys", theirs["id"]),
        headers=acme.owner_headers,
    )

    assert response.status_code == 404
    assert _stored(db_session, theirs["id"]).revoked_at is None


def test_a_key_that_never_existed_answers_the_same_way(acme: Tenant) -> None:
    response = acme.client.delete(
        acme.path("api-keys", str(uuid.uuid4())),
        headers=acme.owner_headers,
    )

    assert response.status_code == 404


# --- who may do this --------------------------------------------------------


def test_keys_are_for_administrators(acme: Tenant) -> None:
    headers = acme.member("agent@example.com", WorkspaceRole.AGENT)

    assert acme.client.get(acme.path("api-keys"), headers=headers).status_code == 403
    assert (
        acme.client.post(
            acme.path("api-keys"), json={"name": "Mine"}, headers=headers
        ).status_code
        == 403
    )


def test_issuing_needs_a_plan_with_api_access(
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
    db_session: Session,
) -> None:
    """Business only, which is what the plan catalogue already says."""
    tenant = Tenant(client, user_repository, membership_repository, "on-growth")
    put_on_plan(db_session, tenant.workspace_id, PlanTier.GROWTH)

    response = client.post(
        tenant.path("api-keys"),
        json={"name": "Staging server"},
        headers=tenant.owner_headers,
    )

    assert response.status_code == 402
    assert response.json()["code"] == "feature_not_in_plan"


def test_a_plan_change_never_traps_a_live_key(
    acme: Tenant,
    db_session: Session,
) -> None:
    """Listing and revoking are not gated, and that is the point.

    Being unable to turn off a credential because of a billing change is
    the wrong way for anything to fail.
    """
    issued = _issue(acme)

    # Moved rather than re-subscribed: this workspace already has a
    # subscription, and there is one per workspace.
    subscription = db_session.scalars(
        select(Subscription).where(
            Subscription.workspace_id == uuid.UUID(acme.workspace_id)
        )
    ).one()
    subscription.plan = PlanTier.STARTER
    db_session.flush()

    assert (
        acme.client.get(acme.path("api-keys"), headers=acme.owner_headers).status_code
        == 200
    )
    assert (
        acme.client.delete(
            acme.path("api-keys", issued["id"]), headers=acme.owner_headers
        ).status_code
        == 200
    )


def test_a_stranger_is_told_the_workspace_does_not_exist(
    acme: Tenant,
    client: TestClient,
    user_repository: UserRepository,
    membership_repository: WorkspaceMembershipRepository,
) -> None:
    rival = Tenant(client, user_repository, membership_repository, "rival-store")

    response = client.get(acme.path("api-keys"), headers=rival.owner_headers)

    assert response.status_code == 404


def test_managing_keys_needs_a_token(client: TestClient, acme: Tenant) -> None:
    assert client.get(acme.path("api-keys")).status_code == 401


# --- the record -------------------------------------------------------------


def test_issuing_and_revoking_reach_the_audit_log(acme: Tenant) -> None:
    issued = _issue(acme)
    acme.client.delete(
        acme.path("api-keys", issued["id"]),
        headers=acme.owner_headers,
    )

    entries = acme.client.get(
        acme.path("audit-logs"),
        headers=acme.owner_headers,
    ).json()["items"]
    events = [item["event"] for item in entries]

    assert AuditEvent.API_KEY_CREATED.value in events
    assert AuditEvent.API_KEY_REVOKED.value in events

    created = next(
        item for item in entries if item["event"] == AuditEvent.API_KEY_CREATED.value
    )
    assert created["metadata"]["api_key_id"] == issued["id"]
    assert created["actor"]["email"] == "owner-acme-fashion@example.com"


def test_the_key_never_reaches_the_audit_log(acme: Tenant) -> None:
    """An audit log is read by more people than the key was issued to."""
    issued = _issue(acme)

    entries = acme.client.get(
        acme.path("audit-logs"),
        headers=acme.owner_headers,
    ).json()

    assert issued["key"] not in str(entries)
    assert issued["key_prefix"] in str(entries)


def test_nothing_can_look_a_key_up_by_its_fragment(
    acme: Tenant,
    db_session: Session,
) -> None:
    """The fragment is a label, not a way in.

    It is stored unhashed and shown freely, so the only thing that must be
    true of it is that presenting it authenticates nothing.
    """
    issued = _issue(acme)
    keys = ApiKeyRepository(db_session)

    assert keys.get_by_hash(hash_token(issued["key_prefix"])) is None
    assert keys.get_by_hash(issued["key_prefix"]) is None
