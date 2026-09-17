"""El reporte de materiales: qué material salió y qué material volvió.

Responde la pregunta de logística, no la de la orden: *en este periodo, y en
esta sede, qué se instaló y qué se retiró de los domicilios*. Por eso la fila
del reporte no es una orden de trabajo sino **un movimiento de material**. Una
orden que instaló tres materiales y retiró uno son cuatro filas, y así la
columna «Cantidad» suma lo que realmente se movió; agrupando por orden habría
que inventar una cantidad para una fila que representa cuatro cosas distintas.

El origen es `WorkOrderMaterialMovement`, que es lo que el técnico declara en
campo durante la atención. No se lee `WorkOrderLiquidationItem`, que es su
copia congelada al liquidar: esa existe para que la liquidación siga siendo
legible aunque el catálogo cambie, y llega más tarde. Un material declarado en
una orden atendida pero todavía sin liquidar tiene que aparecer en el reporte
-es justo el que logística está esperando validar-, y leyendo la liquidación
no aparecería.
"""

from apps.inventory.models import WorkOrderMaterialMovement


# Qué recorta cada opción del desplegable «Reporte».
#
# La clave es lo que viaja en el formulario; el `codes` son los códigos de
# `OrderType` que deja pasar. Se filtra por código y no por nombre porque el
# nombre es texto editable desde el admin -una tilde, una mayúscula- y el
# reporte dejaría de encontrar su propio tipo sin avisar de nada.
#
# «Todo» no lleva códigos: no recorta por tipo, así que también trae las
# órdenes cuyo tipo no tiene opción propia en la lista (retiros, cambios de
# plan, requerimientos). Si «Todo» fuera la suma de las opciones visibles, un
# material declarado en un tipo sin opción propia no saldría en ninguna vista.
REPORT_SCOPES = {
    "ALL": {"label": "Todo", "codes": ()},
    "INSTALLATION": {"label": "Cable - Instalaciones", "codes": ("INSTALLATION",)},
    "ANNEX": {"label": "Cable - Anexos", "codes": ("TV_ANNEX",)},
    "RECONNECTION": {"label": "Cable - Reconexiones", "codes": ("RECONNECTION",)},
    "CUT": {"label": "Cable - Cortes", "codes": ("CUT",)},
    "SERVICES": {"label": "Cable - Servicios", "codes": ("CABLE_SERVICES",)},
    # Se conserva FAULT como filtro combinado por compatibilidad con el
    # reporte/API de Kevin, pero la etiqueta ya no afirma que todo sea Cable:
    # incluye tanto CABLE_FAULT como INTERNET_FAULT.
    "FAULT": {
        "label": "Averías - Internet y Cable",
        "codes": ("CABLE_FAULT", "INTERNET_FAULT"),
    },
    # Filtros específicos adicionales para operación y conciliación.
    "INTERNET_FAULT": {
        "label": "Internet - Averías",
        "codes": ("INTERNET_FAULT",),
    },
    "CABLE_FAULT": {
        "label": "Cable - Averías",
        "codes": ("CABLE_FAULT",),
    },
}

DEFAULT_SCOPE = "ALL"

SCOPE_CHOICES = [(key, value["label"]) for key, value in REPORT_SCOPES.items()]


# Sobre qué fecha de la orden se recorta el periodo.
#
# Son dos preguntas distintas y cada una tiene su fecha correcta:
#
# «issued» -emisión- es la del reporte en pantalla. Es la fecha que la hoja
# imprime en su primera columna, así que es la que deja cuadrar lo que se ve
# con lo que se pidió.
#
# «attended» -atención real- es la de logística. El material sale de la
# mochila del técnico cuando lo usa, no cuando ATC emitió la orden. Con corte
# semanal la diferencia no es un caso raro: una orden emitida el viernes y
# atendida el lunes cae en la semana equivocada todos los viernes, y el cuadre
# de mochila no cierra por material que sí se consumió, solo que en la otra
# semana.
#
# Una orden sin atender no tiene `attended_at` y por eso no entra en el
# recorte por atención. Es lo correcto para un cuadre -material declarado en
# una orden aún en curso todavía puede corregirse- y además vuelve solo: en
# cuanto la orden se cierra, la siguiente consulta del mismo periodo ya la
# trae.
DATE_BASIS = {
    "issued": "work_order__created_at__date",
    "attended": "work_order__attended_at__date",
}

DEFAULT_DATE_BASIS = "issued"

DATE_BASIS_CHOICES = [
    ("issued", "Emisión de la orden"),
    ("attended", "Atención real"),
]


