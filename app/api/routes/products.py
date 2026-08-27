import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dependencies.workspace import WorkspaceAdminDep, WorkspaceMemberDep
from app.api.errors import (
    PRODUCT_CONFLICT,
    PRODUCT_NOT_FOUND,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.models.product import ProductStatus
from app.repositories.product_repository import ProductWithVariants
from app.schemas.product import (
    ProductCreate,
    ProductPage,
    ProductRead,
    ProductUpdate,
    VariantRead,
)
from app.services.product_service import ProductServiceDep

router = APIRouter(
    prefix="/workspaces/{workspace_id}/products",
    tags=["products"],
)

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}


def _read(entry: ProductWithVariants) -> ProductRead:
    product = entry.product

    return ProductRead(
        id=product.id,
        external_id=product.external_id,
        name=product.name,
        description=product.description,
        status=product.status,
        price=product.price,
        currency=product.currency,
        metadata=product.meta,
        variants=[VariantRead.model_validate(variant) for variant in entry.variants],
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


# Reading is any member's, writing is an admin's. Unlike contacts, where
# writing is an agent's job: a price list is what the business charges,
# and an agent answering messages should not be able to change it by
# accident in the middle of a conversation.
@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={**SCOPED, **PRODUCT_CONFLICT},
)
def create_product(
    payload: ProductCreate,
    access: WorkspaceAdminDep,
    service: ProductServiceDep,
) -> ProductRead:
    return _read(service.create(access, payload))


@router.get("", responses=SCOPED)
def list_products(
    access: WorkspaceMemberDep,
    service: ProductServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(max_length=255)] = None,
    status_filter: Annotated[ProductStatus | None, Query(alias="status")] = None,
    in_stock: Annotated[bool | None, Query()] = None,
) -> ProductPage:
    """One page of this workspace's catalogue, newest first.

    `search` matches a name, a description, or the SKU of any variant --
    a customer quoting a SKU back is quoting the only identifier they
    were ever given.

    `in_stock` means a variant that is counted and positive. A product
    whose stock nobody tracks is neither in nor out, and it is left out of
    both answers rather than guessed at.

    `status` is spelled `status_filter` in Python only because `status` is
    the name of the FastAPI module imported above.
    """
    entries, total = service.list_for(
        access,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
        in_stock=in_stock,
    )

    return ProductPage(
        items=[_read(entry) for entry in entries],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{product_id}", responses={**SCOPED, **PRODUCT_NOT_FOUND})
def read_product(
    product_id: uuid.UUID,
    access: WorkspaceMemberDep,
    service: ProductServiceDep,
) -> ProductRead:
    return _read(service.get(access, product_id))


@router.patch(
    "/{product_id}",
    responses={**SCOPED, **PRODUCT_NOT_FOUND, **PRODUCT_CONFLICT},
)
def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    access: WorkspaceAdminDep,
    service: ProductServiceDep,
) -> ProductRead:
    """Change a product, and optionally its whole set of variants.

    Supplying `variants` replaces them; omitting it leaves them alone.
    """
    return _read(service.update(access, product_id, payload))


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**SCOPED, **PRODUCT_NOT_FOUND},
)
def delete_product(
    product_id: uuid.UUID,
    access: WorkspaceAdminDep,
    service: ProductServiceDep,
) -> None:
    service.delete(access, product_id)
