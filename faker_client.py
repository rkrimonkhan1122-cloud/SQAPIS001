"""
faker_client.py — REAL US identity generator for SQAPI v4.2 (ALL SELF)

Python port of the user's faker.php — fetches a COMPLETELY FRESH real US
identity from fakenamegenerator.com (same headers / same HTML parsing as
the PHP reference) and normalizes it for the Square checkout flow.

WHY: the old flow used a random name + a static list of famous business
addresses and only ever sent the ZIP to the issuer. Strict-AVS merchants
returned ADDRESS_VERIFICATION_FAILURE / AVS_REJECTED. Now EVERY request
gets a real, internally-consistent US identity (name + street + city +
state + zip + phone) that is used consistently across customer →
billing_contact → buyer_postal_code, and the full street/city/state is
now also sent in the 3DS verification billing_contact so AVS has real
data to match against.

Source failover chain (the API NEVER breaks):
  1. https://www.fakenamegenerator.com/gen-random-us-us.php  (direct — ALL SELF)
  2. $FAKER_URL (optional self-hosted faker.php, e.g. https://faker.tatsuyo.xyz/faker.php)
  3. Local fallback identity generator (old _rand_identity logic)

Thread-safe (used from check_multi_sync worker threads).
"""

import os
import re
import json
import random
import string
import threading
import time
from typing import Optional, Dict, Any, List, Tuple

try:
    from curl_cffi import requests as cffi
    HAS_CFFI = True
except Exception:
    HAS_CFFI = False
    try:
        import httpx as _httpx
        _HTTPX = _httpx
    except Exception:
        _HTTPX = None

FNG_URL = "https://www.fakenamegenerator.com/gen-random-us-us.php"
PHP_FAKER_URL = os.environ.get("FAKER_URL", "https://faker.tatsuyo.xyz/faker.php")

FNG_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "accept-language": "en-GB,en-US;q=0.9,en;q=0.8,bn;q=0.7",
    "referer": "https://www.fakenamegenerator.com/",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "same-origin",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36 CrKey/1.54.250320",
}

# ─────────────────────────────────────────────────────────────
#  Local fallback (last resort — old checker.py logic)
# ─────────────────────────────────────────────────────────────

_FIRST = ["james", "john", "robert", "michael", "william", "david", "richard", "joseph",
          "thomas", "charles", "emma", "olivia", "ava", "isabella", "sophia", "mia",
          "charlotte", "amelia", "harper", "evelyn"]
_LAST = ["smith", "johnson", "williams", "brown", "jones", "garcia", "miller", "davis",
         "wilson", "taylor", "anderson", "thomas", "jackson", "white", "harris", "martin"]
_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com"]
_REAL_US_ADDRESSES = [
    ("350 5th Ave", "New York", "NY", "10118"),
    ("1 World Trade Center", "New York", "NY", "10007"),
    ("11 Wall St", "New York", "NY", "10005"),
    ("30 Rockefeller Plaza", "New York", "NY", "10112"),
    ("3500 W Olive Ave", "Burbank", "CA", "91505"),
    ("1600 Amphitheatre Pkwy", "Mountain View", "CA", "94043"),
    ("405 Howard St", "San Francisco", "CA", "94105"),
    ("233 S Wacker Dr", "Chicago", "IL", "60606"),
    ("875 N Michigan Ave", "Chicago", "IL", "60611"),
    ("2800 Post Oak Blvd", "Houston", "TX", "77056"),
    ("3000 Oak Lawn Ave", "Dallas", "TX", "75219"),
    ("400 Broad St", "Seattle", "WA", "98109"),
    ("100 Federal St", "Boston", "MA", "02110"),
    ("265 Peachtree St NE", "Atlanta", "GA", "30303"),
    ("1701 Bryant St", "Denver", "CO", "80202"),
    ("3799 Las Vegas Blvd S", "Las Vegas", "NV", "89109"),
    ("1601 Market St", "Philadelphia", "PA", "19103"),
]

_NAME_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}


