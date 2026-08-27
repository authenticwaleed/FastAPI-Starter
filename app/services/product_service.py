import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ProductConflictError, ProductNotFoundError
from app.db.session import SessionDep
from app.models.product import Product, ProductStatus
from app.repositories.product_repository import (
    ProductRepository,
    ProductWithVariants,
    VariantSpec,
)
from app.schemas.product import ProductCreate, ProductUpdate, VariantWrite
from app.services.workspace_service import WorkspaceAccess


class ProductService:
    """A workspace's catalogue.

    Every method takes the WorkspaceAccess a dependency already resolved,
    like every other tenant-scoped service here, so there is no way to
    reach this for a workspace whose membership was never checked.

    Products and their variants are written together in one transaction.
    A product that exists for a moment with no sizes is a product a
    customer can be told the wrong thing about, and a request that failed
    halfway should leave nothing at all.
    """

    def __init__(self, session: Session, products: ProductRepository) -> None:
        self._session = session
        self._products = products

    def create(
        self,
        access: WorkspaceAccess,
        payload: ProductCreate,
    ) -> ProductWithVariants:
        workspace_id = access.workspace.id

        try:
            product = self._products.create(
                workspace_id=workspace_id,
                name=payload.name,
                description=payload.description,
                status=payload.status,
                price=payload.price,
                currency=payload.currency,
                external_id=payload.external_id,
                meta=payload.metadata,
            )
            variants = self._products.replace_variants(
                workspace_id,
                product,
                _specs(payload.variants),
            )
            self._session.commit()
        except IntegrityError as exc:
            # An external id or a SKU already in this workspace's
            # catalogue. The unique indexes are what settle it, including
            # against a sync running at the same time as the dashboard.
            self._session.rollback()
            raise ProductConflictError(workspace_id) from exc

        return ProductWithVariants(product=product, variants=variants)

    def get(
        self,
        access: WorkspaceAccess,
        product_id: uuid.UUID,
    ) -> ProductWithVariants:
        product = self._require(access, product_id)

        return self._products.with_variants(access.workspace.id, [product])[0]

    def list_for(
        self,
        access: WorkspaceAccess,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: ProductStatus | None = None,
        in_stock: bool | None = None,
    ) -> tuple[Sequence[ProductWithVariants], int]:
        workspace_id = access.workspace.id

        products = self._products.list_for_workspace(
            workspace_id,
            limit=page_size,
            offset=(page - 1) * page_size,
            search=search,
            status=status,
            in_stock=in_stock,
        )
        # The same filters, counted rather than fetched, so `total` is the
        # size of the filtered set and not of the catalogue.
        total = self._products.count_for_workspace(
            workspace_id,
            search=search,
            status=status,
            in_stock=in_stock,
        )

        return self._products.with_variants(workspace_id, products), total

    def update(
        self,
        access: WorkspaceAccess,
        product_id: uuid.UUID,
        payload: ProductUpdate,
    ) -> ProductWithVariants:
        workspace_id = access.workspace.id
        product = self._require(access, product_id)

        try:
            self._products.update(
                product,
                name=payload.name,
                description=payload.description,
                status=payload.status,
                price=payload.price,
                currency=payload.currency,
                external_id=payload.external_id,
                meta=payload.metadata,
            )

            if payload.variants is not None:
                # Supplied means "make them exactly this". Omitted means
                # "leave them alone", the same as every other field.
                self._products.replace_variants(
                    workspace_id,
                    product,
                    _specs(payload.variants),
                )

            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ProductConflictError(workspace_id) from exc

        return self._products.with_variants(workspace_id, [product])[0]

    def delete(self, access: WorkspaceAccess, product_id: uuid.UUID) -> None:
        """Remove it, and its variants with it.

        A hard delete rather than an archive, because `archived` is
        already a status and a business that wants the row kept has a way
        to say so. Two ways of hiding a product, one of which is
        invisible in the API, would be one too many.
        """
        self._products.delete(self._require(access, product_id))
        self._session.commit()

    def _require(self, access: WorkspaceAccess, product_id: uuid.UUID) -> Product:
        product = self._products.get(access.workspace.id, product_id)

        if product is None:
            raise ProductNotFoundError(access.workspace.id, product_id)

        return product


def _specs(variants: Sequence[VariantWrite]) -> list[VariantSpec]:
    return [
        VariantSpec(
            external_id=variant.external_id,
            sku=variant.sku,
            title=variant.title,
            price=variant.price,
            stock_quantity=variant.stock_quantity,
            attributes=variant.attributes,
        )
        for variant in variants
    ]


def get_product_repository(session: SessionDep) -> ProductRepository:
    return ProductRepository(session)


ProductRepositoryDep = Annotated[
    ProductRepository,
    Depends(get_product_repository),
]


def get_product_service(
    session: SessionDep,
    products: ProductRepositoryDep,
) -> ProductService:
    return ProductService(session=session, products=products)


ProductServiceDep = Annotated[ProductService, Depends(get_product_service)]
