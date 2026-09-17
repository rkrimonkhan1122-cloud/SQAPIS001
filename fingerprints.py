"""
fingerprints.py — Unlimited browser fingerprint + User-Agent rotation.

v6 HITTER — NO WINDOWS. Only macOS, iOS (iPhone/iPad), Android, Linux, ChromeOS.

Every call to `random_fingerprint()` returns a COMPLETE, realistic, internally-
consistent browser profile:
  • User-Agent string (Chrome 124–155 on non-Windows platforms, LATEST-weighted:
    80% of profiles use the newest 8 Chrome builds — exactly like real traffic)
  • sec-ch-ua / sec-ch-ua-mobile / sec-ch-ua-platform client hints
  • Full device info dict for BasisTheory (screen size, hardware, WebGL, etc.)
  • Accept-Language header
  • Timezone + JS-convention UTC offset (for payment browser_info)

11 non-Windows OS variants × 32 Chrome versions (latest-weighted) ×
40+ GPU strings × 20+ screens × 2024-2026 device models = MILLIONS of unique
combinations. Every request — and every retry — gets a brand-new identity.
"""
from __future__ import annotations

import random
import uuid
from typing import Dict, Any, Tuple


# ── Chrome versions (124 → 155) with LATEST-WEIGHTED selection ───────────────
# Real-world Chrome traffic concentrates on the newest builds — 80% of our
# profiles pick from the newest 8 versions, the rest spread over the tail.
CHROME_VERSIONS = list(range(124, 156))    # 124, 125, ..., 155
LATEST_CHROME = CHROME_VERSIONS[-8:]       # 148..155 — the real-world majority


def weighted_chrome_version() -> int:
    """Pick a Chrome version the way real traffic does: mostly latest."""
    if random.random() < 0.80:
        return random.choice(LATEST_CHROME)
    return random.choice(CHROME_VERSIONS)


