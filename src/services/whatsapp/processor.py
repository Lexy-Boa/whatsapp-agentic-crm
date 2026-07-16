"""
WhatsApp message processing helpers.

This module bridges the webhook layer (IncomingMessage) with the speech
pipeline (VoiceTranscriber), keeping the actual HTTP and ML concerns
cleanly separated.
"""

from __future__ import annotations

import structlog

from src.core.privacy import mask_phone
from src.services.speech.transcriber import TranscriptionResult, VoiceTranscriber
from src.services.whatsapp.client import WhatsAppClient
from src.services.whatsapp.message_parser import IncomingMessage

logger = structlog.get_logger(__name__)


async def process_voice_message(
    message: IncomingMessage,
    whatsapp_client: WhatsAppClient,
    transcriber: VoiceTranscriber,
) -> TranscriptionResult:
    """
    Download a voice note from WhatsApp and transcribe it.

    Args:
        message:         The inbound message (must have media_id set).
        whatsapp_client: Authenticated Meta Cloud API client for media download.
        transcriber:     Initialised VoiceTranscriber (Whisper + dialect).

    Returns:
        TranscriptionResult with text, detected language, dialect, and
        confidence scores.

    Raises:
        ValueError: if the message has no media_id.
        httpx.HTTPStatusError: if media download fails.
        openai.APIError: if transcription fails.
    """
    if not message.media_id:
        raise ValueError(
            f"process_voice_message called on message {message.message_id!r} "
            "which has no media_id"
        )

    logger.info(
        "voice_processing_started",
        message_id=message.message_id,
        from_phone=mask_phone(message.from_phone),
        media_id=message.media_id,
    )

    # Step 1: Download audio from WhatsApp CDN
    audio_bytes, mime_type = await whatsapp_client.download_media(message.media_id)

    logger.debug(
        "voice_audio_downloaded",
        message_id=message.message_id,
        size_bytes=len(audio_bytes),
        mime_type=mime_type,
    )

    # Step 2: Transcribe (Whisper → dialect detection → normalization)
    result = await transcriber.transcribe(
        audio_bytes=audio_bytes,
        mime_type=mime_type,
        # No language_hint here — we don't have the customer profile yet.
        # A future task will pass customer.language_preference.
    )

    logger.info(
        "voice_processing_complete",
        message_id=message.message_id,
        from_phone=mask_phone(message.from_phone),
        language=result.language,
        dialect=result.dialect,
        dialect_confidence=result.dialect_confidence,
        transcription_confidence=result.transcription_confidence,
        word_count=result.word_count,
        duration_seconds=result.duration_seconds,
    )

    return result
