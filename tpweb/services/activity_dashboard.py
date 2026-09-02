import re
from collections import Counter
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count, Max
from django.db.models.functions import TruncDate
from django.utils import timezone

from tpweb.middleware.access_control import EXEMPT_PATH_PREFIXES
from tpweb.models.RequestLog import RequestLog
from tpweb.services.ip_geolocation import geolocate_ip
from tpweb.services.workspace import PUBLIC_WORKSPACE_USERNAME

ACTIVITY_WINDOW_DAYS = 30
TOP_PAGES_LIMIT = 10
TOP_LOCATIONS_LIMIT = 10
TOP_ERROR_PATHS_LIMIT = 10
STATUS_BUCKETS = ("2xx", "3xx", "4xx", "5xx")

# Allauth's login view -- an anonymous POST here is someone (or something)
# actually submitting a username/password, not just wandering into a gated
# page. A successful POST logs in with `user` already set on the request
# (login() runs inside the view, before the middleware logs it), so
# `user__isnull=True` on this prefix means the attempt failed.
LOGIN_ATTEMPT_PATH_PREFIX = "/accounts/login"

_ID_SEGMENT = re.compile(r"^\d+$")

# Keep in sync with KNOWN_BOT_SIGNATURES in static/js/pages/activity-dashboard.js
# (the JS copy badges individual rows; this one drives the aggregate summary
# below, which needs every blocked request in the window, not just the
# top-10-by-IP rows the page actually renders -- so the same classification
# has to live server-side too rather than being computed once in JS).
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


def _classify_bot(user_agent):
    if not user_agent:
        return None
    for label, pattern in BOT_SIGNATURES:
        if pattern.search(user_agent):
            return label
    return None


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


def _ip_breakdown(qs, limit=TOP_LOCATIONS_LIMIT):
    """Group an already-scoped queryset by IP: count, last seen, geolocation,
    the single most common user agent, and how many distinct paths it hit.

    The latter two are the cheap bot signal: a scanner's user agent tends to
    be a bare HTTP client (curl/python-requests/Go-http-client) or a scanner
    name, and it probes many different routes, while a person on a browser
    sticks to a handful of pages with a real browser UA."""
    rows = list(
        qs.exclude(ip__isnull=True)
        .values("ip")
        .annotate(
            count=Count("id"),
            last_seen=Max("created_at"),
            distinct_paths=Count("path", distinct=True),
        )
        .order_by("-count")[:limit]
    )
    ip_list = [row["ip"] for row in rows]

    # Plain Python tally instead of a second annotate(Count("user_agent")):
    # we want the single most-common UA per IP, not a count of each distinct
    # one, so grouping by (ip, user_agent) and picking the max per ip in SQL
    # is more work than just tallying it here.
    agents_by_ip = {}
    for ip, ua in qs.filter(ip__in=ip_list).values_list("ip", "user_agent"):
        agents_by_ip.setdefault(ip, Counter())[ua or ""] += 1

    breakdown = []
    for row in rows:
        ip = row["ip"]
        location = geolocate_ip(ip)
        top_agents = agents_by_ip.get(ip)
        breakdown.append(
            {
                "ip": ip,
                "count": row["count"],
                "last_seen": row["last_seen"].isoformat(),
                "distinct_paths": row["distinct_paths"],
                "user_agent": top_agents.most_common(1)[0][0] if top_agents else "",
                "country": location["country"] if location else None,
                "country_code": location["country_code"] if location else None,
                "city": location["city"] if location else None,
                "region": location["region"] if location else None,
            }
        )
    return breakdown


def _authenticated_location_breakdown(window_qs, limit=TOP_LOCATIONS_LIMIT):
    """Where real, logged-in sessions connect from -- one row per IP, top by
    request volume, annotated with which account(s) used it."""
    authenticated_qs = window_qs.exclude(user__isnull=True)
    breakdown = _ip_breakdown(authenticated_qs, limit)
    ip_list = [row["ip"] for row in breakdown]

    # Plain Python dedup instead of .values(...).distinct(): RequestLog's
    # default ordering (-created_at) isn't in the selected fields, so Django
    # pulls it into the query to satisfy ORDER BY -- which then makes every
    # row "distinct" again (each request has its own timestamp) and defeats
    # the dedup entirely.
    users_by_ip = {}
    for ip, username in authenticated_qs.filter(ip__in=ip_list).values_list("ip", "user__username"):
        users_by_ip.setdefault(ip, set()).add(username)

    for row in breakdown:
        row["users"] = sorted(users_by_ip.get(row["ip"], set()))
    return breakdown