# Las columnas, en el orden del sistema que se reemplaza.
#
# Se declaran una sola vez y las cuatro salidas -pantalla, PDF, Excel y Word-
# las leen de aquí. Cuando cada formato traía su propia lista, añadir una
# columna significaba tocar cuatro archivos y descubrir en el cuarto que el
# Excel llevaba meses sin una que el PDF sí tenía.
#
# `width` es el peso relativo de la columna al repartir el ancho de la hoja.
# Lo usan el PDF y el Excel; la pantalla reparte sola.
COLUMNS = [
    {"key": "order_number", "label": "Orden", "width": 9},
    {"key": "order_type", "label": "Tipo", "width": 11},
    {"key": "issued_on", "label": "Emisión", "width": 8},
    {"key": "customer_code", "label": "Código", "width": 8},
    {"key": "customer_name", "label": "Abonado", "width": 18},
    {"key": "address", "label": "Dirección", "width": 20},
    {"key": "material", "label": "Material", "width": 14},
    {"key": "quantity", "label": "Cantidad", "width": 8, "numeric": True},
    {"key": "action", "label": "Acción", "width": 9},
    {"key": "mac", "label": "MAC / Equipo OT", "width": 12},
    {"key": "attended_on", "label": "Atención", "width": 8},
    {"key": "situation", "label": "Situación", "width": 9},
    {"key": "technician", "label": "Técnico", "width": 13},
]


def _address_of(order):
    """El domicilio donde se hizo el trabajo.

    Sale de la suscripción y no del abonado: un abonado puede tener varios
    domicilios y el material se instaló en uno concreto. Buscarlo por el
    cliente obligaría a elegir entre varios sin saber cuál, y logística
    validaría el retiro contra una dirección que no es la que visitó el
    técnico.
    """
    address = getattr(order.subscription, "address", None)

    return address.address if address else ""


def _mac_of(order):
    """El MAC/equipo general registrado en la ficha de campo de la OT.

    Este valor pertenece a la orden completa, no al movimiento individual de
    material que ocupa la fila. Por eso puede repetirse en varias filas de la
    misma OT y no debe interpretarse como serial del material mostrado.

    La ficha es opcional -el técnico la llena durante la atención y puede
    cerrarse sin ella-, así que su ausencia se lee como celda vacía y no como
    error: un material declarado sin ficha sigue siendo material que salió del
    almacén y tiene que contarse.
    """
    sheet = getattr(order, "field_sheet", None)

    return sheet.equipment_code if sheet else ""


def _technician_of(order):
    technician = order.assigned_technician

    return technician.get_full_name() or technician.username if technician else ""


def _row(movement):
    """Una fila del reporte a partir de un movimiento de material."""
    order = movement.work_order
    customer = order.subscription.customer

    return {
        "order_number": order.order_number,
        "order_type": order.order_type.name if order.order_type_id else "",
        "issued_on": order.created_at,
        "customer_code": customer.code,
        "customer_name": str(customer),
        "address": _address_of(order),
        "material": movement.material.name,
        "quantity": movement.quantity,
        "unit": movement.material.get_unit_of_measure_display(),
        "action": movement.get_movement_type_display(),
        "is_removal": (
            movement.movement_type
            == WorkOrderMaterialMovement.MovementType.REMOVED
        ),
        "mac": _mac_of(order),
        "attended_on": order.attended_at,
        "situation": order.get_status_display(),
        "technician": _technician_of(order),
    }


def material_movements(
    *,
    branch,
    date_from,
    date_to,
    scope=DEFAULT_SCOPE,
    date_basis=DEFAULT_DATE_BASIS,
):
    """Los movimientos de material del periodo, ya acotados y ordenados.

    Por defecto el rango se aplica sobre la **emisión de la orden**
    -`created_at`-, que es la fecha que el reporte muestra en su primera
    columna y con la que el operador pide el periodo.

    `date_basis="attended"` recorta por la atención real en vez de por la
    emisión. Es la pregunta de logística, que cuadra mochilas por semana y
    necesita el día en que el material se consumió.

    Las dos fechas son inclusivas.
    """
    campo_fecha = DATE_BASIS.get(date_basis, DATE_BASIS[DEFAULT_DATE_BASIS])

    movements = (
        WorkOrderMaterialMovement.objects
        .select_related(
            "material",
            "work_order",
            "work_order__order_type",
            "work_order__assigned_technician",
            "work_order__field_sheet",
            "work_order__subscription",
            "work_order__subscription__customer",
            "work_order__subscription__address",
        )
        .filter(**{
            f"{campo_fecha}__gte": date_from,
            f"{campo_fecha}__lte": date_to,
        })
    )

    if branch is not None:
        movements = movements.filter(work_order__branch=branch)

    codes = REPORT_SCOPES.get(scope, REPORT_SCOPES[DEFAULT_SCOPE])["codes"]

    if codes:
        movements = movements.filter(work_order__order_type__code__in=codes)

    return movements.order_by(
        "work_order__created_at",
        "work_order__order_number",
        "movement_type",
        "material__name",
    )


def build_report(*, branch, date_from, date_to, scope=DEFAULT_SCOPE):
    """Todo lo que las cuatro salidas necesitan para imprimirse."""
    movements = material_movements(
        branch=branch,
        date_from=date_from,
        date_to=date_to,
        scope=scope,
    )

    rows = [_row(movement) for movement in movements]

    return {
        "columns": COLUMNS,
        "rows": rows,
        "total": len(rows),
        "branch": branch,
        "date_from": date_from,
        "date_to": date_to,
        "scope": scope,
        "scope_label": REPORT_SCOPES.get(
            scope, REPORT_SCOPES[DEFAULT_SCOPE]
        )["label"],
        "title": "Registro de materiales",
    }