# ── Operating system profiles — NO WINDOWS ──────────────────────────────────
OS_PROFILES = [
    # ── macOS — Intel MacBook ────────────────────────────────────────────────
    {
        "name": "mac_intel",
        "ua_platform": "Macintosh; Intel Mac OS X 10_15_7",
        "nav_platform": "MacIntel",
        "sec_ch_ua_platform": '"macOS"',
        "os_name": "macOS",
        "ua_mobile": False,
        "screens": [(1440, 900), (1680, 1050), (2560, 1440), (1920, 1080),
                    (1280, 800), (1366, 768)],
        "gpus": [
            ("Google Inc. (Intel)",
             "ANGLE (Intel Inc., Intel(R) Iris(TM) Plus Graphics 645, OpenGL 4.1)"),
            ("Google Inc. (Intel)",
             "ANGLE (Intel Inc., Intel(R) Iris(TM) Plus Graphics 655, OpenGL 4.1)"),
            ("Google Inc. (AMD)",
             "ANGLE (AMD, AMD Radeon Pro 5500 XT OpenGL Engine, OpenGL 4.1)"),
            ("Google Inc. (AMD)",
             "ANGLE (AMD, AMD Radeon Pro 5300M OpenGL Engine, OpenGL 4.1)"),
            ("Google Inc. (Intel)",
             "ANGLE (Intel Inc., Intel(R) HD Graphics 630, OpenGL 4.1)"),
        ],
        "hardware_concurrency": [4, 8, 12, 16],
        "device_memory": [8, 16, 32],
        "timezones": ["America/New_York", "America/Los_Angeles", "America/Chicago",
                      "America/Denver", "America/Detroit", "America/Phoenix",
                      "America/Toronto", "America/Vancouver", "Europe/London",
                      "Europe/Paris", "Europe/Berlin"],
    },
    # ── macOS — Apple Silicon MacBook (M1) ───────────────────────────────────
    {
        "name": "mac_m1",
        "ua_platform": "Macintosh; Intel Mac OS X 10_15_7",  # UA still says Intel for compat
        "nav_platform": "MacIntel",
        "sec_ch_ua_platform": '"macOS"',
        "os_name": "macOS",
        "ua_mobile": False,
        "screens": [(1440, 900), (1680, 1050), (2560, 1600), (1920, 1080)],
        "gpus": [
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)"),
        ],
        "hardware_concurrency": [8],
        "device_memory": [8, 16],
        "timezones": ["America/New_York", "America/Los_Angeles", "America/Chicago",
                      "America/Toronto", "Europe/London"],
    },
    # ── macOS — Apple Silicon MacBook (M2) ───────────────────────────────────
    {
        "name": "mac_m2",
        "ua_platform": "Macintosh; Intel Mac OS X 10_15_7",
        "nav_platform": "MacIntel",
        "sec_ch_ua_platform": '"macOS"',
        "os_name": "macOS",
        "ua_mobile": False,
        "screens": [(1512, 982), (1800, 1169), (2560, 1664), (1440, 900)],
        "gpus": [
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)"),
        ],
        "hardware_concurrency": [8, 10],
        "device_memory": [8, 16, 24],
        "timezones": ["America/New_York", "America/Los_Angeles", "America/Chicago",
                      "America/Toronto", "Europe/London", "Europe/Paris"],
    },
    # ── macOS — Apple Silicon MacBook (M3 / M3 Pro / M3 Max) ─────────────────
    {
        "name": "mac_m3",
        "ua_platform": "Macintosh; Intel Mac OS X 10_15_7",
        "nav_platform": "MacIntel",
        "sec_ch_ua_platform": '"macOS"',
        "os_name": "macOS",
        "ua_mobile": False,
        "screens": [(1800, 1169), (2560, 1664), (3024, 1964), (3456, 2234),
                    (1512, 982)],
        "gpus": [
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple M3, Unspecified Version)"),
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Pro, Unspecified Version)"),
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple M3 Max, Unspecified Version)"),
        ],
        "hardware_concurrency": [8, 10, 12, 16, 18],
        "device_memory": [16, 24, 32, 48, 64, 96, 128],
        "timezones": ["America/New_York", "America/Los_Angeles", "America/Chicago",
                      "America/Toronto", "America/Vancouver", "Europe/London",
                      "Europe/Paris", "Europe/Berlin", "Asia/Tokyo"],
    },
    # ── macOS — Apple Silicon MacBook (M4 / M4 Pro) ──────────────────────────
    {
        "name": "mac_m4",
        "ua_platform": "Macintosh; Intel Mac OS X 10_15_7",
        "nav_platform": "MacIntel",
        "sec_ch_ua_platform": '"macOS"',
        "os_name": "macOS",
        "ua_mobile": False,
        "screens": [(1800, 1169), (2560, 1664), (3024, 1964), (3456, 2234)],
        "gpus": [
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple M4, Unspecified Version)"),
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple M4 Pro, Unspecified Version)"),
        ],
        "hardware_concurrency": [10, 12, 14, 16],
        "device_memory": [16, 24, 32, 48, 64],
        "timezones": ["America/New_York", "America/Los_Angeles", "America/Chicago",
                      "America/Toronto", "Europe/London", "Asia/Tokyo"],
    },
    # ── iOS — iPhone (mobile Chrome) ─────────────────────────────────────────
    # Note: iOS Chrome uses the same engine as Safari (WebKit). The UA contains
    # "CriOS" instead of "Chrome". This is the real iPhone Chrome UA format.
    {
        "name": "iphone",
        # iPhone Chrome UA: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) ... CriOS/124.0.6367.111 ..."
        # We'll build this specially in _build_user_agent since it's CriOS not Chrome
        "ua_platform": "iPhone",  # special marker — see _build_user_agent
        "nav_platform": "iPhone",
        "sec_ch_ua_platform": '"iOS"',
        "os_name": "iOS",
        "ua_mobile": True,
        "screens": [(390, 844), (393, 852), (414, 896), (428, 926),
                    (375, 812), (430, 932), (1179, 2556)],
        # iOS doesn't expose GPU via WebGL in the same way — use Apple's ANGLE
        "gpus": [
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple A15 Bionic, Unspecified Version)"),
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple A16 Bionic, Unspecified Version)"),
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple A17 Pro, Unspecified Version)"),
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple A18 Pro, Unspecified Version)"),
        ],
        "hardware_concurrency": [6],     # iPhones have 6-core CPUs
        "device_memory": [4, 6, 8],      # iOS doesn't expose deviceMemory, but BT expects a value
        "timezones": ["America/New_York", "America/Los_Angeles", "America/Chicago",
                      "America/Denver", "America/Toronto", "Europe/London",
                      "Europe/Paris", "Asia/Tokyo", "Asia/Singapore"],
    },
    # ── iOS — iPad (tablet Chrome) ────────────────────────────────────────────
    {
        "name": "ipad",
        "ua_platform": "iPad",  # special marker — see _build_user_agent
        "nav_platform": "iPad",
        "sec_ch_ua_platform": '"iOS"',
        "os_name": "iOS",
        "ua_mobile": False,   # iPad reports as non-mobile
        "screens": [(820, 1180), (1024, 1366), (768, 1024), (834, 1194),
                    (834, 1112), (1024, 768)],
        "gpus": [
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)"),
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)"),
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple A14X Bionic, Unspecified Version)"),
            ("Google Inc. (Apple)",
             "ANGLE (Apple, ANGLE Metal Renderer: Apple A12Z Bionic, Unspecified Version)"),
        ],
        "hardware_concurrency": [8, 10],
        "device_memory": [4, 6, 8, 16],
        "timezones": ["America/New_York", "America/Los_Angeles", "America/Chicago",
                      "America/Toronto", "Europe/London", "Asia/Tokyo"],
    },
    # ── Android — Phone (mobile Chrome) ──────────────────────────────────────
    {
        "name": "android_phone",
        "ua_platform": "Linux; Android 14; SM-S928U",  # Samsung S24 Ultra
        "nav_platform": "Linux armv8l",
        "sec_ch_ua_platform": '"Android"',
        "os_name": "Android",
        "ua_mobile": True,
        "screens": [(1080, 2316), (1440, 3120), (720, 1600), (1080, 2400),
                    (1170, 2532), (1284, 2778), (1440, 3088), (720, 1560)],
        "gpus": [
            ("Google Inc. (Qualcomm)",
             "ANGLE (Qualcomm, Adreno (TM) 750, OpenGL ES 3.2)"),
            ("Google Inc. (Qualcomm)",
             "ANGLE (Qualcomm, Adreno (TM) 740, OpenGL ES 3.2)"),
            ("Google Inc. (ARM)",
             "ANGLE (ARM, Mali-G715 MC9, OpenGL ES 3.2)"),
            ("Google Inc. (ARM)",
             "ANGLE (ARM, Mali-G78 MP24, OpenGL ES 3.2)"),
        ],
        "hardware_concurrency": [8],  # Most Android flagships have 8 cores
        "device_memory": [4, 6, 8, 12, 16],
        "timezones": ["America/New_York", "America/Los_Angeles", "America/Chicago",
                      "America/Denver", "America/Toronto", "Europe/London",
                      "Europe/Paris", "Europe/Berlin", "Asia/Tokyo",
                      "Asia/Singapore", "Asia/Kolkata", "Australia/Sydney"],
    },
    # ── Android — Tablet ─────────────────────────────────────────────────────
    {
        "name": "android_tablet",
        "ua_platform": "Linux; Android 14; SM-X910",  # Galaxy Tab S9
        "nav_platform": "Linux armv8l",
        "sec_ch_ua_platform": '"Android"',
        "os_name": "Android",
        "ua_mobile": False,
        "screens": [(1600, 2560), (2048, 1536), (1200, 1920), (2560, 1600)],
        "gpus": [
            ("Google Inc. (Qualcomm)",
             "ANGLE (Qualcomm, Adreno (TM) 740, OpenGL ES 3.2)"),
            ("Google Inc. (ARM)",
             "ANGLE (ARM, Mali-G715 MC9, OpenGL ES 3.2)"),
        ],
        "hardware_concurrency": [8],
        "device_memory": [8, 12, 16],
        "timezones": ["America/New_York", "America/Los_Angeles", "America/Chicago",
                      "Europe/London", "Asia/Tokyo"],
    },
    # ── Linux (Ubuntu / Fedora desktop) ──────────────────────────────────────
    {
        "name": "linux",
        "ua_platform": "X11; Linux x86_64",
        "nav_platform": "Linux x86_64",
        "sec_ch_ua_platform": '"Linux"',
        "os_name": "Linux",
        "ua_mobile": False,
        "screens": [(1920, 1080), (2560, 1440), (1366, 768), (3840, 2160),
                    (1680, 1050), (1440, 900)],
        "gpus": [
            ("Google Inc. (NVIDIA)",
             "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002503) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (NVIDIA)",
             "ANGLE (NVIDIA, NVIDIA GeForce RTX 4060 (0x00002803) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (Intel)",
             "ANGLE (Intel, Intel(R) UHD Graphics 630 (0x00003E9B) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (AMD)",
             "ANGLE (AMD, AMD Radeon RX 6700 XT (0x000073DF) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Mesa/X.org",
             "Mesa Intel(R) UHD Graphics 630 (CFL GT2)"),
            ("Mesa/X.org",
             "Mesa Intel(R) Iris(R) Xe Graphics (TGL GT2)"),
            ("Mesa/X.org",
             "llvmpipe (LLVM 15.0.7, 256 bits)"),
        ],
        "hardware_concurrency": [4, 8, 12, 16, 32],
        "device_memory": [8, 16, 32, 64],
        "timezones": ["America/New_York", "America/Chicago", "America/Los_Angeles",
                      "America/Denver", "America/Toronto", "Europe/London",
                      "Europe/Paris", "Europe/Berlin", "Europe/Madrid",
                      "Asia/Tokyo", "Asia/Singapore"],
    },
    # ── ChromeOS (Chromebook) ────────────────────────────────────────────────
    {
        "name": "chromeos",
        "ua_platform": "X11; CrOS x86_64 14526.89.0",
        "nav_platform": "Linux x86_64",
        "sec_ch_ua_platform": '"Chrome OS"',
        "os_name": "ChromeOS",
        "ua_mobile": False,
        "screens": [(1920, 1080), (1366, 768), (1536, 864), (2560, 1440)],
        "gpus": [
            ("Google Inc. (Intel)",
             "ANGLE (Intel, Intel(R) UHD Graphics 605 (0x00003185) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (Intel)",
             "ANGLE (Intel, Intel(R) UHD Graphics 620 (0x00005916) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
            ("Google Inc. (Intel)",
             "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics (TGL GT2) Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ],
        "hardware_concurrency": [4, 8],
        "device_memory": [4, 8],
        "timezones": ["America/New_York", "America/Chicago", "America/Los_Angeles",
                      "America/Denver"],
    },
]


# ── Language / locale pool ──────────────────────────────────────────────────
LANGUAGES = [
    ("en-US", "en-US,en;q=0.9"),
    ("en-US", "en-US,en;q=0.9,es;q=0.8"),
    ("en-GB", "en-GB,en;q=0.9"),
    ("en-US", "en-US,en;q=0.9,fr;q=0.8"),
    ("en",    "en,en-US;q=0.9"),
    ("en-US", "en-US,en;q=0.9,de;q=0.8"),
    ("en-US", "en-US,en;q=0.9,pt;q=0.8"),
    ("en-CA", "en-CA,en;q=0.9,fr-CA;q=0.8"),
    ("en-AU", "en-AU,en;q=0.9"),
    ("en-US", "en-US,en;q=0.9,zh-CN;q=0.8"),
    ("en-US", "en-US,en;q=0.9,ja;q=0.8"),
    ("en-US", "en-US,en;q=0.9,ko;q=0.8"),
]


# ── Android device model pool (for realistic UA strings) ────────────────────
ANDROID_PHONE_MODELS = [
    "SM-S938U",   # Samsung Galaxy S25 Ultra
    "SM-S936U",   # Samsung Galaxy S25+
    "SM-S931U",   # Samsung Galaxy S25
    "SM-S928U",   # Samsung Galaxy S24 Ultra
    "SM-S918U",   # Samsung Galaxy S23 Ultra
    "SM-S908U",   # Samsung Galaxy S22 Ultra
    "SM-G998U",   # Samsung Galaxy S21 Ultra
    "Pixel 9 Pro XL",
    "Pixel 9 Pro",
    "Pixel 9",
    "Pixel 8 Pro",
    "Pixel 8",
    "Pixel 7 Pro",
    "Pixel 7",
    "SM-A546U",   # Samsung Galaxy A54
    "SM-A536U",   # Samsung Galaxy A53
    "OnePlus CPH2695",  # OnePlus 13
    "OnePlus CPH2581",  # OnePlus 12
    "OnePlus CPH2449",  # OnePlus 11
    "CPH2399",    # OnePlus 10 Pro
]

ANDROID_TABLET_MODELS = [
    "SM-X920",    # Galaxy Tab S10+
    "SM-X926B",   # Galaxy Tab S10 Ultra
    "SM-X910",    # Galaxy Tab S9
    "SM-X906U",   # Galaxy Tab S8 Ultra
    "SM-X800U",   # Galaxy Tab S8+
    "SM-T970",    # Galaxy Tab S7+
    "Pixel Tablet",
]

IOS_VERSIONS = [
    # iOS 18 — current majority
    ("18_5", "18.5"),
    ("18_4", "18.4"),
    ("18_3", "18.3"),
    ("18_2", "18.2"),
    ("18_1", "18.1"),
    ("18_0", "18.0"),
    # iOS 17 — still in the wild
    ("17_5", "17.5"),
    ("17_4", "17.4"),
    ("17_3", "17.3"),
    ("17_2", "17.2"),
    ("17_1_1", "17.1.1"),
    ("17_0_3", "17.0.3"),
    ("16_7_5", "16.7.5"),
    ("16_6", "16.6"),
]

IPHONE_MODELS = [
    "iPhone17,5",  # iPhone 16e
    "iPhone17,4",  # iPhone 16 Plus
    "iPhone17,3",  # iPhone 16
    "iPhone17,2",  # iPhone 16 Pro Max
    "iPhone17,1",  # iPhone 16 Pro
    "iPhone16,2",  # iPhone 15 Pro Max
    "iPhone16,1",  # iPhone 15 Pro
    "iPhone15,3",  # iPhone 14 Pro Max
    "iPhone15,2",  # iPhone 14 Pro
    "iPhone14,7",  # iPhone 14
    "iPhone14,8",  # iPhone 14 Plus
    "iPhone13,4",  # iPhone 12 Pro Max
    "iPhone13,3",  # iPhone 12 Pro
    "iPhone13,2",  # iPhone 12
]

IPAD_MODELS = [
    "iPad16,3",  # iPad Pro 11-inch (M5)
    "iPad16,4",  # iPad Pro 11-inch (M5) cellular
    "iPad15,3",  # iPad Air 13-inch (M3)
    "iPad15,4",  # iPad Air 13-inch (M3) cellular
    "iPad14,5",  # iPad Pro 13-inch (M4)
    "iPad14,6",  # iPad Pro 13-inch (M4) cellular
    "iPad14,3",  # iPad Pro 11-inch (M4)
    "iPad14,4",  # iPad Pro 11-inch (M4) cellular
    "iPad13,8",  # iPad Pro 12.9-inch (M2)
    "iPad13,4",  # iPad Air (M1)
    "iPad12,1",  # iPad (10th gen)
]


# ── Extra real GPU strings appended to every OS profile (100x pool) └────────
_EXTRA_GPUS = {
    "mac_intel": [
        ("Google Inc. (Intel)", "ANGLE (Intel Inc., Intel(R) Iris(TM) Plus Graphics 640, OpenGL 4.1)"),
        ("Google Inc. (Intel)", "ANGLE (Intel Inc., Intel(R) UHD Graphics 630, OpenGL 4.1)"),
        ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon Pro 560X OpenGL Engine, OpenGL 4.1)"),
        ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon Pro 570X OpenGL Engine, OpenGL 4.1)"),
        ("Google Inc. (Intel)", "ANGLE (Intel Inc., Intel(R) UHD Graphics 617, OpenGL 4.1)"),
    ],
    "iphone": [
        ("Apple Inc.", "ANGLE (Apple, ANGLE Metal Renderer: Apple A18 Pro, Unspecified Version)"),
        ("Apple Inc.", "ANGLE (Apple, ANGLE Metal Renderer: Apple A18, Unspecified Version)"),
        ("Apple Inc.", "ANGLE (Apple, ANGLE Metal Renderer: Apple A17 Pro, Unspecified Version)"),
        ("Apple Inc.", "ANGLE (Apple, ANGLE Metal Renderer: Apple A16 GPU, Unspecified Version)"),
        ("Apple Inc.", "ANGLE (Apple, ANGLE Metal Renderer: Apple A15 GPU, Unspecified Version)"),
    ],
    "ipad": [
        ("Apple Inc.", "ANGLE (Apple, ANGLE Metal Renderer: Apple M4, Unspecified Version)"),
        ("Apple Inc.", "ANGLE (Apple, ANGLE Metal Renderer: Apple M3, Unspecified Version)"),
        ("Apple Inc.", "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)"),
        ("Apple Inc.", "ANGLE (Apple, ANGLE Metal Renderer: Apple M1, Unspecified Version)"),
    ],
    "android_phone": [
        ("Qualcomm", "ANGLE (Qualcomm, Adreno (TM) 830, Vulkan 1.3.x (Android 15))"),
        ("Qualcomm", "ANGLE (Qualcomm, Adreno (TM) 750, Vulkan 1.3.x (Android 15))"),
        ("Qualcomm", "ANGLE (Qualcomm, Adreno (TM) 740, Vulkan 1.3.x (Android 14))"),
        ("ARM", "ANGLE (ARM, Mali-G715-Immortalis MC11, Vulkan 1.3.x (Android 15))"),
        ("Samsung", "ANGLE (Samsung, Xclipse 940, Vulkan 1.3.x (Android 15))"),
    ],
    "android_tablet": [
        ("Qualcomm", "ANGLE (Qualcomm, Adreno (TM) 750, Vulkan 1.3.x (Android 15))"),
        ("Qualcomm", "ANGLE (Qualcomm, Adreno (TM) 740, Vulkan 1.3.x (Android 14))"),
        ("ARM", "ANGLE (ARM, Mali-G710-Immortalis MC10, Vulkan 1.3.x (Android 14))"),
    ],
    "linux": [
        ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 5080 (0x00002B00), OpenGL 4.6)"),
        ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 4090 (0x00002684), OpenGL 4.6)"),
        ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 (0x00002786), OpenGL 4.6)"),
        ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 9070 XT (0x00007550), OpenGL 4.6)"),
        ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 7900 XTX (0x0000744C), OpenGL 4.6)"),
        ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) Arc(TM) A770 Graphics (0x000056A0), OpenGL 4.6)"),
        ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 770 (0x00004680), OpenGL 4.6)"),
        ("Google Inc. (Intel)", "ANGLE (Intel, Mesa Intel(R) Iris(R) Xe Graphics (TGL GT2), OpenGL 4.6)"),
    ],
    "chromeos": [
        ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics, OpenGL 4.6)"),
        ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon Graphics (Ryzen 5000), OpenGL 4.6)"),
        ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 605, OpenGL 4.5)"),
    ],
}

