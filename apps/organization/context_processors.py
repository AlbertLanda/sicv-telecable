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

    Orden de resolución:
    1. sede elegida en la sesión;
    2. sede asignada al usuario;
    3. Huancayo como sede por defecto.

    La selección activa no modifica la sede asignada al usuario.
    """
    if not request.user.is_authenticated:
        return None

    branch_id = request.session.get(ACTIVE_BRANCH_SESSION_KEY)

    if branch_id:
        branch = Branch.objects.filter(
            pk=branch_id,
            is_active=True,
        ).first()

        if branch:
            return branch

    if request.user.branch_id:
        branch = Branch.objects.filter(
            pk=request.user.branch_id,
            is_active=True,
        ).first()

        if branch:
            return branch

    return (
        Branch.objects
        .filter(
            code="HUANCAYO",
            is_active=True,
        )
        .first()
    )


def get_active_office(request, branch=None):
    """
    Oficina desde la que se está atendiendo ahora.

    Orden de resolución:
    1. oficina elegida en la sesión;
    2. oficina asignada al usuario si pertenece a la sede activa;
    3. primera oficina activa de la sede activa.
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

    if (
        request.user.office_id
        and request.user.office.branch_id == branch.pk
        and request.user.office.is_active
    ):
        return request.user.office

    return (
        Office.objects
        .filter(
            branch=branch,
            is_active=True,
        )
        .order_by("name", "pk")
        .first()
    )


# Ítems de "Clientes" que existían en el sistema anterior y todavía no
# tienen pantalla propia. "Clientes" ya tiene enlaces reales (Buscar
# cliente, Nuevo cliente, Bandeja de despacho), así que estos se agregan
# a esa misma caja del menú como filas pendientes, en lugar de abrir una
# sección aparte -es una sola sección, como en el sistema anterior.
CLIENTES_PENDING_ITEMS = [
    "Datos",
    # "Deuda", "Historial de pagos" y "Comprobantes de pago" salieron de esta
    # lista al construirse el modulo de cobranza: ya son enlaces reales en la
    # seccion Clientes, igual que "Buscar cliente".
    "Contrato cable",
    "Contrato",
    "Orden",
    "Equipos",
    "Compromiso de pago",
    "Suscripción",
    "Equipo Susc.",
    "Planta externa",
]


# El resto de secciones del menú, con los ítems que tenían en el sistema
# anterior. La sección se abre y se recorre con normalidad; lo que está
# marcado como pendiente es cada ítem, porque es el ítem el que todavía
# no tiene pantalla. Cada uno sale de aquí en cuanto se construya y pasa
# a ser un enlace real, igual que "Buscar cliente".
#
# El menú se queda en Clientes, Caja y Reportes. No se replican del
# sistema anterior:
#   - "Soporte": ahí el proveedor atendía sus propias incidencias
#     técnicas, y ese rol ya no existe -el soporte lo damos nosotros.
#   - "Cliente2" y "Programar": no aportan nada que no esté ya en las
#     tres secciones de arriba.
#
# "Configurar" sí se construyó, con contenido que no estaba en ninguna
# otra sección: el mantenimiento de planes y servicios, que hasta ahora
# solo se podía hacer por comando o desde el admin de Django.
SIDEBAR_PENDING_SECTIONS = [
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
        "selected_customer_id": request.session.get("selected_customer_id"),
        "sidebar_clientes_pending_items": CLIENTES_PENDING_ITEMS,
        "sidebar_pending_sections": SIDEBAR_PENDING_SECTIONS,
    }
