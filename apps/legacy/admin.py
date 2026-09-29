from django import forms
from django.contrib import admin
from django.utils import timezone

from .models import LegacyRecord, LegacyRecordCorrection


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
    autocomplete_fields = (
        "customer",
        "subscription",
    )
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
