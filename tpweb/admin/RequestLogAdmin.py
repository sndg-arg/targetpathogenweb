from django.contrib import admin

from tpweb.models.RequestLog import RequestLog


@admin.register(RequestLog)
class RequestLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "user", "ip", "method", "path", "status_code"]
    list_filter = ["user", "method", "status_code"]
    search_fields = ["path", "ip", "user__username"]
    date_hierarchy = "created_at"
    list_select_related = ["user"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
