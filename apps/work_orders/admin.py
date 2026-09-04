from django.contrib import admin

from apps.work_orders.models import (
    OrderReason,
    OrderSubtype,
    OrderType,
    OrderCause,
    OrderResult,
    WorkOrder,
    WorkOrderAssignment,
    WorkOrderEvidence,
    WorkOrderFieldSheet,
    WorkOrderLiquidation,
    WorkOrderLiquidationCorrection,
    WorkOrderLiquidationItem,
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


class WorkOrderLiquidationInline(admin.StackedInline):
    model = WorkOrderLiquidation
    extra = 0

    readonly_fields = (
        "liquidated_by",
        "liquidated_at",
        "resolution_detail",
        "technical_notes",
        "network_element",
        "network_port",
        "equipment_serial",
        "signal_level_dbm",
        "cable_meters_used",
        "krill_reference",
        "review_status",
        "correction_count",
        "created_at",
        "updated_at",
    )

    can_delete = False

    def has_add_permission(self, request, obj=None):
        # La liquidación solo nace de liquidate_order().
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("liquidated_by")


class WorkOrderLiquidationItemInline(admin.TabularInline):
    model = WorkOrderLiquidationItem
    extra = 0

    readonly_fields = (
        "movement_type",
        "material_code",
        "material_name",
        "quantity",
        "unit_of_measure",
        "remarks",
        "created_at",
    )

    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class WorkOrderFieldSheetInline(admin.StackedInline):
    """
    Ficha técnica de campo, en modo consulta.

    Se completa desde la ficha web de la orden vía services.update_field_sheet();
    el Admin es solo un espejo de auditoría, igual que la liquidación.
    """

    model = WorkOrderFieldSheet
    extra = 0

    readonly_fields = (
        "nap",
        "terminal",
        "equipment_code",
        "seal_number",
        "notes",
        "updated_by",
        "created_at",
        "updated_at",
    )

    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("updated_by")


class WorkOrderEvidenceInline(admin.TabularInline):
    model = WorkOrderEvidence
    extra = 0

    readonly_fields = (
        "file",
        "description",
        "uploaded_by",
        "created_at",
    )

    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "uploaded_by", "liquidation"
        )


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
        "seller",
        "status",
        "priority",
        "attention_type",
        "scheduled_at",
        "liquidation_display",
        "liquidated_by_display",
        "liquidated_at_display",
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
    raw_id_fields = (
        "subscription",
        "assigned_technician",
        "seller",
        "created_by",
    )
    # `status` es de solo lectura también para impedir marcar LIQUIDATED a
    # mano y saltarse liquidate_order(): la liquidación exige su registro.
    readonly_fields = (
        "status",
        "assigned_technician",
        "scheduled_at",
        "started_at",
        "attended_at",
        "created_at",
        "updated_at",
    )
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
        "seller",
        "liquidation",
        "liquidation__liquidated_by",
    )
    inlines = [
        WorkOrderFieldSheetInline,
        WorkOrderLiquidationInline,
        WorkOrderEvidenceInline,
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

    @staticmethod
    def _liquidation(obj):
        """Liquidación de la orden, o None si todavía no fue liquidada."""
        try:
            return obj.liquidation
        except WorkOrder.liquidation.RelatedObjectDoesNotExist:
            return None

    @admin.display(description="Liquidada", boolean=True)
    def liquidation_display(self, obj):
        return self._liquidation(obj) is not None

    @admin.display(description="Liquidado por")
    def liquidated_by_display(self, obj):
        liquidation = self._liquidation(obj)

        return liquidation.liquidated_by if liquidation else "—"

    @admin.display(description="Fecha de liquidación")
    def liquidated_at_display(self, obj):
        liquidation = self._liquidation(obj)

        return liquidation.liquidated_at if liquidation else "—"


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


class WorkOrderLiquidationCorrectionInline(admin.TabularInline):
    """Traza de la única corrección, en modo consulta."""

    model = WorkOrderLiquidationCorrection
    extra = 0

    fields = (
        "corrected_by",
        "created_at",
        "correction_reason",
        "values_before",
        "values_after",
        "remarks",
    )

    readonly_fields = fields

    can_delete = False

    def has_add_permission(self, request, obj=None):
        # Las correcciones solo nacen de resubmit_liquidation().
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("corrected_by")


@admin.register(WorkOrderLiquidation)
class WorkOrderLiquidationAdmin(admin.ModelAdmin):
    list_display = (
        "work_order",
        "liquidated_by",
        "liquidated_at",
        "review_status",
        "correction_count",
        "correction_requested_by",
        "correction_requested_at",
        "validated_by",
        "validated_at",
        "equipment_serial",
    )
    list_filter = (
        "review_status",
        "correction_count",
        ("liquidated_by", admin.RelatedOnlyFieldListFilter),
        ("validated_by", admin.RelatedOnlyFieldListFilter),
        "liquidated_at",
    )
    search_fields = (
        "work_order__order_number",
        "resolution_detail",
        "technical_notes",
        "equipment_serial",
        "network_element",
    )
    list_select_related = (
        "work_order",
        "liquidated_by",
        "correction_requested_by",
        "validated_by",
    )
    date_hierarchy = "liquidated_at"
    readonly_fields = (
        "work_order",
        "liquidated_by",
        "liquidated_at",
        "resolution_detail",
        "technical_notes",
        "network_element",
        "network_port",
        "equipment_serial",
        "signal_level_dbm",
        "cable_meters_used",
        "krill_reference",
        # El ciclo de revisión completo es de solo lectura en el Admin: se
        # mueve únicamente por los servicios de services.py. En particular,
        # VALIDATED no puede marcarse desde un select.
        "review_status",
        "submitted_by",
        "submitted_at",
        "submission_remarks",
        "correction_count",
        "correction_reason",
        "correction_requested_by",
        "correction_requested_at",
        "resubmitted_at",
        "validated_by",
        "validated_at",
        "validation_remarks",
        "created_at",
        "updated_at",
    )
    inlines = [
        WorkOrderLiquidationItemInline,
        WorkOrderLiquidationCorrectionInline,
        WorkOrderEvidenceInline,
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WorkOrderLiquidationCorrection)
class WorkOrderLiquidationCorrectionAdmin(admin.ModelAdmin):
    """Consulta y auditoría de las correcciones aplicadas."""

    list_display = (
        "liquidation",
        "corrected_by",
        "created_at",
        "correction_reason",
    )
    list_filter = (
        "created_at",
        ("corrected_by", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = (
        "liquidation__work_order__order_number",
        "correction_reason",
        "remarks",
    )
    list_select_related = ("liquidation__work_order", "corrected_by")
    date_hierarchy = "created_at"

    readonly_fields = (
        "liquidation",
        "corrected_by",
        "correction_reason",
        "values_before",
        "values_after",
        "items_before",
        "items_after",
        "remarks",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WorkOrderEvidence)
class WorkOrderEvidenceAdmin(admin.ModelAdmin):
    list_display = (
        "work_order",
        "description",
        "file",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("created_at",)
    search_fields = ("work_order__order_number", "description")
    list_select_related = ("work_order", "uploaded_by", "liquidation")
    raw_id_fields = ("work_order", "liquidation", "uploaded_by")
    readonly_fields = ("created_at",)

    def has_delete_permission(self, request, obj=None):
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