def _rand_fallback_identity() -> Dict[str, Any]:
    first = random.choice(_FIRST).capitalize()
    last = random.choice(_LAST).capitalize()
    tag = "".join(random.choices(string.digits, k=random.randint(2, 5)))
    email = f"{first.lower()}{last.lower()}{tag}@{random.choice(_DOMAINS)}"
    area, exch, num = random.randint(200, 999), random.randint(200, 999), random.randint(1000, 9999)
    street, city, state, zc = random.choice(_REAL_US_ADDRESSES)
    return {
        "first": first, "last": last, "full_name": f"{first} {last}",
        "email": email, "phone": f"{area}{exch}{num}",
        "street": street, "city": city, "state": state, "zip": zc,
        "gender": None, "birthday": None, "age": None, "ssn": None,
        "mothers_maiden_name": None, "company": None, "occupation": None,
        "geo": {"latitude": None, "longitude": None},
        "username": None, "website": None,
        "source": "local-fallback",
    }


def _make_email(first: str, last: str) -> str:
    tag = "".join(random.choices(string.digits, k=random.randint(2, 4)))
    style = random.choice(["dot", "plain", "underscore"])
    f, l = first.lower(), last.lower()
    if style == "dot":
        local = f"{f}.{l}{tag}"
    elif style == "underscore":
        local = f"{f}_{l}{tag}"
    else:
        local = f"{f}{l}{tag}"
    return f"{local}@{random.choice(_DOMAINS)}"


