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

        response["X-Request-Duration-Ms"] = f"{duration_ms:.1f}"
        logger.info(
            "request completed",
            extra={
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 1),
            },
        )
        return response
