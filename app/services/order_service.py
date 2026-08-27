import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ContactNotFoundError,
    OrderAlreadyExistsError,
    OrderNotConfirmableError,
    OrderNotFoundError,
)
from app.db.session import SessionDep
from app.models.order import Order, OrderStatus
from app.repositories.contact_repository import ContactRepository
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderCreate, OrderUpdate
from app.services.contact_service import ContactRepositoryDep
from app.services.workspace_service import WorkspaceAccess

# What the assistant is shown of a customer's history. Three is a
# customer's recent orders as a person would mean it; a year of them
# would fill the prompt with things nobody is asking about.
ORDERS_IN_CONTEXT = 3


class OrderService:
    """A workspace's orders, and the answers a customer asks for.

    Two kinds of caller, with two different boundaries. The dashboard
    reaches every order in the workspace, because an agent looking at an
    inbox is looking at all of them. The assistant reaches one contact's,
    because the question it is answering came from that contact -- and
    the plan is explicit that a customer must not be able to reach
    somebody else's order.
    """

    def __init__(
        self,
        session: Session,
        orders: OrderRepository,
        contacts: ContactRepository,
    ) -> None:
        self._session = session
        self._orders = orders
        self._contacts = contacts

    def create(self, access: WorkspaceAccess, payload: OrderCreate) -> Order:
        workspace_id = access.workspace.id

        if self._contacts.get(workspace_id, payload.contact_id) is None:
            # Checked here rather than left to the composite foreign key,
            # so that naming a contact from another workspace answers
            # "no such contact" rather than a 500 from the database.
            raise ContactNotFoundError(workspace_id, payload.contact_id)

        try:
            order = self._orders.create(
                workspace_id=workspace_id,
                contact_id=payload.contact_id,
                status=payload.status,
                external_id=payload.external_id,
                order_number=payload.order_number,
                currency=payload.currency,
                subtotal=payload.subtotal,
                shipping_total=payload.shipping_total,
                total=payload.total,
                shipping_address=payload.shipping_address,
                tracking_number=payload.tracking_number,
                tracking_url=payload.tracking_url,
                placed_at=payload.placed_at,
                meta=payload.metadata,
            )
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise OrderAlreadyExistsError(workspace_id, payload.external_id) from exc

        return order

    def get(self, access: WorkspaceAccess, order_id: uuid.UUID) -> Order:
        return self._require(access, order_id)

    def list_for(
        self,
        access: WorkspaceAccess,
        *,
        page: int = 1,
        page_size: int = 20,
        contact_id: uuid.UUID | None = None,
        status: OrderStatus | None = None,
        search: str | None = None,
    ) -> tuple[Sequence[Order], int]:
        workspace_id = access.workspace.id

        orders = self._orders.list_for_workspace(
            workspace_id,
            limit=page_size,
            offset=(page - 1) * page_size,
            contact_id=contact_id,
            status=status,
            search=search,
        )
        total = self._orders.count_for_workspace(
            workspace_id,
            contact_id=contact_id,
            status=status,
            search=search,
        )

        return orders, total

    def update(
        self,
        access: WorkspaceAccess,
        order_id: uuid.UUID,
        payload: OrderUpdate,
    ) -> Order:
        order = self._require(access, order_id)

        self._orders.update(
            order,
            status=payload.status,
            order_number=payload.order_number,
            currency=payload.currency,
            subtotal=payload.subtotal,
            shipping_total=payload.shipping_total,
            total=payload.total,
            shipping_address=payload.shipping_address,
            tracking_number=payload.tracking_number,
            tracking_url=payload.tracking_url,
            placed_at=payload.placed_at,
            meta=payload.metadata,
        )
        self._session.commit()

        return order

    def confirm(self, access: WorkspaceAccess, order_id: uuid.UUID) -> Order:
        """Move a pending order to confirmed.

        Its own endpoint rather than a PATCH setting `status`, because it
        is the one status change that means somebody decided something
        rather than somebody recorded something. Both routes exist and
        both go through here, so the rule below cannot be sidestepped by
        picking the other one.
        """
        order = self._require(access, order_id)

        if order.status is not OrderStatus.PENDING:
            raise OrderNotConfirmableError(order_id, order.status)

        self._orders.update(order, status=OrderStatus.CONFIRMED)
        self._session.commit()

        return order

    def for_contact(
        self,
        workspace_id: uuid.UUID,
        contact_id: uuid.UUID,
        *,
        limit: int = ORDERS_IN_CONTEXT,
    ) -> Sequence[Order]:
        """The orders the assistant may see when answering this person.

        Takes a workspace and a contact and nothing else. There is no
        argument here that could widen it to another customer, which is
        the whole point: the plan's rule is that one customer cannot
        reach another's order, and this is that rule as a shape rather
        than as a check somebody has to remember.
        """
        return self._orders.list_for_contact(workspace_id, contact_id, limit=limit)

    def _require(self, access: WorkspaceAccess, order_id: uuid.UUID) -> Order:
        order = self._orders.get(access.workspace.id, order_id)

        if order is None:
            raise OrderNotFoundError(access.workspace.id, order_id)

        return order


def get_order_repository(session: SessionDep) -> OrderRepository:
    return OrderRepository(session)


OrderRepositoryDep = Annotated[OrderRepository, Depends(get_order_repository)]


def get_order_service(
    session: SessionDep,
    orders: OrderRepositoryDep,
    contacts: ContactRepositoryDep,
) -> OrderService:
    return OrderService(session=session, orders=orders, contacts=contacts)


OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]
