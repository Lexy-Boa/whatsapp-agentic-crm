"""
Text-to-speech stub for voice responses in Indian languages.

For MVP, TTS is not configured and this module always returns None.
When a TTS provider is integrated, implement the `generate` method
to call the provider's API, upload the audio, and return a public URL.

Supported future providers:
  - AI4Bharat Indic TTS (open source, supports ml/ta/hi)
  - Google Cloud Text-to-Speech
  - Azure Cognitive Services TTS
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


class TextToSpeech:
    """
    Generate voice responses in Indian languages.

    MVP implementation always returns None (TTS not configured).
    Replace `generate` with a real API call once a provider is chosen.
    """

    def __init__(self, provider: str | None = None) -> None:
        self._provider = provider
        if provider:
            logger.info("tts_initialized", provider=provider)
        else:
            logger.debug("tts_disabled_no_provider")

    @property
    def is_configured(self) -> bool:
        """True if a TTS provider is set up and ready to use."""
        return self._provider is not None

    async def generate(
        self,
        text: str,
        language: str,
        voice_id: str | None = None,
    ) -> str | None:
        """
        Generate speech from text and return a public URL to the audio file.

        Args:
            text:     Text to synthesise.
            language: ISO 639-1 code (ml, ta, en, …).
            voice_id: Optional provider-specific voice identifier.

        Returns:
            Public URL to the generated audio file, or None if TTS is not
            configured or generation fails.
        """
        if not self._provider:
            logger.debug("tts_skipped_not_configured")
            return None

        # Future implementation:
        # audio_bytes = await self._call_provider(text, language, voice_id)
        # url = await self._upload_audio(audio_bytes)
        # return url
        logger.warning("tts_generate_not_implemented", provider=self._provider)
        return None

    async def close(self) -> None:
        """Release any provider resources."""
        pass
