from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.product import ProductStatus

# Money in, money out. `Decimal` rather than `float` all the way through:
# a price that arrives as 19.99 and is stored as 19.989999999999998 is a
# total that is wrong once it is multiplied by three.
Money = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]

Currency = Annotated[str, Field(min_length=3, max_length=3)]


def normalise_currency(value: str | None) -> str | None:
    """Uppercased, and letters only.

    `pkr` and `PKR` are the same currency, and storing both would make
    every report group them apart. A module function rather than a method,
    because two schemas need it and a validator borrowed off another class
    is a line nobody enjoys reading.
    """
    if value is None:
        return None

    code = value.strip().upper()

    if not code.isalpha():
        raise ValueError("currency must be a three-letter ISO 4217 code")

    return code


class VariantWrite(BaseModel):
    """One buyable version of a product, as submitted."""

    external_id: Annotated[str, Field(max_length=255)] | None = None
    sku: Annotated[str, Field(max_length=100)] | None = None
    title: Annotated[str, Field(max_length=255)] | None = None

    # Null means "the product's price applies", not "free".
    price: Money | None = None

    # Null means "this business does not track stock", which is a
    # different answer from 0 and must stay one -- see the column.
    stock_quantity: Annotated[int, Field(ge=0)] | None = None

    attributes: dict[str, Any] = Field(default_factory=dict)


class VariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_id: str | None
    sku: str | None
    title: str | None
    price: Decimal | None
    stock_quantity: int | None
    attributes: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ProductCreate(BaseModel):
    """A product and, in the same request, everything buyable under it.

    Variants are nested rather than given endpoints of their own, which
    is the plan's endpoint list read literally. It is also the shape a
    storefront sync sends: a product arrives with its sizes, and two
    round trips to store it would be two chances to store half of it.
    """

    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: str | None = None
    status: ProductStatus = ProductStatus.ACTIVE
    price: Money | None = None
    currency: Currency | None = None
    external_id: Annotated[str, Field(max_length=255)] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    variants: list[VariantWrite] = Field(default_factory=list)

    @field_validator("currency")
    @classmethod
    def _iso_4217(cls, value: str | None) -> str | None:
        return normalise_currency(value)


class ProductUpdate(BaseModel):
    """A partial update. An omitted field means "leave this alone".

    `variants` is the exception, and deliberately: supplying it replaces
    the set entirely. Merging would need a rule for matching an incoming
    variant to an existing row, and no rule covers the hand-entered ones
    that have neither an external id nor a SKU.
    """

    name: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    description: str | None = None
    status: ProductStatus | None = None
    price: Money | None = None
    currency: Currency | None = None
    external_id: Annotated[str, Field(max_length=255)] | None = None
    metadata: dict[str, Any] | None = None
    variants: list[VariantWrite] | None = None

    @field_validator("currency")
    @classmethod
    def _iso_4217(cls, value: str | None) -> str | None:
        return normalise_currency(value)


class ProductRead(BaseModel):
    """One product, with everything needed to answer a question about it.

    `populate_by_name` because this one is built by hand -- the variants
    are fetched separately and there is no single object to validate from
    -- while `metadata` still has to read `meta` when it is not.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    external_id: str | None
    name: str
    description: str | None
    status: ProductStatus
    price: Decimal | None
    currency: str | None
    # Aliased for the reason ContactRead's is: `metadata` is taken on a
    # declarative class, so the attribute carrying that column is `meta`.
    metadata: dict[str, Any] = Field(validation_alias="meta")
    variants: list[VariantRead]
    created_at: datetime
    updated_at: datetime


class ProductPage(BaseModel):
    items: list[ProductRead]
    total: int
    page: int
    page_size: int
