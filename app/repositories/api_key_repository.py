import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.api_key import ApiKey


class ApiKeyRepository:
    """Every query against the api_keys table lives here."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        name: str,
        key_prefix: str,
        key_hash: str,
        expires_at: datetime | None,
    ) -> ApiKey:
        key = ApiKey(
            workspace_id=workspace_id,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            expires_at=expires_at,
        )

        self._session.add(key)
        self._session.flush()

        return key

    def get(self, workspace_id: uuid.UUID, key_id: uuid.UUID) -> ApiKey | None:
        return self._session.scalar(
            select(ApiKey).where(
                ApiKey.workspace_id == workspace_id,
                ApiKey.id == key_id,
            )
        )

    def get_by_hash(self, key_hash: str) -> ApiKey | None:
        """The lookup one authenticated request costs.

        Deliberately not workspace-scoped, and the second query in this
        codebase that is not -- the other being the one that turns a
        WhatsApp delivery into a workspace. A key arrives with nothing but
        itself to say whose it is, so finding that out *is* the question.
        Everything downstream takes the workspace from the row this
        returns, so the boundary is established here rather than assumed.
        """
        return self._session.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))

    def list_for_workspace(self, workspace_id: uuid.UUID) -> Sequence[ApiKey]:
        """A workspace's keys, newest first, revoked ones included.

        Revoked keys stay in the list because they are the useful half of
        the screen after an incident: which key was leaked, when it was
        last used, and when somebody turned it off.
        """
        return self._session.scalars(
            select(ApiKey)
            .where(ApiKey.workspace_id == workspace_id)
            .order_by(ApiKey.created_at.desc(), ApiKey.id)
        ).all()

    def revoke(self, key: ApiKey, at: datetime) -> ApiKey:
        key.revoked_at = at
        self._session.flush()

        return key

    def touch(self, key: ApiKey, at: datetime) -> ApiKey:
        """Record that the key was just used.

        Its own method rather than a line in the service, because when
        this is called is a decision the service makes and has to be able
        to make sparingly -- see ApiKeyService.authenticate.
        """
        key.last_used_at = at
        self._session.flush()

        return key
