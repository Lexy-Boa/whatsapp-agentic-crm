"""
Qdrant vector store wrapper for product embeddings.
"""

from __future__ import annotations

import structlog
from qdrant_client import AsyncQdrantClient
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential, before_sleep_log
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    Range,
    VectorParams,
)

from src.config import get_settings

logger = structlog.get_logger(__name__)
_std_logger = __import__("logging").getLogger(__name__)


class VectorStore:
    """
    Async wrapper around Qdrant for product embedding storage and search.

    Create once at startup and reuse. Call ``initialize()`` before any
    search or upsert operations to ensure the collection exists.
    """

    VECTOR_SIZE = 1536  # OpenAI text-embedding-3-small dimensions

    def __init__(self) -> None:
        settings = get_settings()
        self.COLLECTION_NAME = settings.qdrant_collection
        self._client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            api_key=settings.qdrant_api_key or None,
        )

    async def initialize(self) -> None:
        """Create the Qdrant collection if it does not already exist."""
        collections = await self._client.get_collections()
        existing = {c.name for c in collections.collections}
        if self.COLLECTION_NAME not in existing:
            await self._client.create_collection(
                collection_name=self.COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=self.VECTOR_SIZE,
                    distance=Distance.COSINE,
                ),
            )
            logger.info("qdrant_collection_created", collection=self.COLLECTION_NAME)
        else:
            logger.debug("qdrant_collection_exists", collection=self.COLLECTION_NAME)

    async def upsert_product(
        self,
        product_id: str,
        store_id: str,
        embedding: list[float],
        metadata: dict,
    ) -> None:
        """
        Insert or update a product's embedding in Qdrant.

        Args:
            product_id: UUID string of the product (used as point ID).
            store_id:   UUID string of the store (stored in payload for filtering).
            embedding:  Dense float vector of length VECTOR_SIZE.
            metadata:   Payload dict (name, sku, price, occasions, category, …).
        """
        payload = {
            "store_id": store_id,
            **metadata,
        }
        point = PointStruct(id=product_id, vector=embedding, payload=payload)
        await self._client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=[point],
        )
        logger.debug("vector_upserted", product_id=product_id)

    @retry(
        retry=retry_if_exception_type((ConnectionError, OSError)),
        wait=wait_exponential(min=1, max=30),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(_std_logger, __import__("logging").WARNING),
    )
    async def search(
        self,
        query_embedding: list[float],
        store_id: str,
        limit: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """
        Find the nearest products to a query vector.

        Args:
            query_embedding: Dense query vector.
            store_id:        Filter results to this store.
            limit:           Maximum number of results.
            filters:         Optional dict with keys price_min, price_max, occasion.

        Returns:
            List of dicts: {product_id, score, metadata}.
        """
        must: list = [
            FieldCondition(key="store_id", match=MatchValue(value=store_id))
        ]

        if filters:
            price_min = filters.get("price_min")
            price_max = filters.get("price_max")
            if price_min is not None or price_max is not None:
                range_kwargs: dict = {}
                if price_min is not None:
                    range_kwargs["gte"] = float(price_min)
                if price_max is not None:
                    range_kwargs["lte"] = float(price_max)
                must.append(FieldCondition(key="price", range=Range(**range_kwargs)))

        query_filter = Filter(must=must) if must else None

        results = await self._client.search(
            collection_name=self.COLLECTION_NAME,
            query_vector=query_embedding,
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
        )

        return [
            {
                "product_id": str(hit.id),
                "score": hit.score,
                "metadata": hit.payload or {},
            }
            for hit in results
        ]

    async def delete_product(self, product_id: str) -> None:
        """Remove a product's embedding from the vector store."""
        await self._client.delete(
            collection_name=self.COLLECTION_NAME,
            points_selector=PointIdsList(points=[product_id]),
        )
        logger.debug("vector_deleted", product_id=product_id)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()
