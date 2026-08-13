from django.contrib import admin

from apps.work_orders.models import (
    OrderReason,
    OrderType,
    WorkOrder,
    WorkOrderStatusHistory,
)


@admin.register(OrderType)
class OrderTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(OrderReason)
class OrderReasonAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "order_type", "classification", "is_active")
    list_filter = ("order_type", "classification", "is_active")
    search_fields = ("code", "name")


class WorkOrderStatusHistoryInline(admin.TabularInline):
    model = WorkOrderStatusHistory
    extra = 0
    readonly_fields = ("changed_at",)


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "subscription",
        "order_type",
        "reason",
        "branch",
        "zone",
        "attention_type",
        "status",
        "priority",
        "created_at",
    )
    list_filter = ("status", "priority", "attention_type", "order_type", "branch")
    search_fields = ("order_number", "detail")
    raw_id_fields = ("subscription", "assigned_technician", "created_by")
    readonly_fields = ("created_at", "updated_at")
    inlines = [WorkOrderStatusHistoryInline]


@admin.register(WorkOrderStatusHistory)
class WorkOrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("work_order", "previous_status", "new_status", "changed_by", "changed_at")
    list_filter = ("new_status",)
    readonly_fields = ("changed_at",)
