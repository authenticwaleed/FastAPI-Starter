import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends

from app.api.dependencies.auth import CurrentUserDep
from app.core import context
from app.core.exceptions import InsufficientWorkspaceRoleError
from app.models.workspace_membership import WorkspaceRole
from app.services.workspace_service import (
    MAY_ADMINISTER,
    MAY_CLOSE,
    MAY_HANDLE_CUSTOMERS,
    WorkspaceAccess,
    WorkspaceServiceDep,
)


def get_workspace_access(
    workspace_id: uuid.UUID,
    user: CurrentUserDep,
    service: WorkspaceServiceDep,
) -> WorkspaceAccess:
    """Turn the workspace id in the path into proven access to it.

    Every route under `/workspaces/{workspace_id}` depends on this rather
    than on the raw id, so a handler is never holding an id it has not
    already established the caller may use. The tenant check happens once,
    in one place, before any handler body runs -- which is the only version
    of it that cannot be forgotten in a route added later.

    """
    return service.access(workspace_id, user)


async def bound_workspace_access(
    access: Annotated[WorkspaceAccess, Depends(get_workspace_access)],
) -> WorkspaceAccess:
    """The same access, with the workspace added to the log context.

    Its own dependency, and asynchronous, and both are the point.

    FastAPI runs a synchronous dependency in a worker thread, which gets a
    *copy* of the context: anything it binds is thrown away when the
    thread returns, so binding inside the resolver above reaches nothing --
    not the endpoint, not the summary line. An asynchronous one runs in
    the request's own task, where a binding is visible to everything after
    it and to the middleware that logs the request when it is over.

    Resolved after the check above, never before. An id somebody guessed
    at is not a workspace, and a log line saying it was would be worse
    than no line at all.
    """
    context.bind(workspace_id=access.workspace.id)

    return access


# Every route hangs off the binding wrapper rather than the resolver, so
# that reaching a workspace and saying which one was reached are the same
# act and cannot come apart.
WorkspaceAccessDep = Annotated[WorkspaceAccess, Depends(bound_workspace_access)]


def require_workspace_role(
    *allowed: WorkspaceRole,
) -> Callable[[WorkspaceAccess], WorkspaceAccess]:
    """Build a dependency that admits only these roles.

    The alternative is an `if` at the top of each handler, and the trouble
    with that is not repetition but silence: a route written next month
    that forgets one looks exactly like a route that is deliberately open.
    Stated as a dependency the requirement is in the signature, in the
    generated OpenAPI, and impossible to leave out by omission.

    Note what this does *not* replace. The service checks the same thing
    again, because a service is also called by other services and, before
    long, by background jobs, none of which pass through a route. This is
    the declaration; the service is the enforcement.
    """
    permitted = frozenset(allowed)

    def dependency(access: WorkspaceAccessDep) -> WorkspaceAccess:
        if access.role not in permitted:
            raise InsufficientWorkspaceRoleError(access.workspace.id, access.role)

        return access

    return dependency


# Any active member, whatever their role: the check is membership itself.
WorkspaceMemberDep = WorkspaceAccessDep

WorkspaceAgentDep = Annotated[
    WorkspaceAccess,
    Depends(require_workspace_role(*MAY_HANDLE_CUSTOMERS)),
]

WorkspaceAdminDep = Annotated[
    WorkspaceAccess,
    Depends(require_workspace_role(*MAY_ADMINISTER)),
]

WorkspaceOwnerDep = Annotated[
    WorkspaceAccess,
    Depends(require_workspace_role(*MAY_CLOSE)),
]
