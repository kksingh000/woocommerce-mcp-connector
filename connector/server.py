"""
MCP connector for WooCommerce (read-only: orders, products).

Exposes 6 MCP tools:
  - list_orders, get_order, search_orders
  - list_products, get_product, search_products

Auth:
  Reads WOOCOMMERCE_URL, WOOCOMMERCE_CONSUMER_KEY, WOOCOMMERCE_CONSUMER_SECRET
  from the environment (see .env.example). Never hardcode real credentials.

Rate limiting:
  WooCommerce (and this mock) can return 429 with a Retry-After header.
  `_request()` below retries with exponential backoff + jitter, honoring
  Retry-After when present, up to MAX_RETRIES attempts.

Run as a standalone MCP server (stdio transport):
    python connector/server.py
"""

from __future__ import annotations

import asyncio
import os
import random
from typing import Any, Optional

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
WOOCOMMERCE_URL = os.environ.get("WOOCOMMERCE_URL", "http://localhost:8000")
CONSUMER_KEY = os.environ.get("WOOCOMMERCE_CONSUMER_KEY", "")
CONSUMER_SECRET = os.environ.get("WOOCOMMERCE_CONSUMER_SECRET", "")

MAX_RETRIES = 4
BASE_BACKOFF_SECONDS = 1.0

server = Server("woocommerce-connector")


# ---------------------------------------------------------------------------
# HTTP layer with auth + rate-limit backoff
# ---------------------------------------------------------------------------
async def _request(method: str, path: str, params: Optional[dict] = None) -> Any:
    if not CONSUMER_KEY or not CONSUMER_SECRET:
        raise RuntimeError(
            "Missing WOOCOMMERCE_CONSUMER_KEY / WOOCOMMERCE_CONSUMER_SECRET. "
            "Set them in your environment (see .env.example)."
        )

    params = dict(params or {})
    params["consumer_key"] = CONSUMER_KEY
    params["consumer_secret"] = CONSUMER_SECRET

    url = f"{WOOCOMMERCE_URL}{path}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        attempt = 0
        while True:
            attempt += 1
            resp = await client.request(method, url, params=params)

            if resp.status_code == 429:
                if attempt > MAX_RETRIES:
                    raise RuntimeError(
                        f"Rate limited after {MAX_RETRIES} retries: {resp.text}"
                    )
                retry_after = resp.headers.get("Retry-After")
                if retry_after is not None:
                    wait = float(retry_after)
                else:
                    wait = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                wait += random.uniform(0, 0.5)  # jitter
                await asyncio.sleep(wait)
                continue

            if resp.status_code == 401:
                raise RuntimeError(
                    "Authentication failed: invalid consumer key/secret."
                )
            if resp.status_code == 404:
                raise RuntimeError(f"Not found: {path}")
            resp.raise_for_status()
            return resp.json(), resp.headers


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
async def list_orders(status: Optional[str] = None, page: int = 1, per_page: int = 10) -> dict:
    params = {"page": page, "per_page": per_page}
    if status:
        params["status"] = status
    data, headers = await _request("GET", "/wp-json/wc/v3/orders", params)
    return {
        "orders": data,
        "total": int(headers.get("X-WP-Total", len(data))),
        "total_pages": int(headers.get("X-WP-TotalPages", 1)),
        "page": page,
    }


async def get_order(order_id: int) -> dict:
    data, _ = await _request("GET", f"/wp-json/wc/v3/orders/{order_id}")
    return data


async def search_orders(query: str, page: int = 1, per_page: int = 10) -> dict:
    params = {"search": query, "page": page, "per_page": per_page}
    data, headers = await _request("GET", "/wp-json/wc/v3/orders", params)
    return {
        "orders": data,
        "total": int(headers.get("X-WP-Total", len(data))),
        "total_pages": int(headers.get("X-WP-TotalPages", 1)),
        "page": page,
    }


async def list_products(status: Optional[str] = None, page: int = 1, per_page: int = 10) -> dict:
    params = {"page": page, "per_page": per_page}
    if status:
        params["status"] = status
    data, headers = await _request("GET", "/wp-json/wc/v3/products", params)
    return {
        "products": data,
        "total": int(headers.get("X-WP-Total", len(data))),
        "total_pages": int(headers.get("X-WP-TotalPages", 1)),
        "page": page,
    }


async def get_product(product_id: int) -> dict:
    data, _ = await _request("GET", f"/wp-json/wc/v3/products/{product_id}")
    return data


async def search_products(query: str, page: int = 1, per_page: int = 10) -> dict:
    params = {"search": query, "page": page, "per_page": per_page}
    data, headers = await _request("GET", "/wp-json/wc/v3/products", params)
    return {
        "products": data,
        "total": int(headers.get("X-WP-Total", len(data))),
        "total_pages": int(headers.get("X-WP-TotalPages", 1)),
        "page": page,
    }


TOOL_IMPLS = {
    "list_orders": list_orders,
    "get_order": get_order,
    "search_orders": search_orders,
    "list_products": list_products,
    "get_product": get_product,
    "search_products": search_products,
}


# ---------------------------------------------------------------------------
# MCP tool specs
# ---------------------------------------------------------------------------
@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_orders",
            description="List store orders, optionally filtered by status "
                        "(pending, processing, on-hold, completed, cancelled, refunded, failed).",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Order status filter (optional)"},
                    "page": {"type": "integer", "default": 1, "minimum": 1},
                    "per_page": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
                },
            },
        ),
        Tool(
            name="get_order",
            description="Get a single order by its numeric ID.",
            inputSchema={
                "type": "object",
                "properties": {"order_id": {"type": "integer"}},
                "required": ["order_id"],
            },
        ),
        Tool(
            name="search_orders",
            description="Search orders by customer name, email, or order ID substring.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "page": {"type": "integer", "default": 1, "minimum": 1},
                    "per_page": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="list_products",
            description="List store products, optionally filtered by status (publish, draft).",
            inputSchema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "page": {"type": "integer", "default": 1, "minimum": 1},
                    "per_page": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
                },
            },
        ),
        Tool(
            name="get_product",
            description="Get a single product by its numeric ID.",
            inputSchema={
                "type": "object",
                "properties": {"product_id": {"type": "integer"}},
                "required": ["product_id"],
            },
        ),
        Tool(
            name="search_products",
            description="Search products by name or SKU.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "page": {"type": "integer", "default": 1, "minimum": 1},
                    "per_page": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    import json

    if name not in TOOL_IMPLS:
        raise ValueError(f"Unknown tool: {name}")
    try:
        result = await TOOL_IMPLS[name](**arguments)
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
