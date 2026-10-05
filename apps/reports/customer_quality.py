"""Revisión de datos del padrón actual, sin corregir ni fusionar registros.

Las comprobaciones se resuelven en SQL para paginar antes de cargar abonados.
Un documento coincidente es una señal de revisión, no prueba de duplicidad.
"""

from django.db.models import (
    BooleanField, Case, Count, Exists, F, OuterRef, Q, Subquery, Value, When,
)
from django.db.models.functions import Concat, Length, Trim, Upper

from apps.customers.models import Customer, CustomerAddress


ISSUES = (
    ("document", "Documento por revisar", "Tipo desconocido, número vacío, formato DNI/RUC o espacios y mayúsculas pendientes de normalizar."),
    ("duplicate", "Posible documento duplicado", "Mismo tipo y número, ignorando espacios exteriores y mayúsculas, en otro abonado de esta sede; incluye inactivos."),
    ("name", "Sin nombre o razón social", "No tiene nombres ni apellidos, falta la razón social o el tipo de persona es desconocido."),
    ("address", "Sin dirección completa", "No tiene una dirección activa con dirección y distrito informados."),
    ("contact", "Sin medio de contacto", "No tiene teléfono principal, teléfono secundario ni correo informado."),
)


def _flag(condition):
    return Case(
        When(condition, then=Value(True)),
        default=Value(False),
        output_field=BooleanField(),
    )


def customers_with_quality_flags(branch):
    """Consulta cerrada a la sede activa, también al buscar coincidencias."""
    customers = Customer.objects.filter(branch=branch) if branch else Customer.objects.none()
    customers = customers.annotate(
        quality_document=Upper(Trim("document_number")),
        quality_document_length=Length(Trim("document_number")),
        quality_key=Concat("document_type", Value(":"), Upper(Trim("document_number"))),
        quality_first_name=Trim("first_name"),
        quality_paternal_surname=Trim("paternal_surname"),
        quality_maternal_surname=Trim("maternal_surname"),
        quality_business_name=Trim("business_name"),
        quality_phone=Trim("phone"),
        quality_secondary_phone=Trim("secondary_phone"),
        quality_email=Trim("email"),
    )
    duplicates = (
        customers.exclude(quality_document="")
        .order_by()
        .values("quality_key")
        .annotate(matches=Count("pk"))
        .filter(matches__gt=1)
        .values("quality_key")
    )
    complete_addresses = (
        CustomerAddress.objects.filter(customer_id=OuterRef("pk"), is_active=True)
        .annotate(quality_address=Trim("address"), quality_district=Trim("district"))
        .exclude(quality_address="")
        .exclude(quality_district="")
    )
    document_issue = (
        ~Q(document_type__in=Customer.DocumentType.values)
        | Q(quality_document="")
        | ~Q(document_number=F("quality_document"))
        | (Q(document_type="DNI") & ~Q(
            quality_document__regex=r"^[0-9]{8}$", quality_document_length=8,
        ))
        | (Q(document_type="RUC") & ~Q(
            quality_document__regex=r"^[0-9]{11}$", quality_document_length=11,
        ))
    )
    name_issue = (
        ~Q(person_type__in=Customer.PersonType.values)
        | Q(person_type="LEGAL", quality_business_name="")
        | Q(
            person_type="NATURAL", quality_first_name="",
            quality_paternal_surname="", quality_maternal_surname="",
        )
    )
    return customers.annotate(
        issue_document=_flag(document_issue),
        issue_duplicate=_flag(Q(quality_key__in=Subquery(duplicates))),
        issue_name=_flag(name_issue),
        issue_address=~Exists(complete_addresses),
        issue_contact=_flag(Q(quality_phone="", quality_secondary_phone="", quality_email="")),
    ).order_by("code", "pk")


def any_issue():
    condition = Q()
    for key, _label, _description in ISSUES:
        condition |= Q(**{f"issue_{key}": True})
    return condition


def quality_summary(customers):
    return customers.aggregate(
        total=Count("pk"),
        flagged=Count("pk", filter=any_issue()),
        **{key: Count("pk", filter=Q(**{f"issue_{key}": True})) for key, _, _ in ISSUES},
    )


def issues_for(customer):
    return [label for key, label, _ in ISSUES if getattr(customer, f"issue_{key}")]
