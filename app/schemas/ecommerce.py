from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.integrations.ecommerce.base import EcommerceProviderName
from app.models.ecommerce_account import EcommerceAccountStatus


class StorefrontConnect(BaseModel):
    """Which shop to install into this workspace."""

    # `acme.myshopify.com`. Checked properly by the adapter, which is the
    # only place that knows what a valid one looks like -- and has to,
    # because this string is interpolated into a URL the server calls.
    shop_domain: Annotated[str, Field(min_length=3, max_length=255)]


class StorefrontInstall(BaseModel):
    """Where to send the shop owner next.

    The client's job is to redirect them here. Nothing is connected until
    they approve it and the provider calls back.
    """

    authorize_url: str
    shop_domain: str


class StorefrontRead(BaseModel):
    """What is connected, with no part of the token in it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider: EcommerceProviderName
    shop_domain: str
    status: EcommerceAccountStatus
    # Null until the first full read finishes, which is what a dashboard
    # shows as "not synced yet".
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SyncReport(BaseModel):
    """What one run of a sync did.

    `skipped` is the interesting number: it counts records the storefront
    sent that were already as new here, which is what a retry looks like
    from the inside.
    """

    products: int
    orders: int
    contacts: int
    skipped: int
