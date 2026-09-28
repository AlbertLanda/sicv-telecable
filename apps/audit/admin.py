from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "branch", "description", "status_code")
    list_filter = ("branch", "method", "status_code")
    search_fields = (
        "actor__username",
        "actor__first_name",
        "actor__last_name",
        "description",
        "route_name",
        "path",
    )
    readonly_fields = (
        "actor",
        "branch",
        "method",
        "route_name",
        "path",
        "status_code",
        "description",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
