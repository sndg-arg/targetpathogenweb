from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View

from tpweb.models.BlockedIP import BlockedIP
from tpweb.services.activity_dashboard import (
    DEFAULT_ACTIVITY_WINDOW_DAYS,
    build_activity_dashboard_data,
)
from tpweb.services.ip_blocking import block_ip, unblock_ip

# Fixed set rather than an arbitrary ?days=N -- every query in
# build_activity_dashboard_data() runs over the full window with no
# pagination, so an unbounded value could force a full-table scan back to
# whenever RequestLog logging started.
PERIOD_CHOICES_DAYS = (7, 14, 30, 90)


class ActivityDashboardView(LoginRequiredMixin, UserPassesTestMixin, View):
    template_name = "activity/dashboard.html"

    def test_func(self):
        # Blocking/unblocking an IP shuts a visitor out of the whole site,
        # not just this dashboard -- reserve that to the owner rather than
        # every account with the (already sensitive) can_view_activity grant.
        if self.request.method == "POST":
            return self.request.user.is_superuser
        return self.request.user.has_perm("tpweb.can_view_activity")

    def get(self, request, *args, **kwargs):
        window_days = self._resolve_window_days(request)
        return render(
            request,
            self.template_name,
            {
                "activity_dashboard_data": build_activity_dashboard_data(days=window_days),
                "window_days": window_days,
                "period_choices": [
                    {"days": days, "label": f"{days}d"} for days in PERIOD_CHOICES_DAYS
                ],
                "blocked_ips": BlockedIP.objects.select_related("blocked_by"),
            },
        )

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        ip = (request.POST.get("ip") or "").strip()
        window_days = self._resolve_window_days(request)
        if not ip:
            messages.error(request, "Missing IP address.")
        elif action == "block":
            block_ip(ip, blocked_by=request.user, reason=request.POST.get("reason", ""))
            messages.success(request, f"Blocked {ip} from the entire site.")
        elif action == "unblock":
            unblock_ip(ip)
            messages.success(request, f"Unblocked {ip}.")
        else:
            messages.error(request, "Unknown action.")
        return redirect(f"{reverse('tpwebapp:activity_dashboard')}?days={window_days}")

    def _resolve_window_days(self, request):
        raw = request.GET.get("days")
        try:
            days = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_ACTIVITY_WINDOW_DAYS
        return days if days in PERIOD_CHOICES_DAYS else DEFAULT_ACTIVITY_WINDOW_DAYS
