"""Turning a storefront's products and orders into this application's own.

Knows nothing about Shopify, which is the plan's instruction for this
phase. What comes in is `base.py`'s vocabulary; what goes out is rows in
the catalogue and orders tables that were already there before any
storefront existed.

Everything here is an upsert keyed on the provider's own id, which is what
makes a repeated delivery harmless. Shopify retries a webhook it did not
get a prompt 200 for, and it sends `orders/updated` for changes this
application does not care about; applying either twice has to produce the
same rows as applying it once. It does, because the key is theirs and not
ours -- and because a payload older than what is already stored is
ignored rather than written backwards.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.phone import normalise_phone_number
from app.db.session import SessionDep
from app.integrations.ecommerce.base import (
    RemoteCustomer,
    RemoteOrder,
    RemoteProduct,
)
from app.models.contact import Contact, ContactStatus
from app.models.order import OrderStatus
from app.models.product import ProductStatus
from app.repositories.contact_repository import ContactRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import ProductRepository, VariantSpec
from app.services.contact_service import ContactRepositoryDep
from app.services.order_service import OrderRepositoryDep
from app.services.product_service import ProductRepositoryDep

logger = logging.getLogger(__name__)

# Where a synced record remembers when the storefront last changed it.
# Kept in `metadata` rather than as a column: it is the provider's clock,
# not this application's, and nothing but this module ever reads it.
SOURCE_UPDATED_AT = "source_updated_at"

# The storefront says things like "fulfilled"; the adapter has already
# reduced those to this application's vocabulary, and anything it could
# not place lands as pending rather than as a guess.
_STATUSES = {status.value: status for status in OrderStatus}


@dataclass
class SyncReport:
    """What one run of a sync did, for the person who pressed the button."""

    products: int = 0
    orders: int = 0
    contacts: int = 0
    skipped: int = 0


class EcommerceSyncService:
    """Writes a storefront's records into the workspace's own tables."""

    def __init__(
        self,
        session: Session,
        products: ProductRepository,
        orders: OrderRepository,
        contacts: ContactRepository,
    ) -> None:
        self._session = session
        self._products = products
        self._orders = orders
        self._contacts = contacts

    def commit(self) -> None:
        """End the transaction the writes above are sitting in.

        The methods here only flush, because the two callers batch
        differently: a full sync writes a whole catalogue and commits
        once at the end, while a webhook is one delivery and one
        transaction. Committing inside each upsert would give the first
        caller a thousand transactions and no way to fail cleanly halfway.
        """
        self._session.commit()

    # --- products ----------------------------------------------------------

    def upsert_product(
        self,
        workspace_id: uuid.UUID,
        remote: RemoteProduct,
        report: SyncReport | None = None,
    ) -> None:
        report = report or SyncReport()
        existing = self._products.get_by_external_id(workspace_id, remote.external_id)

        if existing is not None and _is_stale(existing.meta, remote.updated_at):
            # A retry, or a delivery overtaken by a newer one. Applying it
            # would undo a change that has already landed.
            report.skipped += 1
            return

        meta = _stamped(remote.updated_at)
        status = ProductStatus.ACTIVE if remote.active else ProductStatus.DRAFT

        if existing is None:
            product = self._products.create(
                workspace_id=workspace_id,
                name=remote.name,
                description=remote.description,
                status=status,
                price=remote.price,
                currency=remote.currency,
                external_id=remote.external_id,
                meta=meta,
            )
        else:
            product = self._products.update(
                existing,
                name=remote.name,
                description=remote.description,
                status=status,
                price=remote.price,
                currency=remote.currency,
                meta=meta,
            )

        # Replaced rather than merged, which is what makes a variant
        # removed in the shop disappear here too. A merge would leave a
        # size the business has stopped selling in every answer the
        # assistant gives.
        self._products.replace_variants(
            workspace_id,
            product,
            [
                VariantSpec(
                    external_id=variant.external_id,
                    sku=variant.sku,
                    title=variant.title,
                    price=variant.price,
                    stock_quantity=variant.stock_quantity,
                    attributes=variant.attributes,
                )
                for variant in remote.variants
            ],
        )
        report.products += 1

    def delete_product(self, workspace_id: uuid.UUID, external_id: str) -> None:
        product = self._products.get_by_external_id(workspace_id, external_id)

        if product is None:
            # Deleted twice, or never synced. Both are the outcome the
            # caller wanted.
            return

        self._products.delete(product)

    # --- orders ------------------------------------------------------------

    def upsert_order(
        self,
        workspace_id: uuid.UUID,
        remote: RemoteOrder,
        report: SyncReport | None = None,
    ) -> None:
        report = report or SyncReport()
        existing = self._orders.get_by_external_id(workspace_id, remote.external_id)

        if existing is not None and _is_stale(existing.meta, remote.updated_at):
            report.skipped += 1
            return

        contact = self._contact_for(workspace_id, remote.customer, report)

        if contact is None:
            # Nothing to attach it to and nothing to reach them on. An
            # order this application could never answer a question about
            # is not worth storing incorrectly.
            logger.info("Skipped a synced order with no way to identify a customer")
            report.skipped += 1
            return

        fields = {
            "status": _STATUSES.get(remote.status, OrderStatus.PENDING),
            "order_number": remote.order_number,
            "currency": remote.currency,
            "subtotal": remote.subtotal,
            "shipping_total": remote.shipping_total,
            "total": remote.total,
            "shipping_address": remote.shipping_address,
            "tracking_number": remote.tracking_number,
            "tracking_url": remote.tracking_url,
            "placed_at": remote.placed_at,
            "meta": _stamped(remote.updated_at),
        }

        if existing is None:
            self._orders.create(
                workspace_id=workspace_id,
                contact_id=contact.id,
                external_id=remote.external_id,
                **fields,  # type: ignore[arg-type]
            )
        else:
            # The contact is deliberately not among the fields. An order
            # moving to a different customer is not something a storefront
            # edit should be able to do quietly -- that is exactly how one
            # person ends up able to ask about another person's order.
            self._orders.update(existing, **fields)  # type: ignore[arg-type]

        report.orders += 1

    # --- customers ---------------------------------------------------------

    def _contact_for(
        self,
        workspace_id: uuid.UUID,
        customer: RemoteCustomer,
        report: SyncReport,
    ) -> Contact | None:
        """Find or create the person an order belongs to.

        Matched on the phone number first, because that is the identity
        this product uses -- it reaches people on WhatsApp, and two
        records for one number would split a customer's history down the
        middle. The storefront's own customer id is the fallback, so a
        shop whose customers have no numbers still maps consistently.
        """
        number = _number(customer.phone_number)

        if number is not None:
            existing = self._contacts.get_by_phone_number(workspace_id, number)

            if existing is not None:
                return self._enriched(existing, customer)

        if customer.external_id is not None:
            by_id = self._contacts.get_by_external_id(
                workspace_id,
                customer.external_id,
            )

            if by_id is not None:
                return self._enriched(by_id, customer)

        if number is None:
            return None

        report.contacts += 1

        return self._contacts.create(
            workspace_id=workspace_id,
            phone_number=number,
            name=customer.name,
            email=customer.email,
            # Somebody who has placed an order is a customer, not a lead.
            status=ContactStatus.CUSTOMER,
            source="shopify",
            external_id=customer.external_id,
            meta={},
        )

    def _enriched(self, contact: Contact, customer: RemoteCustomer) -> Contact:
        """Fill in what the shop knows and this workspace does not.

        Only the blanks. A name an agent typed by hand is worth more than
        one a checkout form collected, and overwriting it every sync
        would undo somebody's work on a schedule.
        """
        return self._contacts.update(
            contact,
            name=contact.name or customer.name,
            email=contact.email or customer.email,
            external_id=contact.external_id or customer.external_id,
        )


def _stamped(updated_at: datetime | None) -> dict[str, str]:
    when = updated_at or datetime.now(UTC)

    return {SOURCE_UPDATED_AT: when.isoformat()}


def _is_stale(meta: dict[str, object], updated_at: datetime | None) -> bool:
    """Whether what is stored already reflects a change at least this new.

    Absent either timestamp the answer is no, and the write goes ahead:
    an unnecessary write is a rewrite of the same values, where a skipped
    one is a stale catalogue nobody can explain.
    """
    if updated_at is None:
        return False

    stored = meta.get(SOURCE_UPDATED_AT)

    if not isinstance(stored, str):
        return False

    try:
        return datetime.fromisoformat(stored) >= updated_at
    except ValueError:
        return False


def _number(phone_number: str | None) -> str | None:
    if not phone_number:
        return None

    try:
        return normalise_phone_number(phone_number)
    except ValueError:
        # A number this product cannot reach anybody on is not a number.
        # The order is still stored if the customer can be found another
        # way; it is only this one field that is unusable.
        return None


def get_ecommerce_sync_service(
    session: SessionDep,
    products: ProductRepositoryDep,
    orders: OrderRepositoryDep,
    contacts: ContactRepositoryDep,
) -> EcommerceSyncService:
    return EcommerceSyncService(
        session=session,
        products=products,
        orders=orders,
        contacts=contacts,
    )


EcommerceSyncServiceDep = Annotated[
    EcommerceSyncService,
    Depends(get_ecommerce_sync_service),
]
