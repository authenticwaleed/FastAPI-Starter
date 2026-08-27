import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models.order import Order, OrderStatus


class OrderRepository:
    """Every query against the orders table lives here.

    Workspace-scoped throughout, and contact-scoped wherever the
    assistant is the caller. Those are two different boundaries doing two
    different jobs: the workspace keeps one business's orders away from
    another's, and the contact keeps one customer's away from another's.
    The second is the one the plan singles out, because it is the one a
    conversation can get wrong.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        contact_id: uuid.UUID,
        status: OrderStatus = OrderStatus.PENDING,
        external_id: str | None = None,
        order_number: str | None = None,
        currency: str | None = None,
        subtotal: Decimal | None = None,
        shipping_total: Decimal | None = None,
        total: Decimal | None = None,
        shipping_address: str | None = None,
        tracking_number: str | None = None,
        tracking_url: str | None = None,
        placed_at: datetime | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Order:
        order = Order(
            workspace_id=workspace_id,
            contact_id=contact_id,
            status=status,
            external_id=external_id,
            order_number=order_number,
            currency=currency,
            subtotal=subtotal,
            shipping_total=shipping_total,
            total=total,
            shipping_address=shipping_address,
            tracking_number=tracking_number,
            tracking_url=tracking_url,
            placed_at=placed_at,
            meta=meta or {},
        )

        self._session.add(order)
        self._session.flush()

        return order

    def get(self, workspace_id: uuid.UUID, order_id: uuid.UUID) -> Order | None:
        return self._session.scalar(
            select(Order).where(
                Order.id == order_id,
                Order.workspace_id == workspace_id,
            )
        )

    def get_by_external_id(
        self,
        workspace_id: uuid.UUID,
        external_id: str,
    ) -> Order | None:
        return self._session.scalar(
            select(Order).where(
                Order.workspace_id == workspace_id,
                Order.external_id == external_id,
            )
        )

    def list_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        contact_id: uuid.UUID | None = None,
        status: OrderStatus | None = None,
        search: str | None = None,
    ) -> Sequence[Order]:
        statement = self._filtered(
            select(Order),
            workspace_id,
            contact_id=contact_id,
            status=status,
            search=search,
        )

        return self._session.scalars(
            statement.order_by(
                Order.placed_at.desc().nullslast(),
                Order.created_at.desc(),
                Order.id,
            )
            .limit(limit)
            .offset(offset)
        ).all()

    def count_for_workspace(
        self,
        workspace_id: uuid.UUID,
        *,
        contact_id: uuid.UUID | None = None,
        status: OrderStatus | None = None,
        search: str | None = None,
    ) -> int:
        statement = self._filtered(
            select(func.count()).select_from(Order),
            workspace_id,
            contact_id=contact_id,
            status=status,
            search=search,
        )

        return self._session.scalar(statement) or 0

    def list_for_contact(
        self,
        workspace_id: uuid.UUID,
        contact_id: uuid.UUID,
        *,
        limit: int,
    ) -> Sequence[Order]:
        """This customer's orders, most recent first.

        The query the assistant runs, and the reason it takes both ids.
        Neither is optional and neither has a default: the whole guarantee
        this table offers is that an answer about an order was looked up
        for the person who asked, and a method that could be called
        without a contact would be a way to lose it.
        """
        return self._session.scalars(
            select(Order)
            .where(
                Order.workspace_id == workspace_id,
                Order.contact_id == contact_id,
            )
            .order_by(
                Order.placed_at.desc().nullslast(),
                Order.created_at.desc(),
                Order.id,
            )
            .limit(limit)
        ).all()

    def update(
        self,
        order: Order,
        *,
        status: OrderStatus | None = None,
        order_number: str | None = None,
        currency: str | None = None,
        subtotal: Decimal | None = None,
        shipping_total: Decimal | None = None,
        total: Decimal | None = None,
        shipping_address: str | None = None,
        tracking_number: str | None = None,
        tracking_url: str | None = None,
        placed_at: datetime | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Order:
        """Apply what was supplied; `None` means "no change" as always."""
        for field, value in (
            ("status", status),
            ("order_number", order_number),
            ("currency", currency),
            ("subtotal", subtotal),
            ("shipping_total", shipping_total),
            ("total", total),
            ("shipping_address", shipping_address),
            ("tracking_number", tracking_number),
            ("tracking_url", tracking_url),
            ("placed_at", placed_at),
            ("meta", meta),
        ):
            if value is not None:
                setattr(order, field, value)

        self._session.flush()

        return order

    def _filtered(
        self,
        statement: Select[Any],
        workspace_id: uuid.UUID,
        *,
        contact_id: uuid.UUID | None,
        status: OrderStatus | None,
        search: str | None,
    ) -> Select[Any]:
        statement = statement.where(Order.workspace_id == workspace_id)

        if contact_id is not None:
            statement = statement.where(Order.contact_id == contact_id)

        if status is not None:
            statement = statement.where(Order.status == status)

        if search:
            # The two strings a person quotes: the number on their
            # receipt, and the one on the courier's tracking page.
            pattern = f"%{search}%"
            statement = statement.where(
                or_(
                    Order.order_number.ilike(pattern),
                    Order.external_id.ilike(pattern),
                    Order.tracking_number.ilike(pattern),
                )
            )

        return statement
