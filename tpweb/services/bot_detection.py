"""Shared bot classification -- used by both the Activity dashboard's
aggregates (tpweb/services/activity_dashboard.py) and real-time auto-block
enforcement (tpweb.middleware.access_control.BlockedIPMiddleware), so the
two can't silently drift apart.

Keep BOT_SIGNATURES in sync with KNOWN_BOT_SIGNATURES in
static/js/pages/activity-dashboard.js (that copy only badges individual rows
client-side; it can't share this module across the Python/JS boundary).
"""

import re

BOT_SIGNATURES = (
    (
        "AI crawler",
        re.compile(
            r"claudebot|gptbot|ccbot|bytespider|perplexitybot|amazonbot|google-extended", re.I
        ),
    ),
    (
        "Search crawler",
        re.compile(r"googlebot|bingbot|duckduckbot|yandexbot|baiduspider|slurp", re.I),
    ),
    (
        "HTTP client",
        re.compile(
            r"python-requests|python-urllib|python/\d|aiohttp|go-http-client|libwww-perl|okhttp|node-fetch|axios/",
            re.I,
        ),
    ),
    ("Generic bot", re.compile(r"\bbot\b|crawler|spider|scraper|headlesschrome|\bworker\b", re.I)),
)

# Categories confident enough to auto-block the moment they touch a
# non-exempt path (see BlockedIPMiddleware) -- deliberately excludes
# "HTTP client" (could be an internal monitor/test, not necessarily
# hostile) and "Search crawler" (Googlebot/Bingbot; harmless against a site
# that's already private + Disallow: /, no reason to burn a block-list
# entry on it).
AUTO_BLOCK_BOT_LABELS = ("AI crawler", "Generic bot")


def classify_bot(user_agent):
    if not user_agent:
        return None
    for label, pattern in BOT_SIGNATURES:
        if pattern.search(user_agent):
            return label
    return None
