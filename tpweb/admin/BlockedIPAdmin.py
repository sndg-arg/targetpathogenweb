from django.contrib import admin

from tpweb.models.BlockedIP import BlockedIP
from tpweb.services.ip_blocking import unblock_ip


@admin.register(BlockedIP)
class BlockedIPAdmin(admin.ModelAdmin):
    list_display = ["ip", "reason", "blocked_by", "created_at"]
    search_fields = ["ip", "reason", "blocked_by__username"]
    list_select_related = ["blocked_by"]

    # Deleting straight off the queryset/instance would bypass
    # ip_blocking.unblock_ip()'s cache invalidation (BlockedIPMiddleware
    # caches the blocked-IP set for 60s), leaving the IP wrongly 403'd on
    # this and every other web process for up to that long. Routing through
    # unblock_ip() -- the same function the (now-removed) dashboard button
    # used -- keeps this the one place that both deletes and busts the cache.
    def delete_model(self, request, obj):
        unblock_ip(obj.ip)

    def delete_queryset(self, request, queryset):
        for ip in queryset.values_list("ip", flat=True):
            unblock_ip(ip)
