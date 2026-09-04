"""Serializadores del trabajo de campo de una Orden Técnica.

Este módulo integra la ficha creada en el frente web con el canal API del
técnico. No crea una segunda OT: todos los datos siguen colgando de la misma
`WorkOrder` mediante ficha, evidencias y metrajes de instalación.
"""

from pathlib import Path

from rest_framework import serializers

from apps.services.models import InstallationMaterialRule, InstallationMaterialUsage
from apps.work_orders.models import WorkOrderEvidence, WorkOrderFieldSheet


MAX_EVIDENCE_SIZE = 10 * 1024 * 1024
ALLOWED_EVIDENCE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
}
ALLOWED_EVIDENCE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


class WorkOrderStartSerializer(serializers.Serializer):
    remarks = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=1000,
    )


class WorkOrderFieldSheetSerializer(serializers.ModelSerializer):
    updated_by = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrderFieldSheet
        fields = [
            "nap",
            "terminal",
            "equipment_code",
            "seal_number",
            "notes",
            "updated_by",
            "updated_at",
        ]
        read_only_fields = ["updated_by", "updated_at"]

    def get_updated_by(self, sheet):
        if not sheet.updated_by_id:
            return None
        return {"id": sheet.updated_by_id, "display_name": str(sheet.updated_by)}


class WorkOrderFieldSheetUpdateSerializer(serializers.Serializer):
    nap = serializers.CharField(required=False, allow_blank=True, max_length=60)
    terminal = serializers.CharField(required=False, allow_blank=True, max_length=30)
    equipment_code = serializers.CharField(required=False, allow_blank=True, max_length=120)
    seal_number = serializers.CharField(required=False, allow_blank=True, max_length=60)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Debe enviar al menos un campo de la ficha técnica."
            )
        return attrs


class InstallationMaterialUsageSerializer(serializers.ModelSerializer):
    material = serializers.CharField(source="rule.material", read_only=True)
    material_label = serializers.CharField(source="rule.get_material_display", read_only=True)

    class Meta:
        model = InstallationMaterialUsage
        fields = [
            "id",
            "material",
            "material_label",
            "meters_used",
            "free_meters_snapshot",
            "excess_meters",
            "excess_price_per_meter_snapshot",
            "excess_charge",
            "updated_at",
        ]
        read_only_fields = fields


class InstallationMaterialUsageInputSerializer(serializers.Serializer):
    material = serializers.ChoiceField(choices=InstallationMaterialRule.Material.choices)
    meters_used = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
    )


class WorkOrderEvidenceSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrderEvidence
        fields = ["id", "file", "description", "uploaded_by", "created_at"]
        read_only_fields = fields

    def get_uploaded_by(self, evidence):
        if not evidence.uploaded_by_id:
            return None
        return {"id": evidence.uploaded_by_id, "display_name": str(evidence.uploaded_by)}


class WorkOrderEvidenceUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        default="",
    )

    def validate_file(self, file):
        if file.size > MAX_EVIDENCE_SIZE:
            raise serializers.ValidationError("La evidencia no puede superar 10 MB.")

        extension = Path(file.name or "").suffix.lower()
        content_type = getattr(file, "content_type", "")

        if extension not in ALLOWED_EVIDENCE_EXTENSIONS:
            raise serializers.ValidationError(
                "Formato no permitido. Use JPG, PNG, WEBP o PDF."
            )
        if content_type and content_type not in ALLOWED_EVIDENCE_CONTENT_TYPES:
            raise serializers.ValidationError("El tipo de archivo no está permitido.")
        return file
