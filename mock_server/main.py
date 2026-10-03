"""
Mock WooCommerce REST API v3 server.

Simulates enough of the real WooCommerce REST API (orders + products)
to exercise an MCP connector end-to-end with zero real credentials:
- API-key auth (consumer_key / consumer_secret) exactly like real WooCommerce
- Pagination headers (X-WP-Total, X-WP-TotalPages)
- A deliberate rate limiter (429 + Retry-After) so the connector's
  backoff logic has something real to handle
- Basic list/get/search semantics matching WooCommerce's query params

Run:
    uvicorn mock_server.main:app --port 8000 --reload
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock WooCommerce API", version="3.0.0")

# ---------------------------------------------------------------------------
# Fake credentials (fine to hardcode — this is a mock, not a real store)
# ---------------------------------------------------------------------------
VALID_CONSUMER_KEY = "ck_mock_1234567890abcdef1234567890abcdef12345678"
VALID_CONSUMER_SECRET = "cs_mock_1234567890abcdef1234567890abcdef12345678"

# ---------------------------------------------------------------------------
# Rate limiting: 5 requests per 10 seconds per consumer key
# ---------------------------------------------------------------------------
RATE_LIMIT = 5
RATE_WINDOW_SECONDS = 10
_request_log: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(consumer_key: str) -> Optional[int]:
    """Returns seconds-to-wait if rate limited, else None."""
    now = time.time()
    window_start = now - RATE_WINDOW_SECONDS
    log = _request_log[consumer_key]
    # drop stale entries
    while log and log[0] < window_start:
        log.pop(0)
    if len(log) >= RATE_LIMIT:
        retry_after = int(RATE_WINDOW_SECONDS - (now - log[0])) + 1
        return max(retry_after, 1)
    log.append(now)
    return None


# ---------------------------------------------------------------------------
# Fake data store
# ---------------------------------------------------------------------------
PRODUCTS = [
    {"id": 101, "name": "Classic Cotton Tee", "sku": "TEE-001", "price": "499.00",
     "stock_quantity": 120, "status": "publish"},
    {"id": 102, "name": "Slim Fit Jeans", "sku": "JNS-014", "price": "1499.00",
     "stock_quantity": 45, "status": "publish"},
    {"id": 103, "name": "Canvas Tote Bag", "sku": "BAG-007", "price": "399.00",
     "stock_quantity": 0, "status": "publish"},
    {"id": 104, "name": "Wool Blend Scarf", "sku": "SCF-022", "price": "699.00",
     "stock_quantity": 30, "status": "draft"},
    {"id": 105, "name": "Leather Belt", "sku": "BLT-009", "price": "899.00",
     "stock_quantity": 60, "status": "publish"},
]

ORDERS = [
    {"id": 5001, "status": "processing", "total": "1998.00", "currency": "INR",
     "customer_id": 12, "billing": {"first_name": "Aarav", "last_name": "Sharma",
     "email": "aarav.sharma@example.com"}, "line_items": [{"product_id": 101, "quantity": 4}],
     "date_created": "2026-09-28T10:15:00"},
    {"id": 5002, "status": "completed", "total": "1499.00", "currency": "INR",
     "customer_id": 13, "billing": {"first_name": "Priya", "last_name": "Verma",
     "email": "priya.verma@example.com"}, "line_items": [{"product_id": 102, "quantity": 1}],
     "date_created": "2026-09-29T14:02:00"},
    {"id": 5003, "status": "on-hold", "total": "399.00", "currency": "INR",
     "customer_id": 14, "billing": {"first_name": "Rohan", "last_name": "Gupta",
     "email": "rohan.gupta@example.com"}, "line_items": [{"product_id": 103, "quantity": 1}],
     "date_created": "2026-09-30T09:40:00"},
    {"id": 5004, "status": "cancelled", "total": "899.00", "currency": "INR",
     "customer_id": 12, "billing": {"first_name": "Aarav", "last_name": "Sharma",
     "email": "aarav.sharma@example.com"}, "line_items": [{"product_id": 105, "quantity": 1}],
     "date_created": "2026-10-01T11:20:00"},
    {"id": 5005, "status": "processing", "total": "998.00", "currency": "INR",
     "customer_id": 15, "billing": {"first_name": "Neha", "last_name": "Iyer",
     "email": "neha.iyer@example.com"}, "line_items": [{"product_id": 101, "quantity": 2}],
     "date_created": "2026-10-02T16:55:00"},
]


# ---------------------------------------------------------------------------
# Auth dependency — WooCommerce supports query-param OR Basic auth for
# consumer_key/consumer_secret over HTTPS. We support both here.
# ---------------------------------------------------------------------------
def authenticate(
    request: Request,
    consumer_key: Optional[str] = Query(None),
    consumer_secret: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
) -> str:
    ck, cs = consumer_key, consumer_secret

    if not ck and authorization and authorization.startswith("Basic "):
        import base64
        try:
            decoded = base64.b64decode(authorization[6:]).decode()
            ck, cs = decoded.split(":", 1)
        except Exception:
            pass

    if not ck or not cs:
        raise HTTPException(
            status_code=401,
            detail={"code": "woocommerce_api_authentication_error",
                    "message": "Consumer key/secret missing."},
        )
    if ck != VALID_CONSUMER_KEY or cs != VALID_CONSUMER_SECRET:
        raise HTTPException(
            status_code=401,
            detail={"code": "woocommerce_api_authentication_error",
                    "message": "Consumer key/secret is invalid."},
        )

    retry_after = check_rate_limit(ck)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail={"code": "woocommerce_rest_rate_limit_exceeded",
                    "message": f"Too many requests. Retry after {retry_after}s."},
            headers={"Retry-After": str(retry_after)},
        )
    return ck


def paginate(items: list, page: int, per_page: int) -> tuple[list, int, int]:
    total = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page)
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end], total, total_pages


# ---------------------------------------------------------------------------
# Routes — mirror real WooCommerce REST API v3 paths
# ---------------------------------------------------------------------------
@app.get("/wp-json/wc/v3/orders")
def list_orders(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    customer: Optional[int] = Query(None),
    _auth: str = None,
):
    _auth = authenticate(request, request.query_params.get("consumer_key"),
                          request.query_params.get("consumer_secret"),
                          request.headers.get("authorization"))

    results = ORDERS
    if status:
        results = [o for o in results if o["status"] == status]
    if customer:
        results = [o for o in results if o["customer_id"] == customer]
    if search:
        s = search.lower()
        results = [
            o for o in results
            if s in o["billing"]["email"].lower()
            or s in o["billing"]["first_name"].lower()
            or s in o["billing"]["last_name"].lower()
            or s in str(o["id"])
        ]

    page_items, total, total_pages = paginate(results, page, per_page)
    return JSONResponse(
        content=page_items,
        headers={"X-WP-Total": str(total), "X-WP-TotalPages": str(total_pages)},
    )


@app.get("/wp-json/wc/v3/orders/{order_id}")
def get_order(order_id: int, request: Request):
    authenticate(request, request.query_params.get("consumer_key"),
                 request.query_params.get("consumer_secret"),
                 request.headers.get("authorization"))
    for o in ORDERS:
        if o["id"] == order_id:
            return o
    raise HTTPException(status_code=404, detail={
        "code": "woocommerce_rest_shop_order_invalid_id",
        "message": "Invalid ID."})


@app.get("/wp-json/wc/v3/products")
def list_products(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    sku: Optional[str] = Query(None),
):
    authenticate(request, request.query_params.get("consumer_key"),
                 request.query_params.get("consumer_secret"),
                 request.headers.get("authorization"))

    results = PRODUCTS
    if status:
        results = [p for p in results if p["status"] == status]
    if sku:
        results = [p for p in results if p["sku"].lower() == sku.lower()]
    if search:
        s = search.lower()
        results = [p for p in results if s in p["name"].lower() or s in p["sku"].lower()]

    page_items, total, total_pages = paginate(results, page, per_page)
    return JSONResponse(
        content=page_items,
        headers={"X-WP-Total": str(total), "X-WP-TotalPages": str(total_pages)},
    )


@app.get("/wp-json/wc/v3/products/{product_id}")
def get_product(product_id: int, request: Request):
    authenticate(request, request.query_params.get("consumer_key"),
                 request.query_params.get("consumer_secret"),
                 request.headers.get("authorization"))
    for p in PRODUCTS:
        if p["id"] == product_id:
            return p
    raise HTTPException(status_code=404, detail={
        "code": "woocommerce_rest_product_invalid_id",
        "message": "Invalid ID."})


@app.get("/health")
def health():
    return {"status": "ok"}
