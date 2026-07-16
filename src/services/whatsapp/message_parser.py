"""
Parse incoming Meta WhatsApp Cloud API webhook payloads into structured
IncomingMessage objects.

Meta sends a nested JSON envelope:
  { "object": "whatsapp_business_account",
    "entry": [{ "changes": [{ "value": { "messages": [...], "contacts": [...] } }] }] }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import structlog

logger = structlog.get_logger(__name__)

MessageKind = Literal["text", "voice", "image", "document", "unknown"]


@dataclass
class IncomingMessage:
    message_id: str
    from_phone: str           # Customer's phone number (E.164 without +)
    to_phone: str             # Store's WhatsApp number
    timestamp: datetime       # UTC
    message_type: MessageKind

    # Text
    text: str | None = None

    # Media (image / document / voice)
    media_id: str | None = None
    media_mime_type: str | None = None
    caption: str | None = None

    # Voice-specific
    voice_duration_seconds: int | None = None


def parse_webhook_payload(
    payload: dict,
    business_phone: str = "",
) -> list[IncomingMessage]:
    """
    Parse a Meta WhatsApp Cloud API webhook payload.

    Returns only real inbound messages; delivery receipts (statuses) are silently
    ignored.  Malformed individual message entries are logged and skipped so that
    one bad entry never drops the whole batch.

    Args:
        payload: Parsed JSON body from the webhook POST.
        business_phone: The store's WhatsApp number, used as ``to_phone``.
    """
    results: list[IncomingMessage] = []

    # Meta Cloud API nests messages inside entry[].changes[].value.messages[]
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            raw_messages = value.get("messages") or []
            for raw in raw_messages:
                try:
                    msg = _parse_single(raw, business_phone)
                    if msg is not None:
                        results.append(msg)
                except Exception:
                    logger.warning(
                        "whatsapp_message_parse_error",
                        message_id=raw.get("id"),
                        msg_type=raw.get("type"),
                        exc_info=True,
                    )

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_single(raw: dict, business_phone: str) -> IncomingMessage | None:
    """Parse one message object from the messages array."""
    msg_id = raw.get("id", "")
    from_phone = raw.get("from", "")
    raw_type = raw.get("type", "unknown")
    timestamp = _parse_timestamp(raw.get("timestamp", "0"))

    base = dict(
        message_id=msg_id,
        from_phone=from_phone,
        to_phone=business_phone,
        timestamp=timestamp,
    )

    if raw_type == "text":
        return IncomingMessage(
            **base,
            message_type="text",
            text=raw.get("text", {}).get("body"),
        )

    if raw_type in ("voice", "audio"):
        voice_obj = raw.get("voice") or raw.get("audio") or {}
        return IncomingMessage(
            **base,
            message_type="voice",
            media_id=voice_obj.get("id"),
            media_mime_type=voice_obj.get("mime_type"),
            # Meta Cloud API doesn't include duration in webhook; populated later
        )

    if raw_type == "image":
        img = raw.get("image", {})
        return IncomingMessage(
            **base,
            message_type="image",
            media_id=img.get("id"),
            media_mime_type=img.get("mime_type"),
            caption=img.get("caption"),
        )

    if raw_type == "document":
        doc = raw.get("document", {})
        return IncomingMessage(
            **base,
            message_type="document",
            media_id=doc.get("id"),
            media_mime_type=doc.get("mime_type"),
            caption=doc.get("caption"),
        )

    # interactive, reaction, sticker, etc. — treat as unknown
    logger.debug("whatsapp_unknown_message_type", msg_type=raw_type, msg_id=msg_id)
    return IncomingMessage(**base, message_type="unknown")


def _parse_timestamp(raw: str | int) -> datetime:
    """Convert a Unix timestamp string/int to a UTC-aware datetime."""
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return datetime.now(timezone.utc)
