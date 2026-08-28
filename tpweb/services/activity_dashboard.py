import re
from collections import Counter
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from tpweb.models.RequestLog import RequestLog
from tpweb.services.workspace import PUBLIC_WORKSPACE_USERNAME

ACTIVITY_WINDOW_DAYS = 30
TOP_PAGES_LIMIT = 10
STATUS_BUCKETS = ("2xx", "3xx", "4xx", "5xx")

_ID_SEGMENT = re.compile(r"^\d+$")


def _normalize_path(path):
    """Collapse numeric-id segments so /protein/123 and /protein/456 count
    as the same "which section is popular" bucket instead of fragmenting."""
    segments = path.strip("/").split("/")
    if segments == [""]:
        return "/"
    normalized = ["<id>" if _ID_SEGMENT.match(seg) else seg for seg in segments]
    return "/" + "/".join(normalized)


def _status_bucket(status_code):
    if 200 <= status_code < 300:
        return "2xx"
    if 300 <= status_code < 400:
        return "3xx"
    if 400 <= status_code < 500:
        return "4xx"
    return "5xx"


def build_activity_dashboard_data(days=ACTIVITY_WINDOW_DAYS):
    now = timezone.now()
    today = now.date()
    window_start = now - timedelta(days=days)
    window_qs = RequestLog.objects.filter(created_at__gte=window_start)

    kpis = {
        "requests_today": RequestLog.objects.filter(created_at__date=today).count(),
        "unique_users": window_qs.exclude(user__isnull=True).values("user_id").distinct().count(),
        "unique_ips": window_qs.exclude(ip__isnull=True).values("ip").distinct().count(),
        "errors": window_qs.filter(status_code__gte=400).count(),
        "window_days": days,
    }

    counts_by_day = {
        row["day"]: row["count"]
        for row in window_qs.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
    }
    timeseries = [
        {
            "date": (today - timedelta(days=offset)).isoformat(),
            "count": counts_by_day.get(today - timedelta(days=offset), 0),
        }
        for offset in range(days - 1, -1, -1)
    ]

    status_counts = Counter(
        _status_bucket(code) for code in window_qs.values_list("status_code", flat=True)
    )
    status_breakdown = [
        {"bucket": bucket, "count": status_counts.get(bucket, 0)} for bucket in STATUS_BUCKETS
    ]

    path_counts = Counter(_normalize_path(p) for p in window_qs.values_list("path", flat=True))
    top_pages = [
        {"path": path, "count": count} for path, count in path_counts.most_common(TOP_PAGES_LIMIT)
    ]

    accounts = [
        {
            "username": u.username,
            "is_superuser": u.is_superuser,
            "last_login": u.last_login.isoformat() if u.last_login else None,
        }
        for u in get_user_model()
        .objects.filter(is_active=True)
        .exclude(username=PUBLIC_WORKSPACE_USERNAME)
        .order_by("username")
    ]

    return {
        "kpis": kpis,
        "timeseries": timeseries,
        "status_breakdown": status_breakdown,
        "top_pages": top_pages,
        "accounts": accounts,
    }
