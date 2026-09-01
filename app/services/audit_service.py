"""Recording what a business's own people did to it.

The plan asks for this on behalf of business accounts, and the reason
those customers ask is external: somebody eventually has to be shown who
removed a colleague, who disconnected the number, who deleted the policy
the assistant had been answering from.

Nothing here takes a WorkspaceAccess, and that is deliberate rather than
inconvenient. Almost every service in this application ends up recording
something -- workspaces, memberships, invitations, the knowledge base,
billing -- so an audit service that imported the module those services
get their access type from would be imported by its own dependency. It
speaks in ids instead, which is all an audit entry is made of anyway.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db.session import SessionDep
from app.models.audit_log import AuditEvent, AuditLog
from app.models.user import User
from app.repositories.audit_log_repository import AuditLogRepository


class AuditService:
    """Writing the record, and reading it back.

    Two halves that barely touch, like notifications. Writing is done by
    the service where the thing actually happened, in that service's
    transaction -- so this side only flushes, and whoever caused the entry
    owns the commit. An entry committed separately from the act it
    describes can outlive a rollback, and an audit log with an event in it
    that never happened is worse than no audit log, because somebody will
    believe it.

    Reading is checked at the door instead of here: the endpoint declares
    both the administrator role and the plan feature, in its signature.
    Repeating the role check in this class would mean importing the module
    that resolves it, which is the module every writer of audit entries
    already imports -- see this file's own docstring.
    """

    def __init__(self, session: Session, logs: AuditLogRepository) -> None:
        self._session = session
        self._logs = logs

    # --- writing -----------------------------------------------------------

    def did(
        self,
        workspace_id: uuid.UUID,
        event: AuditEvent,
        *,
        actor_user_id: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Record that this happened, here, by them.

        Called after the act has succeeded and before the caller commits,
        so that the two are one write. `actor_user_id` is left out only
        where there is genuinely nobody behind it -- a payment provider
        changing a subscription -- because an audit entry that names the
        wrong person is not a gap in the record, it is an accusation.
        """
        return self._logs.record(
            workspace_id=workspace_id,
            event=event,
            actor_user_id=actor_user_id,
            meta=meta or {},
        )

    # --- reading -----------------------------------------------------------

    def list_for(
        self,
        workspace_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        event: AuditEvent | None = None,
        actor_user_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[tuple[AuditLog, User | None]], int]:
        """A page of the history, newest first, with a total.

        Filtered on the way in rather than in the client, because the
        useful questions are narrow ones -- what did this account do, what
        happened to the knowledge base last month -- and an audit log is
        the one table here that only ever grows.
        """
        entries = self._logs.list_for_workspace(
            workspace_id,
            limit=page_size,
            offset=(page - 1) * page_size,
            event=event,
            actor_user_id=actor_user_id,
            since=since,
            until=until,
        )
        total = self._logs.count_for_workspace(
            workspace_id,
            event=event,
            actor_user_id=actor_user_id,
            since=since,
            until=until,
        )

        return entries, total


def get_audit_log_repository(session: SessionDep) -> AuditLogRepository:
    return AuditLogRepository(session)


AuditLogRepositoryDep = Annotated[
    AuditLogRepository,
    Depends(get_audit_log_repository),
]


def get_audit_service(
    session: SessionDep,
    logs: AuditLogRepositoryDep,
) -> AuditService:
    return AuditService(session=session, logs=logs)


AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
