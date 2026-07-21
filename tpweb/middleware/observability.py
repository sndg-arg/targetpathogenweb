import logging
import time


logger = logging.getLogger("tpweb.request")


NOINDEX_PATH_PREFIXES = (
    "/binder/",
    "/structure/",
    "/structure_export/",
    "/structure_raw/",
)


def _first_forwarded_ip(forwarded_for):
    if not forwarded_for:
        return ""
    return forwarded_for.split(",")[0].strip()


def _single_line(value, limit=240):
    value = (value or "").strip()
    if not value:
        return "-"
    value = " ".join(value.split())
    if len(value) > limit:
        return value[: limit - 1] + "..."
    return value


class RequestTimingMiddleware:
    """Log request duration and expose it via response headers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started_at = time.perf_counter()
        response = self.get_response(request)
        duration_ms = (time.perf_counter() - started_at) * 1000

        # X-Forwarded-For is set by Traefik; REMOTE_ADDR alone would just be the proxy's
        # own IP. Take the first hop (the original client) since a comma-separated chain
        # means the request passed through more than one proxy.
        forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
        real_ip = request.META.get("HTTP_X_REAL_IP", "")
        remote_addr = request.META.get("REMOTE_ADDR", "")
        client_ip = _first_forwarded_ip(forwarded_for) or real_ip or remote_addr
        user_agent = _single_line(request.META.get("HTTP_USER_AGENT", ""))
        referer = _single_line(request.META.get("HTTP_REFERER", ""))

        if request.path.startswith(NOINDEX_PATH_PREFIXES):
            response["X-Robots-Tag"] = "noindex, nofollow"

        response["X-Request-Duration-Ms"] = f"{duration_ms:.1f}"
        logger.info(
            "request completed method=%s path=%s status=%s duration_ms=%s ip=%s remote_addr=%s x_forwarded_for=%r ua=%r referer=%r",
            request.method,
            request.path,
            response.status_code,
            round(duration_ms, 1),
            client_ip,
            remote_addr or "-",
            _single_line(forwarded_for, limit=360),
            user_agent,
            referer,
            extra={
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 1),
                "ip": client_ip,
                "remote_addr": remote_addr,
                "x_forwarded_for": forwarded_for,
                "user_agent": user_agent,
                "referer": referer,
            },
        )
        return response
