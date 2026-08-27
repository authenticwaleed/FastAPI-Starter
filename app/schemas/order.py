from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.order import OrderStatus
from app.schemas.product import Currency, Money, normalise_currency


class OrderCreate(BaseModel):
    """An order, as the dashboard or a sync submits one.

    The contact is named rather than described. An order is always for
    somebody the workspace already knows, and creating a contact by side
    effect here would be a second, quieter path into the contacts table
    with none of its rules.
    """

    contact_id: UUID
    status: OrderStatus = OrderStatus.PENDING
    external_id: Annotated[str, Field(max_length=255)] | None = None
    order_number: Annotated[str, Field(max_length=64)] | None = None
    currency: Currency | None = None
    subtotal: Money | None = None
    shipping_total: Money | None = None
    total: Money | None = None
    shipping_address: str | None = None
    tracking_number: Annotated[str, Field(max_length=128)] | None = None
    tracking_url: Annotated[str, Field(max_length=500)] | None = None
    placed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def _iso_4217(cls, value: str | None) -> str | None:
        return normalise_currency(value)


class OrderUpdate(BaseModel):
    """A partial update. An omitted field means "leave this alone".

    The contact is not here. Moving an order to a different customer is
    not an edit, it is a correction of who it was ever for, and doing it
    through a PATCH nobody notices is how one person ends up able to ask
    about another person's order.
    """

    status: OrderStatus | None = None
    order_number: Annotated[str, Field(max_length=64)] | None = None
    currency: Currency | None = None
    subtotal: Money | None = None
    shipping_total: Money | None = None
    total: Money | None = None
    shipping_address: str | None = None
    tracking_number: Annotated[str, Field(max_length=128)] | None = None
    tracking_url: Annotated[str, Field(max_length=500)] | None = None
    placed_at: datetime | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("currency")
    @classmethod
    def _iso_4217(cls, value: str | None) -> str | None:
        return normalise_currency(value)


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    contact_id: UUID
    external_id: str | None
    order_number: str | None
    status: OrderStatus
    currency: str | None
    subtotal: Decimal | None
    shipping_total: Decimal | None
    total: Decimal | None
    shipping_address: str | None
    tracking_number: str | None
    tracking_url: str | None
    placed_at: datetime | None
    # Reads the model's `meta` attribute, which carries the column the
    # plan calls `metadata`: the name is taken on a declarative class by
    # `Base.metadata`, and without the alias this reads that instead.
    metadata: dict[str, Any] = Field(validation_alias="meta")
    created_at: datetime
    updated_at: datetime


class OrderPage(BaseModel):
    items: list[OrderRead]
    total: int
    page: int
    page_size: int
