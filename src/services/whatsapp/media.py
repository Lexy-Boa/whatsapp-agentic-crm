"""
Media download and local storage utilities.

Currently saves to /tmp/{store_id}/{media_id}.{ext}.
A future task will replace this with Cloudflare R2 upload.
"""

from __future__ import annotations

import mimetypes
import os

import structlog

from src.services.whatsapp.client import WhatsAppClient

logger = structlog.get_logger(__name__)

# Fallback extensions for common WhatsApp MIME types not always in mimetypes db
_MIME_TO_EXT: dict[str, str] = {
    "audio/ogg": ".ogg",
    "audio/ogg; codecs=opus": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "application/pdf": ".pdf",
}


async def download_and_store_media(
    client: WhatsAppClient,
    media_id: str,
    store_id: str,
) -> str:
    """
    Download media from WhatsApp and store it locally.

    Args:
        client: An initialised WhatsAppClient.
        media_id: The media ID from the webhook payload.
        store_id: Namespace for the local file path (e.g. tenant or session ID).

    Returns:
        Absolute path of the saved file (e.g. ``/tmp/store123/wamid_abc.ogg``).

    Raises:
        OSError: if the directory cannot be created or the file cannot be written.
        httpx.HTTPStatusError: propagated from WhatsAppClient on download failure.
    """
    file_bytes, mime_type = await client.download_media(media_id)

    ext = _resolve_extension(mime_type)
    safe_id = media_id.replace("/", "_").replace("\\", "_")
    filename = f"{safe_id}{ext}"

    dir_path = f"/tmp/{store_id}"
    os.makedirs(dir_path, exist_ok=True)

    file_path = os.path.join(dir_path, filename)
    with open(file_path, "wb") as fh:
        fh.write(file_bytes)

    logger.info(
        "whatsapp_media_stored",
        media_id=media_id,
        path=file_path,
        size_bytes=len(file_bytes),
        mime_type=mime_type,
    )
    return file_path


def _resolve_extension(mime_type: str) -> str:
    """Return a file extension (with leading dot) for a MIME type."""
    # Check our hand-crafted table first (handles 'audio/ogg; codecs=opus' etc.)
    base_mime = mime_type.split(";")[0].strip().lower()
    if base_mime in _MIME_TO_EXT:
        return _MIME_TO_EXT[base_mime]
    if mime_type in _MIME_TO_EXT:
        return _MIME_TO_EXT[mime_type]

    # Fall back to the stdlib mimetypes module
    ext = mimetypes.guess_extension(base_mime)
    if ext:
        return ext

    return ".bin"
