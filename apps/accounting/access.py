from django.core.exceptions import PermissionDenied

from apps.payments.models import Issuer
from .models import CompanyAccess


def available_issuers(user):
    if not user.is_authenticated or not user.is_active or not user.has_perm("accounting.view_workspace"):
        return Issuer.objects.none()
    issuers = Issuer.objects.filter(is_active=True)
    if user.is_superuser or user.role == "ADMIN":
        return issuers
    return issuers.filter(pk__in=CompanyAccess.objects.filter(user=user, enabled=True).values("issuer_id"))


def require_access(user, issuer, permission="accounting.view_workspace"):
    if not user.has_perm(permission) or not available_issuers(user).filter(pk=issuer.pk).exists():
        raise PermissionDenied
