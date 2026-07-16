"""
End-to-end pipeline test against live services.

Runs the ConversationOrchestrator with live DB, Redis, Qdrant, and AI APIs
for a single message. This is useful for validating the DemoBoutique demo
flows without going through the webhook.

Requires all services running (docker compose up -d) and a valid .env.

Examples:
    python -m scripts.test_full_pipeline \
        --store-id <uuid> \
        --phone "+919876543210" \
        --message "looking for a kasavu saree under 10000"

    python -m scripts.test_full_pipeline \
        --store-id <uuid> \
        --phone "+919876543210" \
        --voice-file test_audio/test1.ogg
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


async def run(
    *,
    store_id: uuid.UUID,
    phone: str,
    message: str | None,
    voice_file: Path | None,
    mime_type: str,
) -> None:
    from src.config import get_settings
    from src.core.orchestrator import ConversationOrchestrator
    from src.core.product_matcher import ProductMatcher
    from src.db.postgres import close_db, get_session, init_db
    from src.db.redis_client import close_redis, init_redis
    from src.db.repositories.conversation_repo import ConversationRepository
    from src.db.repositories.customer_repo import CustomerRepository
    from src.db.repositories.handoff_repo import HandoffRepository
    from src.db.repositories.message_repo import MessageRepository
    from src.db.repositories.product_repo import ProductRepository
    from src.db.vector_store import VectorStore
    from src.services.ai.claude_client import ClaudeClient
    from src.services.ai.embeddings import EmbeddingService
    from src.services.ai.response_generator import DEFAULT_STORE_CONFIG
    from src.services.ai.tool_executor import ToolExecutor
    from src.services.speech.transcriber import VoiceTranscriber
    from src.services.whatsapp.client import WhatsAppClient

    settings = get_settings()

    missing = []
    if not settings.anthropic_api_key:
        missing.append("ANTHROPIC_API_KEY")
    if not settings.openai_api_key:
        missing.append("OPENAI_API_KEY")
    if voice_file and not settings.groq_api_key.get_secret_value():
        missing.append("GROQ_API_KEY")

    if missing:
        print(
            f"\nError: missing required environment variables: {', '.join(missing)}\n"
            "Add them to your .env file.",
            file=sys.stderr,
        )
        sys.exit(1)

    mode = "voice" if voice_file else "text"
    print(f"\n{'=' * 65}")
    print("FULL PIPELINE - end-to-end orchestrator test")
    print(f"{'=' * 65}")
    print(f"Store ID  : {store_id}")
    print(f"Phone     : {phone}")
    print(f"Mode      : {mode}")
    if message is not None:
        print(f"Message   : {message}")
    if voice_file is not None:
        print(f"Voice file: {voice_file}")
        print(f"MIME type : {mime_type}")
    print(f"Model     : {settings.claude_model}")

    media_bytes = voice_file.read_bytes() if voice_file else None

    print("\nInitializing infrastructure...")
    await init_db()
    await init_redis()

    vector_store = VectorStore()
    await vector_store.initialize()

    claude_client = ClaudeClient()
    whatsapp_client = WhatsAppClient(
        access_token=settings.whatsapp_access_token,
        phone_number_id=settings.whatsapp_phone_number_id,
    )
    transcriber = VoiceTranscriber()
    embedding_service = EmbeddingService()

    try:
        async for session in get_session():
            product_repo = ProductRepository(session)
            customer_repo = CustomerRepository(session)
            conversation_repo = ConversationRepository(session)
            message_repo = MessageRepository(session)
            handoff_repo = HandoffRepository(session)

            product_matcher = ProductMatcher(
                embedding_service=embedding_service,
                vector_store=vector_store,
                product_repo=product_repo,
            )
            tool_executor = ToolExecutor(
                product_matcher=product_matcher,
                product_repo=product_repo,
                store_id=store_id,
            )

            orchestrator = ConversationOrchestrator(
                store_id=store_id,
                store_config=DEFAULT_STORE_CONFIG,
                whatsapp_client=whatsapp_client,
                transcriber=transcriber,
                claude_client=claude_client,
                tool_executor=tool_executor,
                tts=None,
                customer_repo=customer_repo,
                conversation_repo=conversation_repo,
                message_repo=message_repo,
                handoff_repo=handoff_repo,
            )

            print("\nProcessing message...")
            result = await orchestrator.process_message(
                customer_phone=phone.lstrip("+"),
                message_type="voice" if voice_file else "text",
                content=message,
                media_bytes=media_bytes,
                media_mime_type=mime_type if voice_file else None,
            )

        print(f"\n-- Result {'-' * 54}")
        status = "success" if result.success else "failed"
        print(f"  Status           : {status}")
        print(f"  Response sent    : {result.response_sent}")
        print(f"  Response type    : {result.response_type}")
        print(f"  Handoff created  : {result.handoff_created}")
        if result.handoff_id:
            print(f"  Handoff ID       : {result.handoff_id}")
        print(f"  Total time       : {result.total_time_ms} ms")
        if result.transcription_time_ms is not None:
            print(f"  Transcription    : {result.transcription_time_ms} ms")
        if result.ai_time_ms is not None:
            print(f"  AI time          : {result.ai_time_ms} ms")
        if result.response_text:
            print("\n  Response text:")
            print(f"  {result.response_text}")
        if result.error:
            print(f"\n  Error: {result.error}", file=sys.stderr)
        print()

        if not result.success:
            sys.exit(1)

    finally:
        await claude_client.close()
        await whatsapp_client.close()
        await close_db()
        await close_redis()
        await vector_store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the full orchestrator pipeline against live services.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--store-id",
        required=True,
        metavar="UUID",
        help="Store UUID (must exist in the database).",
    )
    parser.add_argument(
        "--phone",
        required=True,
        metavar="PHONE",
        help='Customer phone number (for example "+919876543210").',
    )
    parser.add_argument(
        "--message",
        metavar="TEXT",
        help="Message text to send through the pipeline.",
    )
    parser.add_argument(
        "--voice-file",
        type=Path,
        metavar="PATH",
        help="Optional local audio file to process as a voice note.",
    )
    parser.add_argument(
        "--mime-type",
        default="audio/ogg",
        metavar="MIME",
        help="MIME type for --voice-file. Defaults to audio/ogg.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        store_id = uuid.UUID(args.store_id)
    except ValueError:
        print(f"Error: '{args.store_id}' is not a valid UUID.", file=sys.stderr)
        sys.exit(1)

    if not args.message and not args.voice_file:
        parser.error("Provide either --message or --voice-file.")
    if args.message and args.voice_file:
        parser.error("Use only one of --message or --voice-file per run.")
    if args.voice_file and not args.voice_file.exists():
        parser.error(f"Voice file not found: {args.voice_file}")

    asyncio.run(
        run(
            store_id=store_id,
            phone=args.phone,
            message=args.message,
            voice_file=args.voice_file,
            mime_type=args.mime_type,
        )
    )


if __name__ == "__main__":
    main()
