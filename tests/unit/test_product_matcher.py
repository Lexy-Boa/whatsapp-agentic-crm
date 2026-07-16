"""
Unit tests for ProductMatcher.

All external I/O (DB, Qdrant, OpenAI) is mocked — zero real API calls.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.product_matcher import MatchQuery, ProductMatch, ProductMatcher
from src.db.repositories.product_repo import ProductRepository
from src.db.vector_store import VectorStore
from src.services.ai.embeddings import EmbeddingService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STORE_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def make_product(
    sku: str = "DMB-0001",
    name: str = "Test Product",
    base_price: float = 5000.0,
    category: str = "saree",
    occasions: list | None = None,
) -> SimpleNamespace:
    """
    Return a SimpleNamespace that looks like a Product ORM instance.

    Using SimpleNamespace avoids SQLAlchemy instrumentation issues while
    still exposing all attributes that ProductMatcher accesses.
    """
    return SimpleNamespace(
        id=uuid.uuid4(),
        sku=sku,
        name=name,
        base_price=base_price,
        category=category,
        is_active=True,
        images=[],
        tags=[],
        occasions=occasions or [],
        shopify_id=None,
        store_id=STORE_ID,
        description=None,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_products() -> list[Product]:
    return [
        make_product(
            sku="DMB-2341",
            name="Traditional Kasavu Saree",
            base_price=8500.0,
            occasions=["wedding", "festival", "traditional"],
        ),
        make_product(
            sku="DMB-2342",
            name="Red Silk Wedding Saree",
            base_price=15000.0,
            occasions=["wedding", "engagement"],
        ),
    ]


@pytest.fixture
def mock_embedding_service() -> EmbeddingService:
    svc = AsyncMock(spec=EmbeddingService)
    svc.embed_text.return_value = [0.1] * 1536
    return svc


@pytest.fixture
def mock_vector_store() -> VectorStore:
    return AsyncMock(spec=VectorStore)


@pytest.fixture
def mock_repo() -> ProductRepository:
    return AsyncMock(spec=ProductRepository)


@pytest.fixture
def product_matcher(
    mock_embedding_service, mock_vector_store, mock_repo
) -> ProductMatcher:
    return ProductMatcher(
        embedding_service=mock_embedding_service,
        vector_store=mock_vector_store,
        product_repo=mock_repo,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exact_sku_match(product_matcher, mock_repo, sample_products):
    """A query containing a valid SKU returns an exact match without embedding."""
    mock_repo.get_by_sku.return_value = sample_products[0]

    query = MatchQuery(text="Do you have DMB-2341?")
    results = await product_matcher.find_products(query, STORE_ID)

    assert len(results) == 1
    assert results[0].match_type == "exact"
    assert results[0].score == 1.0
    assert results[0].product.sku == "DMB-2341"
    # No embedding should have been generated for an exact match
    product_matcher._embeddings.embed_text.assert_not_called()


@pytest.mark.asyncio
async def test_semantic_search(product_matcher, mock_repo, mock_vector_store, sample_products):
    """Natural language query uses semantic search and applies price filter."""
    red_saree = sample_products[1]
    mock_repo.get_by_sku.return_value = None  # no SKU in query
    mock_vector_store.search.return_value = [
        {"product_id": str(red_saree.id), "score": 0.92, "metadata": {}},
    ]
    mock_repo.get_by_ids.return_value = [red_saree]

    query = MatchQuery(text="red silk saree", price_range=(5000.0, 15000.0))
    results = await product_matcher.find_products(query, STORE_ID)

    assert len(results) > 0
    assert all(
        5000.0 <= float(r.product.base_price) <= 15000.0 for r in results
    )
    assert results[0].match_type == "semantic"


@pytest.mark.asyncio
async def test_occasion_filter_excludes_non_matching(
    product_matcher, mock_repo, mock_vector_store, sample_products
):
    """Products whose occasions don't match the query occasion are excluded."""
    kasavu = sample_products[0]  # occasions: wedding, festival, traditional
    red_saree = sample_products[1]  # occasions: wedding, engagement

    mock_repo.get_by_sku.return_value = None
    mock_vector_store.search.return_value = [
        {"product_id": str(kasavu.id), "score": 0.85, "metadata": {}},
        {"product_id": str(red_saree.id), "score": 0.80, "metadata": {}},
    ]
    mock_repo.get_by_ids.return_value = [kasavu, red_saree]

    # Only kasavu has "festival" in its occasions
    query = MatchQuery(text="saree for festival", occasion="festival")
    results = await product_matcher.find_products(query, STORE_ID)

    assert len(results) == 1
    assert results[0].product.sku == "DMB-2341"


