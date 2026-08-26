import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dependencies.workspace import WorkspaceAgentDep, WorkspaceMemberDep
from app.api.errors import (
    CONTACT_CONFLICT,
    CONTACT_NOT_FOUND,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.models.contact import ContactStatus
from app.schemas.contact import (
    ContactCreate,
    ContactPage,
    ContactRead,
    ContactUpdate,
)
from app.services.contact_service import ContactServiceDep

router = APIRouter(
    prefix="/workspaces/{workspace_id}/contacts",
    tags=["contacts"],
)

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}


# Reading takes WorkspaceMemberDep and writing takes WorkspaceAgentDep: a
# viewer has read-only access to the dashboard, and handling the people
# who message the business is an agent's actual job rather than an
# administrative act.
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={**SCOPED, **CONTACT_CONFLICT},
)
def create_contact(
    payload: ContactCreate,
    access: WorkspaceAgentDep,
    service: ContactServiceDep,
) -> ContactRead:
    return ContactRead.model_validate(service.create(access, payload))


@router.get("", responses=SCOPED)
def list_contacts(
    access: WorkspaceMemberDep,
    service: ContactServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(max_length=150)] = None,
    status_filter: Annotated[ContactStatus | None, Query(alias="status")] = None,
    source: Annotated[str | None, Query(max_length=50)] = None,
) -> ContactPage:
    """One page of this workspace's contacts, newest first.

    `status` is spelled `status_filter` in Python only because `status` is
    already the name of the FastAPI module imported above; the query
    parameter a client sends is `status`.
    """
    contacts, total = service.list_for(
        access,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
        source=source,
    )

    return ContactPage(
        items=[ContactRead.model_validate(contact) for contact in contacts],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{contact_id}", responses={**SCOPED, **CONTACT_NOT_FOUND})
def read_contact(
    contact_id: uuid.UUID,
    access: WorkspaceMemberDep,
    service: ContactServiceDep,
) -> ContactRead:
    return ContactRead.model_validate(service.get(access, contact_id))


@router.patch(
    "/{contact_id}",
    responses={**SCOPED, **CONTACT_NOT_FOUND, **CONTACT_CONFLICT},
)
def update_contact(
    contact_id: uuid.UUID,
    payload: ContactUpdate,
    access: WorkspaceAgentDep,
    service: ContactServiceDep,
) -> ContactRead:
    return ContactRead.model_validate(service.update(access, contact_id, payload))
