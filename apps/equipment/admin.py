from django.contrib import admin

from .models import Equipment, EquipmentAssignment, EquipmentReview


class HistoryAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Equipment)
class EquipmentAdmin(HistoryAdmin):
    list_display = ("serial_number", "mac_address", "kind", "branch", "status")
    search_fields = ("serial_number", "mac_address")


@admin.register(EquipmentAssignment)
class EquipmentAssignmentAdmin(HistoryAdmin):
    list_display = ("equipment", "service_code_snapshot", "assigned_at", "removed_at")


admin.site.register(EquipmentReview, HistoryAdmin)
