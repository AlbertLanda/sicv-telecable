from django.contrib import admin

from apps.inventory.models import Material, WorkOrderMaterialMovement


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "unit_of_measure", "is_active")
    list_filter = ("unit_of_measure", "is_active")
    search_fields = ("code", "name")
    ordering = ("name",)


@admin.register(WorkOrderMaterialMovement)
class WorkOrderMaterialMovementAdmin(admin.ModelAdmin):
    list_display = (
        "work_order",
        "movement_type",
        "material",
        "quantity",
        "recorded_by",
        "updated_at",
    )
    list_filter = ("movement_type", "material")
    search_fields = ("work_order__order_number", "material__code", "material__name")
    readonly_fields = (
        "work_order",
        "movement_type",
        "material",
        "quantity",
        "remarks",
        "recorded_by",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
