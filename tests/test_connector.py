"""
End-to-end test script: starts nothing itself — run the mock server first
(see README), then run this script against it.

Exercises:
  1. Auth success (valid keys)
  2. Auth failure (bad keys)
  3. list_orders (with and without status filter)
  4. get_order (found + not found)
  5. search_orders
  6. list_products / get_product / search_products
  7. Rate-limit handling: hammer the server past its limit and confirm
     the connector's backoff logic recovers instead of crashing

Run:
    python tests/test_connector.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("WOOCOMMERCE_URL", "http://localhost:8000")
os.environ.setdefault("WOOCOMMERCE_CONSUMER_KEY", "ck_mock_1234567890abcdef1234567890abcdef12345678")
os.environ.setdefault("WOOCOMMERCE_CONSUMER_SECRET", "cs_mock_1234567890abcdef1234567890abcdef12345678")

from connector import server as conn  # noqa: E402

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"

results = []


def check(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not condition else ""))
    results.append(condition)


async def run():
    print(f"Target: {conn.WOOCOMMERCE_URL}\n")

    # 1. list_orders — all
    res = await conn.list_orders()
    check("list_orders returns orders", len(res["orders"]) > 0, str(res))
    check("list_orders includes pagination meta", "total" in res and "total_pages" in res)

    # 2. list_orders — filtered by status
    res = await conn.list_orders(status="processing")
    check(
        "list_orders filters by status",
        all(o["status"] == "processing" for o in res["orders"]),
        str(res),
    )

    # 3. get_order — found
    all_orders = await conn.list_orders(per_page=100)
    first_id = all_orders["orders"][0]["id"]
    order = await conn.get_order(first_id)
    check("get_order returns correct order", order["id"] == first_id, str(order))

    # 4. get_order — not found
    try:
        await conn.get_order(999999)
        check("get_order raises on missing order", False, "did not raise")
    except RuntimeError as e:
        check("get_order raises on missing order", "Not found" in str(e), str(e))

    # 5. search_orders
    res = await conn.search_orders(query="aarav")
    check(
        "search_orders matches by first name",
        len(res["orders"]) > 0 and all("aarav" in o["billing"]["first_name"].lower() for o in res["orders"]),
        str(res),
    )

    # 6. list_products
    res = await conn.list_products()
    check("list_products returns products", len(res["products"]) > 0, str(res))

    # 7. list_products — filtered
    res = await conn.list_products(status="draft")
    check(
        "list_products filters by status",
        all(p["status"] == "draft" for p in res["products"]),
        str(res),
    )

    # 8. get_product
    all_products = await conn.list_products(per_page=100)
    pid = all_products["products"][0]["id"]
    product = await conn.get_product(pid)
    check("get_product returns correct product", product["id"] == pid, str(product))

    # 9. search_products
    res = await conn.search_products(query="tee")
    check(
        "search_products matches by name",
        len(res["products"]) > 0,
        str(res),
    )

    # 10. Bad credentials
    old_secret = conn.CONSUMER_SECRET
    conn.CONSUMER_SECRET = "wrong_secret"
    try:
        await conn.list_orders()
        check("bad credentials raise auth error", False, "did not raise")
    except RuntimeError as e:
        check("bad credentials raise auth error", "Authentication failed" in str(e), str(e))
    finally:
        conn.CONSUMER_SECRET = old_secret

    # 11. Rate-limit handling — fire more requests than the mock server allows
    #     per window (5 / 10s) and confirm the connector backs off and
    #     eventually succeeds rather than raising.
    print("\nFiring burst requests to trigger rate limiting (this takes a few seconds)...")
    try:
        burst_results = await asyncio.gather(*[conn.list_orders() for _ in range(8)])
        check(
            "rate-limit backoff recovers",
            all("orders" in r for r in burst_results),
            "one or more burst requests failed",
        )
    except RuntimeError as e:
        check("rate-limit backoff recovers", False, str(e))

    print(f"\n{sum(results)}/{len(results)} checks passed.")
    if not all(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run())
