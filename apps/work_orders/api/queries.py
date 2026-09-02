"""
Definición de «orden disponible» para el canal del técnico.

Este módulo existe para que la regla viva en **un solo sitio**. La consumen
dos endpoints escritos en jornadas distintas:

- el listado `available/` (miércoles), que decide qué ve el técnico;
- la toma `claim/` (viernes), que decide qué puede tomar.

Si cada uno declarara su propio filtro, bastaría con que uno de los dos
cambiara para que la app mostrara órdenes que la toma rechaza. El técnico
vería un botón que le rebota con 409 sin explicación posible. Por eso la
expresión se escribe una vez y se reutiliza, en lugar de repetirse.

**Dónde vive y por qué no en el dominio.** «Disponible» no es un concepto de
`WorkOrder`: la bandeja de despacho web publica otro conjunto de órdenes y
sigue siendo válida. Es una regla del canal técnico, así que se declara en la
capa del canal y no se añade un manager al modelo. No hay migración, no hay
estado nuevo y el dominio queda intacto.
"""

from apps.work_orders.models import WorkOrder
from apps.work_orders.services import INSTALLATION_ORDER_TYPE_CODE


def available_work_orders(queryset=None):
    """Órdenes que un técnico puede ver y tomar desde la app.

    Los cuatro filtros están decididos por negocio (bloqueo B1 del día 1,
    cerrado el 02/09), pero **no tienen la misma vida útil**. La distinción
    importa: quien tenga que ampliar el alcance más adelante debe saber cuál
    de estas líneas es una regla y cuál es un recorte temporal.

    1. ``status = PENDING`` — sin ejecución todavía. Es además la condición
       exacta que usa el claim, y esa coincidencia es deliberada: lo que se
       lista es exactamente lo que se puede tomar.

       Quedan fuera ``DERIVED`` y ``REPROGRAMMED`` aunque el dominio los
       admita en `ASSIGNABLE_STATUSES`. En ambos ya hubo una decisión
       operativa previa —derivar a otra área, pactar una fecha con el
       cliente— y una toma desde la app la desharía sin que nadie se entere.

    2. ``assigned_technician IS NULL`` — sin responsable. Hoy es redundante
       con PENDING, porque `create_work_order()` rechaza el técnico y
       `assign_technician()` mueve la orden a ASSIGNED: no existe camino que
       deje una PENDING con dueño. Se conserva igualmente porque cuesta cero
       y sostiene la garantía si mañana aparece otra vía de creación.

    3. ``attention_type = FIELD`` — **regla permanente**. NOC atiende por
       sistema y el técnico atiende en campo. Una orden marcada
       ``SYSTEM`` que se colara en la app podría ser tomada por un técnico,
       pasaría a ASSIGNED con él como responsable y quedaría bloqueada para
       quien debe resolverla en remoto.

    4. ``order_type.code = INSTALLATION`` — **recorte de alcance del MVP**,
       no una regla de negocio. El hito del 07/09 es el circuito de
       instalaciones FTTH. Abrirlo a averías u otros trabajos de campo es
       cambiar esta línea y nada más; el resto del diseño no se entera.

       El código se importa del dominio en lugar de escribirse aquí: es el
       mismo que usa `create_installation_work_order()` para registrar la
       orden. Si estuviera escrito dos veces, un cambio en uno solo dejaría
       al canal publicando un tipo distinto del que el alta comercial crea —
       es decir, instalaciones reales que no aparecen en la app.

       La comparación es exacta, así que el `DEMO-INSTALLATION` de datos de
       prueba queda fuera sin necesitar una exclusión aparte.

    El parámetro `queryset` permite aplicar la regla sobre una consulta ya
    preparada —con `select_related()` en el listado, con
    `select_for_update()` en el claim— sin que este módulo tenga que conocer
    ninguno de los dos casos.
    """
    base = WorkOrder.objects.all() if queryset is None else queryset

    return base.filter(
        status=WorkOrder.Status.PENDING,
        assigned_technician__isnull=True,
        attention_type=WorkOrder.AttentionType.FIELD,
        order_type__code=INSTALLATION_ORDER_TYPE_CODE,
    )
