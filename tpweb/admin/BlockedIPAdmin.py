from django.contrib import admin

from tpweb.models.BlockedIP import BlockedIP


@admin.register(BlockedIP)
class BlockedIPAdmin(admin.ModelAdmin):
    list_display = ["ip", "reason", "blocked_by", "created_at"]
    search_fields = ["ip", "reason", "blocked_by__username"]
    list_select_related = ["blocked_by"]
