"""
WhatsApp webhook endpoints for Meta Cloud API.

GET  /webhook  — one-time verification challenge (WhatsApp calls this during setup)
POST /webhook  — receive inbound messages, deduplicate, and queue for processing
"""

from __future__ import annotations

import hashlib
import hmac
import json

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse

from src.config import get_settings
from src.core.privacy import mask_phone
from src.db.redis_client import get_redis
from src.services.observability.events import emit_system_event
from src.services.whatsapp.message_parser import IncomingMessage, parse_webhook_payload
from src.workers.queue import enqueue_message

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["whatsapp"])
settings = get_settings()

# Redis key prefix and TTL for deduplication
_DEDUP_PREFIX = "wa:msg:"
_DEDUP_TTL_SECONDS = 86_400  # 24 hours


# ---------------------------------------------------------------------------
# GET /webhook — verification handshake
# ---------------------------------------------------------------------------

@router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(request: Request) -> str:
    """
    Meta WhatsApp Cloud API webhook verification.

    WhatsApp sends:
        ?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=<challenge>

    We must return hub.challenge as plain text if the token matches.
    """
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")

    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        logger.info("whatsapp_webhook_verified")
        await emit_system_event(
            event_type="webhook_verified",
            event_level="info",
            component="webhook",
            summary="Webhook verification challenge accepted.",
            event_status="ok",
        )
        return challenge

    logger.warning(
        "whatsapp_webhook_verification_failed",
        mode=mode,
        token_matches=(token == settings.whatsapp_verify_token),
    )
    await emit_system_event(
        event_type="webhook_rejected",
        event_level="warning",
        component="webhook",
        summary="Webhook verification failed.",
        event_status="rejected",
        details={"mode": mode, "token_matches": token == settings.whatsapp_verify_token},
    )
    raise HTTPException(status_code=403, detail="Verification failed")


# ---------------------------------------------------------------------------
# POST /webhook — receive messages
# ---------------------------------------------------------------------------

@router.post("/webhook", status_code=200)
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """
    Receive inbound WhatsApp messages from Meta Cloud API.

    1. Verify X-Hub-Signature-256 (skipped in dev if secret is unset).
    2. Parse the JSON payload into IncomingMessage objects.
    3. Deduplicate via Redis NX and queue new messages for async processing.
    4. Return 200 immediately — Meta retries on non-2xx.
    """
    body = await request.body()

    # -- Signature verification ------------------------------------------------
    if settings.whatsapp_app_secret:
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        if not _verify_signature(body, sig_header, settings.whatsapp_app_secret):
            logger.warning("whatsapp_invalid_signature", signature_present=bool(sig_header))
            await emit_system_event(
                event_type="webhook_rejected",
                event_level="warning",
                component="webhook",
                summary="Webhook rejected due to invalid signature.",
                event_status="rejected",
            )
            raise HTTPException(status_code=403, detail="Invalid signature")
    else:
        logger.debug("whatsapp_signature_check_skipped_no_secret")

    # -- Parse payload ---------------------------------------------------------
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("whatsapp_invalid_json_body")
        await emit_system_event(
            event_type="webhook_rejected",
            event_level="warning",
            component="webhook",
            summary="Webhook rejected due to invalid JSON body.",
            event_status="rejected",
        )
        raise HTTPException(status_code=400, detail="Invalid JSON")

    messages = parse_webhook_payload(
        payload,
        business_phone=settings.whatsapp_phone_number,
    )

    # -- Queue for async processing; return 200 immediately -------------------
    if messages:
        background_tasks.add_task(_enqueue_messages, messages)

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Background task — deduplicate + enqueue
# ---------------------------------------------------------------------------

async def _enqueue_messages(messages: list[IncomingMessage]) -> None:
    """
    Deduplicate and push each new message onto the processing queue.

    Redis SET NX with 24-hour TTL prevents duplicate processing when
    Meta re-delivers the same webhook.
    """
    redis = get_redis()

    for msg in messages:
        dedup_key = f"{_DEDUP_PREFIX}{msg.message_id}"
        is_new = await redis.set(dedup_key, "1", nx=True, ex=_DEDUP_TTL_SECONDS)

        if not is_new:
            logger.info(
                "whatsapp_duplicate_skipped",
                message_id=msg.message_id,
                from_phone=mask_phone(msg.from_phone),
            )
            await emit_system_event(
                event_type="webhook_duplicate_skipped",
                event_level="info",
                component="webhook",
                summary="Duplicate webhook delivery skipped.",
                event_status="duplicate",
                customer_phone_masked=mask_phone(msg.from_phone),
                details={"whatsapp_message_id": msg.message_id},
            )
            continue

        logger.info(
            "whatsapp_message_received",
            message_id=msg.message_id,
            from_phone=mask_phone(msg.from_phone),
            to_phone=mask_phone(msg.to_phone),
            message_type=msg.message_type,
            has_text=msg.text is not None,
            has_media=msg.media_id is not None,
            timestamp=msg.timestamp.isoformat(),
        )
        await emit_system_event(
            event_type="webhook_received",
            event_level="info",
            component="webhook",
            summary=f"Inbound {msg.message_type} message received from WhatsApp.",
            event_status="received",
            customer_phone_masked=mask_phone(msg.from_phone),
            details={
                "whatsapp_message_id": msg.message_id,
                "message_type": msg.message_type,
                "has_text": msg.text is not None,
                "has_media": msg.media_id is not None,
            },
        )

        # Serialise to Redis queue for the MessageProcessorWorker
        queue_payload = {
            "store_id": settings.store_id,
            "from_phone": msg.from_phone,
            "message_type": msg.message_type,
            "text": msg.text,
            "media_id": msg.media_id,
            "media_mime_type": msg.media_mime_type,
            "whatsapp_message_id": msg.message_id,
            "recovery_attempts": 0,
        }
        await enqueue_message(redis, queue_payload)
        logger.debug("whatsapp_message_queued", message_id=msg.message_id)
        await emit_system_event(
            event_type="message_queued",
            event_level="info",
            component="queue",
            summary="Inbound message queued for worker processing.",
            event_status="queued",
            customer_phone_masked=mask_phone(msg.from_phone),
            details={
                "whatsapp_message_id": msg.message_id,
                "message_type": msg.message_type,
            },
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_signature(body: bytes, signature_header: str, secret: str) -> bool:
    """
    Verify the X-Hub-Signature-256 header.

    Format: ``sha256=<hex_digest>``
    Uses hmac.compare_digest to prevent timing-attack leaks.
    """
    expected_hex = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    expected = f"sha256={expected_hex}"
    return hmac.compare_digest(expected, signature_header)
