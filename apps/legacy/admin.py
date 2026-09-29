from django import forms
from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from .models import (
    LegacyChargeSnapshot,
    LegacyContractSnapshot,
    LegacyPaymentAllocationSnapshot,
    LegacyPaymentSnapshot,
    LegacyReceiptSnapshot,
    LegacyRecord,
    LegacyRecordCorrection,
    LegacyWorkOrderEvidence,
    LegacyWorkOrderMaterial,
    LegacyWorkOrderParticipant,
    LegacyWorkOrderSnapshot,
)


class LegacyRecordAdminForm(forms.ModelForm):
    correction_reason = forms.CharField(
        required=False,
        label="Motivo de la corrección",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=(
            "Obligatorio cuando se modifica la interpretación normalizada. "
            "El payload original nunca se modifica."
        ),
    )

    class Meta:
        model = LegacyRecord
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        if (
            self.instance.pk
            and "normalized_payload" in self.changed_data
            and not (cleaned.get("correction_reason") or "").strip()
        ):
            self.add_error(
                "correction_reason",
                "Indique por qué se corrige el dato migrado.",
            )
        return cleaned


@admin.register(LegacyRecord)
class LegacyRecordAdmin(admin.ModelAdmin):
    form = LegacyRecordAdminForm
    list_display = (
        "source",
        "entity_type",
        "legacy_id",
        "customer",
        "subscription",
        "review_status",
        "imported_at",
    )
    list_filter = ("source", "entity_type", "review_status")
    search_fields = (
        "legacy_id",
        "customer__code",
        "customer__document_number",
        "subscription__service_code",
    )
    autocomplete_fields = ("subscription",)
    readonly_fields = (
        "source",
        "entity_type",
        "legacy_id",
        "raw_payload",
        "imported_by",
        "imported_at",
        "validated_by",
        "validated_at",
        "updated_at",
    )
    fields = (
        "source",
        "entity_type",
        "legacy_id",
        "customer",
        "subscription",
        "target_content_type",
        "target_object_id",
        "raw_payload",
        "normalized_payload",
        "correction_reason",
        "review_status",
        "review_notes",
        "imported_by",
        "imported_at",
        "validated_by",
        "validated_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        previous_payload = None
        if change and "normalized_payload" in form.changed_data:
            previous_payload = (
                LegacyRecord.objects
                .filter(pk=obj.pk)
                .values_list("normalized_payload", flat=True)
                .first()
            )
            obj.review_status = LegacyRecord.ReviewStatus.CORRECTED

        if (
            obj.review_status == LegacyRecord.ReviewStatus.VALIDATED
            and obj.validated_at is None
        ):
            obj.validated_by = request.user
            obj.validated_at = timezone.now()

        super().save_model(request, obj, form, change)

        if previous_payload is not None and previous_payload != obj.normalized_payload:
            LegacyRecordCorrection.objects.create(
                record=obj,
                previous_payload=previous_payload,
                new_payload=obj.normalized_payload,
                reason=form.cleaned_data["correction_reason"].strip(),
                corrected_by=request.user,
            )


@admin.register(LegacyRecordCorrection)
class LegacyRecordCorrectionAdmin(admin.ModelAdmin):
    list_display = ("record", "corrected_by", "created_at")
    list_filter = ("record__entity_type", "created_at")
    search_fields = ("record__legacy_id", "reason")
    readonly_fields = (
        "record",
        "previous_payload",
        "new_payload",
        "reason",
        "corrected_by",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False



class LegacyCorrectionReasonForm(forms.ModelForm):
    correction_reason = forms.CharField(
        required=False,
        label="Motivo de la corrección",
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Obligatorio al modificar un dato histórico normalizado.",
    )

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and self.changed_data:
            changed = set(self.changed_data) - {"correction_reason"}
            if changed and not (cleaned.get("correction_reason") or "").strip():
                self.add_error(
                    "correction_reason",
                    "Indique por qué se corrige el dato histórico.",
                )
        return cleaned


class LegacyAuditedAdminMixin:
    """Sincroniza correcciones estructuradas con LegacyRecord."""

    def _legacy_record_for(self, obj):
        content_type = ContentType.objects.get_for_model(
            obj,
            for_concrete_model=False,
        )
        return LegacyRecord.objects.filter(
            target_content_type=content_type,
            target_object_id=obj.pk,
        ).first()

    def save_model(self, request, obj, form, change):
        before = None
        if change and obj.pk:
            previous = type(obj).objects.get(pk=obj.pk)
            before = previous.normalized_snapshot()

        super().save_model(request, obj, form, change)

        if before is None:
            return

        after = obj.normalized_snapshot()
        if before == after:
            return

        record = self._legacy_record_for(obj)
        if record is None:
            return

        reason = (form.cleaned_data.get("correction_reason") or "").strip()
        record.apply_normalized_correction(
            after,
            user=request.user,
            reason=reason,
        )


class LegacyReadOnlyInlineMixin:
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class LegacyWorkOrderParticipantInline(
    LegacyReadOnlyInlineMixin,
    admin.TabularInline,
):
    model = LegacyWorkOrderParticipant
    readonly_fields = (
        "legacy_user_code",
        "name_snapshot",
        "role_snapshot",
        "started_at",
        "ended_at",
        "notes",
    )


class LegacyWorkOrderMaterialInline(
    LegacyReadOnlyInlineMixin,
    admin.TabularInline,
):
    model = LegacyWorkOrderMaterial
    readonly_fields = (
        "legacy_material_code",
        "name_snapshot",
        "quantity",
        "unit_snapshot",
        "movement_type",
        "notes",
    )


class LegacyWorkOrderEvidenceInline(
    LegacyReadOnlyInlineMixin,
    admin.TabularInline,
):
    model = LegacyWorkOrderEvidence
    readonly_fields = (
        "original_name",
        "legacy_reference",
        "file",
        "description",
    )


@admin.register(LegacyContractSnapshot)
class LegacyContractSnapshotAdmin(LegacyAuditedAdminMixin, admin.ModelAdmin):
    form = type(
        "LegacyContractSnapshotForm",
        (LegacyCorrectionReasonForm,),
        {"Meta": type(
            "Meta",
            (),
            {"model": LegacyContractSnapshot, "fields": "__all__"},
        )},
    )
    list_display = (
        "legacy_contract_number",
        "customer",
        "subscription",
        "plan_name_snapshot",
        "start_date",
        "status",
        "is_validated",
    )
    list_filter = ("status", "modality", "is_validated")
    search_fields = (
        "legacy_contract_number",
        "customer__code",
        "subscription__service_code",
        "plan_name_snapshot",
    )
    autocomplete_fields = ("subscription", "service_type", "plan")
    readonly_fields = ("customer", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": (
            "customer",
            "subscription",
            "legacy_contract_number",
            "service_type",
            "service_name_snapshot",
            "plan",
            "plan_name_snapshot",
            "equipment_snapshot",
        )}),
        ("Historia", {"fields": (
            "status",
            "legacy_status",
            "modality",
            "installments",
            "start_date",
            "end_date",
            "last_activation_date",
            "last_cut_date",
            "notes",
        )}),
        ("Revisión", {"fields": (
            "is_validated",
            "validation_notes",
            "correction_reason",
            "created_at",
            "updated_at",
        )}),
    )


