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


# Ítems de "Clientes" que existían en el sistema anterior y todavía no
# tienen pantalla propia. "Clientes" ya tiene enlaces reales (Buscar
# cliente, Nuevo cliente, Bandeja de despacho), así que estos se agregan
# a esa misma caja del menú como filas pendientes, en lugar de abrir una
# sección aparte -es una sola sección, como en el sistema anterior.
CLIENTES_PENDING_ITEMS = [
    "Datos",
    "Deuda",
    "Historial de pagos",
    "Comprobantes de pago",
    "Contrato cable",
    "Contrato",
    "Orden",
    "Equipos",
    "Compromiso de pago",
    "Suscripción",
    "Equipo Susc.",
    "Planta externa",
]


# Secciones del menú lateral que todavía no tienen módulo propio, con sus
# ítems tal como existían en el sistema anterior. Se anuncian para que el
# operador vea el mapa completo del sistema -es el mismo que ya conoce-,
# pero se pintan deshabilitadas: un enlace muerto confunde más que un
# ítem marcado como pendiente. Cada ítem sale de esta lista en cuanto su
# pantalla exista de verdad (y pasa a construirse como enlace real, igual
# que "Buscar cliente" o "Nuevo cliente").
#
# "Soporte" del sistema anterior no se replica: ahí el proveedor
# gestionaba sus propias incidencias técnicas, y ese rol ya no existe -el
# soporte del sistema ahora lo damos nosotros mismos, no un módulo aparte.
SIDEBAR_PENDING_SECTIONS = [
    {
        "name": "Cliente2",
        "items": [],
    },
    {
        "name": "Caja",
        "items": [
            "Control de comprobantes",
            "Buscar comprobante",
            "Listar comprobantes",
            "Nota de crédito",
            "Nota de crédito2",
            "Gastos",
            "Depósitos",
            "Composición",
        ],
    },
    {
        "name": "Reportes",
        "items": [
            "Cierre de caja",
            "Abonados",
            "Servicios",
            "Cobranza",
            "Contratos",
        ],
    },
    {
        "name": "Programar",
        "items": [],
    },
    {
        "name": "Configurar",
        "items": [],
    },
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
        "sidebar_clientes_pending_items": CLIENTES_PENDING_ITEMS,
        "sidebar_pending_sections": SIDEBAR_PENDING_SECTIONS,
    }