for _p in OS_PROFILES:
    _p["gpus"].extend(_EXTRA_GPUS.get(_p["name"], []))

# Extra realistic MacBook screens for the four macOS profiles
_MAC_SCREENS = [(1512, 982), (1728, 1117), (2056, 1329), (3024, 1964)]
for _p in OS_PROFILES:
    if _p["os_name"] == "macOS":
        _p["screens"].extend(_MAC_SCREENS)


# ── Build a sec-ch-ua client hint string matching the Chrome version ─────────
def _build_sec_ch_ua(chrome_version: int, is_ios: bool = False) -> str:
    """Build a realistic sec-ch-ua header for the given Chrome version.

    iOS Chrome (CriOS) doesn't send sec-ch-ua — it returns an empty string.
    """
    if is_ios:
        return ""   # iOS Chrome doesn't send sec-ch-ua

    # GREASE brand rotation (Google's actual pattern)
    grease_brands = [
        ('Not/A)Brand', '8'),
        ('Not/A)Brand', '8'),
        ('Not.A/Brand', '8'),
        ('Not?A_Brand', '24'),
        ('Not_A Brand', '24'),
        ('Not:A-Brand', '24'),
        ('Not)A;Brand', '99'),
        ('Not"Or"Brand', '99'),
    ]
    grease = random.choice(grease_brands)
    parts = [
        f'"{grease[0]}";v="{grease[1]}"',
        f'"Google Chrome";v="{chrome_version}"',
        f'"Chromium";v="{chrome_version}"',
    ]
    random.shuffle(parts)
    return ", ".join(parts)