def _login_attempts_breakdown(window_qs, limit=TOP_LOCATIONS_LIMIT):
    """IPs that actually tried a username/password and failed -- a real
    (if mistaken) person, or credential-stuffing. Kept separate from
    _blocked_attempts_breakdown: that bucket is everyone who got redirected
    to the login wall on a random path without ever attempting to log in,
    which is almost entirely bots/scanners, not login attempts."""
    login_qs = window_qs.filter(
        user__isnull=True, method="POST", path__startswith=LOGIN_ATTEMPT_PATH_PREFIX
    )
    return _ip_breakdown(login_qs, limit)


def _blocked_queryset(window_qs):
    """Anonymous requests to a non-exempt path -- exactly what
    LoginRequiredMiddleware actually redirected. Shared by the blocked-
    attempts breakdown and the KPI/timeseries split below so both agree on
    the same definition of "blocked" (excludes EXEMPT_PATH_PREFIXES, mainly
    /accounts/: an anonymous visit to the login page itself is completely
    normal traffic, never redirected, not a blocked attempt)."""
    blocked_qs = window_qs.filter(user__isnull=True)
    for prefix in EXEMPT_PATH_PREFIXES:
        blocked_qs = blocked_qs.exclude(path__startswith=prefix)
    return blocked_qs


def _blocked_attempts_breakdown(window_qs, limit=TOP_LOCATIONS_LIMIT):
    """IPs that hit the login wall without ever attempting to authenticate --
    scans, bots, or a collaborator who hasn't been given a login yet. This
    also means actual login attempts (see _login_attempts_breakdown) never
    land here, since /accounts/ is excluded wholesale by _blocked_queryset."""
    return _ip_breakdown(_blocked_queryset(window_qs), limit)


def _bot_traffic_summary(window_qs):
    """Classify EVERY blocked request in the window (not just the
    top-10-by-IP rows _blocked_attempts_breakdown renders) by bot type and
    tally distinct IPs + total requests per type.

    A handful of IPs belonging to the same crawler can otherwise fill most
    of that top-10 table on their own, both overstating how many distinct
    actors are visible and crowding out other, less prolific ones -- this
    is the "how much of this is which kind of noise" rollup that table
    alone can't answer."""
    stats_by_label = {}
    for ip, user_agent in _blocked_queryset(window_qs).values_list("ip", "user_agent"):
        label = _classify_bot(user_agent) or "Unclassified"
        entry = stats_by_label.setdefault(label, {"ips": set(), "requests": 0})
        if ip:
            entry["ips"].add(ip)
        entry["requests"] += 1

    summary = [
        {"label": label, "ip_count": len(stats["ips"]), "requests": stats["requests"]}
        for label, stats in stats_by_label.items()
    ]
    summary.sort(key=lambda row: row["requests"], reverse=True)
    return summary


# Well-known noise every browser/crawler requests unprompted (favicon,
# robots.txt) -- a 404 on these isn't a real problem to investigate, and
# without this filter it can crowd out genuinely broken routes in a
# TOP_ERROR_PATHS_LIMIT-sized list.
_NOISE_ERROR_PATH_SUFFIXES = ("/favicon.ico", "/robots.txt", "/apple-touch-icon.png")


def _top_error_paths(window_qs, limit=TOP_ERROR_PATHS_LIMIT):
    """Which routes actually produced 4xx/5xx responses, with a breakdown of
    which exact status codes -- the "what broke" complement to the aggregate
    Errors KPI, so a spike doesn't require a trip to the admin to find out
    what's failing."""
    codes_by_path = {}
    for path, code in window_qs.filter(status_code__gte=400).values_list("path", "status_code"):
        if path.endswith(_NOISE_ERROR_PATH_SUFFIXES):
            continue
        normalized = _normalize_path(path)
        codes_by_path.setdefault(normalized, Counter())[code] += 1

    ranked = sorted(codes_by_path.items(), key=lambda item: sum(item[1].values()), reverse=True)
    return [
        {
            "path": path,
            "count": sum(codes.values()),
            "codes": [{"code": code, "count": count} for code, count in codes.most_common()],
        }
        for path, codes in ranked[:limit]
    ]


