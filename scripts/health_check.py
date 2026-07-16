"""
Verify all services and connections.

Usage:
    python -m scripts.health_check                          # Check all
    python -m scripts.health_check --db                     # Database only
    python -m scripts.health_check --redis                  # Redis only
    python -m scripts.health_check --qdrant                 # Qdrant only
    python -m scripts.health_check --claude                 # Claude API only
    python -m scripts.health_check --whisper                # Speech provider only
    python -m scripts.health_check --shopify                # Shopify (uses .env vars)
    python -m scripts.health_check --whatsapp               # WhatsApp API only
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

OK = "[OK]"
FAIL = "[FAIL]"

passed = 0
failed = 0


def report(label: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    icon = OK if ok else FAIL
    suffix = f" ({detail})" if detail else ""
    print(f"  {icon} {label}{suffix}")
    if ok:
        passed += 1
    else:
        failed += 1


async def check_db() -> None:
    from src.db.postgres import check_db_health, close_db, init_db

    try:
        await init_db()
        ok = await check_db_health()
        report("PostgreSQL", ok, "ping OK" if ok else "connection failed")
    except Exception as exc:
        report("PostgreSQL", False, str(exc))
    finally:
        try:
            await close_db()
        except Exception:
            pass


async def check_redis() -> None:
    from src.db.redis_client import check_redis_health, close_redis, init_redis

    try:
        await init_redis()
        ok = await check_redis_health()
        report("Redis", ok, "ping OK" if ok else "connection failed")
    except Exception as exc:
        report("Redis", False, str(exc))
    finally:
        try:
            await close_redis()
        except Exception:
            pass


async def check_qdrant() -> None:
    from src.config import get_settings
    from src.db.vector_store import VectorStore

    settings = get_settings()
    vector_store = VectorStore()
    try:
        await vector_store.initialize()
        client = vector_store._client  # type: ignore[attr-defined]
        collections = await client.get_collections()
        names = [c.name for c in collections.collections]
        collection = settings.qdrant_collection
        if collection in names:
            info = await client.get_collection(collection)
            count = info.vectors_count or 0
            report("Qdrant", True, f"collection '{collection}': {count} vectors")
        else:
            report("Qdrant", True, f"connected (collection '{collection}' not yet created)")
    except Exception as exc:
        report("Qdrant", False, str(exc))
    finally:
        try:
            await vector_store.close()
        except Exception:
            pass


async def check_claude() -> None:
    from src.config import get_settings

    settings = get_settings()
    if not settings.anthropic_api_key:
        report("Claude API", False, "ANTHROPIC_API_KEY not set")
        return

    try:
        from src.services.ai.claude_client import ClaudeClient

        client = ClaudeClient()
        result = await client.complete(
            system="You are a test assistant.",
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=10,
        )
        ok = bool(result and len(result) > 0)
        report("Claude API", ok, f"model={settings.claude_model}" if ok else "empty response")
        await client.close()
    except Exception as exc:
        report("Claude API", False, str(exc))


async def check_whisper() -> None:
    from src.config import get_settings

    settings = get_settings()
    provider = settings.whisper_provider.lower()

    if provider == "groq":
        api_key = settings.groq_api_key.get_secret_value()
        if not api_key:
            report("Speech Provider", False, "GROQ_API_KEY not set")
            return
        try:
            from groq import AsyncGroq

            client = AsyncGroq(api_key=api_key)
            models = await client.models.list()
            ok = any(settings.whisper_model in model.id for model in models.data)
            detail = (
                f"provider=groq, model={settings.whisper_model}"
                if ok
                else f"provider=groq, model={settings.whisper_model} not found"
            )
            report("Speech Provider", ok, detail)
        except Exception as exc:
            report("Speech Provider", False, str(exc))
        return

    if provider == "openai":
        if not settings.openai_api_key:
            report("Speech Provider", False, "OPENAI_API_KEY not set")
            return
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            models = await client.models.list()
            ok = any("whisper" in model.id for model in models.data)
            detail = (
                f"provider=openai, model={settings.whisper_model}"
                if ok
                else "provider=openai, whisper model not found"
            )
            report("Speech Provider", ok, detail)
            await client.close()
        except Exception as exc:
            report("Speech Provider", False, str(exc))
        return

    report("Speech Provider", False, f"unsupported provider '{settings.whisper_provider}'")


async def check_shopify() -> None:
    from src.config import get_settings

    settings = get_settings()
    shop_domain = getattr(settings, "shopify_shop_domain", "") or os.environ.get(
        "SHOPIFY_SHOP_DOMAIN", ""
    )
    access_token = getattr(settings, "shopify_access_token", "") or os.environ.get(
        "SHOPIFY_ACCESS_TOKEN", ""
    )

    if not shop_domain or not access_token:
        report("Shopify", False, "SHOPIFY_SHOP_DOMAIN or SHOPIFY_ACCESS_TOKEN not set")
        return

    try:
        from src.services.shopify.client import ShopifyClient

        client = ShopifyClient(shop_domain=shop_domain, access_token=access_token)
        products = await client.get_products(limit=1)
        report("Shopify", True, f"shop={shop_domain}, at least {len(products)} product(s)")
        await client.close()
    except Exception as exc:
        report("Shopify", False, str(exc))


async def check_whatsapp() -> None:
    from src.config import get_settings

    settings = get_settings()
    if not settings.whatsapp_access_token:
        report("WhatsApp Cloud API", False, "WHATSAPP_ACCESS_TOKEN not set")
        return
    if not settings.whatsapp_phone_number_id:
        report("WhatsApp Cloud API", False, "WHATSAPP_PHONE_NUMBER_ID not set")
        return

    try:
        import httpx

        url = f"https://graph.facebook.com/v22.0/{settings.whatsapp_phone_number_id}"
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
            timeout=10.0,
        ) as client:
            response = await client.get(url)
            ok = response.status_code == 200
            detail = (
                "Cloud API reachable"
                if ok
                else f"HTTP {response.status_code}"
            )
            report("WhatsApp Cloud API", ok, detail)
    except Exception as exc:
        report("WhatsApp Cloud API", False, str(exc))


async def run_checks(args: argparse.Namespace) -> None:
    run_all = not any(
        [
            args.db,
            args.redis,
            args.qdrant,
            args.claude,
            args.whisper,
            args.shopify,
            args.whatsapp,
        ]
    )

    print("\n" + ("-" * 55))
    print("  WhatsApp CRM - Health Check")
    print("-" * 55)

    if run_all or args.db:
        await check_db()
    if run_all or args.redis:
        await check_redis()
    if run_all or args.qdrant:
        await check_qdrant()
    if run_all or args.claude:
        await check_claude()
    if run_all or args.whisper:
        await check_whisper()
    if run_all or args.shopify:
        await check_shopify()
    if run_all or args.whatsapp:
        await check_whatsapp()

    total = passed + failed
    print("-" * 55)
    if failed == 0:
        print(f"  All {total} checks passed.")
    else:
        print(f"  {passed}/{total} passed - {failed} failed")
    print()

    if failed > 0:
        sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify all services and connections.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--db", action="store_true", help="Check PostgreSQL only")
    parser.add_argument("--redis", action="store_true", help="Check Redis only")
    parser.add_argument("--qdrant", action="store_true", help="Check Qdrant only")
    parser.add_argument("--claude", action="store_true", help="Check Claude API only")
    parser.add_argument("--whisper", action="store_true", help="Check speech provider only")
    parser.add_argument(
        "--shopify", action="store_true", help="Check Shopify connection (uses .env)"
    )
    parser.add_argument("--whatsapp", action="store_true", help="Check WhatsApp API only")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run_checks(args))


if __name__ == "__main__":
    main()
