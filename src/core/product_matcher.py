"""
High-level product matching logic combining exact SKU lookup and semantic search.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

import structlog

from src.db.repositories.product_repo import ProductRepository
from src.db.vector_store import VectorStore
from src.models.product import Product
from src.services.ai.embeddings import EmbeddingService

logger = structlog.get_logger(__name__)

_SKU_RE = re.compile(r"\b([A-Z]{2,6}-\d{3,6})\b")
_TERM_RE = re.compile(r"[a-zA-Z]{3,}")
_STOP_WORDS = {
    "the",
    "and",
    "for",
    "with",
    "under",
    "over",
    "near",
    "need",
    "want",
    "show",
    "give",
    "looking",
    "please",
    "something",
}


@dataclass
class MatchQuery:
    """Parameters for a product search request."""

    text: str | None = None
    image_embedding: list[float] | None = None
    occasion: str | None = None
    price_range: tuple[float, float] | None = None
    attributes: dict | None = field(default_factory=dict)


@dataclass
class ProductMatch:
    """A single search result with score and match strategy."""

    product: Product
    score: float
    match_type: str  # "exact" | "semantic" | "filter"


class ProductMatcher:
    """
    Find products that best match a customer's query.

    Strategy:
    1. If the query contains a recognizable SKU pattern -> exact DB lookup.
    2. Otherwise, try semantic search using embeddings + Qdrant.
    3. If semantic search fails or returns nothing, fall back to DB text search.
    4. Apply Python-level filters and return ranked results.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
        product_repo: ProductRepository,
    ) -> None:
        self._embeddings = embedding_service
        self._vector_store = vector_store
        self._repo = product_repo

    async def find_products(
        self,
        query: MatchQuery,
        store_id: uuid.UUID,
        limit: int = 5,
    ) -> list[ProductMatch]:
        """
        Find products matching the query.

        Returns at most ``limit`` ProductMatch objects ordered by score desc.
        Returns an empty list when there is nothing to search.
        """
        if query.text:
            sku_match = _SKU_RE.search(query.text)
            if sku_match:
                sku = sku_match.group(1)
                product = await self._repo.get_by_sku(store_id, sku)
                if product:
                    logger.info("exact_sku_match", sku=sku)
                    return [ProductMatch(product=product, score=1.0, match_type="exact")]

        if not query.text:
            return []

        semantic_matches = await self._semantic_search(query, store_id, limit)
        if semantic_matches:
            return semantic_matches

        return await self._fallback_text_search(query, store_id, limit)

    async def _semantic_search(
        self,
        query: MatchQuery,
        store_id: uuid.UUID,
        limit: int,
    ) -> list[ProductMatch]:
        try:
            embedding = await self._embeddings.embed_text(query.text or "")

            qdrant_filters: dict = {}
            if query.price_range:
                lo, hi = query.price_range
                qdrant_filters["price_min"] = lo
                qdrant_filters["price_max"] = hi

            search_results = await self._vector_store.search(
                query_embedding=embedding,
                store_id=str(store_id),
                limit=limit * 3,
                filters=qdrant_filters,
            )

            if not search_results:
                logger.warning(
                    "semantic_search_empty_falling_back",
                    query_length=len(query.text or ""),
                )
                return []

            product_ids = [uuid.UUID(r["product_id"]) for r in search_results]
            score_map = {r["product_id"]: r["score"] for r in search_results}
            products = await self._repo.get_by_ids(product_ids, store_id=store_id)

            matches = self._filter_products(
                products,
                query=query,
                score_lookup=lambda product: score_map.get(str(product.id), 0.0),
                match_type="semantic",
            )
            logger.info(
                "semantic_search_complete",
                query_length=len(query.text or ""),
                results=len(matches),
            )
            return matches[:limit]
        except Exception as exc:
            logger.warning(
                "semantic_search_failed_falling_back",
                query_length=len(query.text or ""),
                error=str(exc),
            )
            return []

    async def _fallback_text_search(
        self,
        query: MatchQuery,
        store_id: uuid.UUID,
        limit: int,
    ) -> list[ProductMatch]:
        if not query.text:
            return []

        search_terms = _extract_search_terms(query.text, query.occasion)
        candidates: dict[uuid.UUID, Product] = {}

        for term in search_terms:
            products = await self._repo.search_text(store_id, term, limit=limit * 3)
            for product in products:
                candidates[product.id] = product

        if not candidates:
            logger.info("fallback_text_search_no_results", query_length=len(query.text))
            return []

        lowered_terms = [term.lower() for term in search_terms]
        matches = self._filter_products(
            list(candidates.values()),
            query=query,
            score_lookup=lambda product: _fallback_score(product, lowered_terms),
            match_type="filter",
        )
        logger.info(
            "fallback_text_search_complete",
            query_length=len(query.text),
            results=len(matches),
        )
        return matches[:limit]

    def _filter_products(
        self,
        products: list[Product],
        *,
        query: MatchQuery,
        score_lookup,
        match_type: str,
    ) -> list[ProductMatch]:
        matches: list[ProductMatch] = []
        for product in products:
            if query.price_range:
                lo, hi = query.price_range
                if not (lo <= float(product.base_price) <= hi):
                    continue

            if query.occasion:
                occ = query.occasion.lower()
                product_occasions = [o.lower() for o in (product.occasions or [])]
                if occ not in product_occasions:
                    continue

            matches.append(
                ProductMatch(
                    product=product,
                    score=float(score_lookup(product)),
                    match_type=match_type,
                )
            )

        matches.sort(key=lambda m: m.score, reverse=True)
        return matches

    async def find_similar(
        self,
        product_id: uuid.UUID,
        store_id: uuid.UUID,
        limit: int = 5,
    ) -> list[ProductMatch]:
        """
        Find products similar to a given product by reusing its stored embedding.
        """
        pid_str = str(product_id)
        points = await self._vector_store._client.retrieve(
            collection_name=self._vector_store.COLLECTION_NAME,
            ids=[pid_str],
            with_vectors=True,
        )
        if not points:
            logger.warning("find_similar_no_embedding", product_id=pid_str)
            return []

        embedding = points[0].vector
        results = await self._vector_store.search(
            query_embedding=embedding,
            store_id=str(store_id),
            limit=limit + 1,
        )
        results = [r for r in results if r["product_id"] != pid_str][:limit]

        if not results:
            return []

        product_ids = [uuid.UUID(r["product_id"]) for r in results]
        score_map = {r["product_id"]: r["score"] for r in results}
        products = await self._repo.get_by_ids(product_ids, store_id=store_id)

        return [
            ProductMatch(
                product=product,
                score=score_map.get(str(product.id), 0.0),
                match_type="semantic",
            )
            for product in products
        ]


def _extract_search_terms(text: str, occasion: str | None = None) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    for raw in _TERM_RE.findall(text.lower()):
        if raw in _STOP_WORDS:
            continue
        if raw not in seen:
            terms.append(raw)
            seen.add(raw)

    if occasion:
        lowered = occasion.lower()
        if lowered not in seen:
            terms.append(lowered)

    return terms[:8]


def _fallback_score(product: Product, terms: list[str]) -> float:
    haystack = " ".join(
        [
            getattr(product, "name", "") or "",
            getattr(product, "description", "") or "",
            " ".join(getattr(product, "occasions", []) or []),
            getattr(product, "category", "") or "",
        ]
    ).lower()

    if not terms:
        return 0.1

    score = 0.0
    for term in terms:
        if term in haystack:
            score += 1.0

    return score / len(terms)