def _clean_phone(raw: Optional[str]) -> str:
    """Normalize any phone string to 10 digits (US national number)."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) > 10:
        digits = digits[-10:]
    if len(digits) == 10 and digits[0] in "23456789":
        return digits
    return ""


def _split_name(full_name: str) -> Tuple[str, str]:
    """'Frank S. Hanson' → ('Frank', 'Hanson'); handles suffixes."""
    parts = [p for p in re.split(r"\s+", (full_name or "").strip()) if p]
    if not parts:
        return "", ""
    while parts and parts[-1].lower() in _NAME_SUFFIXES:
        parts.pop()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0].capitalize(), random.choice(_LAST).capitalize()
    first = parts[0].capitalize()
    last = parts[-1].capitalize()
    return first, last


# ─────────────────────────────────────────────────────────────
#  HTML parsing — exact port of the PHP parser
# ─────────────────────────────────────────────────────────────

def _txt(html: str, pattern: str, group: int = 1) -> str:
    m = re.search(pattern, html, re.S)
    if not m:
        return ""
    val = m.group(group)
    val = re.sub(r"<[^>]+>", "", val)
    return val.replace("&amp;", "&").strip()


def _parse_fng_html(html: str) -> Dict[str, Any]:
    """Port of faker.php DOM parsing (regex equivalent, same fields)."""
    # Name: <div class="address"><h3>Frank S. Hanson</h3>
    full_name = _txt(html, r'<div class="address">\s*<h3>(.*?)</h3>')

    # Gender: silhouette img alt inside bcs div
    gender = _txt(html, r'<div class="bcs"[^>]*>.*?<img[^>]*alt="([^"]*)"', 1)

    # Address: <div class="adr">  street <br /> city, ST zip </div>
    street = city = state = zc = ""
    m = re.search(r'<div class="adr">(.*?)</div>', html, re.S)
    if m:
        adr_html = m.group(1)
        adr_html = re.sub(r'<br\s*/?>', '\n', adr_html, flags=re.I)
        adr_text = re.sub(r'<[^>]+>', '', adr_html)
        lines = [ln.strip() for ln in adr_text.split("\n") if ln.strip()]
        if lines:
            street = lines[0]
            if len(lines) > 1:
                cm = re.match(r'^(.+?),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$', lines[1])
                if cm:
                    city, state, zc = cm.group(1).strip(), cm.group(2), cm.group(3)
                else:
                    city = lines[1]
        else:
            # fallback: microdata spans
            street = _txt(adr_html or html, r'itemprop="streetAddress"[^>]*>(.*?)<')
            city = _txt(adr_html or html, r'itemprop="addressLocality"[^>]*>(.*?)<')
            state = _txt(adr_html or html, r'itemprop="addressRegion"[^>]*>(.*?)<')
            zc = _txt(adr_html or html, r'itemprop="postalCode"[^>]*>(.*?)<')

    # dl-horizontal key/value pairs (PHP: ddCleanText — direct text nodes only)
    fields: Dict[str, str] = {}
    card_types = {"Visa": "Visa", "MasterCard": "MasterCard", "Mastercard": "MasterCard",
                  "American Express": "American Express", "Discover": "Discover",
                  "Diners Club": "Diners Club", "JCB": "JCB", "UnionPay": "UnionPay",
                  "EnRoute": "EnRoute"}
    card_type = ""
    for dl_m in re.finditer(r'<dl class="dl-horizontal">(.*?)</dl>', html, re.S):
        dl = dl_m.group(1)
        dts = re.findall(r'<dt>(.*?)</dt>', dl, re.S)
        dds = re.findall(r'<dd[^>]*>(.*?)</dd>', dl, re.S)
        if not dts or not dds:
            continue
        key = re.sub(r'<[^>]+>', '', dts[0]).strip()
        dd = dds[0]
        dd = re.sub(r'<div class="adtl".*?</div>', '', dd, flags=re.S)
        dd = re.sub(r'<[^>]+>', '', dd)
        val = dd.strip()
        if key in card_types:
            card_type = key
            key = "CardNumber"
        if key:
            fields[key] = val

    # Geo coordinates → lat / lng
    lat = lng = None
    geo_str = fields.get("Geo coordinates", "")
    gm = re.match(r'^([-\d.]+),\s*([-\d.]+)$', geo_str)
    if gm:
        try:
            lat, lng = float(gm.group(1)), float(gm.group(2))
        except ValueError:
            pass

    # Age
    age = None
    am = re.search(r'(\d+)', fields.get("Age", ""))
    if am:
        age = int(am.group(1))

    first, last = _split_name(full_name)
    phone = _clean_phone(fields.get("Phone", ""))
    # v4.2.1 — REALISTIC DATA, ALL FROM FAKENAMEGENERATOR:
    #   • name = FIRST + LAST only (middle initial dropped — "John Schultz")
    #   • email = the FNG email itself (realistic name-shaped address)
    full_name = f"{first} {last}".strip()
    email = (fields.get("Email Address") or "").strip() or _make_email(first or "James", last or "Wilson")

    return {
        "first": first, "last": last,
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "street": street, "city": city, "state": state, "zip": zc.split("-")[0],
        "gender": gender or None,
        "birthday": fields.get("Birthday") or None,
        "age": age,
        "ssn": fields.get("SSN") or None,
        "mothers_maiden_name": fields.get("Mother's maiden name") or None,
        "company": fields.get("Company") or None,
        "occupation": fields.get("Occupation") or None,
        "geo": {"latitude": lat, "longitude": lng},
        "username": fields.get("Username") or None,
        "website": fields.get("Website") or None,
        "fng_email": fields.get("Email Address") or None,
        "source": "fakenamegenerator.com",
    }


# ─────────────────────────────────────────────────────────────
#  Upstream fetchers
# ─────────────────────────────────────────────────────────────

def _http_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 15) -> Tuple[Optional[str], int]:
    """GET via curl_cffi (Chrome TLS) — fallback httpx. Returns (text, status)."""
    if HAS_CFFI:
        try:
            r = cffi.get(url, headers=headers or {}, timeout=timeout, impersonate="chrome131")
            return (r.text or ""), r.status_code
        except Exception:
            return None, 0
    if _HTTPX is not None:
        try:
            with _HTTPX.Client(http2=True, timeout=timeout,
                               headers=headers or {}, follow_redirects=True) as cl:
                r = cl.get(url)
                return (r.text or ""), r.status_code
        except Exception:
            return None, 0
    return None, 0


def _fetch_fng() -> Optional[Dict[str, Any]]:
    """Source 1: direct fakenamegenerator.com (ALL SELF — same as faker.php)."""
    for attempt in range(2):
        html, code = _http_get(FNG_URL, headers=FNG_HEADERS, timeout=20)
        if html and code == 200 and 'class="adr"' in html:
            try:
                ident = _parse_fng_html(html)
                if ident["first"] and ident["zip"] and ident["street"]:
                    return ident
            except Exception:
                pass
        time.sleep(0.8 * (attempt + 1))
    return None


def _fetch_php_faker() -> Optional[Dict[str, Any]]:
    """Source 2: self-hosted faker.php (if deployed) — parses its JSON."""
    if not PHP_FAKER_URL or "tatsuyo.xyz" not in PHP_FAKER_URL:
        # only used if the env var points at a live PHP endpoint
        if not os.environ.get("FAKER_URL"):
            return None
    body, code = _http_get(PHP_FAKER_URL, headers={"accept": "application/json"}, timeout=15)
    if not body or code != 200:
        return None
    try:
        data = json.loads(body)
        if not data.get("success"):
            return None
        d = data.get("data") or {}
        addr = d.get("address") or {}
        first, last = _split_name(d.get("name", ""))
        phone = _clean_phone(((d.get("phone") or {}).get("number")) or "")
        online = d.get("online") or {}
        return {
            "first": first, "last": last,
            "full_name": f"{first} {last}".strip(),
            "email": (online.get("email") or "").strip() or _make_email(first or "James", last or "Wilson"),
            "phone": phone,
            "street": addr.get("street", ""), "city": addr.get("city", ""),
            "state": addr.get("state", ""), "zip": (addr.get("zip") or "").split("-")[0],
            "gender": d.get("gender"), "birthday": d.get("birthday"), "age": d.get("age"),
            "ssn": d.get("ssn"), "mothers_maiden_name": d.get("mothers_maiden_name"),
            "company": (d.get("employment") or {}).get("company"),
            "occupation": (d.get("employment") or {}).get("occupation"),
            "geo": {"latitude": (d.get("geo") or {}).get("latitude"),
                    "longitude": (d.get("geo") or {}).get("longitude")},
            "username": (d.get("online") or {}).get("username"),
            "website": (d.get("online") or {}).get("website"),
            "source": "faker.php",
        }
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
#  Identity pool (resilience — FNG hiccups never break a check)
# ─────────────────────────────────────────────────────────────

_POOL: List[Dict[str, Any]] = []
_POOL_LOCK = threading.Lock()
_POOL_MAX = 8
_pool_fills = 0


def _pool_put(ident: Dict[str, Any]):
    global _pool_fills
    with _POOL_LOCK:
        if len(_POOL) < _POOL_MAX:
            _POOL.append(ident)
            _pool_fills += 1


def _pool_pop() -> Optional[Dict[str, Any]]:
    with _POOL_LOCK:
        if _POOL:
            return _POOL.pop(0)
    return None


def _pool_prefill(n: int = 2):
    """Best-effort pool prefill (called lazily / from background)."""
    for _ in range(n):
        ident = _fetch_fng() or _fetch_php_faker()
        if ident:
            _pool_put(ident)
        else:
            break


_prefill_done = False
_prefill_lock = threading.Lock()


def _ensure_prefilled():
    """First call triggers a background prefill so the first check is fast."""
    global _prefill_done
    if _prefill_done:
        return
    with _prefill_lock:
        if _prefill_done:
            return
        _prefill_done = True
    t = threading.Thread(target=_pool_prefill, args=(2,), daemon=True)
    t.start()


def get_identity(force_fresh: bool = True) -> Dict[str, Any]:
    """Get a REAL US identity for one checkout attempt.

    Chain: fakenamegenerator.com → $FAKER_URL (faker.php) → pool → local fallback.
    Every successful live fetch also refills the pool for later resilience.
    """
    global _prefill_done
    _ensure_prefilled()

    ident = _fetch_fng()
    if ident is None:
        ident = _fetch_php_faker()
    if ident is not None:
        _pool_put(ident)          # keep the pool stocked
        return ident

    # live fetch failed → try the pool (identities that ORIGINATED from faker)
    pooled = _pool_pop()
    if pooled is not None:
        pooled = dict(pooled)
        pooled["source"] = f"{pooled.get('source')} (pool)"
        # refresh the random parts that must be unique per attempt
        pooled["email"] = _make_email(pooled["first"], pooled["last"])
        return pooled

    # last resort — local fallback so the API NEVER breaks
    return _rand_fallback_identity()


def get_identity_safe() -> Dict[str, Any]:
    """get_identity() that can never raise."""
    try:
        return get_identity()
    except Exception:
        try:
            return _rand_fallback_identity()
        except Exception:
            return {"first": "James", "last": "Wilson", "full_name": "James Wilson",
                    "email": "james.wilson842@gmail.com", "phone": "5086195382",
                    "street": "350 5th Ave", "city": "New York", "state": "NY",
                    "zip": "10118", "source": "hardcoded-fallback"}


def status() -> Dict[str, Any]:
    """Diagnostics for /faker endpoint."""
    with _POOL_LOCK:
        pool_size = len(_POOL)
    return {
        "primary_source": "fakenamegenerator.com (direct — ALL SELF)",
        "secondary_source": os.environ.get("FAKER_URL", PHP_FAKER_URL) + " (only if live)",
        "fallback": "local random identity",
        "pool_size": pool_size,
        "pool_max": _POOL_MAX,
        "pool_fills_total": _pool_fills,
        "curl_cffi": HAS_CFFI,
    }


if __name__ == "__main__":
    ident = get_identity()
    print(json.dumps(ident, indent=2, default=str))