@admin.register(LegacyWorkOrderSnapshot)
class LegacyWorkOrderSnapshotAdmin(LegacyAuditedAdminMixin, admin.ModelAdmin):
    form = type(
        "LegacyWorkOrderSnapshotForm",
        (LegacyCorrectionReasonForm,),
        {"Meta": type(
            "Meta",
            (),
            {"model": LegacyWorkOrderSnapshot, "fields": "__all__"},
        )},
    )
    list_display = (
        "legacy_order_number",
        "customer",
        "order_type_name_snapshot",
        "issued_at",
        "status",
        "attention_type",
        "is_validated",
    )
    list_filter = ("status", "attention_type", "responsibility", "is_validated")
    search_fields = (
        "legacy_order_number",
        "customer__code",
        "subscription__service_code",
        "order_type_name_snapshot",
        "reason_name_snapshot",
    )
    autocomplete_fields = (
        "subscription",
        "order_type",
        "reason",
        "branch",
        "zone",
        "derived_from",
    )
    readonly_fields = ("customer", "created_at", "updated_at")
    inlines = (
        LegacyWorkOrderParticipantInline,
        LegacyWorkOrderMaterialInline,
        LegacyWorkOrderEvidenceInline,
    )



class LegacyPaymentAllocationInline(
    LegacyReadOnlyInlineMixin,
    admin.TabularInline,
):
    model = LegacyPaymentAllocationSnapshot
    readonly_fields = (
        "charge",
        "amount",
        "discount",
        "notes",
        "created_at",
    )


