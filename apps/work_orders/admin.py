from django.contrib import admin

from apps.work_orders.models import (
    OrderReason,
    OrderSubtype,
    OrderType,
    OrderCause,
    OrderResult,
    WorkOrder,
    WorkOrderAssignment,
    WorkOrderReprogramming,
    WorkOrderStatusHistory,
)


@admin.register(OrderType)
class OrderTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")

@admin.register(OrderSubtype)
class OrderSubtypeAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "order_type",
        "is_active",
    )

    list_filter = (
        "order_type",
        "is_active",
    )

    search_fields = (
        "code",
        "name",
    )

@admin.register(OrderReason)
class OrderReasonAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "order_type", "classification", "is_active")
    list_filter = ("order_type", "classification", "is_active")
    search_fields = ("code", "name")

@admin.register(OrderCause)
class OrderCauseAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "order_type",
        "is_active",
    )

    list_filter = (
        "order_type",
        "is_active",
    )

    search_fields = (
        "code",
        "name",
    )

@admin.register(OrderResult)
class OrderResultAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "order_type",
        "is_success",
        "is_active",
    )

    list_filter = (
        "order_type",
        "is_success",
        "is_active",
    )

    search_fields = (
        "code",
        "name",
    )

class WorkOrderStatusHistoryInline(admin.TabularInline):
    model = WorkOrderStatusHistory
    extra = 0

    readonly_fields = (
        "previous_status",
        "new_status",
        "changed_by",
        "remarks",
        "changed_at",
    )

    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # El historial de estados solo se genera vía change_status().
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("changed_by")


class WorkOrderAssignmentInline(admin.TabularInline):
    model = WorkOrderAssignment
    extra = 0

    readonly_fields = (
        "technician",
        "assigned_by",
        "assigned_at",
        "unassigned_at",
        "remarks",
    )

    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "technician", "assigned_by"
        )


class WorkOrderReprogrammingInline(admin.TabularInline):
    model = WorkOrderReprogramming
    extra = 0

    readonly_fields = (
        "previous_schedule",
        "new_schedule",
        "reason",
        "created_by",
        "created_at",
    )

    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("created_by")


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "subscription",
        "customer_display",
        "order_type",
        "subtype",
        "reason",
        "cause",
        "result",
        "branch",
        "zone",
        "assigned_technician",
        "status",
        "priority",
        "attention_type",
        "scheduled_at",
        "created_at",
    )
    list_filter = (
        "status",
        ("branch", admin.RelatedOnlyFieldListFilter),
        ("zone", admin.RelatedOnlyFieldListFilter),
        ("assigned_technician", admin.RelatedOnlyFieldListFilter),
        ("order_type", admin.RelatedOnlyFieldListFilter),
        ("subtype", admin.RelatedOnlyFieldListFilter),
        "priority",
        "attention_type",
    )
    search_fields = (
        "order_number",
        "detail",
        "subscription__customer__document_number",
        "subscription__customer__code",
        "subscription__customer__first_name",
        "subscription__customer__paternal_surname",
        "subscription__customer__maternal_surname",
        "subscription__customer__business_name",
    )
    raw_id_fields = ("subscription", "assigned_technician", "created_by")
    readonly_fields = ("started_at", "attended_at", "created_at", "updated_at")
    date_hierarchy = "created_at"
    # Cubre las relaciones que se pintan en list_display y, además, el
    # segundo salto que hacen sus __str__: Subscription muestra su plan,
    # Zone muestra su sede y los catálogos muestran su tipo de orden.
    # Sin esto el changelist dispara una consulta por celda y por fila.
    list_select_related = (
        "subscription",
        "subscription__customer",
        "subscription__plan",
        "order_type",
        "subtype",
        "subtype__order_type",
        "reason",
        "reason__order_type",
        "cause",
        "cause__order_type",
        "result",
        "result__order_type",
        "branch",
        "zone",
        "zone__branch",
        "assigned_technician",
    )
    inlines = [
        WorkOrderStatusHistoryInline,
        WorkOrderAssignmentInline,
        WorkOrderReprogrammingInline,
    ]

    # Los __str__ de estos catálogos muestran su tipo de orden, y los de Zone
    # su sede. Sin este select_related el formulario consulta una vez por
    # cada <option> que pinta en el desplegable.
    RELATED_FORM_FIELDS = {
        "subtype": "order_type",
        "reason": "order_type",
        "cause": "order_type",
        "result": "order_type",
        "zone": "branch",
    }

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        related = self.RELATED_FORM_FIELDS.get(db_field.name)

        if related:
            kwargs["queryset"] = db_field.remote_field.model.objects.select_related(
                related
            )

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.display(description="Cliente", ordering="subscription__customer")
    def customer_display(self, obj):
        return obj.subscription.customer


@admin.register(WorkOrderStatusHistory)
class WorkOrderStatusHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "work_order",
        "previous_status",
        "new_status",
        "changed_by",
        "changed_at",
    )
    list_filter = ("new_status", "changed_at")
    search_fields = ("work_order__order_number",)
    list_select_related = ("work_order", "changed_by")
    readonly_fields = (
        "work_order",
        "previous_status",
        "new_status",
        "changed_by",
        "remarks",
        "changed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WorkOrderAssignment)
class WorkOrderAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "work_order",
        "technician",
        "assigned_by",
        "assigned_at",
        "unassigned_at",
    )
    list_filter = (("technician", admin.RelatedOnlyFieldListFilter), "assigned_at")
    search_fields = ("work_order__order_number",)
    list_select_related = ("work_order", "technician", "assigned_by")
    readonly_fields = (
        "work_order",
        "technician",
        "assigned_by",
        "assigned_at",
        "unassigned_at",
        "remarks",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(WorkOrderReprogramming)
class WorkOrderReprogrammingAdmin(admin.ModelAdmin):
    list_display = (
        "work_order",
        "previous_schedule",
        "new_schedule",
        "created_by",
        "created_at",
    )
    list_filter = ("created_at",)
    search_fields = ("work_order__order_number",)
    list_select_related = ("work_order", "created_by")
    readonly_fields = (
        "work_order",
        "previous_schedule",
        "new_schedule",
        "reason",
        "created_by",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
