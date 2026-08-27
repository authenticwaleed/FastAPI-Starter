from fastapi import APIRouter, Request, status

from app.api.dependencies.workspace import WorkspaceAdminDep, WorkspaceMemberDep
from app.api.errors import (
    STOREFRONT_CONFLICT,
    STOREFRONT_NOT_FOUND,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.schemas.ecommerce import (
    StorefrontConnect,
    StorefrontInstall,
    StorefrontRead,
    SyncReport,
)
from app.services.ecommerce_service import EcommerceServiceDep

router = APIRouter(
    prefix="/workspaces/{workspace_id}/integrations/shopify",
    tags=["ecommerce"],
)

# The provider calls this one, and it has no workspace in its path for
# the same reason the WhatsApp webhook does not: an app is configured
# with a single redirect URI. Which workspace an installation belongs to
# travels in the signed `state` instead.
callback_router = APIRouter(
    prefix="/integrations/shopify",
    tags=["ecommerce"],
)

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}


# Connecting a storefront is administration: it hands this application
# read access to every price and every order the business has. An agent
# answering messages does not get to do that.
@router.post("/install", responses={**SCOPED, **STOREFRONT_CONFLICT})
def begin_install(
    payload: StorefrontConnect,
    access: WorkspaceAdminDep,
    service: EcommerceServiceDep,
) -> StorefrontInstall:
    """Start an installation, and say where to send the shop owner.

    Nothing is connected yet. What comes back is a URL on the provider's
    own domain, where the owner approves the permissions; the provider
    then calls the callback below.
    """
    installation = service.begin_install(access, payload.shop_domain)

    return StorefrontInstall(
        authorize_url=installation.authorize_url,
        shop_domain=installation.shop_domain,
    )


@router.get("", responses={**SCOPED, **STOREFRONT_NOT_FOUND})
def read_storefront(
    access: WorkspaceMemberDep,
    service: EcommerceServiceDep,
) -> StorefrontRead:
    return StorefrontRead.model_validate(service.connected(access))


@router.post("/sync", responses={**SCOPED, **STOREFRONT_NOT_FOUND})
def sync_storefront(
    access: WorkspaceAdminDep,
    service: EcommerceServiceDep,
) -> SyncReport:
    """Read the whole shop and write it into this workspace.

    The first sync, and the button somebody presses when they think
    something is missing. Safe to press twice: it is the same upsert the
    webhooks use, run over everything rather than over one record.

    Synchronous, which is honest for a catalogue of a few hundred
    products and will not be for a few hundred thousand. Moving it to a
    background job is the background-jobs phase, and the shape here does
    not change when it does.
    """
    report = service.sync_all(access)

    return SyncReport(
        products=report.products,
        orders=report.orders,
        contacts=report.contacts,
        skipped=report.skipped,
    )


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**SCOPED, **STOREFRONT_NOT_FOUND},
)
def disconnect_storefront(
    access: WorkspaceAdminDep,
    service: EcommerceServiceDep,
) -> None:
    """Stop using the storefront, and destroy the token.

    What was already synced stays. A business that disconnects has
    stopped granting access; it has not asked to lose its own catalogue.
    """
    service.disconnect(access)


@callback_router.get("/callback")
def complete_install(
    request: Request,
    service: EcommerceServiceDep,
) -> dict[str, str]:
    """Where the provider sends the shop owner back to.

    Unauthenticated, because the caller is a shop owner's browser
    arriving from the provider. What vouches for it is the provider's own
    HMAC over the query string and the signed `state` this application
    put there -- both checked in the service, and both required.
    """
    account = service.complete_install(dict(request.query_params))

    return {"status": "connected", "shop_domain": account.shop_domain}
