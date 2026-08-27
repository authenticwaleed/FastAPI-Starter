import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dependencies.workspace import WorkspaceAgentDep, WorkspaceMemberDep
from app.api.errors import (
    CONTACT_NOT_FOUND,
    ORDER_CONFLICT,
    ORDER_NOT_FOUND,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.models.order import OrderStatus
from app.schemas.order import OrderCreate, OrderPage, OrderRead, OrderUpdate
from app.services.order_service import OrderServiceDep

router = APIRouter(
    prefix="/workspaces/{workspace_id}/orders",
    tags=["orders"],
)

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}


def _read(order: object) -> OrderRead:
    return OrderRead.model_validate(order)


# Writing takes WorkspaceAgentDep rather than the admin the catalogue
# needs. Editing a price list is deciding what the business charges;
# marking an order shipped and pasting in a tracking number is the work
# an agent does all day, between messages.
#
# POST is not in the plan's endpoint list, which starts at GET -- because
# the plan expects orders to arrive from a storefront. It is here so that
# a business without one, which is most of the plan's first customers,
# can still record an order taken over WhatsApp; the sync in the next
# phase writes through the same service.
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={**SCOPED, **CONTACT_NOT_FOUND, **ORDER_CONFLICT},
)
def create_order(
    payload: OrderCreate,
    access: WorkspaceAgentDep,
    service: OrderServiceDep,
) -> OrderRead:
    return _read(service.create(access, payload))


@router.get("", responses=SCOPED)
def list_orders(
    access: WorkspaceMemberDep,
    service: OrderServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    contact_id: Annotated[uuid.UUID | None, Query()] = None,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    search: Annotated[str | None, Query(max_length=128)] = None,
) -> OrderPage:
    """One page of this workspace's orders, most recently placed first.

    `contact_id` is what an agent opening a conversation asks for: this
    person's orders, next to what they are saying.

    `search` matches the order number, the storefront's id, or the
    tracking number -- the three strings a customer ever quotes back.
    """
    orders, total = service.list_for(
        access,
        page=page,
        page_size=page_size,
        contact_id=contact_id,
        status=status_filter,
        search=search,
    )

    return OrderPage(
        items=[_read(order) for order in orders],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{order_id}", responses={**SCOPED, **ORDER_NOT_FOUND})
def read_order(
    order_id: uuid.UUID,
    access: WorkspaceMemberDep,
    service: OrderServiceDep,
) -> OrderRead:
    return _read(service.get(access, order_id))


@router.patch("/{order_id}", responses={**SCOPED, **ORDER_NOT_FOUND})
def update_order(
    order_id: uuid.UUID,
    payload: OrderUpdate,
    access: WorkspaceAgentDep,
    service: OrderServiceDep,
) -> OrderRead:
    """Record what has happened to an order.

    The contact is not changeable here. Moving an order to a different
    customer is not an edit; it is a correction of who it was ever for,
    and doing it through a PATCH nobody notices is how one person ends up
    able to ask about another person's order.
    """
    return _read(service.update(access, order_id, payload))


@router.post(
    "/{order_id}/confirm",
    responses={**SCOPED, **ORDER_NOT_FOUND, **ORDER_CONFLICT},
)
def confirm_order(
    order_id: uuid.UUID,
    access: WorkspaceAgentDep,
    service: OrderServiceDep,
) -> OrderRead:
    """Confirm a pending order.

    Its own endpoint rather than a PATCH, because it is the one status
    change that records a decision rather than an observation. Anything
    not pending is refused: confirming is a step forward, not a way to
    undo a cancellation.
    """
    return _read(service.confirm(access, order_id))
