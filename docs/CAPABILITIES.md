# Agent Capabilities — WooCommerce Connector

## What the agent CAN do

Through this connector, an Agent Studio agent can, for the connected WooCommerce store:

- **List orders**, optionally filtered by status (`pending`, `processing`, `on-hold`,
  `completed`, `cancelled`, `refunded`, `failed`), with pagination.
- **Fetch a single order** by its numeric ID (customer billing info, line items,
  total, currency, status, created date).
- **Search orders** by customer first/last name, email, or order ID substring.
- **List products**, optionally filtered by status (`publish`, `draft`, etc.), with pagination.
- **Fetch a single product** by its numeric ID (name, SKU, price, stock quantity, status).
- **Search products** by name or SKU.

All operations are **read-only**. The connector never issues POST, PUT, PATCH, or
DELETE requests against the store.

## What the agent CANNOT do

- **Cannot create, modify, or cancel orders.** No refunds, no status changes, no
  order edits of any kind.
- **Cannot create, edit, or delete products**, adjust prices, or change stock levels.
- **Cannot access customer PII beyond what WooCommerce's order/product endpoints
  already return** (billing name/email on orders). No access to payment methods,
  stored cards, or full customer account records.
- **Cannot access store settings, coupons, taxes, shipping zones, webhooks, or
  any other WooCommerce resource** — only the two endpoints above are implemented.
- **Cannot bypass WooCommerce's own API key scope.** If the underlying consumer
  key is read-only (as recommended), write calls would fail at the WooCommerce
  layer regardless; this connector adds no additional privilege.
- **Does not cache or persist any data it reads.** Every tool call hits the
  live (or mock) API fresh — there is no local datastore, so results reflect
  the store at query time but repeated identical queries cost repeated API calls.

## Assumptions & limitations

- **Built and tested against a mock WooCommerce API** (`mock_server/`), not a
  real store, per the task's "no real customer data / no credentials" constraint.
  Swapping `WOOCOMMERCE_URL` + real consumer key/secret in `.env` should work
  unmodified against a real WooCommerce install, since the mock mirrors the
  real REST API v3 shape (same auth mechanism, same pagination headers,
  same resource fields) — but this has not been verified against a live store.
- **Rate-limit handling** uses exponential backoff with jitter and honors a
  `Retry-After` header when present, capped at 4 retries. WooCommerce itself
  doesn't enforce a fixed public rate limit (it depends on hosting/WAF), so
  the real-world ceiling may differ from the mock's deliberately low
  5-requests/10-seconds limit.
- **Search is substring/case-insensitive**, matching WooCommerce's own
  `search` query param semantics for products, and a best-effort emulation
  for orders (WooCommerce's real order search is less documented/consistent
  across versions — this connector searches billing name, email, and order ID).
- **No webhook/streaming support.** This is a pull-only connector; an agent
  must poll `list_orders` to notice new orders.
- **Single-store, single-credential.** No multi-tenant support — one
  WooCommerce URL and one API key pair per connector instance.