# ── Build a complete User-Agent string ──────────────────────────────────────
def _build_user_agent(os_profile: dict, chrome_version: int,
                      ios_version=None) -> str:
    """Build a Chrome/CriOS User-Agent string for the given OS + version.

    iOS uses CriOS (Chrome for iOS). Everything else uses Chrome.
    `ios_version` is an optional pre-picked (ua_token, dotted) tuple so the
    CALLER can track the exact iOS version and keep the TLS fingerprint
    (WebKit/Safari stack) perfectly in sync with the UA.
    """
    platform = os_profile["ua_platform"]

    # ── iOS iPhone (CriOS) ────────────────────────────────────────────────
    if platform == "iPhone":
        ios_ver, ios_ver_dot = ios_version or random.choice(IOS_VERSIONS)
        # Real iPhone Chrome UA format:
        # Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/124.0.6367.111 Mobile/15E148 Safari/604.1
        build = random.choice(["15E148", "21B101", "21C50", "20D67", "20A362", "21F90"])
        patch = random.randint(80, 130)
        return (f"Mozilla/5.0 (iPhone; CPU iPhone OS {ios_ver} like Mac OS X) "
                f"AppleWebKit/605.1.15 (KHTML, like Gecko) "
                f"CriOS/{chrome_version}.0.{6367 if chrome_version < 130 else 6990}.{patch} "
                f"Mobile/{build} Safari/604.1")

    # ── iOS iPad (CriOS) ──────────────────────────────────────────────────
    if platform == "iPad":
        ios_ver, ios_ver_dot = ios_version or random.choice(IOS_VERSIONS)
        build = random.choice(["15E148", "21B101", "21C50", "20D67", "21F90"])
        patch = random.randint(80, 130)
        return (f"Mozilla/5.0 (iPad; CPU OS {ios_ver} like Mac OS X) "
                f"AppleWebKit/605.1.15 (KHTML, like Gecko) "
                f"CriOS/{chrome_version}.0.{6367 if chrome_version < 130 else 6990}.{patch} "
                f"Mobile/{build} Safari/604.1")

    # ── Android Phone ─────────────────────────────────────────────────────
    if os_profile["name"] == "android_phone":
        model = random.choice(ANDROID_PHONE_MODELS)
        android_ver = random.choice([13, 14, 15])
        return (f"Mozilla/5.0 (Linux; Android {android_ver}; {model}) "
                f"AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{chrome_version}.0.0.0 Mobile Safari/537.36")

    # ── Android Tablet ────────────────────────────────────────────────────
    if os_profile["name"] == "android_tablet":
        model = random.choice(ANDROID_TABLET_MODELS)
        android_ver = random.choice([13, 14, 15])
        return (f"Mozilla/5.0 (Linux; Android {android_ver}; {model}) "
                f"AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{chrome_version}.0.0.0 Safari/537.36")

    # ── macOS / Linux / ChromeOS ──────────────────────────────────────────
    return (f"Mozilla/5.0 ({platform}) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{chrome_version}.0.0.0 Safari/537.36")


