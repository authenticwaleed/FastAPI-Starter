from fastapi import APIRouter, Request, status

from app.api.dependencies.workspace import WorkspaceAdminDep, WorkspaceMemberDep
from app.api.errors import (
    STOREFRONT_CONFLICT,
    STOREFRONT_NOT_FOUND,
    UNAUTHORISED,
    WORKSPACE_FORBIDDEN,
    WORKSPACE_NOT_FOUND,
)
from app.integrations.ecommerce.base import (
    EcommerceProviderName,
    InstallCallback,
)
from app.schemas.ecommerce import (
    StorefrontConnect,
    StorefrontInstall,
    StorefrontRead,
    SyncReport,
)
from app.services.ecommerce_service import EcommerceServiceDep

# The storefront is a path parameter rather than a separate set of
# routes, which is what "do not duplicate business logic" looks like at
# this layer: connecting Shopify and connecting WooCommerce are the same
# four operations, and the only thing that differs is which adapter runs.
# The enum validates it, so an unknown provider is a 422 before any
# handler does anything.
#
# The URLs are unchanged from when Shopify was the only one:
# `/integrations/shopify/install` is still exactly that path.
router = APIRouter(
    prefix="/workspaces/{workspace_id}/integrations/{provider}",
    tags=["ecommerce"],
)

# The provider calls this one, and it has no workspace in its path for
# the same reason the WhatsApp webhook does not: a storefront app is
# configured with a single callback URL. Which workspace an installation
# belongs to travels in the signed `state` instead.
callback_router = APIRouter(
    prefix="/integrations/{provider}",
    tags=["ecommerce"],
)

SCOPED = {**UNAUTHORISED, **WORKSPACE_FORBIDDEN, **WORKSPACE_NOT_FOUND}


# Connecting a storefront is administration: it hands this application
# read access to every price and every order the business has. An agent
# answering messages does not get to do that.
@router.post("/install", responses={**SCOPED, **STOREFRONT_CONFLICT})
def begin_install(
    provider: EcommerceProviderName,
    payload: StorefrontConnect,
    access: WorkspaceAdminDep,
    service: EcommerceServiceDep,
) -> StorefrontInstall:
    """Start an installation, and say where to send the shop owner.

    Nothing is connected yet. What comes back is a URL on the provider's
    own domain, where the owner approves the permissions; the provider
    then calls the callback below.
    """
    installation = service.begin_install(access, provider, payload.shop_domain)

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
    provider: EcommerceProviderName,
    request: Request,
    service: EcommerceServiceDep,
) -> dict[str, str]:
    """Where a provider that redirects the browser back sends it.

    Unauthenticated, because the caller is a shop owner's browser
    arriving from the provider. What vouches for it is the signed `state`
    this application put in the request, plus whatever proof the provider
    itself offers -- for Shopify an HMAC over the query string, both
    checked in the service.
    """
    account = service.complete_install(
        provider,
        InstallCallback(params=dict(request.query_params)),
    )

    return {"status": "connected", "shop_domain": account.shop_domain}


@callback_router.post("/callback")
async def receive_install_callback(
    provider: EcommerceProviderName,
    request: Request,
    service: EcommerceServiceDep,
) -> dict[str, str]:
    """Where a provider that posts its credentials sends them.

    WooCommerce's half of the flow, and the reason there are two verbs on
    one path. Its store does not redirect a browser back carrying a
    grant; it POSTs the key pair here, server to server, and sends the
    browser to the dashboard instead.

    Async because the body has to be read, like the webhooks. Nothing in
    that body is signed -- WooCommerce signs this with nothing at all --
    so what has to hold is the state, which the store echoes back and the
    service checks.
    """
    account = service.complete_install(
        provider,
        InstallCallback(params=dict(request.query_params), body=await request.body()),
    )

    return {"status": "connected", "shop_domain": account.shop_domain}
