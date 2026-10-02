from django.contrib import admin

from .forms import FiscalProfileForm
from .models import FiscalDocument, FiscalEvent, FiscalProfile, FiscalProfileRevision
from .services import profile_snapshot
from django.db import transaction


@admin.register(FiscalProfile)
class FiscalProfileAdmin(admin.ModelAdmin):
    form = FiscalProfileForm
    list_display = ["issuer", "modality", "billing_trigger", "updated_at"]
    readonly_fields = ["issuer", "updated_by", "updated_at"]

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
        FiscalProfileRevision.objects.create(profile=obj, actor=request.user, snapshot=profile_snapshot(obj))

    def has_add_permission(self, request):
        # El primer perfil se prepara desde la pantalla por empresa.
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FiscalDocument)
class FiscalDocumentAdmin(ReadOnlyAdmin):
    list_display = ["public_id", "issuer", "customer", "status", "source_total", "created_at"]
    list_filter = ["status", "branch", "document_type"]


@admin.register(FiscalEvent)
class FiscalEventAdmin(ReadOnlyAdmin):
    list_display = ["document", "action", "actor", "created_at"]


@admin.register(FiscalProfileRevision)
class FiscalProfileRevisionAdmin(ReadOnlyAdmin):
    list_display = ["profile", "actor", "created_at"]


# La configuración OSE se edita en su pantalla para conservar revisiones.
from .models import (OseConnection, OseConnectionRevision, OseSimulation,
                     OseSimulationAttempt, OseSimulationEvent, OseSimulatorReceipt)

for evidence_model in (OseConnection, OseConnectionRevision, OseSimulation,
                       OseSimulationAttempt, OseSimulationEvent, OseSimulatorReceipt):
    admin.site.register(evidence_model, ReadOnlyAdmin)
