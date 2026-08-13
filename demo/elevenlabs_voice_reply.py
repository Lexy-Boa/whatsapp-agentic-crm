"""Give Avni a voice: render CRM reply text as a spoken voice note via ElevenLabs.

The production pipeline hears Malayalam (Whisper large-v3 transcription) but
replies in text. This demo closes the loop: the same reply text comes back as
a voice note in the customer's language, rendered by ElevenLabs `eleven_v3`
(one of the few TTS models that speaks Malayalam).

Usage:
    export ELEVENLABS_API_KEY=...            # never committed; see .env.example
    python demo/elevenlabs_voice_reply.py --demo          # regenerate the 3 committed samples
    python demo/elevenlabs_voice_reply.py "any reply text" -o demo/audio/out.mp3

Voice: "Bella" (professional, warm) — picked by native-speaker ear test
across three candidates; Malayalam judged ~90% natural by a Malayalam speaker.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("elevenlabs_demo")

API_BASE = "https://api.elevenlabs.io/v1"
MODEL_ID = "eleven_v3"
DEFAULT_VOICE_ID = "hpp4J3VqNfWAUOO0d1Us"  # Bella
AUDIO_DIR = Path(__file__).parent / "audio"

DEMO_SAMPLES = {
    # Product availability answer, Malayalam — the reply Avni sends when a
    # customer voice-notes "is that kasavu saree in stock?"
    "reply-malayalam.mp3": (
        "നമസ്കാരം! നിങ്ങൾ ചോദിച്ച കസവ് സാരി ഇപ്പോൾ സ്റ്റോക്കിൽ ഉണ്ട്. "
        "വേണമെങ്കിൽ ഓർഡർ ചെയ്യാൻ ഞാൻ സഹായിക്കാം."
    ),
    # Order status, English.
    "reply-english.mp3": (
        "Hi! Good news, your order was shipped yesterday and should reach you "
        "by Saturday. I will send you the tracking link right away."
    ),
    # Manglish code-switch — how Kerala actually texts.
    "reply-manglish.mp3": (
        "Chechi, aa kasavu saree stockil undu! Price 2,450 rupees aanu. "
        "Vendengil njan ippol thanne order cheyyam, COD option um undu, ketto!"
    ),
}


class TTSError(Exception):
    """ElevenLabs TTS call failed after retries."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in (429, 500, 502, 503, 504)
    )


@retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, max=10),
    reraise=True,
)
def synthesize(text: str, voice_id: str = DEFAULT_VOICE_ID) -> bytes:
    """Render `text` to MP3 bytes. Language is auto-detected from the text."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise TTSError("ELEVENLABS_API_KEY is not set (see .env.example)")

    response = httpx.post(
        f"{API_BASE}/text-to-speech/{voice_id}",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": api_key},
        json={"text": text, "model_id": MODEL_ID},
        timeout=120,
    )
    response.raise_for_status()
    return response.content


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("text", nargs="?", help="reply text to speak")
    parser.add_argument("-o", "--out", default=str(AUDIO_DIR / "reply.mp3"))
    parser.add_argument("--voice", default=DEFAULT_VOICE_ID, help="ElevenLabs voice_id")
    parser.add_argument("--demo", action="store_true", help="regenerate the 3 committed samples")
    args = parser.parse_args()

    jobs = (
        {name: text for name, text in DEMO_SAMPLES.items()}
        if args.demo
        else {Path(args.out).name: args.text}
    )
    if not args.demo and not args.text:
        parser.error("pass reply text, or use --demo")

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in jobs.items():
        out_path = AUDIO_DIR / name if args.demo else Path(args.out)
        try:
            audio = synthesize(text, voice_id=args.voice)
        except (httpx.HTTPError, TTSError) as exc:
            log.error("TTS failed for %s: %s", name, exc)
            return 1
        out_path.write_bytes(audio)
        log.info("wrote %s (%d bytes)", out_path, len(audio))
    return 0


if __name__ == "__main__":
    sys.exit(main())