@pytest.mark.asyncio
async def test_no_results_when_qdrant_empty(
    product_matcher, mock_repo, mock_vector_store
):
    """Empty Qdrant result returns an empty list gracefully."""
    mock_repo.get_by_sku.return_value = None
    mock_vector_store.search.return_value = []
    mock_repo.search_text.return_value = []

    query = MatchQuery(text="something obscure")
    results = await product_matcher.find_products(query, STORE_ID)

    assert results == []


@pytest.mark.asyncio
async def test_no_text_returns_empty(product_matcher):
    """A query with no text and no SKU returns an empty list immediately."""
    results = await product_matcher.find_products(MatchQuery(), STORE_ID)
    assert results == []
    product_matcher._embeddings.embed_text.assert_not_called()


@pytest.mark.asyncio
async def test_embed_called_once_for_semantic(
    product_matcher, mock_repo, mock_vector_store, sample_products
):
    """embed_text is called exactly once per semantic search."""
    mock_repo.get_by_sku.return_value = None
    mock_vector_store.search.return_value = [
        {"product_id": str(sample_products[0].id), "score": 0.9, "metadata": {}},
    ]
    mock_repo.get_by_ids.return_value = [sample_products[0]]

    await product_matcher.find_products(MatchQuery(text="kasavu saree"), STORE_ID)

    product_matcher._embeddings.embed_text.assert_called_once()


@pytest.mark.asyncio
async def test_results_sorted_by_score_descending(
    product_matcher, mock_repo, mock_vector_store, sample_products
):
    """Results are returned in descending score order."""
    p1, p2 = sample_products

    mock_repo.get_by_sku.return_value = None
    mock_vector_store.search.return_value = [
        {"product_id": str(p1.id), "score": 0.70, "metadata": {}},
        {"product_id": str(p2.id), "score": 0.95, "metadata": {}},
    ]
    mock_repo.get_by_ids.return_value = [p1, p2]

    results = await product_matcher.find_products(
        MatchQuery(text="wedding saree"), STORE_ID
    )

    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_falls_back_to_text_search_when_embeddings_fail(
    product_matcher, mock_repo, mock_embedding_service, sample_products
):
    """If embeddings fail, matcher falls back to DB text search."""
    mock_repo.get_by_sku.return_value = None
    mock_embedding_service.embed_text.side_effect = Exception("quota exhausted")
    mock_repo.search_text.side_effect = [
        [sample_products[0]],
        [],
    ]

    results = await product_matcher.find_products(
        MatchQuery(text="kasavu saree"),
        STORE_ID,
    )

    assert len(results) == 1
    assert results[0].product.sku == "DMB-2341"
    assert results[0].match_type == "filter"


@pytest.mark.asyncio
async def test_fallback_search_uses_occasion_terms(
    product_matcher, mock_repo, mock_embedding_service, sample_products
):
    """Fallback search can find products by occasion when embeddings are unavailable."""
    mock_repo.get_by_sku.return_value = None
    mock_embedding_service.embed_text.side_effect = Exception("quota exhausted")
    mock_repo.search_text.side_effect = [
        [],
        [sample_products[0], sample_products[1]],
    ]

    results = await product_matcher.find_products(
        MatchQuery(text="saree for wedding", occasion="wedding", price_range=(0, 10000)),
        STORE_ID,
    )

    assert len(results) == 1
    assert results[0].product.sku == "DMB-2341"
    assert results[0].match_type == "filter"
