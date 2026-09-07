"""Real IP-level blocking, enforced by
tpweb.middleware.access_control.BlockedIPMiddleware on every request --
distinct from LoginRequiredMiddleware, which just redirects anonymous
traffic to the login page. Blocking is fully automatic (BlockedIPMiddleware
calls block_ip() itself for a recognized bot); unblocking happens in the
Django admin (BlockedIPAdmin routes deletes through unblock_ip() here).
"""

from django.core.cache import cache

from tpweb.models.BlockedIP import BlockedIP

# Read on (almost) every request by the middleware, so the full blocked-IP
# set is cached rather than hit the DB per request. block_ip()/unblock_ip()
# invalidate this explicitly, so the TTL is only a safety net for a change
# made outside those two functions (e.g. straight in the Django admin).
BLOCKED_IPS_CACHE_KEY = "Target:blocked_ips"
BLOCKED_IPS_CACHE_TTL_SECONDS = 60


def _blocked_ip_set():
    cached = cache.get(BLOCKED_IPS_CACHE_KEY)
    if cached is not None:
        return cached
    value = set(BlockedIP.objects.values_list("ip", flat=True))
    cache.set(BLOCKED_IPS_CACHE_KEY, value, BLOCKED_IPS_CACHE_TTL_SECONDS)
    return value


def is_ip_blocked(ip):
    if not ip:
        return False
    return ip in _blocked_ip_set()


def block_ip(ip, blocked_by=None, reason=""):
    """Idempotent -- blocking an already-blocked IP just updates who/why."""
    blocked, _created = BlockedIP.objects.update_or_create(
        ip=ip, defaults={"blocked_by": blocked_by, "reason": reason}
    )
    cache.delete(BLOCKED_IPS_CACHE_KEY)
    return blocked


def unblock_ip(ip):
    deleted, _ = BlockedIP.objects.filter(ip=ip).delete()
    cache.delete(BLOCKED_IPS_CACHE_KEY)
    return deleted > 0
