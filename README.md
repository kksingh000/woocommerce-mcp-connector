# WooCommerce MCP Connector

A private MCP connector giving an Agent Studio agent read access to a
WooCommerce store's orders and products — built and tested entirely against
a bundled mock API, so it's fully runnable with zero real credentials.

## What's in here

```
mock_server/        Mock WooCommerce REST API v3 (FastAPI) — orders + products,
                     API-key auth, pagination, deliberate rate limiting
connector/
  server.py          The MCP server itself (6 tools, stdio transport)
  mcp_tool_spec.json Standalone MCP tool specification (JSON Schema)
tests/
  test_connector.py  End-to-end test script (run mock server first)
docs/
  CAPABILITIES.md    What the agent can/cannot do
.env.example         Copy to .env — mock credentials work out of the box
requirements.txt
```

## Setup

```bash
pip install -r requirements.txt
```

Requires Python 3.10+. Note: `requirements.txt` pins `mcp<2` — the MCP SDK's
2.x line renamed `FastMCP`→`MCPServer` and changed the decorator API this
connector uses; v1 is what `connector/server.py` is written against.

## Run it

**1. Start the mock WooCommerce API** (in one terminal):

```bash
uvicorn mock_server.main:app --port 8000
```

Confirm it's up: `curl http://localhost:8000/health` → `{"status":"ok"}`

**2. Set credentials** (in another terminal):

```bash
cp .env.example .env
# The example file's mock credentials already match the mock server —
# no editing needed unless you point this at a real WooCommerce store.
export $(cat .env | xargs)
```

**3. Run the test suite:**

```bash
python tests/test_connector.py
```

Expected: `12/12 checks passed.`

**4. Run the MCP server standalone** (what an Agent Studio agent would spawn):

```bash
python connector/server.py
```

This starts an MCP server over stdio and blocks, waiting for a client
(an MCP host / agent runtime) to connect and call its tools.

## Pointing at a real WooCommerce store

1. In WordPress admin: **WooCommerce → Settings → Advanced → REST API** →
   generate a key with **Read** permissions only.
2. Set `WOOCOMMERCE_URL` to your store's base URL, and
   `WOOCOMMERCE_CONSUMER_KEY` / `WOOCOMMERCE_CONSUMER_SECRET` to the
   generated values.
3. Everything else is unchanged — the connector talks to real WooCommerce's
   REST API v3 the same way it talks to the mock, since the mock mirrors
   that API's auth, pagination, and resource shape.

This has **not been tested against a live store** (per the task's
constraint against using real customer data/credentials) — see
`docs/CAPABILITIES.md` for what that means in practice.

## Design notes

- **Auth**: WooCommerce REST API v3's native scheme — consumer key/secret as
  query params (also works as HTTP Basic auth; the connector supports both
  on the mock server side for realism, and uses query params on the client side).
- **Rate-limit handling**: exponential backoff + jitter, honors `Retry-After`,
  capped at 4 retries, surfaces a clear error if still rate-limited after that.
- **MCP tool spec**: `connector/mcp_tool_spec.json` is the same 6 tools
  described independently of the code, for review without reading Python.
