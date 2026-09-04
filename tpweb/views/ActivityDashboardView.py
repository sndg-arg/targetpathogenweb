from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import render
from django.views import View

from tpweb.services.activity_dashboard import build_activity_dashboard_data


class ActivityDashboardView(LoginRequiredMixin, UserPassesTestMixin, View):
    template_name = "activity/dashboard.html"

    def test_func(self):
        return self.request.user.has_perm("tpweb.can_view_activity")

    def get(self, request, *args, **kwargs):
        return render(
            request,
            self.template_name,
            {"activity_dashboard_data": build_activity_dashboard_data()},
        )
