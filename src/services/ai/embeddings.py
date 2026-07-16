"""
Embedding generation using OpenAI's text-embedding-3-small model.
"""

from __future__ import annotations

import structlog
from openai import APIConnectionError, RateLimitError, InternalServerError
from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential, before_sleep_log

from src.config import get_settings

logger = structlog.get_logger(__name__)
_std_logger = __import__("logging").getLogger(__name__)

_RETRYABLE_ERRORS = (APIConnectionError, RateLimitError, InternalServerError)


class EmbeddingService:
    """
    Generate dense text embeddings for semantic product search.

    Uses OpenAI's text-embedding-3-small (1536 dimensions).
    Create once and reuse — the AsyncOpenAI client manages connection pooling.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_embedding_model

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_ERRORS),
        wait=wait_exponential(min=1, max=30),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(_std_logger, __import__("logging").WARNING),
    )
    async def embed_text(self, text: str) -> list[float]:
        """
        Generate an embedding for a single text string.

        Args:
            text: Any text (query, product description, etc.)

        Returns:
            Float vector of length 1536.
        """
        response = await self._client.embeddings.create(
            model=self._model,
            input=text.strip(),
        )
        embedding = response.data[0].embedding
        logger.debug("embedding_generated", model=self._model, text_length=len(text))
        return embedding

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_ERRORS),
        wait=wait_exponential(min=1, max=30),
        stop=stop_after_attempt(3),
        before_sleep=before_sleep_log(_std_logger, __import__("logging").WARNING),
    )
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Batch-generate embeddings for multiple texts in a single API call.

        Args:
            texts: List of text strings. OpenAI supports up to 2048 inputs.

        Returns:
            List of float vectors, in the same order as the input.
        """
        if not texts:
            return []
        response = await self._client.embeddings.create(
            model=self._model,
            input=[t.strip() for t in texts],
        )
        # Response items are ordered by index
        items = sorted(response.data, key=lambda d: d.index)
        logger.debug("batch_embedding_generated", count=len(items))
        return [item.embedding for item in items]

    async def embed_product(self, product) -> list[float]:
        """
        Build a rich text representation of a product and embed it.

        Combines name, description, category, occasions, and tags so that
        semantic search can match on any of these attributes.

        Args:
            product: A Product ORM instance or any object with the expected
                     attributes (name, description, category, occasions, tags).

        Returns:
            Float vector of length 1536.
        """
        parts: list[str] = [product.name]

        if getattr(product, "description", None):
            parts.append(product.description)

        if getattr(product, "category", None):
            parts.append(f"Category: {product.category}")

        occasions = getattr(product, "occasions", None) or []
        if occasions:
            parts.append("Occasions: " + ", ".join(str(o) for o in occasions))

        tags = getattr(product, "tags", None) or []
        if tags:
            parts.append("Tags: " + ", ".join(str(t) for t in tags))

        text = ". ".join(parts)
        return await self.embed_text(text)
