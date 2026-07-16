"""
Test the transcription pipeline from the command line.

Text mode  — skips Whisper, tests dialect detection + normalization only
             (no OpenAI API key required):
    python scripts/test_transcription.py --text "എന്തിനാ ഈ സാരി" --language ml
    python -m scripts.test_transcription --text "மச்சி டா" --language ta

Audio mode — full pipeline including Whisper API call
             (requires OPENAI_API_KEY in environment / .env):
    python scripts/test_transcription.py --audio /path/to/voice.ogg
    python -m scripts.test_transcription --audio /tmp/voice.ogg --language ml
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Make sure the project root is on sys.path when run directly
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


async def run_text_mode(text: str, language: str) -> None:
    """Dialect detection + normalization only — no Whisper call."""
    from src.services.speech.dialect_detector import DialectDetector
    from src.services.speech.normalizer import DialectNormalizer

    print(f"\n{'─' * 60}")
    print("TEXT MODE — dialect detection + normalization")
    print(f"{'─' * 60}")
    print(f"Input text : {text}")
    print(f"Language   : {language}")

    detector = DialectDetector()
    normalizer = DialectNormalizer()

    dialect_info = await detector.detect(text, language)
    dialect_name = dialect_info.name if dialect_info else None

    normalized = normalizer.normalize(text, language, dialect_name)

    print(f"\n── Dialect Detection ─────────────────────────────────")
    if dialect_info:
        print(f"  Dialect    : {dialect_info.name}")
        print(f"  Region     : {dialect_info.region}")
        print(f"  Confidence : {dialect_info.confidence:.2%}")
        print(f"  Formality  : {dialect_info.formality}")
        print(f"  Markers    : {', '.join(dialect_info.markers_found)}")
    else:
        print("  No dialect detected (below threshold or language not supported)")

    print(f"\n── Normalization ─────────────────────────────────────")
    if normalized != text:
        print(f"  Original   : {text}")
        print(f"  Normalized : {normalized}")
    else:
        print("  No changes (text already in canonical form)")

    print()


async def run_audio_mode(audio_path: str, language_hint: str | None) -> None:
    """Full pipeline: Whisper → dialect detection → normalization."""
    path = Path(audio_path)
    if not path.exists():
        print(f"Error: file not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    # Infer MIME type from extension
    _EXT_TO_MIME = {
        ".ogg": "audio/ogg",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".webm": "audio/webm",
        ".flac": "audio/flac",
        ".aac": "audio/aac",
    }
    mime_type = _EXT_TO_MIME.get(path.suffix.lower(), "audio/ogg")

    print(f"\n{'─' * 60}")
    print("AUDIO MODE — full Whisper transcription pipeline")
    print(f"{'─' * 60}")
    print(f"File       : {audio_path}")
    print(f"MIME type  : {mime_type}")
    print(f"Language   : {language_hint or 'auto-detect'}")
    print(f"Calling Whisper API…")

    from src.services.speech.transcriber import VoiceTranscriber

    audio_bytes = path.read_bytes()

    transcriber = VoiceTranscriber()
    result = await transcriber.transcribe(
        audio_bytes=audio_bytes,
        mime_type=mime_type,
        language_hint=language_hint,
    )

    print(f"\n── Transcription Result ──────────────────────────────")
    print(f"  Text (normalized)   : {result.text}")
    print(f"  Text (raw Whisper)  : {result.raw_text}")
    print(f"  Language            : {result.language}")
    print(f"  Dialect             : {result.dialect or 'none'}")
    print(f"  Dialect confidence  : {result.dialect_confidence:.2%}")
    print(f"  Transcr. confidence : {result.transcription_confidence:.2%}")
    print(f"  Duration            : {result.duration_seconds:.1f}s")
    print(f"  Word count          : {result.word_count}")
    print()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Test the voice transcription pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--text",
        metavar="TEXT",
        help="Run dialect detection + normalization on TEXT (no API call).",
    )
    mode.add_argument(
        "--audio",
        metavar="FILE",
        help="Transcribe an audio file using the full Whisper pipeline.",
    )
    p.add_argument(
        "--language",
        metavar="LANG",
        default=None,
        help="ISO 639-1 language code hint (e.g. ml, ta, en). Optional.",
    )
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.text:
        if not args.language:
            parser.error("--language is required in text mode (e.g. --language ml)")
        asyncio.run(run_text_mode(args.text, args.language))
    else:
        asyncio.run(run_audio_mode(args.audio, args.language))


if __name__ == "__main__":
    main()
