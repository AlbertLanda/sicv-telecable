from django import forms
from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from .models import (
    LegacyContractSnapshot,
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


class LegacyWorkOrderParticipantInline(admin.TabularInline):
    model = LegacyWorkOrderParticipant
    extra = 0


class LegacyWorkOrderMaterialInline(admin.TabularInline):
    model = LegacyWorkOrderMaterial
    extra = 0


class LegacyWorkOrderEvidenceInline(admin.TabularInline):
    model = LegacyWorkOrderEvidence
    extra = 0


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