# ── Build a complete device info dict for BasisTheory ───────────────────────
def _build_device_info(os_profile: dict, chrome_version: int,
                       screen: Tuple[int, int],
                       gpu: Tuple[str, str],
                       hardware_concurrency: int,
                       device_memory: int,
                       timezone: str,
                       language: str,
                       is_mobile: bool) -> Dict[str, Any]:
    """Build the deviceInfo dict sent to BasisTheory's /sessions endpoint.

    All fields are kept consistent with the User-Agent so Whop/BasisTheory
    can't detect the request as coming from an automated tool.
    """
    screen_w, screen_h = screen
    # Inner dimensions are slightly smaller than screen (browser chrome)
    if is_mobile:
        # Mobile — inner == screen (no browser chrome takes height on mobile typically)
        inner_w = screen_w
        inner_h = screen_h - random.choice([0, 0, 40, 56])
    else:
        # Desktop — browser chrome takes ~80px
        inner_w = screen_w
        inner_h = screen_h - random.choice([40, 56, 72, 80, 100, 110])
        if inner_h < 600:
            inner_h = 600

    # Build uaBrands — iOS doesn't send these, but BT expects the field
    is_ios = os_profile["os_name"] == "iOS"
    if is_ios:
        ua_brands = []   # iOS Chrome doesn't expose client hints
    else:
        ua_brands = [
            {"brand": "Not/A)Brand", "version": "8"},
            {"brand": "Google Chrome", "version": str(chrome_version)},
            {"brand": "Chromium", "version": str(chrome_version)},
        ]

    return {
        "uaBrands":          ua_brands,
        "uaMobile":          is_mobile,
        "uaPlatform":        os_profile["os_name"],
        "languages":         [language, "en"] if not language.startswith("en") else [language],
        "timeZone":          timezone,
        "cookiesEnabled":    True,
        "localStorageEnabled": True,
        "sessionStorageEnabled": True,
        "platform":          os_profile["nav_platform"],
        "hardwareConcurrency": hardware_concurrency,
        "deviceMemoryGb":    device_memory,
        "deviceMemory":      device_memory,
        "screenWidth":       screen_w,
        "screenHeight":      screen_h,
        "screenAvailWidth":  screen_w,
        "screenAvailHeight": screen_h - random.choice([40, 56, 72]),
        "innerWidth":        inner_w,
        "innerHeight":       inner_h,
        "devicePixelRatio":  random.choice([2, 2, 2.5, 3, 3, 3.5]) if is_mobile
                             else random.choice([1, 1, 1.25, 1.5, 2, 2]),
        "maxTouchPoints":    5 if is_mobile else 0,
        "network": {
            "effectiveType": "4g",
            "rtt": random.choice([50, 100, 150, 200, 250]),
            "downlink": random.choice([5, 7.5, 10, 15, 20, 25]),
        },
        "plugins":   [] if is_mobile else ["PDF Viewer", "Chrome PDF Viewer",
                                           "Chromium PDF Viewer", "WebKit built-in PDF"],
        "mimeTypes": [] if is_mobile else ["application/pdf", "text/pdf"],
        "webdriver":          False,
        "suspectedHeadless":  False,
        "webglVendor":        gpu[0],
        "webglRenderer":      gpu[1],
        "colorDepth":         24,
        "pixelDepth":         24,
        "vendor":             "Google Inc.",
        "vendorSub":          "",
        "productSub":         "20030107",
        "product":            "Gecko",
        "appName":            "Netscape",
        "appCodeName":        "Mozilla",
        "appVersion":         f"5.0 ({os_profile['ua_platform']}) AppleWebKit/537.36 "
                              f"(KHTML, like Gecko) Chrome/{chrome_version}.0.0.0 Safari/537.36",
    }


