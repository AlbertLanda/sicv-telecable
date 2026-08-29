from apps.organization.models import Branch


# Clave de sesión donde vive la sede activa. La sede activa NO es la sede
# del usuario: es desde qué sede está consultando en este momento. Un ATC
# de Huancayo atiende la llamada de un abonado de Oroya cambiando de sede
# aquí, sin que su asignación (user.branch) cambie nunca.
ACTIVE_BRANCH_SESSION_KEY = "active_branch_id"


def get_active_branch(request):
    """
    Sede desde la que se está consultando ahora.

    Orden de resolución: lo elegido en esta sesión, y si no hay nada,
    la sede del propio usuario. Devuelve None si ninguna aplica -por
    ejemplo, un usuario sin sede asignada que aún no eligió una-, y en
    ese caso las consultas no se acotan por sede.
    """
    if not request.user.is_authenticated:
        return None

    branch_id = request.session.get(ACTIVE_BRANCH_SESSION_KEY)

    if branch_id:
        branch = Branch.objects.filter(pk=branch_id, is_active=True).first()

        if branch:
            return branch

    return request.user.branch


def organization(request):
    """Sede activa y sedes disponibles, para la barra de navegación."""
    if not request.user.is_authenticated:
        return {}

    return {
        "active_branch": get_active_branch(request),
        "available_branches": Branch.objects.filter(is_active=True),
    }