def build_activity_dashboard_data(days=ACTIVITY_WINDOW_DAYS):
    now = timezone.now()
    # localdate(), not now.date(): a plain .date() on the UTC-aware `now`
    # gives the UTC calendar date, while the __date lookups below convert to
    # the server's active time zone -- on a non-UTC server those two
    # boundaries disagree (today can show 0 while "today" timestamps already
    # exist), so both sides need to agree on the same time zone.
    today = timezone.localdate()
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
    # unique_ips counts every scanner/crawler IP alongside real sessions --
    # this is the "how many of those were an actual logged-in visitor"
    # context line under that KPI, so the headline number doesn't read as
    # audience size on its own.
    unique_ips_authenticated = (
        window_qs.exclude(user__isnull=True)
        .exclude(ip__isnull=True)
        .values("ip")
        .distinct()
        .count()
    )
    errors = window_qs.filter(status_code__gte=400).count()
    previous_errors = previous_qs.filter(status_code__gte=400).count()

    # How much of the window's traffic never made it past the login wall --
    # the "how much of this is noise" headline that used to require paging
    # down to the status-code chart (3xx bucket) to even notice.
    total_requests = window_qs.count()
    blocked_requests = _blocked_queryset(window_qs).count()
    blocked_requests_pct = round((blocked_requests / total_requests) * 100) if total_requests else 0

    kpis = {
        "requests_today": requests_today,
        "requests_today_delta_pct": _delta_pct(requests_today, requests_yesterday),
        "unique_users": unique_users,
        "unique_users_delta_pct": _delta_pct(unique_users, previous_unique_users),
        "unique_ips": unique_ips,
        "unique_ips_delta_pct": _delta_pct(unique_ips, previous_unique_ips),
        "unique_ips_authenticated": unique_ips_authenticated,
        "errors": errors,
        "errors_delta_pct": _delta_pct(errors, previous_errors),
        "blocked_requests": blocked_requests,
        "blocked_requests_pct": blocked_requests_pct,
        "window_days": days,
    }

    # Split by authenticated/anonymous rather than one combined line -- with
    # login-wall scanning now a large share of traffic (see blocked_requests
    # above), a single "Requests" line reads any bot ramp-up as real growth.
    def _counts_by_day(qs):
        return {
            row["day"]: row["count"]
            for row in qs.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(count=Count("id"))
        }

    authenticated_counts_by_day = _counts_by_day(window_qs.exclude(user__isnull=True))
    anonymous_counts_by_day = _counts_by_day(window_qs.filter(user__isnull=True))
    timeseries = [
        {
            "date": (today - timedelta(days=offset)).isoformat(),
            "authenticated": authenticated_counts_by_day.get(today - timedelta(days=offset), 0),
            "anonymous": anonymous_counts_by_day.get(today - timedelta(days=offset), 0),
        }
        for offset in range(days - 1, -1, -1)
    ]

    status_counts = Counter(
        _status_bucket(code) for code in window_qs.values_list("status_code", flat=True)
    )
    status_breakdown = [
        {"bucket": bucket, "count": status_counts.get(bucket, 0)} for bucket in STATUS_BUCKETS
    ]

    # Authenticated requests only -- the whole site sits behind a login wall,
    # so an anonymous hit here never actually saw the page, it just bounced
    # off the redirect. Counting those in "what they look at" let scanner
    # traffic (e.g. a crawler probing every /protein/<id>) outweigh the two
    # real accounts' actual usage.
    path_counts = Counter(
        _normalize_path(p)
        for p in window_qs.exclude(user__isnull=True).values_list("path", flat=True)
    )
    top_pages = [
        {"path": path, "count": count} for path, count in path_counts.most_common(TOP_PAGES_LIMIT)
    ]

    accounts = [
        {
            "username": u.username,
            "is_superuser": u.is_superuser,
            "is_staff": u.is_staff,
            "last_login": u.last_login.isoformat() if u.last_login else None,
        }
        for u in get_user_model()
        .objects.filter(is_active=True)
        .exclude(username=PUBLIC_WORKSPACE_USERNAME)
        .order_by("username")
    ]

    locations = _authenticated_location_breakdown(window_qs)
    login_attempts = _login_attempts_breakdown(window_qs)
    blocked_attempts = _blocked_attempts_breakdown(window_qs)
    bot_traffic_summary = _bot_traffic_summary(window_qs)
    top_error_paths = _top_error_paths(window_qs)

    # Lets the chart flag "logging only just started" instead of a real
    # traffic ramp-up when the log's actual history is shorter than the
    # requested window (e.g. right after RequestLog itself was deployed).
    earliest_log_at = (
        RequestLog.objects.order_by("created_at").values_list("created_at", flat=True).first()
    )

    return {
        "kpis": kpis,
        "timeseries": timeseries,
        "logging_started_at": earliest_log_at.isoformat() if earliest_log_at else None,
        "status_breakdown": status_breakdown,
        "top_pages": top_pages,
        "top_error_paths": top_error_paths,
        "accounts": accounts,
        "locations": locations,
        "login_attempts": login_attempts,
        "blocked_attempts": blocked_attempts,
        "bot_traffic_summary": bot_traffic_summary,
    }
