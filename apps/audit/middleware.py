from apps.organization.context_processors import get_active_branch

from .models import AuditEvent


ACTION_LABELS = {
    "reports:accounting_review": "Guardó una revisión de ejemplos contables QA",
    # Se conservan las etiquetas del registro de equipos retirado como historia.
    "equipment:create": "Registró un equipo de abonado",
    "equipment:assign": "Registró una asignación de equipo",
    "equipment:remove": "Registró un retiro de equipo",
    "equipment:review": "Revisó el estado de un equipo",
    "customers:create": "Registró un cliente",
    "contracts:contract_create": "Registró un contrato",
    "contracts:contract_edit": "Editó un contrato",
    "payments:register": "Registró un pago",
    "payments:commitment_create": "Registró un compromiso de pago",
    "payments:commitment_cancel": "Anuló un compromiso de pago",
    "payments:void": "Anuló un pago",
    "accounts:personnel_create": "Registró personal",
    "accounts:personnel_update": "Actualizó personal",
    "organization:set_active_branch": "Cambió la sede activa",
    "organization:set_active_office": "Cambió la oficina activa",
}


class ActivityAuditMiddleware:
    """Registra POST/PUT/PATCH/DELETE sin almacenar el cuerpo de la petición."""

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
    EXCLUDED_ROUTES = {"login", "logout", "audit:activity", "accounts:profile"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        self._record(request, response)
        return response

    def _record(self, request, response):
        user = getattr(request, "user", None)
        if (
            user is None
            or not user.is_authenticated
            or request.method in self.SAFE_METHODS
            or response.status_code >= 500
        ):
            return

        match = getattr(request, "resolver_match", None)
        route_name = match.view_name if match is not None else ""
        if route_name in self.EXCLUDED_ROUTES:
            return

        description = ACTION_LABELS.get(route_name)
        if not description:
            readable = route_name.replace(":", " / ").replace("_", " ")
            description = f"Ejecutó {readable or request.path}"

        try:
            branch = get_active_branch(request)
        except Exception:
            branch = getattr(user, "branch", None)

        try:
            AuditEvent.objects.create(
                actor=user,
                branch=branch,
                method=request.method,
                route_name=route_name[:180],
                path=request.path[:500],
                status_code=response.status_code,
                description=description[:240],
            )
        except Exception:
            # La auditoría nunca debe romper una operación válida del SICV.
            return
