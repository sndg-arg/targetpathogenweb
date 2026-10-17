import ipaddress
import logging

import requests
from django.core.cache import cache

logger = logging.getLogger("tpweb.request")

LOCATION_CACHE_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days -- an IP's location rarely changes
LOCATION_FAILURE_CACHE_TTL_SECONDS = 60 * 60  # 1 hour -- don't hammer the API on a transient miss
_LOOKUP_TIMEOUT_SECONDS = 3
_MISSING = object()


def _is_public(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved)


def geolocate_ip(ip):
    """Country/city for a public IP, cached. Returns None for private IPs,
    malformed input, or a failed/unresolvable lookup."""
    if not ip or not _is_public(ip):
        return None

    cache_key = f"Target:iplocation:{ip}"
    cached = cache.get(cache_key, _MISSING)
    if cached is not _MISSING:
        return cached or None

    location = _fetch_location(ip)
    ttl = LOCATION_CACHE_TTL_SECONDS if location else LOCATION_FAILURE_CACHE_TTL_SECONDS
    cache.set(cache_key, location, ttl)
    return location


def _fetch_location(ip):
    try:
        response = requests.get(
            f"http://ip-api.com/json/{ip}",
            params={"fields": "status,country,countryCode,city,regionName"},
            timeout=_LOOKUP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        logger.exception("IP geolocation lookup failed for %s", ip)
        return None

    if payload.get("status") != "success":
        return None

    return {
        "country": payload.get("country") or "",
        "country_code": payload.get("countryCode") or "",
        "city": payload.get("city") or "",
        "region": payload.get("regionName") or "",
    }
