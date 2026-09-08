from django.contrib import admin

from .models import Charge, Payment, PaymentAllocation, Receipt, ReceiptSequence


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
    raw_id_fields = ["customer", "subscription"]


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
