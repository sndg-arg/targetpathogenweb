import re
from collections import Counter
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Max
from django.db.models.functions import TruncDate
from django.utils import timezone

from tpweb.models.RequestLog import RequestLog
from tpweb.services.ip_geolocation import geolocate_ip
from tpweb.services.workspace import PUBLIC_WORKSPACE_USERNAME

ACTIVITY_WINDOW_DAYS = 30
TOP_PAGES_LIMIT = 10
TOP_LOCATIONS_LIMIT = 10
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


def _delta_pct(current, previous):
    """Signed % change vs a prior period. None when there's no prior period
    to compare against (nothing to divide by, not "0% change")."""
    if not previous:
        return None
    return round(((current - previous) / previous) * 100)


def _location_breakdown(window_qs, limit=TOP_LOCATIONS_LIMIT):
    rows = list(
        window_qs.exclude(ip__isnull=True)
        .values("ip")
        .annotate(count=Count("id"), last_seen=Max("created_at"))
        .order_by("-count")[:limit]
    )
    ip_list = [row["ip"] for row in rows]

    users_by_ip = {}
    for entry in (
        window_qs.filter(ip__in=ip_list)
        .exclude(user__isnull=True)
        .values("ip", "user__username")
        .distinct()
    ):
        users_by_ip.setdefault(entry["ip"], []).append(entry["user__username"])

    breakdown = []
    for row in rows:
        ip = row["ip"]
        location = geolocate_ip(ip)
        breakdown.append(
            {
                "ip": ip,
                "count": row["count"],
                "last_seen": row["last_seen"].isoformat(),
                "users": sorted(users_by_ip.get(ip, [])),
                "country": location["country"] if location else None,
                "country_code": location["country_code"] if location else None,
                "city": location["city"] if location else None,
            }
        )
    return breakdown


def build_activity_dashboard_data(days=ACTIVITY_WINDOW_DAYS):
    now = timezone.now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    window_start = now - timedelta(days=days)
    previous_window_start = window_start - timedelta(days=days)

    window_qs = RequestLog.objects.filter(created_at__gte=window_start)
    previous_qs = RequestLog.objects.filter(
        created_at__gte=previous_window_start, created_at__lt=window_start
    )

    requests_today = RequestLog.objects.filter(created_at__date=today).count()
    requests_yesterday = RequestLog.objects.filter(created_at__date=yesterday).count()
    unique_users = window_qs.exclude(user__isnull=True).values("user_id").distinct().count()
    previous_unique_users = (
        previous_qs.exclude(user__isnull=True).values("user_id").distinct().count()
    )
    unique_ips = window_qs.exclude(ip__isnull=True).values("ip").distinct().count()
    previous_unique_ips = previous_qs.exclude(ip__isnull=True).values("ip").distinct().count()
    errors = window_qs.filter(status_code__gte=400).count()
    previous_errors = previous_qs.filter(status_code__gte=400).count()

    kpis = {
        "requests_today": requests_today,
        "requests_today_delta_pct": _delta_pct(requests_today, requests_yesterday),
        "unique_users": unique_users,
        "unique_users_delta_pct": _delta_pct(unique_users, previous_unique_users),
        "unique_ips": unique_ips,
        "unique_ips_delta_pct": _delta_pct(unique_ips, previous_unique_ips),
        "errors": errors,
        "errors_delta_pct": _delta_pct(errors, previous_errors),
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

    locations = _location_breakdown(window_qs)

    return {
        "kpis": kpis,
        "timeseries": timeseries,
        "status_breakdown": status_breakdown,
        "top_pages": top_pages,
        "accounts": accounts,
        "locations": locations,
    }
