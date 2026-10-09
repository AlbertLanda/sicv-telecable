"""Company-scoped, read-only links to internal receipts, never fiscal acceptance."""
from collections import defaultdict

from django.core.exceptions import PermissionDenied
from django.db.models.functions import Trim, Upper

from apps.payments.models import Receipt
from .access import require_access
from .models import ImportBatch


def receipt_links(*, user, issuer, documents):
    require_access(user, issuer, "accounting.view_workspace")
    documents = list(documents)
    batch_ids = {doc.batch_id for doc in documents}
    permitted_batches = set(ImportBatch.objects.filter(pk__in=batch_ids, issuer=issuer, issuer_ruc=issuer.ruc)
                            .values_list("pk", flat=True))
    if batch_ids != permitted_batches:
        raise PermissionDenied
    keys = sorted({doc.key for doc in documents if int(doc.number) <= 2147483647})
    candidates = defaultdict(list)
    # Bounded IN queries avoid per-document lookups and backend parameter limits.
    for offset in range(0, len(keys), 200):
        chunk = set(keys[offset:offset + 200])
        receipts = (Receipt.objects.filter(sequence__issuer=issuer, sequence__issuer__ruc=issuer.ruc)
            .annotate(normalized_series=Upper(Trim("series")))
            .filter(normalized_series__in={key[1] for key in chunk}, number__in={int(key[2]) for key in chunk},
                    sequence__sunat_code__in={key[0] for key in chunk})
            .select_related("sequence", "payment__customer__branch", "payment__branch")
            .prefetch_related("payment__allocations__charge__subscription__plan",
                              "payment__allocations__charge__subscription__address__zone__branch"))
        for receipt in receipts:
            key = receipt.sequence.sunat_code, receipt.normalized_series, str(receipt.number)
            if key in chunk:
                candidates[key].append(receipt)
    result = {}
    for doc in documents:
        matches = candidates.get(doc.key, [])
        info = {"status": "MISSING", "label": "Sin vínculo en el ERP", "warnings": [],
                "fiscal_state": "No acreditado por este cruce"}
        if len(matches) > 1:
            info.update(status="AMBIGUOUS", label="Clave repetida en varios talonarios; revisar")
        elif matches:
            receipt = matches[0]
            payment, customer = receipt.payment, receipt.payment.customer
            if doc.receiver_document and doc.receiver_document != customer.document_number:
                info.update(status="CONFLICT", label="La identidad del receptor difiere del abonado ERP")
            else:
                allocations = list(payment.allocations.all())
                services, branches = set(), set()
                for allocation in allocations:
                    charge = allocation.charge
                    services.add(charge.description)
                    subscription = charge.subscription
                    if subscription:
                        services.add(subscription.plan.name)
                        address = subscription.address
                        branches.add(str(address.zone.branch if address.zone_id else customer.branch))
                info.update(status="LINKED", label="Coincidencia con constancia interna", customer_id=customer.pk,
                    customer_code=customer.code, customer_name=str(customer), customer_document=customer.document_number,
                    customer_branch=str(customer.branch), service_branches="; ".join(sorted(branches)),
                    services="; ".join(sorted(services)), collection_branch=str(payment.branch), receipt_id=receipt.pk,
                    payment_state={"REGISTERED": "Cobrado", "PENDING": "Pendiente de cobro", "VOIDED": "Cobro anulado"}[payment.status])
                if not doc.receiver_document:
                    info["warnings"].append("El archivo no aporta identidad del receptor para contrastar.")
                amount = sum(a.amount for a in allocations) if allocations else payment.amount
                if doc.currency != "PEN" or amount != doc.total:
                    info["warnings"].append("Moneda o total distintos de la constancia interna.")
        result[doc.key] = info
    return result
