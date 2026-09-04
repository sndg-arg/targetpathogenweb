from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import render
from django.views import View

from tpweb.services.activity_dashboard import (
    DEFAULT_ACTIVITY_WINDOW_DAYS,
    build_activity_dashboard_data,
)

# Fixed set rather than an arbitrary ?days=N -- every query in
# build_activity_dashboard_data() runs over the full window with no
# pagination, so an unbounded value could force a full-table scan back to
# whenever RequestLog logging started.
PERIOD_CHOICES_DAYS = (7, 14, 30, 90)


class ActivityDashboardView(LoginRequiredMixin, UserPassesTestMixin, View):
    template_name = "activity/dashboard.html"

    def test_func(self):
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
            },
        )

    def _resolve_window_days(self, request):
        raw = request.GET.get("days")
        try:
            days = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_ACTIVITY_WINDOW_DAYS
        return days if days in PERIOD_CHOICES_DAYS else DEFAULT_ACTIVITY_WINDOW_DAYS
