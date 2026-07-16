"""
Test voice transcription on a local audio file.

Usage:
    python -m scripts.test_voice_file --file path/to/voice.ogg
    python -m scripts.test_voice_file --file path/to/voice.m4a --language ml

Supports: .ogg, .mp3, .m4a, .wav, .webm

Output:
- Raw transcription (from Whisper)
- Detected language + confidence
- Detected dialect (if Malayalam/Tamil)
- Normalized text
- Claude tool-use response (if ANTHROPIC_API_KEY is set)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_MIME_TYPES = {
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}


def _get_mime_type(suffix: str) -> str:
    return _MIME_TYPES.get(suffix.lower(), "audio/ogg")


async def run(file_path: Path, language_hint: str | None) -> None:
    from src.config import get_settings
    from src.services.speech.transcriber import VoiceTranscriber

    settings = get_settings()

    if not settings.openai_api_key:
        print(
            "\nError: OPENAI_API_KEY is not set.\n"
            "Add it to your .env file — Whisper requires it for transcription.",
            file=sys.stderr,
        )
        sys.exit(1)

    # -- Read file -----------------------------------------------------------
    audio_bytes = file_path.read_bytes()
    mime_type = _get_mime_type(file_path.suffix)

    print(f"\n{'=' * 60}")
    print(f"FILE: {file_path.name}")
    print(f"SIZE: {len(audio_bytes) / 1024:.1f} KB")
    print(f"MIME: {mime_type}")
    if language_hint:
        print(f"HINT: language={language_hint}")
    print(f"{'=' * 60}")

    # -- Step 1: Transcribe --------------------------------------------------
    print("\n🎤 Transcribing with Whisper...")
    transcriber = VoiceTranscriber()
    result = await transcriber.transcribe(
        audio_bytes=audio_bytes,
        mime_type=mime_type,
        language_hint=language_hint,
    )

    print(f"\n📝 RAW TRANSCRIPTION:")
    print(f"   {result.raw_text}")

    print(f"\n🌐 LANGUAGE: {result.language}")
    print(f"   Confidence: {result.transcription_confidence:.0%}")
    if result.duration_seconds:
        print(f"   Duration:   {result.duration_seconds:.1f}s")
    if result.word_count:
        print(f"   Words:      {result.word_count}")

    # -- Step 2: Dialect -----------------------------------------------------
    if result.dialect:
        print(f"\n🗣️  DIALECT DETECTED:")
        print(f"   Name: {result.dialect}")
        print(f"   Confidence: {result.dialect_confidence:.0%}")
    else:
        print(f"\n🗣️  DIALECT: Not detected (or not Malayalam/Tamil)")

    # -- Step 3: Normalized text ---------------------------------------------
    print(f"\n✨ NORMALIZED TEXT:")
    if result.text != result.raw_text:
        print(f"   {result.text}")
    else:
        print(f"   (same as raw)")

    # -- Step 4: Claude tool-use response (requires Claude) ------------------
    if not settings.anthropic_api_key:
        print(f"\n⚠️  Skipping AI response (ANTHROPIC_API_KEY not set)")
        print(f"\n{'=' * 60}\n")
        return

    from src.services.ai.claude_client import ClaudeClient
    from src.services.ai.prompts.system import build_system_prompt
    from src.services.ai.response_generator import DEFAULT_STORE_CONFIG
    from src.services.ai.tools import TOOLS

    claude_client = ClaudeClient()

    # Stub tool executor for testing without DB
    class StubToolExecutor:
        async def execute(self, tool_name: str, tool_input: dict) -> str:
            print(f"\n   [Tool: {tool_name}({json.dumps(tool_input)})]")
            if tool_name == "search_products":
                return json.dumps({
                    "products": [
                        {"name": "Sample Kasavu Saree", "sku": "DMB-001",
                         "price": 8500, "in_stock": True},
                    ]
                })
            elif tool_name == "escalate_to_human":
                return json.dumps({"status": "escalation_requested"})
            return json.dumps({"message": "Stub response"})

    try:
        print(f"\n🧠 CLAUDE TOOL-USE RESPONSE...")
        system_prompt = build_system_prompt(
            store_config=DEFAULT_STORE_CONFIG,
            language=result.language,
            dialect=result.dialect,
        )

        ai_result = await claude_client.complete_with_tools(
            system=system_prompt,
            messages=[{"role": "user", "content": result.text}],
            tools=TOOLS,
            tool_executor=StubToolExecutor(),
        )

        print(f"\n   Tool calls: {len(ai_result.tool_calls_log)}")
        for call in ai_result.tool_calls_log:
            print(f"     - {call.tool_name}")
        if ai_result.escalated:
            print(f"   [Escalated: {ai_result.escalation_reason}]")

        print(f"\n💬 RESPONSE:")
        print(f"   {ai_result.response_text}")

    finally:
        await claude_client.close()

    print(f"\n{'=' * 60}\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Test voice transcription on a local audio file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--file",
        required=True,
        metavar="PATH",
        help="Path to audio file (.ogg, .mp3, .m4a, .wav, .webm)",
    )
    p.add_argument(
        "--language",
        default=None,
        metavar="LANG",
        help="Optional language hint for Whisper (ml, ta, en). Omit to auto-detect.",
    )
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: file not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    if file_path.suffix.lower() not in _MIME_TYPES:
        supported = ", ".join(_MIME_TYPES)
        print(f"Error: unsupported format '{file_path.suffix}'. Supported: {supported}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run(file_path, args.language))


if __name__ == "__main__":
    main()
