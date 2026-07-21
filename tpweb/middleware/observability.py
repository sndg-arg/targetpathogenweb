import logging
import time


logger = logging.getLogger("tpweb.request")


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
        client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else request.META.get("REMOTE_ADDR", "")
        user_agent = request.META.get("HTTP_USER_AGENT", "")
        referer = request.META.get("HTTP_REFERER", "")

        response["X-Request-Duration-Ms"] = f"{duration_ms:.1f}"
        logger.info(
            "request completed method=%s path=%s status=%s duration_ms=%s ip=%s ua=%s referer=%s",
            request.method,
            request.path,
            response.status_code,
            round(duration_ms, 1),
            client_ip,
            user_agent,
            referer,
            extra={
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 1),
                "ip": client_ip,
                "user_agent": user_agent,
                "referer": referer,
            },
        )
        return response