@admin.register(LegacyChargeSnapshot)
class LegacyChargeSnapshotAdmin(LegacyAuditedAdminMixin, admin.ModelAdmin):
    form = type(
        "LegacyChargeSnapshotForm",
        (LegacyCorrectionReasonForm,),
        {"Meta": type(
            "Meta",
            (),
            {"model": LegacyChargeSnapshot, "fields": "__all__"},
        )},
    )
    list_display = (
        "description",
        "customer",
        "period_start",
        "amount",
        "due_date",
        "status",
        "is_validated",
    )
    list_filter = ("status", "currency", "is_validated")
    search_fields = (
        "description",
        "customer__code",
        "customer__document_number",
        "document_snapshot",
    )
    autocomplete_fields = ("subscription",)
    readonly_fields = ("customer", "created_at", "updated_at")


@admin.register(LegacyPaymentSnapshot)
class LegacyPaymentSnapshotAdmin(LegacyAuditedAdminMixin, admin.ModelAdmin):
    form = type(
        "LegacyPaymentSnapshotForm",
        (LegacyCorrectionReasonForm,),
        {"Meta": type(
            "Meta",
            (),
            {"model": LegacyPaymentSnapshot, "fields": "__all__"},
        )},
    )
    list_display = (
        "pk",
        "customer",
        "amount",
        "method_snapshot",
        "paid_at",
        "status",
        "is_validated",
    )
    list_filter = ("status", "method_snapshot", "branch", "is_validated")
    search_fields = (
        "customer__code",
        "customer__document_number",
        "reference",
        "collector_snapshot",
        "registered_by_snapshot",
    )
    autocomplete_fields = ("branch",)
    readonly_fields = ("customer", "created_at", "updated_at")
    inlines = (LegacyPaymentAllocationInline,)


@admin.register(LegacyPaymentAllocationSnapshot)
class LegacyPaymentAllocationSnapshotAdmin(admin.ModelAdmin):
    list_display = ("payment", "charge", "amount", "discount")
    search_fields = (
        "payment__customer__code",
        "charge__description",
    )
    readonly_fields = (
        "payment",
        "charge",
        "amount",
        "discount",
        "notes",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LegacyReceiptSnapshot)
class LegacyReceiptSnapshotAdmin(LegacyAuditedAdminMixin, admin.ModelAdmin):
    form = type(
        "LegacyReceiptSnapshotForm",
        (LegacyCorrectionReasonForm,),
        {"Meta": type(
            "Meta",
            (),
            {"model": LegacyReceiptSnapshot, "fields": "__all__"},
        )},
    )
    list_display = (
        "document_snapshot",
        "payment",
        "issued_at",
        "total",
        "is_validated",
    )
    list_filter = ("document_type_snapshot", "is_validated")
    search_fields = (
        "document_snapshot",
        "series",
        "number",
        "payment__customer__code",
    )
    autocomplete_fields = ("payment",)
    readonly_fields = ("created_at", "updated_at")
