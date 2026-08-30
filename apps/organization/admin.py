from django.contrib import admin

from apps.organization.models import Branch, Office


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


# Zone no se registra a propósito. El modelo sigue existiendo porque es
# llave foránea de CustomerAddress y WorkOrder, y retirarlo del esquema
# es un refactor aparte, no una decisión de esta pantalla.
