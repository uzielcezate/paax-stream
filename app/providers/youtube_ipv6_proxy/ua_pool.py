"""
app/providers/youtube_ipv6_proxy/ua_pool.py
Dynamic User-Agent Pool for anti-bot device fingerprint diversity.

Each IPv6 address is assigned a random User-Agent from this pool at first
handshake, and that same UA is reused for every subsequent request from
that address.  This makes each IPv6 look like a consistent, real device
to the upstream CDN.

The pool mixes mobile and embedded-player User-Agents that are known to
receive standard progressive streams (not DASH manifests):
  - Android ExoPlayer  (what just_audio uses under the hood)
  - iOS Safari / AVPlayer
  - Mobile Chrome (Android)
  - Mobile Safari (iPhone)
  - Samsung Browser
"""
from __future__ import annotations

import random
from typing import List

from app.utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# User-Agent strings — kept current as of early 2026.
#
# Each entry represents a realistic mobile / embedded-player identity.
# The upstream CDN sees these as normal device traffic, not bots.
# ---------------------------------------------------------------------------

USER_AGENTS: List[str] = [
    # ── Android ExoPlayer (what just_audio / YouTube app uses) ────────────
    "com.google.android.youtube/"
    "19.13.34 (Linux; U; Android 14; en_US; Pixel 8 Pro Build/UQ1A.240205.002) "
    "gzip",

    "com.google.android.youtube/"
    "19.09.37 (Linux; U; Android 13; en_US; SM-S918B Build/TP1A.220624.014) "
    "gzip",

    "com.google.android.youtube/"
    "18.48.37 (Linux; U; Android 12; en_US; SM-G991B Build/SP1A.210812.016) "
    "gzip",

    # ── Mobile Chrome (Android) ───────────────────────────────────────────
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.6367.113 Mobile Safari/537.36",

    "Mozilla/5.0 (Linux; Android 14; SM-S928B) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.6312.99 Mobile Safari/537.36",

    "Mozilla/5.0 (Linux; Android 13; SM-A546B) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.6261.119 Mobile Safari/537.36",

    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.6167.164 Mobile Safari/537.36",

    # ── Mobile Safari (iPhone) ────────────────────────────────────────────
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.3.1 Mobile/15E148 Safari/604.1",

    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.2 Mobile/15E148 Safari/604.1",

    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_7_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.6 Mobile/15E148 Safari/604.1",

    # ── iOS YouTube / AVPlayer ────────────────────────────────────────────
    "com.google.ios.youtube/19.13.3 (iPhone16,2; U; CPU iOS 17_4_1 like Mac OS X)",

    "com.google.ios.youtube/19.09.5 (iPhone15,3; U; CPU iOS 17_3_1 like Mac OS X)",

    # ── Samsung Browser ───────────────────────────────────────────────────
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "SamsungBrowser/24.0 Chrome/122.0.6261.105 Mobile Safari/537.36",

    "Mozilla/5.0 (Linux; Android 13; SM-S918B) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "SamsungBrowser/23.0 Chrome/115.0.5790.167 Mobile Safari/537.36",

    # ── Desktop Chrome (fallback diversity) ───────────────────────────────
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",

    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
]


# ── Public API ────────────────────────────────────────────────────────────────

def get_random_user_agent() -> str:
    """Select a random User-Agent from the pool."""
    ua = random.choice(USER_AGENTS)
    log.debug("[UAPool] Selected: %.60s...", ua)
    return ua


def get_all_user_agents() -> List[str]:
    """Return a copy of the full UA pool (for health / debug)."""
    return list(USER_AGENTS)


def ua_pool_size() -> int:
    """Number of User-Agents in the pool."""
    return len(USER_AGENTS)
