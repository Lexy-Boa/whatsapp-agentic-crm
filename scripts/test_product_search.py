"""
Test product matching end-to-end against live DB + Qdrant.

Requires:
  - DB populated (run sync_products.py --mock first)
  - Qdrant running with embeddings
  - OPENAI_API_KEY in .env

Usage:
    python -m scripts.test_product_search --store-id <uuid> --query "kasavu saree"
    python -m scripts.test_product_search --store-id <uuid> --query "red silk saree for wedding"
    python -m scripts.test_product_search --store-id <uuid> --query "DMB-2341"
    python -m scripts.test_product_search --store-id <uuid> \\
        --query "wedding saree" --price-min 5000 --price-max 20000
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
    store_id: uuid.UUID,
    query_text: str,
    price_min: float | None,
    price_max: float | None,
    occasion: str | None,
    limit: int,
) -> None:
    from src.config import get_settings
    from src.core.product_matcher import MatchQuery, ProductMatcher
    from src.db.postgres import init_db, close_db, get_session
    from src.db.repositories.product_repo import ProductRepository
    from src.db.vector_store import VectorStore
    from src.services.ai.embeddings import EmbeddingService

    settings = get_settings()
    if not settings.openai_api_key:
        print("Error: OPENAI_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'─' * 60}")
    print("PRODUCT SEARCH TEST")
    print(f"{'─' * 60}")
    print(f"Store ID  : {store_id}")
    print(f"Query     : {query_text}")
    if price_min is not None or price_max is not None:
        lo = f"₹{price_min:,.0f}" if price_min is not None else "any"
        hi = f"₹{price_max:,.0f}" if price_max is not None else "any"
        print(f"Price     : {lo} – {hi}")
    if occasion:
        print(f"Occasion  : {occasion}")
    print(f"Limit     : {limit}")

    price_range = None
    if price_min is not None and price_max is not None:
        price_range = (price_min, price_max)
    elif price_min is not None:
        price_range = (price_min, 999_999.0)
    elif price_max is not None:
        price_range = (0.0, price_max)

    query = MatchQuery(
        text=query_text,
        price_range=price_range,
        occasion=occasion,
    )

    await init_db()
    vector_store = VectorStore()
    await vector_store.initialize()
    embedding_service = EmbeddingService()

    async for session in get_session():
        repo = ProductRepository(session)
        matcher = ProductMatcher(
            embedding_service=embedding_service,
            vector_store=vector_store,
            product_repo=repo,
        )

        print(f"\nSearching…")
        matches = await matcher.find_products(query, store_id, limit=limit)

        print(f"\n── Results ({len(matches)} found) ──────────────────────────────")
        if not matches:
            print("  No matching products found.")
        for i, match in enumerate(matches, 1):
            p = match.product
            print(f"\n  {i}. {p.name} ({p.sku})")
            print(f"     Match type : {match.match_type}")
            print(f"     Score      : {match.score:.3f}")
            print(f"     Price      : ₹{float(p.base_price):,.0f}")
            print(f"     Category   : {p.category}")
            if p.occasions:
                print(f"     Occasions  : {', '.join(p.occasions)}")
            if p.description:
                desc = p.description[:80] + "…" if len(p.description) > 80 else p.description
                print(f"     Desc       : {desc}")
        print()

    await close_db()
    await vector_store.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Test product search against live DB + Qdrant.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--store-id", required=True, metavar="UUID")
    p.add_argument("--query", required=True, metavar="TEXT")
    p.add_argument("--price-min", type=float, default=None, metavar="AMOUNT")
    p.add_argument("--price-max", type=float, default=None, metavar="AMOUNT")
    p.add_argument("--occasion", default=None, metavar="OCCASION")
    p.add_argument("--limit", type=int, default=5, metavar="N")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        store_id = uuid.UUID(args.store_id)
    except ValueError:
        parser.error(f"Invalid UUID: {args.store_id}")

    asyncio.run(
        run(
            store_id=store_id,
            query_text=args.query,
            price_min=args.price_min,
            price_max=args.price_max,
            occasion=args.occasion,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
