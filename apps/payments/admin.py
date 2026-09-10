from django.contrib import admin

from .models import (
    Charge,
    ChargeConcept,
    Payment,
    PaymentAllocation,
    Receipt,
    ReceiptSequence,
)


@admin.register(ChargeConcept)
class ChargeConceptAdmin(admin.ModelAdmin):
    """El catálogo que se ofrece en la nueva deuda.

    Es la pantalla por la que se da de alta un plan nuevo sin tocar código.
    La familia es el único campo que hay que pensar: dice a cuál de los cuatro
    comportamientos del sistema responde el concepto, y de ella dependen la
    exigencia de periodo y el prorrateo en días.
    """

    list_display = ["name", "family", "code", "is_active"]
    list_filter = ["family", "is_active"]
    list_editable = ["family", "is_active"]
    search_fields = ["name", "code"]
    ordering = ["name"]

    # El código identifica al concepto en el tiempo; el nombre se corrige. Se
    # propone desde el nombre al dar de alta y queda editable, pero cambiarlo
    # en uno que ya se usa rompe lo que lo referencie por código.
    prepopulated_fields = {"code": ("name",)}


class PaymentAllocationInline(admin.TabularInline):
    model = PaymentAllocation
    extra = 0
    raw_id_fields = ["charge"]


@admin.register(Charge)
class ChargeAdmin(admin.ModelAdmin):
    list_display = [
        "description",
        "customer",
        "concept",
        "due_date",
        "amount",
        "status",
    ]
    list_filter = ["concept", "status", "due_date"]
    search_fields = [
        "description",
        "customer__document_number",
        "customer__code",
    ]
    date_hierarchy = "due_date"
    raw_id_fields = ["customer", "subscription", "concept_item"]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = [
        "pk",
        "customer",
        "amount",
        "method",
        "received_at",
        "status",
    ]
    list_filter = ["method", "status", "branch"]
    search_fields = [
        "reference",
        "customer__document_number",
        "customer__code",
    ]
    date_hierarchy = "received_at"
    raw_id_fields = ["customer"]
    inlines = [PaymentAllocationInline]

    # La anulación pasa por Payment.void(), que además devuelve los cargos a su
    # estado real. Editar estos campos a mano en el admin dejaría el pago
    # anulado y la deuda cancelada al mismo tiempo.
    readonly_fields = ["status", "voided_at", "voided_by", "void_reason"]


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ["full_number", "payment", "issued_at"]
    search_fields = ["series", "number"]
    date_hierarchy = "issued_at"


@admin.register(ReceiptSequence)
class ReceiptSequenceAdmin(admin.ModelAdmin):
    list_display = ["series", "last_number", "updated_at"]
