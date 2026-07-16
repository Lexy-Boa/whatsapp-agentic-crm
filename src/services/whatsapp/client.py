"""
Async HTTP client for the Meta WhatsApp Cloud API.

Base URL: https://graph.facebook.com/v22.0/{phone_number_id}
Auth header: Authorization: Bearer {access_token}
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential, before_sleep_log

from src.core.privacy import mask_phone, redact_operational_text
from src.services.observability.events import emit_system_event

logger = structlog.get_logger(__name__)
_std_logger = __import__("logging").getLogger(__name__)

_GRAPH_API_VERSION = "v22.0"
_BASE_URL = "https://graph.facebook.com"
_TIMEOUT = httpx.Timeout(10.0, read=30.0)


@dataclass
class SendResult:
    success: bool
    message_id: str | None = None
    error: str | None = None


class WhatsAppClient:
    """Async client for the Meta WhatsApp Cloud API."""

    def __init__(self, access_token: str, phone_number_id: str, base_url: str = _BASE_URL) -> None:
        self._access_token = access_token
        self._phone_number_id = phone_number_id
        self._base_url = f"{base_url.rstrip('/')}/{_GRAPH_API_VERSION}/{phone_number_id}"
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=_TIMEOUT,
        )

    # ------------------------------------------------------------------
    # Send methods
    # ------------------------------------------------------------------

    async def send_text(self, to: str, text: str) -> SendResult:
        """Send a plain text message."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        return await self._post_message(payload)

    async def send_voice(self, to: str, audio_url: str) -> SendResult:
        """
        Send a voice note.  ``audio_url`` must be publicly accessible so that
        WhatsApp's servers can fetch it.
        """
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "audio",
            "audio": {"link": audio_url},
        }
        return await self._post_message(payload)

    async def send_image(
        self,
        to: str,
        image_url: str,
        caption: str | None = None,
    ) -> SendResult:
        """Send an image with an optional caption."""
        img: dict = {"link": image_url}
        if caption:
            img["caption"] = caption
        payload = {"messaging_product": "whatsapp", "to": to, "type": "image", "image": img}
        return await self._post_message(payload)

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """
        Download media from WhatsApp via Meta Graph API.

        Step 1: GET https://graph.facebook.com/v22.0/{media_id} → get the CDN URL and mime_type.
        Step 2: GET CDN URL with Bearer auth → raw bytes.

        Returns:
            (file_bytes, mime_type)

        Raises:
            httpx.HTTPStatusError: on non-2xx responses.
            ValueError: if the media URL is missing from the metadata response.
        """
        # Step 1: resolve media URL (media endpoint is at graph root, not under phone_number_id)
        media_meta_url = f"{_BASE_URL}/{_GRAPH_API_VERSION}/{media_id}"
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self._access_token}"},
            timeout=_TIMEOUT,
        ) as meta_client:
            meta_resp = await meta_client.get(media_meta_url)
            meta_resp.raise_for_status()
        meta = meta_resp.json()

        media_url: str | None = meta.get("url")
        mime_type: str = meta.get("mime_type", "application/octet-stream")

        if not media_url:
            raise ValueError(
                f"Meta media endpoint returned no URL for media_id={media_id!r}"
            )

        # Step 2: download the actual bytes from the CDN URL
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self._access_token}"},
            timeout=_TIMEOUT,
            follow_redirects=True,
        ) as dl:
            dl_resp = await dl.get(media_url)
            dl_resp.raise_for_status()

        logger.debug(
            "whatsapp_media_downloaded",
            media_id=media_id,
            mime_type=mime_type,
            size_bytes=len(dl_resp.content),
        )
        return dl_resp.content, mime_type

    # ------------------------------------------------------------------
    # Message status
    # ------------------------------------------------------------------

    async def mark_as_read(self, message_id: str) -> bool:
        """
        Mark an inbound message as read (blue ticks).

        Returns True on success, False on failure (non-fatal — never raise).
        """
        try:
            resp = await self._http.post(
                "/messages",
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": message_id,
                },
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.warning(
                "whatsapp_mark_as_read_failed",
                message_id=message_id,
                error=str(exc),
            )
            return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying httpx client."""
        await self._http.aclose()

    async def __aenter__(self) -> WhatsAppClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout)),
        wait=wait_exponential(min=1, max=30),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(_std_logger, __import__("logging").WARNING),
    )
    async def _post_message(self, payload: dict) -> SendResult:
        """POST to /messages and return a normalised SendResult."""
        to = payload.get("to", "?")
        try:
            resp = await self._http.post("/messages", json=payload)
            resp.raise_for_status()
            data = resp.json()
            # Meta Cloud API returns {"messages": [{"id": "wamid..."}]}
            msg_id: str | None = None
            messages = data.get("messages") or []
            if messages:
                msg_id = messages[0].get("id")
            logger.debug(
                "whatsapp_message_sent",
                to=mask_phone(str(to)),
                msg_type=payload.get("type"),
                message_id=msg_id,
            )
            await emit_system_event(
                event_type="whatsapp_send_succeeded",
                event_level="info",
                component="whatsapp",
                summary=f"Outbound {payload.get('type')} message sent to WhatsApp.",
                event_status="ok",
                customer_phone_masked=mask_phone(str(to)),
                details={"message_id": msg_id, "message_type": payload.get("type")},
            )
            return SendResult(success=True, message_id=msg_id)
        except httpx.HTTPStatusError as exc:
            error = redact_operational_text(
                f"HTTP {exc.response.status_code}: {exc.response.text}"
            )
            logger.error(
                "whatsapp_send_failed",
                to=mask_phone(str(to)),
                msg_type=payload.get("type"),
                error=error,
            )
            await emit_system_event(
                event_type="whatsapp_send_failed",
                event_level="error",
                component="whatsapp",
                summary="WhatsApp outbound send failed.",
                event_status="failed",
                customer_phone_masked=mask_phone(str(to)),
                details={"error": error, "message_type": payload.get("type")},
            )
            return SendResult(success=False, error=error)
        except Exception as exc:
            error = str(exc)
            logger.error(
                "whatsapp_send_error",
                to=mask_phone(str(to)),
                msg_type=payload.get("type"),
                error=error,
            )
            await emit_system_event(
                event_type="whatsapp_send_failed",
                event_level="error",
                component="whatsapp",
                summary="WhatsApp outbound send raised an unexpected error.",
                event_status="failed",
                customer_phone_masked=mask_phone(str(to)),
                details={"error": error, "message_type": payload.get("type")},
            )
            return SendResult(success=False, error=error)
