"""
Sync products from Shopify into the local database and Qdrant vector store.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.privacy import summarize_exception_for_operations
from src.db.repositories.product_repo import ProductRepository
from src.db.vector_store import VectorStore
from src.services.ai.embeddings import EmbeddingService
from src.services.shopify.client import ShopifyClient

logger = structlog.get_logger(__name__)

# Tags that indicate product occasions
_OCCASION_TAGS = frozenset({
    "wedding", "festival", "traditional", "casual", "formal",
    "party", "engagement", "puja", "onam", "vishu", "christmas",
    "eid", "diwali", "anniversary",
})

# Simple HTML tag stripper
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class SyncResult:
    total_products: int
    created: int
    updated: int
    errors: int
    duration_seconds: float


def _strip_html(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = _HTML_TAG_RE.sub(" ", html)
    return " ".join(text.split())


def _shopify_to_product_data(shopify_product: dict, store_id: uuid.UUID) -> dict:
    """
    Map a raw Shopify product dict to our Product model field dict.

    Fields mapped:
      - shopify_id  ← Shopify product.id
      - sku         ← first variant's SKU (or product handle as fallback)
      - name        ← title
      - description ← body_html (HTML stripped)
      - category    ← product_type (defaults to "general")
      - base_price  ← first variant price
      - images      ← list of image src URLs
      - tags        ← comma-separated tags → list
      - occasions   ← tags that match _OCCASION_TAGS
      - store_id    ← passed in
    """
    variants = shopify_product.get("variants") or []
    first_variant = variants[0] if variants else {}

    # Price
    try:
        base_price = float(first_variant.get("price", 0) or 0)
    except (ValueError, TypeError):
        base_price = 0.0

    # SKU
    sku = (first_variant.get("sku") or "").strip()
    if not sku:
        sku = shopify_product.get("handle", "") or str(shopify_product["id"])

    # Images
    images = [
        img["src"]
        for img in (shopify_product.get("images") or [])
        if img.get("src")
    ]

    # Tags
    tags_raw = shopify_product.get("tags", "") or ""
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    # Occasions (subset of tags)
    occasions = [t for t in tags if t.lower() in _OCCASION_TAGS]

    # Category
    category = (shopify_product.get("product_type") or "general").strip() or "general"

    # Description
    body_html = shopify_product.get("body_html") or ""
    description = _strip_html(body_html) or None

    return {
        "shopify_id": str(shopify_product["id"]),
        "store_id": store_id,
        "sku": sku,
        "name": shopify_product.get("title", "Unknown Product"),
        "description": description,
        "category": category,
        "base_price": base_price,
        "images": images,
        "tags": tags,
        "occasions": occasions,
        "is_active": shopify_product.get("status", "active") == "active",
    }


class ProductSyncService:
    """
    Sync products from Shopify to local DB + Qdrant vector store.

    Inject dependencies at construction so the service is fully testable.
    """

    def __init__(
        self,
        shopify_client: ShopifyClient,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
        session: AsyncSession,
    ) -> None:
        self._shopify = shopify_client
        self._embeddings = embedding_service
        self._vector_store = vector_store
        self._repo = ProductRepository(session)
        self._session = session

    async def sync_all_products(self, store_id: uuid.UUID) -> SyncResult:
        """
        Full paginated sync of all products from Shopify.

        1. Fetch all products (paginated via since_id).
        2. Upsert each into the products table.
        3. Generate embeddings and store in Qdrant.

        Returns a SyncResult summary.
        """
        start = time.monotonic()
        created = updated = errors = 0
        all_shopify_products: list[dict] = []

        # Paginate through Shopify
        since_id: str | None = None
        while True:
            batch = await self._shopify.get_products(limit=50, since_id=since_id)
            if not batch:
                break
            all_shopify_products.extend(batch)
            since_id = str(batch[-1]["id"])
            if len(batch) < 50:
                break

        logger.info(
            "shopify_products_fetched_total",
            count=len(all_shopify_products),
            store_id=str(store_id),
        )

        for sp in all_shopify_products:
            try:
                was_created = await self._sync_one(sp, store_id)
                if was_created:
                    created += 1
                else:
                    updated += 1
            except Exception as exc:
                logger.error(
                    "product_sync_error",
                    shopify_id=sp.get("id"),
                    error=summarize_exception_for_operations(exc),
                )
                errors += 1

        await self._session.commit()

        result = SyncResult(
            total_products=len(all_shopify_products),
            created=created,
            updated=updated,
            errors=errors,
            duration_seconds=round(time.monotonic() - start, 2),
        )
        logger.info(
            "sync_complete",
            total=result.total_products,
            created=result.created,
            updated=result.updated,
            errors=result.errors,
            duration=result.duration_seconds,
        )
        return result

    async def sync_single_product(
        self, store_id: uuid.UUID, shopify_product_id: str
    ) -> bool:
        """
        Sync a single product by Shopify ID (e.g. triggered by a webhook).

        Returns True on success, False if the product was not found.
        """
        sp = await self._shopify.get_product(shopify_product_id)
        if not sp:
            logger.warning("shopify_product_not_found", shopify_id=shopify_product_id)
            return False

        await self._sync_one(sp, store_id)
        await self._session.commit()
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _sync_one(self, shopify_product: dict, store_id: uuid.UUID) -> bool:
        """
        Upsert one product and update its vector embedding.

        Returns True if a new product was created, False if updated.
        """
        data = _shopify_to_product_data(shopify_product, store_id)
        product, was_created = await self._repo.upsert(data)

        # Generate embedding and store in Qdrant
        embedding = await self._embeddings.embed_product(product)
        await self._vector_store.upsert_product(
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

        return was_created
