import hmac
import json
import logging
import uuid
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Header,
    Query,
    Request,
    Response,
    status,
)

from app.api.dependencies.rate_limit import RateLimiterDep, client_address
from app.api.errors import RATE_LIMITED
from app.core.config import get_settings
from app.core.exceptions import InvalidWebhookError
from app.core.rate_limit import RateLimited
from app.integrations.ecommerce.base import WebhookEvent, WebhookTopic
from app.models.ecommerce_account import EcommerceAccountStatus
from app.services.ai_dispatch import SessionSourceDep, answer_inbound
from app.services.ai_response_service import ReplyWriterDep
from app.services.ecommerce_service import (
    EcommerceAccountRepositoryDep,
    EcommerceProviderDep,
    EcommerceServiceDep,
)
from app.services.ecommerce_sync_service import (
    EcommerceSyncService,
    EcommerceSyncServiceDep,
)
from app.services.knowledge_service import EmbeddingProviderDep
from app.services.message_ingestion_service import MessageIngestionServiceDep
from app.services.whatsapp_service import MessagingProviderDep

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/webhooks",
    tags=["webhooks"],
)


# Neither route is authenticated the way the rest of the API is: the
# caller is Meta, which has no account here. What stands in for a token is
# the verify string on the subscription handshake and an HMAC signature on
# every delivery afterwards.
@router.get("/whatsapp")
def verify_whatsapp_subscription(
    mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> Response:
    """The subscription handshake, run once when the webhook is set up.

    Meta calls this with a string the account holder chose, and accepts
    the subscription only if the same string is echoed back. Comparison is
    constant time, and every failure answers 403 without saying which part
    was wrong.
    """
    expected = get_settings().whatsapp_verify_token

    if (
        mode != "subscribe"
        or expected is None
        or token is None
        or not hmac.compare_digest(token, expected.get_secret_value())
    ):
        logger.warning("A WhatsApp subscription handshake was refused")

        return Response(status_code=status.HTTP_403_FORBIDDEN)

    # Echoed as plain text, which is what Meta expects: a JSON string
    # here fails the handshake with no explanation.
    return Response(content=challenge or "", media_type="text/plain")


@router.post(
    "/whatsapp",
    status_code=status.HTTP_200_OK,
    responses=RATE_LIMITED,
)
async def receive_whatsapp_webhook(
    request: Request,
    background: BackgroundTasks,
    service: MessageIngestionServiceDep,
    embeddings: EmbeddingProviderDep,
    writer: ReplyWriterDep,
    messaging: MessagingProviderDep,
    session_source: SessionSourceDep,
    limiter: RateLimiterDep,
    signature: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
) -> dict[str, str]:
    """Take delivery of whatever WhatsApp is telling us.

    Async, uniquely among the routes that reach the database, because the
    signature covers the raw request body byte for byte and reading that
    body is what needs awaiting. Re-serialising the parsed JSON would
    change the bytes and fail every honest delivery.

    Answers 200 for anything that authenticates, including payloads it
    cannot use. A webhook that answers anything else is one the provider
    sends again, and a delivery that can never be handled would then be
    retried for a day.

    The assistant runs after that 200 rather than before it. Drafting a
    reply is a retrieval and a language model -- seconds -- and Meta reads
    a slow response as a failed delivery and sends the whole envelope
    again. Only messages this delivery actually wrote are followed up, so
    a repeated delivery does not produce a repeated answer.

    Rate limited on deliveries that fail rather than on deliveries. Meta
    sends real traffic in volume from a handful of addresses, so counting
    every delivery would mean either a limit high enough to be no limit
    or one that throttles the provider itself. Counting only the ones
    that do not authenticate leaves an honest sender permanently free and
    stops answering somebody sending forgeries -- which is what "webhook
    abuse" actually names.
    """
    sender = client_address(request)

    # Checked, not spent: arriving is free. What gets spent is below,
    # once a delivery has proved it could not authenticate.
    limiter.check(RateLimited.WEBHOOK_REJECTIONS, sender)

    body = await request.body()

    try:
        service.verify(payload=body, signature_header=signature)
    except InvalidWebhookError:
        limiter.spend(RateLimited.WEBHOOK_REJECTIONS, sender)
        raise

    try:
        payload: Any = json.loads(body)
    except ValueError as exc:
        # Signed, and not JSON. Worth a line, not worth a retry.
        logger.warning("A signed WhatsApp delivery was not JSON")
        limiter.spend(RateLimited.WEBHOOK_REJECTIONS, sender)
        raise InvalidWebhookError from exc

    if not isinstance(payload, dict):
        logger.warning("A signed WhatsApp delivery was not an object")

        return {"status": "ignored"}

    for recorded in service.ingest(payload):
        background.add_task(
            answer_inbound,
            workspace_id=recorded.workspace_id,
            conversation_id=recorded.conversation_id,
            message_id=recorded.message_id,
            # The provider objects are handed over rather than rebuilt.
            # They hold no session, and passing them is what keeps a
            # test's fakes in force for work that outlives the request.
            embeddings=embeddings,
            writer=writer,
            messaging=messaging,
            session_source=session_source,
            # The same counters the dashboard's own AI endpoint spends
            # from, so a runaway conversation cannot cost a workspace
            # more than a person asking for replies by hand could.
            limiter=limiter,
        )

    return {"status": "received"}


@router.post(
    "/shopify",
    status_code=status.HTTP_200_OK,
    responses=RATE_LIMITED,
)
async def receive_shopify_webhook(
    request: Request,
    provider: EcommerceProviderDep,
    storefronts: EcommerceServiceDep,
    sync: EcommerceSyncServiceDep,
    accounts: EcommerceAccountRepositoryDep,
    limiter: RateLimiterDep,
    signature: Annotated[str | None, Header(alias="X-Shopify-Hmac-Sha256")] = None,
    topic: Annotated[str | None, Header(alias="X-Shopify-Topic")] = None,
    shop: Annotated[str | None, Header(alias="X-Shopify-Shop-Domain")] = None,
) -> dict[str, str]:
    """Take delivery of whatever the storefront is telling us.

    Async for the reason the WhatsApp webhook is: the signature covers
    the raw body byte for byte, and reading that body is what needs
    awaiting.

    Answers 200 for anything that authenticates, including topics this
    application does not handle. A webhook subscription is easy to widen
    by accident, and a delivery that can never be acted on would
    otherwise be retried for a day.

    Duplicate deliveries need no special handling, and that is by
    construction rather than by luck. Every write below is an upsert
    keyed on the storefront's own id, so applying the same delivery twice
    produces the same rows -- and a payload older than what is already
    stored is skipped rather than written backwards, which is what makes
    a retry that overtakes a newer change harmless too.

    Rate limited on deliveries that fail, exactly like the WhatsApp one:
    a real storefront sending real traffic is never charged for arriving.
    """
    sender = client_address(request)
    limiter.check(RateLimited.WEBHOOK_REJECTIONS, sender)

    body = await request.body()

    if not provider.verify_webhook(payload=body, signature=signature):
        limiter.spend(RateLimited.WEBHOOK_REJECTIONS, sender)
        logger.warning("A Shopify delivery did not verify")
        raise InvalidWebhookError

    try:
        payload: Any = json.loads(body)
    except ValueError as exc:
        logger.warning("A signed Shopify delivery was not JSON")
        limiter.spend(RateLimited.WEBHOOK_REJECTIONS, sender)
        raise InvalidWebhookError from exc

    if not isinstance(payload, dict):
        return {"status": "ignored"}

    event = provider.parse_webhook(topic=topic, shop=shop, payload=payload)

    if event.topic is None:
        # Subscribed to something nothing here acts on. Acknowledged, so
        # it is not retried, and logged once so somebody can notice.
        logger.info("Ignoring an unhandled Shopify topic: %s", topic)

        return {"status": "ignored"}

    if event.topic is WebhookTopic.UNINSTALLED:
        storefronts.uninstalled(event.shop)

        return {"status": "disconnected"}

    account = accounts.get_by_shop_domain(event.shop)

    if account is None or account.status is not EcommerceAccountStatus.CONNECTED:
        # A shop nothing here is connected to. Acknowledged rather than
        # refused: the delivery is real, it is simply not ours, and a
        # non-200 would have the provider retry it for a day.
        logger.info("Ignoring a Shopify delivery for a shop we do not hold")

        return {"status": "ignored"}

    _apply(event, account.workspace_id, sync)
    sync.commit()

    return {"status": "received"}


def _apply(
    event: WebhookEvent,
    workspace_id: uuid.UUID,
    sync: EcommerceSyncService,
) -> None:
    if event.topic is WebhookTopic.PRODUCT_UPSERT and event.product is not None:
        sync.upsert_product(workspace_id, event.product)
    elif event.topic is WebhookTopic.PRODUCT_DELETE and event.external_id is not None:
        sync.delete_product(workspace_id, event.external_id)
    elif event.topic is WebhookTopic.ORDER_UPSERT and event.order is not None:
        sync.upsert_order(workspace_id, event.order)
