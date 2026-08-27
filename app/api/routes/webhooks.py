import hmac
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request, Response, status

from app.core.config import get_settings
from app.core.exceptions import InvalidWebhookError
from app.services.message_ingestion_service import MessageIngestionServiceDep

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


@router.post("/whatsapp", status_code=status.HTTP_200_OK)
async def receive_whatsapp_webhook(
    request: Request,
    service: MessageIngestionServiceDep,
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
    """
    body = await request.body()

    service.verify(payload=body, signature_header=signature)

    try:
        payload: Any = json.loads(body)
    except ValueError as exc:
        # Signed, and not JSON. Worth a line, not worth a retry.
        logger.warning("A signed WhatsApp delivery was not JSON")
        raise InvalidWebhookError from exc

    if not isinstance(payload, dict):
        logger.warning("A signed WhatsApp delivery was not an object")

        return {"status": "ignored"}

    service.ingest(payload)

    return {"status": "received"}
