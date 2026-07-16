"""
Voice transcription pipeline using Groq Whisper API.

Pipeline:
  1. Write audio bytes to a named temp file (Whisper needs a seekable file).
  2. Call whisper-large-v3-turbo with response_format="verbose_json" for confidence data.
  3. Map Whisper's language name to an ISO 639-1 code.
  4. Run dialect detection if language is ml or ta.
  5. Normalize the transcript text.
  6. Return a structured TranscriptionResult.

The class is safe to instantiate once and reuse across requests.
"""

from __future__ import annotations

import math
import mimetypes
import os
import tempfile
from dataclasses import dataclass

import structlog
from groq import AsyncGroq

from src.config import get_settings
from src.services.speech.dialect_detector import DialectDetector
from src.services.speech.normalizer import DialectNormalizer

logger = structlog.get_logger(__name__)

# Whisper returns full language names; map to ISO 639-1 codes.
_WHISPER_LANG_TO_CODE: dict[str, str] = {
    "malayalam": "ml",
    "tamil": "ta",
    "english": "en",
    "hindi": "hi",
    "telugu": "te",
    "kannada": "kn",
    "arabic": "ar",
    "urdu": "ur",
    "bengali": "bn",
    "marathi": "mr",
    "gujarati": "gu",
    "punjabi": "pa",
    "odia": "or",
    "assamese": "as",
}

# MIME type → file extension for temp file naming
_MIME_TO_EXT: dict[str, str] = {
    "audio/ogg": ".ogg",
    "audio/ogg; codecs=opus": ".ogg",
    "audio/opus": ".opus",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class TranscriptionResult:
    text: str                       # Normalized transcript
    raw_text: str                   # Exactly what Whisper returned
    language: str                   # ISO 639-1 code (ml, ta, en, …)
    dialect: str | None             # Dialect name or None
    dialect_confidence: float       # 0–1; 0.0 if no dialect detected
    transcription_confidence: float # 0–1 derived from Whisper avg_logprob
    duration_seconds: float
    word_count: int


# ---------------------------------------------------------------------------
# Transcriber
# ---------------------------------------------------------------------------

class VoiceTranscriber:
    """
    Voice transcription pipeline combining Whisper + dialect detection.

    Create once (e.g. at app startup) and reuse — the Groq client
    maintains an internal connection pool.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncGroq(api_key=settings.groq_api_key.get_secret_value())
        self._model = settings.whisper_model
        self._detector = DialectDetector()
        self._normalizer = DialectNormalizer()

    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str,
        language_hint: str | None = None,
    ) -> TranscriptionResult:
        """
        Full transcription pipeline.

        Args:
            audio_bytes: Raw audio file bytes.
            mime_type:   MIME type (e.g. "audio/ogg; codecs=opus").
            language_hint: ISO 639-1 code from customer profile, speeds up
                           Whisper and reduces language detection errors.

        Returns:
            TranscriptionResult with normalized text, detected language,
            dialect, and confidence scores.
        """
        ext = _mime_to_ext(mime_type)
        tmp_path: str | None = None

        try:
            # -- Step 1: write to temp file ------------------------------------
            with tempfile.NamedTemporaryFile(
                suffix=ext, delete=False
            ) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            # -- Step 2: call Whisper ------------------------------------------
            whisper_resp = await self._call_whisper(tmp_path, language_hint)

        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        # -- Step 3: extract fields from Whisper response ---------------------
        raw_text: str = whisper_resp.text or ""
        whisper_lang: str = getattr(whisper_resp, "language", "") or ""
        duration: float = float(getattr(whisper_resp, "duration", 0.0) or 0.0)

        language = _WHISPER_LANG_TO_CODE.get(whisper_lang.lower(), whisper_lang.lower() or "und")

        transcription_confidence = _compute_confidence(whisper_resp)

        # -- Step 4: dialect detection (ml / ta only) -------------------------
        dialect_info = await self._detector.detect(raw_text, language)
        dialect_name = dialect_info.name if dialect_info else None
        dialect_confidence = dialect_info.confidence if dialect_info else 0.0

        if dialect_info:
            logger.debug(
                "dialect_detected",
                language=language,
                dialect=dialect_name,
                confidence=dialect_confidence,
                markers=dialect_info.markers_found,
            )

        # -- Step 5: normalize ------------------------------------------------
        normalized_text = self._normalizer.normalize(raw_text, language, dialect_name)

        word_count = len(normalized_text.split()) if normalized_text else 0

        logger.info(
            "transcription_complete",
            language=language,
            dialect=dialect_name,
            duration_seconds=round(duration, 1),
            word_count=word_count,
            transcription_confidence=round(transcription_confidence, 3),
        )

        return TranscriptionResult(
            text=normalized_text,
            raw_text=raw_text,
            language=language,
            dialect=dialect_name,
            dialect_confidence=round(dialect_confidence, 4),
            transcription_confidence=round(transcription_confidence, 4),
            duration_seconds=round(duration, 2),
            word_count=word_count,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _call_whisper(self, file_path: str, language_hint: str | None):
        """Call the Groq Whisper API and return the verbose JSON response."""
        ext = os.path.splitext(file_path)[1] or ".ogg"
        mime_type = mimetypes.guess_type(f"audio{ext}")[0] or "audio/ogg"

        kwargs: dict = {
            "model": self._model,
            "response_format": "verbose_json",
        }
        # Whisper accepts ISO 639-1 language codes as hints
        if language_hint:
            kwargs["language"] = language_hint

        with open(file_path, "rb") as audio_file:
            response = await self._client.audio.transcriptions.create(
                file=(f"audio{ext}", audio_file, mime_type),
                **kwargs,
            )
        return response


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _mime_to_ext(mime_type: str) -> str:
    """Resolve a MIME type to a file extension (with leading dot)."""
    # Normalise: "audio/ogg; codecs=opus" → "audio/ogg"
    base = mime_type.split(";")[0].strip().lower()
    if mime_type in _MIME_TO_EXT:
        return _MIME_TO_EXT[mime_type]
    if base in _MIME_TO_EXT:
        return _MIME_TO_EXT[base]
    ext = mimetypes.guess_extension(base)
    return ext if ext else ".bin"


def _compute_confidence(whisper_resp) -> float:
    """
    Derive a [0, 1] confidence score from Whisper's verbose_json response.

    Uses the mean of per-segment avg_logprob values.
    avg_logprob is in (-∞, 0]; values closer to 0 → higher confidence.
    We map via exp() so that:
      avg_logprob = 0.0  → confidence ≈ 1.00
      avg_logprob = −0.3 → confidence ≈ 0.74
      avg_logprob = −0.7 → confidence ≈ 0.50
      avg_logprob = −1.5 → confidence ≈ 0.22
    """
    segments = getattr(whisper_resp, "segments", None) or []
    if not segments:
        return 0.8  # no segments means short audio; assume reasonable quality

    avg_logprob = sum(
        getattr(seg, "avg_logprob", -0.3) for seg in segments
    ) / len(segments)

    return round(max(0.0, min(1.0, math.exp(avg_logprob))), 4)
