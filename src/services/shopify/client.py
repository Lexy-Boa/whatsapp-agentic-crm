"""
Async Shopify Admin API client.
"""

from __future__ import annotations

import structlog
import httpx

from src.config import get_settings

logger = structlog.get_logger(__name__)


class ShopifyClient:
    """
    Async Shopify Admin API client.

    Usage::

        client = ShopifyClient(
            shop_domain="demoboutique.myshopify.com",
            access_token="shpat_...",
        )
        products = await client.get_products()
        await client.close()
    """

    def __init__(self, shop_domain: str, access_token: str) -> None:
        settings = get_settings()
        base_url = f"https://{shop_domain}/admin/api/{settings.shopify_api_version}"
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "X-Shopify-Access-Token": access_token,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        self._shop_domain = shop_domain

    async def get_products(
        self,
        limit: int = 50,
        since_id: str | None = None,
    ) -> list[dict]:
        """
        Fetch a page of products from Shopify.

        Args:
            limit:    Number of products per page (max 250).
            since_id: Return products after this ID for cursor-based pagination.

        Returns:
            List of Shopify product dicts (each includes ``variants`` and ``images``).
        """
        params: dict = {"limit": min(limit, 250)}
        if since_id:
            params["since_id"] = since_id

        response = await self._client.get("/products.json", params=params)
        response.raise_for_status()
        products = response.json().get("products", [])
        logger.debug("shopify_products_fetched", count=len(products), since_id=since_id)
        return products

    async def get_product(self, product_id: str) -> dict | None:
        """
        Fetch a single product by Shopify product ID.

        Returns None if the product does not exist (404).
        """
        response = await self._client.get(f"/products/{product_id}.json")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json().get("product")

    async def get_inventory_levels(
        self, inventory_item_ids: list[str]
    ) -> dict[str, int]:
        """
        Fetch current inventory levels for a list of inventory item IDs.

        Args:
            inventory_item_ids: List of Shopify inventory_item_id strings.

        Returns:
            Dict mapping inventory_item_id → available quantity.
        """
        if not inventory_item_ids:
            return {}

        ids_str = ",".join(inventory_item_ids)
        response = await self._client.get(
            "/inventory_levels.json",
            params={"inventory_item_ids": ids_str},
        )
        response.raise_for_status()
        return {
            str(item["inventory_item_id"]): int(item.get("available") or 0)
            for item in response.json().get("inventory_levels", [])
        }

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
