from collections import defaultdict
from decimal import Decimal

from .importers import FLAGS
from .models import Review

ZERO = Decimal("0.00")
RESULTS = {
    "WAITING": "Falta cargar la otra fuente",
    "ONLY_LOCAL": "Solo en archivo SICV",
    "ONLY_RVIE": "Solo en archivo SIRE",
    "DIFFERENCE": "Diferencia entre archivos",
    "MATCH": "Coincide en campos comparados",
}


def compare(legacy, rvie):
    left = {doc.key: doc for doc in legacy.documents.all()} if legacy else {}
    right = {doc.key: doc for doc in rvie.documents.all()} if rvie else {}
    rows = []
    for key in sorted(left.keys() | right.keys()):
        local, external = left.get(key), right.get(key)
        doc = local or external
        differences = []
        if not legacy or not rvie:
            result = "WAITING"
        elif not local:
            result = "ONLY_RVIE"
        elif not external:
            result = "ONLY_LOCAL"
        else:
            for field, label in (("currency", "Moneda"), ("total", "Total"), ("base", "Base"),
                                 ("tax", "IGV"), ("issue_date", "Fecha de emisión")):
                a, b = getattr(local, field), getattr(external, field)
                if a != b:
                    differences.append(label + (" sin dato" if a is None or b is None else ""))
            if local.sunat_state and external.sunat_state and local.sunat_state != external.sunat_state:
                differences.append("Código SUNAT de origen")
            if local.receiver_document and external.receiver_document and local.receiver_document != external.receiver_document:
                differences.append("Documento receptor")
            result = "DIFFERENCE" if differences else "MATCH"
        # A matching amount does not certify acceptance or clear source issues.
        flags = sorted(set((local.flags if local else []) + (external.flags if external else [])))
        rows.append({"document": doc, "local": local, "rvie": external, "result": result,
                     "label": RESULTS[result], "differences": differences,
                     "delta": local.total - external.total if local and external and local.currency == external.currency else None,
                     "flags": [FLAGS.get(flag, flag) for flag in flags], "flag_codes": flags,
                     "attention": result != "MATCH" or bool(flags)})
    return rows


def totals_by_currency(documents):
    totals = defaultdict(lambda: {"total": ZERO, "base": ZERO, "tax": ZERO, "count": 0, "incomplete": False})
    for doc in documents:
        row = totals[doc.currency]
        row["count"] += 1
        row["total"] += doc.total
        for field in ("base", "tax"):
            if getattr(doc, field) is None:
                row["incomplete"] = True
            else:
                row[field] += getattr(doc, field)
    return [{"currency": currency, **values} for currency, values in sorted(totals.items())]


def classified_lines(batch, *, cutoff=None):
    if not batch:
        return []
    reviews = Review.objects.filter(document__batch=batch, line__isnull=False)
    if cutoff is not None:
        reviews = reviews.filter(pk__lte=cutoff)
    latest = {}
    for review in reviews.select_related("actor"):
        latest.setdefault(review.line_id, review)
    rows = []
    for doc in batch.documents.prefetch_related("lines"):
        for line in doc.lines.all():
            review = latest.get(line.pk)
            rows.append({"document": doc, "line": line, "review": review,
                         "concept": review.concept if review else line.concept,
                         "technology": review.technology if review else line.technology})
    return rows


def osiptel_summary(lines):
    totals = defaultdict(lambda: {"total": ZERO, "base": ZERO, "tax": ZERO, "count": 0})
    for row in lines:
        key = row["document"].currency, row["concept"], row["technology"]
        item = totals[key]
        item["count"] += 1
        for field in ("base", "tax", "total"):
            item[field] += getattr(row["line"], field)
    return [{"currency": k[0], "concept": k[1], "technology": k[2], **v} for k, v in sorted(totals.items())]
