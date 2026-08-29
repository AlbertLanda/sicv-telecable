from apps.organization.models import Branch, Office


# Clave de sesión donde vive la sede activa. La sede activa NO es la sede
# del usuario: es desde qué sede está consultando en este momento. Un ATC
# de Huancayo atiende la llamada de un abonado de Oroya cambiando de sede
# aquí, sin que su asignación (user.branch) cambie nunca.
ACTIVE_BRANCH_SESSION_KEY = "active_branch_id"


# Oficina activa. Hoy es solo contexto visible en la barra: no acota
# ninguna consulta. Se registra desde ahora porque el flujo de caja la
# va a necesitar -cada cobro se hace en una oficina concreta-, y así el
# operador ya la tiene elegida cuando esa pantalla exista.
ACTIVE_OFFICE_SESSION_KEY = "active_office_id"


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


def get_active_office(request, branch=None):
    """
    Oficina desde la que se está atendiendo ahora.

    Siempre se valida contra la sede activa: si el operador cambia de
    sede, la oficina elegida antes deja de pertenecer a esa sede y se
    descarta, en lugar de quedar mostrando una oficina de otra ciudad.
    """
    if not request.user.is_authenticated:
        return None

    if branch is None:
        branch = get_active_branch(request)

    if branch is None:
        return None

    office_id = request.session.get(ACTIVE_OFFICE_SESSION_KEY)

    if office_id:
        office = Office.objects.filter(
            pk=office_id,
            branch=branch,
            is_active=True,
        ).first()

        if office:
            return office

    # Sin elección válida se cae a la oficina asignada al usuario, y solo
    # si pertenece a la sede activa.
    if request.user.office_id and request.user.office.branch_id == branch.pk:
        return request.user.office

    return None


# Secciones del menú lateral que todavía no tienen módulo. Se anuncian
# para que el operador vea el mapa completo del sistema -es el mismo que
# conoce del sistema anterior-, pero se pintan deshabilitadas: un enlace
# muerto confunde más que una sección marcada como pendiente. Cada una
# sale de esta lista en cuanto su módulo exista.
SIDEBAR_PENDING_SECTIONS = [
    "Caja",
    "Reportes",
    "Programar",
    "Soporte",
    "Configurar",
]


def organization(request):
    """Sede y oficina activas, con sus opciones, para la barra de navegación."""
    if not request.user.is_authenticated:
        return {}

    active_branch = get_active_branch(request)

    offices = (
        Office.objects.filter(branch=active_branch, is_active=True)
        if active_branch
        else Office.objects.none()
    )

    return {
        "active_branch": active_branch,
        "available_branches": Branch.objects.filter(is_active=True),
        "active_office": get_active_office(request, branch=active_branch),
        "available_offices": offices,
        "sidebar_pending_sections": SIDEBAR_PENDING_SECTIONS,
    }
