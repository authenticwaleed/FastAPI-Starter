import uuid
from typing import Annotated

from fastapi import Depends

from app.api.dependencies.auth import CurrentUserDep
from app.services.workspace_service import (
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


WorkspaceAccessDep = Annotated[WorkspaceAccess, Depends(get_workspace_access)]
