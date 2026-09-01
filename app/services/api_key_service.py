import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.exceptions import ApiKeyNotFoundError, InvalidApiKeyError
from app.core.security import api_key_display, generate_api_key, hash_token
from app.db.session import SessionDep
from app.models.api_key import ApiKey
from app.models.audit_log import AuditEvent
from app.repositories.api_key_repository import ApiKeyRepository
from app.schemas.api_key import ApiKeyCreate
from app.services.audit_service import AuditService, AuditServiceDep
from app.services.workspace_service import WorkspaceAccess

# How stale `last_used_at` is allowed to get before a request pays to
# update it. Recording the time of every request on the row a request just
# read turns a read-only call into a write, and serialises every client
# sharing one key onto the same row -- for a column whose only reader is a
# person asking "is this key still in use", where five minutes and five
# milliseconds are the same answer.
TOUCH_AFTER = timedelta(minutes=5)


@dataclass(frozen=True)
class IssuedKey:
    """A new key, together with the one copy of it that will ever exist."""

    key: ApiKey
    secret: str


class ApiKeyService:
    """Issuing machine credentials, and checking the ones presented.

    Two halves with different callers. Issuing is administration, done by
    a person through the management endpoints. Checking is done on behalf
    of whatever software the customer wrote, which has no membership, no
    session and nobody to ask -- so everything it can get wrong has to
    come back as the same refusal.
    """

    def __init__(
        self,
        session: Session,
        keys: ApiKeyRepository,
        audit: AuditService,
    ) -> None:
        self._session = session
        self._keys = keys
        self._audit = audit

    # --- issuing -----------------------------------------------------------

    def create(self, access: WorkspaceAccess, payload: ApiKeyCreate) -> IssuedKey:
        """Mint a key, store what proves it, and hand back the key itself.

        The only moment the value exists in readable form. What is stored
        is its digest and its first eleven characters, so nothing here --
        including this service, a minute later -- can reproduce it.
        """
        secret = generate_api_key()
        expires_at = (
            datetime.now(UTC) + timedelta(days=payload.expires_in_days)
            if payload.expires_in_days is not None
            else None
        )

        key = self._keys.create(
            workspace_id=access.workspace.id,
            name=payload.name,
            key_prefix=api_key_display(secret),
            key_hash=hash_token(secret),
            expires_at=expires_at,
        )
        # The fragment, never the key. An audit log is read by more people
        # than the key was issued to, and a log holding working
        # credentials would be the thing this table is arranged to avoid.
        self._audit.did(
            access.workspace.id,
            AuditEvent.API_KEY_CREATED,
            actor_user_id=access.membership.user_id,
            meta={
                "api_key_id": str(key.id),
                "name": key.name,
                "key_prefix": key.key_prefix,
            },
        )
        self._session.commit()

        return IssuedKey(key=key, secret=secret)

    def list_for(self, access: WorkspaceAccess) -> Sequence[ApiKey]:
        return self._keys.list_for_workspace(access.workspace.id)

    def revoke(self, access: WorkspaceAccess, key_id: uuid.UUID) -> ApiKey:
        """Stop a key working, and keep the row that says it existed.

        Revoking twice is not an error. Somebody turning off a key they
        think is leaked should get the same answer whether or not a
        colleague got there first, and the timestamp stays the one from
        when it actually stopped working.
        """
        key = self._keys.get(access.workspace.id, key_id)

        if key is None:
            raise ApiKeyNotFoundError(access.workspace.id, key_id)

        if key.revoked_at is not None:
            return key

        self._keys.revoke(key, datetime.now(UTC))
        self._audit.did(
            access.workspace.id,
            AuditEvent.API_KEY_REVOKED,
            actor_user_id=access.membership.user_id,
            meta={
                "api_key_id": str(key.id),
                "name": key.name,
                "key_prefix": key.key_prefix,
            },
        )
        self._session.commit()

        return key

    # --- checking ----------------------------------------------------------

    def authenticate(self, presented: str) -> ApiKey:
        """Turn a key somebody sent into the key it is, or refuse.

        Looked up by the digest rather than compared against every row,
        which is why the digest is unsalted -- the argument written out in
        `hash_token`, and it applies with more force here because this
        runs on every call rather than once per invitation. There is no
        secret compared in Python, so there is nothing here for a timing
        attack to measure.

        Unknown, revoked and expired are one refusal. Distinguishing them
        would tell whoever found this key in a log file that it was once
        real, which is exactly what they are trying to find out.
        """
        if not presented:
            raise InvalidApiKeyError

        key = self._keys.get_by_hash(hash_token(presented))
        now = datetime.now(UTC)

        if key is None or not key.usable_at(now):
            raise InvalidApiKeyError

        self._touch(key, now)

        return key

    def _touch(self, key: ApiKey, now: datetime) -> None:
        """Record that the key was used, but not on every request.

        A write per call, on the row that call just read, is a real cost
        for a column nobody reads more precisely than "recently". So it is
        stamped when it has gone stale and skipped otherwise.
        """
        if key.last_used_at is not None and now - key.last_used_at < TOUCH_AFTER:
            return

        self._keys.touch(key, now)
        self._session.commit()


def get_api_key_repository(session: SessionDep) -> ApiKeyRepository:
    return ApiKeyRepository(session)


ApiKeyRepositoryDep = Annotated[ApiKeyRepository, Depends(get_api_key_repository)]


def get_api_key_service(
    session: SessionDep,
    keys: ApiKeyRepositoryDep,
    audit: AuditServiceDep,
) -> ApiKeyService:
    return ApiKeyService(session=session, keys=keys, audit=audit)


ApiKeyServiceDep = Annotated[ApiKeyService, Depends(get_api_key_service)]
