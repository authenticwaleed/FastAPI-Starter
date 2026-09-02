import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies.staff import StaffDep
from app.api.errors import (
    ADMIN_NOT_FOUND,
    ADMIN_UNAUTHORISED,
    CONVERSATION_NOT_FOUND,
    RATE_LIMITED,
    SUPPORT_ACCESS_FORBIDDEN,
)
from app.api.routes.conversations import read_of
from app.models.conversation import ConversationStatus
from app.schemas.conversation import ConversationPage
from app.schemas.message import MessagePage, MessageRead
from app.services.support_access_service import SupportAccessServiceDep

router = APIRouter(
    prefix="/workspaces/{workspace_id}/conversations",
    tags=["platform"],
)

GRANTED = {
    **ADMIN_UNAUTHORISED,
    **SUPPORT_ACCESS_FORBIDDEN,
    **RATE_LIMITED,
    **ADMIN_NOT_FOUND,
}


# The two routes in this whole surface that return what a customer's own
# customers wrote. Everything else on /admin is metadata; these are
# messages, and each one needs a live grant that was asked for with a
# reason and that the customer can see in their own audit log.
#
# `StaffDep` rather than a higher rank, and the grant is what actually
# guards them. A rank says who may ask; the grant says who asked, why,
# about which business, and until when -- which is a stronger thing to
# have written down than a role.
@router.get("", responses=GRANTED)
def list_workspace_conversations(
    workspace_id: uuid.UUID,
    actor: StaffDep,
    service: SupportAccessServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Annotated[list[ConversationStatus] | None, Query()] = None,
) -> ConversationPage:
    """The customer's inbox, as they see it.

    Through the same service and the same renderer their own dashboard
    uses, so what support is looking at is what the customer is looking
    at. A second reading path would eventually show one of them something
    the other cannot see.

    There is no `assigned_to` filter here, unlike the customer's own
    route. "Assigned to me" has no meaning for somebody who is not on the
    team, and offering it would be the first place a staff actor started
    to look like a colleague.
    """
    rows, total = service.conversations(
        actor,
        workspace_id,
        page=page,
        page_size=page_size,
        statuses=status,
    )

    return ConversationPage(
        items=[read_of(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{conversation_id}/messages",
    responses={**GRANTED, **CONVERSATION_NOT_FOUND},
)
def list_workspace_messages(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    actor: StaffDep,
    service: SupportAccessServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 30,
) -> MessagePage:
    """One thread, in full.

    The deepest anything on this surface reaches, and the entry it writes
    names the conversation rather than only the workspace -- because
    "they read the inbox" and "they read this customer's thread with this
    person" are different answers to give afterwards.

    Read-only, and not by convention. The access this runs on carries a
    staff actor rather than a membership, so its role is `viewer`; this
    surface publishes no route that writes tenant data, which a test
    asserts over the whole router; and a service that did write would
    raise on `actor_user_id` rather than record a staff member as one of
    the customer's own people.
    """
    messages, total = service.messages(
        actor,
        workspace_id,
        conversation_id,
        page=page,
        page_size=page_size,
    )

    return MessagePage(
        items=[MessageRead.model_validate(message) for message in messages],
        total=total,
        page=page,
        page_size=page_size,
    )