# ── JS-style timezone offset (for payment browser_info coherence) ────────────
def timezone_offset_minutes(tz_name: str) -> int:
    """UTC offset in minutes using JavaScript's getTimezoneOffset() convention:
    minutes BEHIND UTC (New York = 300, Kolkata = -330, UTC = 0).
    Keeps the payment browser_info perfectly in sync with the fingerprint's
    timezone so BasisTheory sees ONE coherent browser identity.
    """
    try:
        import datetime as _dt
        from zoneinfo import ZoneInfo
        off = ZoneInfo(tz_name).utcoffset(_dt.datetime.now(_dt.timezone.utc))
        return -int(off.total_seconds() // 60)
    except Exception:
        return 0


# ── Pool size (approximate unique profile combinations) ─────────────────────
def pool_size() -> int:
    """Approximate count of unique fingerprint combinations available."""
    total = 0
    for p in OS_PROFILES:
        per_os = (len(p["screens"]) * len(p["gpus"]) *
                  len(p["hardware_concurrency"]) * len(p["device_memory"]) *
                  len(p["timezones"]))
        if p["os_name"] == "iOS":
            per_os *= len(IPHONE_MODELS if p["name"] == "iphone" else IPAD_MODELS)
            per_os *= len(IOS_VERSIONS)
        elif p["name"] == "android_phone":
            per_os *= len(ANDROID_PHONE_MODELS) * 3   # android 13/14/15
        elif p["name"] == "android_tablet":
            per_os *= len(ANDROID_TABLET_MODELS) * 3
        total += per_os
    return total * len(CHROME_VERSIONS) * len(LANGUAGES)


# ── Public API ──────────────────────────────────────────────────────────────
def random_fingerprint() -> Dict[str, Any]:
    """Generate a complete, internally-consistent browser fingerprint.

    Returns a dict with:
      • user_agent:        full UA string
      • sec_ch_ua:         sec-ch-ua header value (empty for iOS)
      • sec_ch_ua_mobile:  "?1" for mobile, "?0" for desktop
      • sec_ch_ua_platform: sec-ch-ua-platform header value
      • accept_language:   Accept-Language header value
      • device_info:       full deviceInfo dict for BasisTheory
      • chrome_version:    int (e.g. 148)
      • os_name:           str (e.g. "macOS", "iOS", "Android", "Linux", "ChromeOS")
      • screen_size:       (w, h) tuple
      • timezone:          str (e.g. "America/New_York")
      • is_mobile:         bool
      • session_id:        random UUID (for cross-request correlation)

    NEVER returns Windows. Only macOS, iOS, Android, Linux, ChromeOS.
    """
    os_profile = random.choice(OS_PROFILES)
    chrome_version = weighted_chrome_version()   # v6: latest-weighted like real traffic
    screen = random.choice(os_profile["screens"])
    gpu = random.choice(os_profile["gpus"])
    hc = random.choice(os_profile["hardware_concurrency"])
    dm = random.choice(os_profile["device_memory"])
    tz = random.choice(os_profile["timezones"])
    lang, accept_lang = random.choice(LANGUAGES)
    is_mobile = os_profile["ua_mobile"]
    is_ios = os_profile["os_name"] == "iOS"

    # v7: pick the iOS version ONCE so the UA and the TLS/WebKit impersonation
    # target (safari18x_ios) stay perfectly coherent for this identity.
    ios_version = random.choice(IOS_VERSIONS) if is_ios else ("", "")

    user_agent = _build_user_agent(os_profile, chrome_version, ios_version=ios_version)
    sec_ch_ua = _build_sec_ch_ua(chrome_version, is_ios=is_ios)
    device_info = _build_device_info(
        os_profile, chrome_version, screen, gpu, hc, dm, tz, lang, is_mobile,
    )

    return {
        "user_agent":         user_agent,
        "sec_ch_ua":          sec_ch_ua,
        "sec_ch_ua_mobile":   "?1" if is_mobile else "?0",
        "sec_ch_ua_platform": os_profile["sec_ch_ua_platform"],
        "accept_language":    accept_lang,
        "device_info":        device_info,
        "chrome_version":     chrome_version,
        "os_name":            os_profile["os_name"],
        "os_profile":         os_profile["name"],
        "screen_size":        screen,
        "timezone":           tz,
        "tz_offset_minutes":  timezone_offset_minutes(tz),
        "is_mobile":          is_mobile,
        "is_ios":             is_ios,
        "ios_version":        ios_version[1],   # v7: e.g. "18.5" ("" for non-iOS)
        "session_id":         str(uuid.uuid4()),
    }


# ── Quick self-test ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Generating 5 random fingerprints (NO WINDOWS):\n")
    os_counts = {}
    for i in range(5):
        fp = random_fingerprint()
        os_counts[fp["os_name"]] = os_counts.get(fp["os_name"], 0) + 1
        mobile_tag = " [MOBILE]" if fp["is_mobile"] else ""
        ios_tag = " [iOS]" if fp["is_ios"] else ""
        print(f"#{i+1}  Chrome {fp['chrome_version']} on {fp['os_name']}{mobile_tag}{ios_tag}  "
              f"({fp['screen_size'][0]}x{fp['screen_size'][1]})  "
              f"profile={fp['os_profile']}")
        print(f"    UA:       {fp['user_agent']}")
        print(f"    sec-ch-ua: {fp['sec_ch_ua'] or '(empty — iOS)'}")
        print(f"    Platform:  {fp['sec_ch_ua_platform']}")
        print(f"    Mobile:    {fp['sec_ch_ua_mobile']}")
        print(f"    Lang:      {fp['accept_language']}")
        print(f"    TZ:        {fp['timezone']}")
        print(f"    GPU:       {fp['device_info']['webglRenderer'][:60]}...")
        print()

    # Verify NO WINDOWS appears in any UA over 1000 runs
    print("Verifying NO WINDOWS over 1000 runs...")
    win_count = 0
    for _ in range(1000):
        fp = random_fingerprint()
        if "Windows" in fp["user_agent"] or fp["os_name"] == "Windows":
            win_count += 1
    print(f"Windows count: {win_count} / 1000  ({'PASS' if win_count == 0 else 'FAIL'})")
