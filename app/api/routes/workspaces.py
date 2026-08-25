from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dependencies.auth import CurrentUserDep
from app.api.dependencies.workspace import WorkspaceAccessDep
from app.api.errors import (
    SLUG_CONFLICT,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspacePage,
    WorkspaceRead,
    WorkspaceUpdate,
)
from app.services.workspace_service import WorkspaceServiceDep

router = APIRouter(
    prefix="/workspaces",
    tags=["workspaces"],
)

# Every route that names a workspace can answer these three, so they are
# spread into each one rather than restated.
SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}


# Sync, like every other route that reaches the database. None of these
# catches anything: the service raises a domain error and the handlers in
# app/api/errors.py decide what that looks like over HTTP.
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={**UNAUTHORISED, **SLUG_CONFLICT},
)
def create_workspace(
    payload: WorkspaceCreate,
    user: CurrentUserDep,
    service: WorkspaceServiceDep,
) -> WorkspaceRead:
    """Create a workspace. The caller becomes its owner."""
    return WorkspaceRead.model_validate(service.create(payload, creator=user))


@router.get("", responses=UNAUTHORISED)
def list_workspaces(
    user: CurrentUserDep,
    service: WorkspaceServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> WorkspacePage:
    """The caller's own workspaces, never anybody else's."""
    workspaces, total = service.list_for(user, page=page, page_size=page_size)

    return WorkspacePage(
        items=[WorkspaceRead.model_validate(workspace) for workspace in workspaces],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{workspace_id}", responses=SCOPED)
def read_workspace(access: WorkspaceAccessDep) -> WorkspaceRead:
    """The dependency has already proved the caller belongs here."""
    return WorkspaceRead.model_validate(access.workspace)


@router.patch("/{workspace_id}", responses=SCOPED)
def update_workspace(
    access: WorkspaceAccessDep,
    payload: WorkspaceUpdate,
    service: WorkspaceServiceDep,
) -> WorkspaceRead:
    return WorkspaceRead.model_validate(service.update(access, payload))


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=SCOPED,
)
def close_workspace(
    access: WorkspaceAccessDep,
    service: WorkspaceServiceDep,
) -> None:
    """Close the workspace.

    It stops appearing anywhere and every path to it answers 404, but the
    rows survive, so this is recoverable by support rather than final.
    """
    service.cancel(access)
