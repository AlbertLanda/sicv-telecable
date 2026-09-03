from django.contrib import admin

from apps.organization.models import Branch, Office, Zone


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(Office)
class OfficeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "branch", "is_active")
    list_filter = ("branch", "is_active")
    search_fields = ("code", "name")


@admin.register(Zone)
class ZoneAdmin(admin.ModelAdmin):
    """Catálogo operativo de pueblos/sectores por sede."""

    list_display = ("name", "branch", "is_active")
    list_filter = ("branch", "is_active")
    search_fields = ("name", "branch__name", "branch__code")
    ordering = ("branch", "name")
