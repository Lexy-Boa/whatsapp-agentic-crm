"""
Create and initialize a new store.

Usage:
    python -m scripts.setup_store \\
        --name "DemoBoutique" \\
        --slug "demoboutique" \\
        --shopify-domain "demoboutique.myshopify.com" \\
        --shopify-token "shpat_xxxxx" \\
        --whatsapp-phone "+919876543210"

This will:
1. Generate a store UUID
2. Test Shopify connection
3. Sync all products from Shopify (with embeddings)
4. Test WhatsApp connection
5. Print the store UUID and .env snippet to add
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

_OK = "\033[92m✓\033[0m"
_FAIL = "\033[91m✗\033[0m"
_WARN = "\033[93m!\033[0m"


def _header(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def _ok(msg: str) -> None:
    print(f"  {_OK}  {msg}")


def _fail(msg: str) -> None:
    print(f"  {_FAIL}  {msg}", file=sys.stderr)


def _warn(msg: str) -> None:
    print(f"  {_WARN}  {msg}")


async def run(
    name: str,
    slug: str,
    shopify_domain: str,
    shopify_token: str,
    whatsapp_phone: str,
    store_id: uuid.UUID,
    skip_whatsapp: bool,
) -> None:
    from src.config import get_settings
    from src.db.postgres import close_db, get_session, init_db
    from src.db.vector_store import VectorStore
    from src.services.ai.embeddings import EmbeddingService
    from src.services.shopify.client import ShopifyClient
    from src.services.shopify.product_sync import ProductSyncService
    from src.services.whatsapp.client import WhatsAppClient

    settings = get_settings()
    errors: list[str] = []

    print(f"\n{'═' * 60}")
    print("  WhatsApp Fashion CRM — Store Setup")
    print(f"{'═' * 60}")
    print(f"  Store name   : {name}")
    print(f"  Store slug   : {slug}")
    print(f"  Store ID     : {store_id}")
    print(f"  Shopify shop : {shopify_domain}")
    print(f"  WhatsApp     : {whatsapp_phone}")

    # ── Step 1: Check OpenAI key ──────────────────────────────────────────
    _header("Step 1: Checking API keys")
    if not settings.openai_api_key:
        _fail("OPENAI_API_KEY is not set — required for product embeddings")
        errors.append("OPENAI_API_KEY missing")
    else:
        _ok("OPENAI_API_KEY found")

    if not settings.anthropic_api_key:
        _warn("ANTHROPIC_API_KEY is not set — AI responses will not work")
    else:
        _ok("ANTHROPIC_API_KEY found")

    if errors:
        print("\nFix the above errors and retry.")
        sys.exit(1)

    # ── Step 2: Init DB ───────────────────────────────────────────────────
    _header("Step 2: Initialising database")
    try:
        await init_db()
        _ok("PostgreSQL connected")
    except Exception as exc:
        _fail(f"Database connection failed: {exc}")
        sys.exit(1)

    # ── Step 3: Test Shopify connection ───────────────────────────────────
    _header("Step 3: Testing Shopify connection")
    shopify_client = ShopifyClient(
        shop_domain=shopify_domain,
        access_token=shopify_token,
    )
    shopify_ok = False
    product_count = 0
    try:
        products = await shopify_client.get_products(limit=10)
        product_count = len(products)
        _ok(f"Shopify connected — fetched {product_count} products (first page)")
        shopify_ok = True
    except Exception as exc:
        _fail(f"Shopify connection failed: {exc}")
        errors.append(f"Shopify: {exc}")
    finally:
        await shopify_client.close()

    # ── Step 4: Sync products ─────────────────────────────────────────────
    if shopify_ok:
        _header("Step 4: Syncing products from Shopify")
        shopify_client2 = ShopifyClient(
            shop_domain=shopify_domain,
            access_token=shopify_token,
        )
        vector_store = VectorStore()
        embedding_service = EmbeddingService()
        try:
            await vector_store.initialize()
            _ok("Qdrant vector store initialised")

            async for session in get_session():
                sync_service = ProductSyncService(
                    shopify_client=shopify_client2,
                    embedding_service=embedding_service,
                    vector_store=vector_store,
                    session=session,
                )
                result = await sync_service.sync_all_products(store_id)
                _ok(
                    f"Sync complete — {result.created} created, "
                    f"{result.updated} updated, {result.errors} errors "
                    f"({result.duration_seconds:.1f}s)"
                )
                break
        except Exception as exc:
            _fail(f"Product sync failed: {exc}")
            errors.append(f"Sync: {exc}")
        finally:
            await shopify_client2.close()
            await vector_store.close()
    else:
        _header("Step 4: Skipping product sync (Shopify connection failed)")

    # ── Step 5: Test WhatsApp connection ──────────────────────────────────
    _header("Step 5: Testing WhatsApp connection")
    if skip_whatsapp:
        _warn("Skipped (--skip-whatsapp flag set)")
    else:
        wa_token = settings.whatsapp_access_token
        if not wa_token:
            _warn("WHATSAPP_ACCESS_TOKEN not set in .env — skipping WhatsApp test")
        else:
            wa_client = WhatsAppClient(access_token=wa_token, phone_number_id=settings.whatsapp_phone_number_id)
            try:
                # Attempt to send a self-test (will succeed if key is valid even if not delivered)
                result = await wa_client.send_text(
                    whatsapp_phone.lstrip("+"),
                    f"Store setup test — {name} ({slug}) is ready! 🎉",
                )
                if result.success:
                    _ok(f"WhatsApp connected — test message sent to {whatsapp_phone}")
                else:
                    _warn(f"WhatsApp API key appears valid but send failed: {result.error}")
            except Exception as exc:
                _fail(f"WhatsApp connection failed: {exc}")
                errors.append(f"WhatsApp: {exc}")
            finally:
                await wa_client.close()

    # ── Cleanup ───────────────────────────────────────────────────────────
    await close_db()

    # ── Result ────────────────────────────────────────────────────────────
    print(f"\n{'═' * 60}")
    if errors:
        print("  Setup completed with errors:")
        for e in errors:
            print(f"    {_FAIL}  {e}")
    else:
        print("  Setup complete!")

    print(f"\n  Add this to your .env:")
    print(f"\n    STORE_ID={store_id}")
    print(f"\n{'═' * 60}\n")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Create and initialise a new store.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--name", required=True, help="Human-readable store name (e.g. 'DemoBoutique')")
    p.add_argument("--slug", required=True, help="URL-safe store slug (e.g. 'demoboutique')")
    p.add_argument("--shopify-domain", required=True, help="Shopify shop domain (e.g. store.myshopify.com)")
    p.add_argument("--shopify-token", required=True, help="Shopify Admin API access token (shpat_...)")
    p.add_argument("--whatsapp-phone", required=True, help="WhatsApp Business phone number (+91...)")
    p.add_argument(
        "--store-id",
        default=None,
        help="Reuse an existing store UUID (omit to generate a new one)",
    )
    p.add_argument(
        "--skip-whatsapp",
        action="store_true",
        help="Skip WhatsApp connection test",
    )
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.store_id:
        try:
            store_id = uuid.UUID(args.store_id)
        except ValueError:
            parser.error(f"Invalid UUID for --store-id: {args.store_id}")
    else:
        store_id = uuid.uuid4()

    asyncio.run(
        run(
            name=args.name,
            slug=args.slug,
            shopify_domain=args.shopify_domain,
            shopify_token=args.shopify_token,
            whatsapp_phone=args.whatsapp_phone,
            store_id=store_id,
            skip_whatsapp=args.skip_whatsapp,
        )
    )


if __name__ == "__main__":
    main()
