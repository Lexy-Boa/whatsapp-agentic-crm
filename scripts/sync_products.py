"""
Sync products from Shopify to the local database and Qdrant vector store.

Usage:
    # Real Shopify sync (requires SHOPIFY_SHOP_DOMAIN + SHOPIFY_ACCESS_TOKEN in .env)
    python -m scripts.sync_products --store-id <uuid>

    # Mock sync from the DemoBoutique demo catalog (no Shopify credentials needed)
    python -m scripts.sync_products --store-id <uuid> --mock

    # Force full re-sync (re-embeds all products)
    python -m scripts.sync_products --store-id <uuid> --full
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


async def run_mock_sync(store_id: uuid.UUID) -> None:
    """Insert the demo mock catalog into DB, with optional Qdrant embeddings."""
    from src.config import get_settings
    from src.db.postgres import close_db, get_session, init_db
    from src.db.repositories.product_repo import ProductRepository
    from src.db.vector_store import VectorStore
    from src.services.ai.embeddings import EmbeddingService

    settings = get_settings()

    fixtures_path = _PROJECT_ROOT / "data" / "demo" / "demoboutique_mock_catalog.json"
    if not fixtures_path.exists():
        fixtures_path = _PROJECT_ROOT / "tests" / "fixtures" / "sample_products.json"
    if not fixtures_path.exists():
        print(f"Error: fixtures not found at {fixtures_path}", file=sys.stderr)
        sys.exit(1)

    with open(fixtures_path, encoding="utf-8") as f:
        fixtures: list[dict] = json.load(f)

    print(f"\n{'=' * 60}")
    print(f"MOCK SYNC - {len(fixtures)} products from mock catalog")
    print(f"{'=' * 60}")
    print(f"Store ID : {store_id}")

    await init_db()
    vector_store: VectorStore | None = None
    embedding_service: EmbeddingService | None = None
    if settings.openai_api_key:
        vector_store = VectorStore()
        await vector_store.initialize()
        embedding_service = EmbeddingService()
    else:
        print(
            "  [warn   ] OPENAI_API_KEY not set - seeding Postgres only; semantic search disabled.",
            file=sys.stderr,
        )

    created = updated = errors = 0

    async for session in get_session():
        repo = ProductRepository(session)

        for fixture in fixtures:
            try:
                data = {
                    "shopify_id": fixture["shopify_product_id"],
                    "store_id": store_id,
                    "sku": fixture["sku"],
                    "name": fixture["name"],
                    "description": fixture.get("description"),
                    "category": fixture.get("category", "general"),
                    "base_price": float(fixture["price"]),
                    "images": [],
                    "tags": fixture.get("occasions", []),
                    "occasions": fixture.get("occasions", []),
                    "is_active": True,
                }
                product, was_created = await repo.upsert(data)
                await repo.upsert_variant(
                    product_id=product.id,
                    sku=product.sku,
                    size="Free Size",
                    color=fixture.get("attributes", {}).get("color"),
                    fabric=fixture.get("attributes", {}).get("fabric"),
                    stock_quantity=int(fixture.get("inventory_quantity", 0)),
                )

                if embedding_service and vector_store:
                    try:
                        embedding = await embedding_service.embed_product(product)
                        await vector_store.upsert_product(
                            product_id=str(product.id),
                            store_id=str(store_id),
                            embedding=embedding,
                            metadata={
                                "name": product.name,
                                "sku": product.sku,
                                "price": float(product.base_price),
                                "category": product.category,
                                "occasions": product.occasions or [],
                            },
                        )
                    except Exception as exc:
                        print(
                            f"  [warn   ] {product.sku} - embedding skipped ({exc})",
                            file=sys.stderr,
                        )

                status = "created" if was_created else "updated"
                print(f"  [{status:7}] {product.sku} - {product.name}")
                if was_created:
                    created += 1
                else:
                    updated += 1

            except Exception as exc:
                print(f"  [error  ] {fixture.get('sku', '?')} - {exc}", file=sys.stderr)
                errors += 1

        await session.commit()

    await close_db()
    if vector_store:
        await vector_store.close()

    print(f"\n{'=' * 24} Result {'=' * 24}")
    print(f"  Created  : {created}")
    print(f"  Updated  : {updated}")
    print(f"  Errors   : {errors}")
    print()


async def run_shopify_sync(store_id: uuid.UUID) -> None:
    """Full Shopify sync using configured credentials."""
    from src.config import get_settings
    from src.db.postgres import close_db, get_session, init_db
    from src.db.vector_store import VectorStore
    from src.services.ai.embeddings import EmbeddingService
    from src.services.shopify.client import ShopifyClient
    from src.services.shopify.product_sync import ProductSyncService

    settings = get_settings()

    shop_domain = getattr(settings, "shopify_shop_domain", "") or ""
    access_token = getattr(settings, "shopify_access_token", "") or ""

    if not shop_domain or not access_token:
        print(
            "\nError: SHOPIFY_SHOP_DOMAIN and SHOPIFY_ACCESS_TOKEN must be set in .env\n"
            "       Use --mock for testing without Shopify credentials.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not settings.openai_api_key:
        print("Error: OPENAI_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print("SHOPIFY SYNC")
    print(f"{'=' * 60}")
    print(f"Store ID  : {store_id}")
    print(f"Shop      : {shop_domain}")

    await init_db()
    shopify_client = ShopifyClient(shop_domain=shop_domain, access_token=access_token)
    vector_store = VectorStore()
    await vector_store.initialize()
    embedding_service = EmbeddingService()

    async for session in get_session():
        sync_service = ProductSyncService(
            shopify_client=shopify_client,
            embedding_service=embedding_service,
            vector_store=vector_store,
            session=session,
        )
        print("Syncing...")
        result = await sync_service.sync_all_products(store_id)

        print(f"\n{'=' * 22} Sync Result {'=' * 22}")
        print(f"  Total    : {result.total_products}")
        print(f"  Created  : {result.created}")
        print(f"  Updated  : {result.updated}")
        print(f"  Errors   : {result.errors}")
        print(f"  Duration : {result.duration_seconds:.1f}s")
        print()

    await shopify_client.close()
    await close_db()
    await vector_store.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Sync products from Shopify to DB + Qdrant.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--store-id",
        required=True,
        metavar="UUID",
        help="Store UUID to associate products with.",
    )
    p.add_argument(
        "--mock",
        action="store_true",
        help="Use the demo mock catalog instead of real Shopify.",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="Force full re-sync (re-embeds all products).",
    )
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        store_id = uuid.UUID(args.store_id)
    except ValueError:
        parser.error(f"Invalid UUID: {args.store_id}")

    if args.mock:
        asyncio.run(run_mock_sync(store_id))
    else:
        asyncio.run(run_shopify_sync(store_id))


if __name__ == "__main__":
    main()
