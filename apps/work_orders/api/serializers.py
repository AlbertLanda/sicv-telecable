"""
Serializadores de la API de órdenes de trabajo del técnico.

Tres formas de **respuesta**, cada una con lo que su pantalla necesita y nada
más:

- `AvailableWorkOrderSerializer` — la bandeja de disponibles, antes de tomar.
- `WorkOrderListSerializer` — la fila de «Mis órdenes», ya tomada.
- `WorkOrderDetailSerializer` — la ficha de una orden propia.

Y una de **entrada**, `WorkOrderClaimSerializer`, que transporta la observación
de la toma. Ninguna transición se decide aquí: la toma la ejecuta el dominio
(`WorkOrder.assign_technician()`), y este serializador solo declara qué campos
se aceptan del cliente — que es justo lo que impide que llegue un `status` o un
`assigned_technician` en el cuerpo.
"""

from rest_framework import serializers

from apps.customers.coordinates import location_payload
from apps.work_orders.models import WorkOrder, WorkOrderLiquidation


class AvailableWorkOrderCustomerSerializer(serializers.Serializer):
    """Identificación mínima del cliente antes de que la OT tenga dueño.

    `available/` es visible para todos los técnicos activos del canal. Antes de
    tomar la orden basta con el código interno y el nombre visible para decidir
    si corresponde atenderla; DNI/RUC/CE/Pasaporte se reservan para una orden
    ya asignada y no viajan en la bandeja compartida.
    """

    code = serializers.CharField(read_only=True)
    display_name = serializers.SerializerMethodField()

    def get_display_name(self, customer):
        return str(customer)


class WorkOrderCustomerSerializer(serializers.Serializer):
    """Identificación del cliente en órdenes que ya pertenecen al técnico.

    Se usa en «Mis órdenes» y en el detalle de una OT propia. Aquí sí puede
    viajar el documento de identificación porque el técnico ya es responsable
    de esa atención y puede necesitar confirmar identidad en puerta.

    `display_name` sale de `str(customer)`, que ya resuelve persona natural
    (nombres y apellidos) y jurídica (razón social) — no se agregan
    propiedades al modelo de `apps/customers`, que está fuera de alcance.
    """

    code = serializers.CharField(read_only=True)
    document_type = serializers.CharField(read_only=True)
    document_number = serializers.CharField(read_only=True)
    display_name = serializers.SerializerMethodField()

    def get_display_name(self, customer):
        return str(customer)


class WorkOrderAddressSerializer(serializers.Serializer):
    """Dirección donde el técnico debe presentarse.

    Sale de `subscription.address`, que es la dirección vigente del servicio.
    Se expone solo lo que sirve para llegar y confirmar el punto: calle,
    referencia, distrito y coordenadas. No se exponen `is_primary`,
    `is_active` ni el resto de la ficha de dirección, que son datos de
    administración del cliente, no de atención en campo.

    Es un `Serializer` plano y no un `ModelSerializer` de `CustomerAddress`
    por la misma razón que `WorkOrderCustomerSerializer`: la forma de la
    respuesta se decide aquí, en el canal técnico.

    **La dirección textual viaja siempre; las coordenadas solo si son
    válidas.** Los valores no se leen directamente del modelo: se piden a
    `apps.customers.coordinates.location_payload()`, la definición única de
    qué cuenta como GPS en el sistema. Un `0`, un `0.0000000` o un par a
    medias se publican como `null` y sin `gps_link`, nunca como una ubicación
    real — un pin en el golfo de Guinea no es un dato pobre, es un dato falso
    que parece bueno, y el técnico lo descubre en la puerta del cliente.
    Conservar la calle y el distrito es lo que le permite llegar igual.

    Las coordenadas viajan como cadena, que es el comportamiento por defecto
    de DRF para `DecimalField` y evita perder precisión al pasar por float.
    """

    address = serializers.CharField(read_only=True)
    reference = serializers.CharField(read_only=True)
    district = serializers.CharField(read_only=True)
    latitude = serializers.DecimalField(
        max_digits=10,
        decimal_places=7,
        read_only=True,
    )
    longitude = serializers.DecimalField(
        max_digits=10,
        decimal_places=7,
        read_only=True,
    )
    gps_link = serializers.CharField(read_only=True)

    def to_representation(self, address):
        # Se serializa el bloque ya saneado en lugar de la instancia. Los
        # campos declarados arriba siguen decidiendo la forma de la respuesta
        # —DRF resuelve cada uno indistintamente sobre un objeto o sobre un
        # diccionario—, y el saneo queda en un solo sitio, compartido con
        # cualquier otra capa que publique la misma ubicación.
        return super().to_representation(location_payload(address))


class WorkOrderListSerializer(serializers.ModelSerializer):
    """Fila del listado «Mis órdenes».

    Cada campo con choices viaja dos veces: el código estable, que es con lo
    que la app decide, y la etiqueta legible, que es lo que pinta en pantalla.
    Así el cliente no tiene que mantener su propia tabla de traducciones ni se
    rompe si mañana cambia una etiqueta.
    """

    customer = WorkOrderCustomerSerializer(
        source="subscription.customer",
        read_only=True,
    )

    service_type = serializers.CharField(
        source="subscription.service_type.name",
        read_only=True,
    )

    plan = serializers.CharField(
        source="subscription.plan.name",
        read_only=True,
    )

    order_type = serializers.CharField(
        source="order_type.name",
        read_only=True,
    )

    # La orden puede no tener subtipo (solo corte y traslado lo usan).
    subtype = serializers.CharField(
        source="subtype.name",
        read_only=True,
        allow_null=True,
    )

    status_display = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    priority_display = serializers.CharField(
        source="get_priority_display",
        read_only=True,
    )

    class Meta:
        model = WorkOrder
        fields = [
            "id",
            "order_number",
            "customer",
            "service_type",
            "plan",
            "order_type",
            "subtype",
            "status",
            "status_display",
            "priority",
            "priority_display",
            "scheduled_at",
            "created_at",
        ]
        read_only_fields = fields


class AvailableWorkOrderSerializer(WorkOrderListSerializer):
    """Fila de la bandeja de órdenes disponibles, **antes** de ser tomada.

    Extiende la fila del listado en lugar de reescribirla, por la misma razón
    que el detalle: un campo que mañana se agregue arriba aparece aquí sin
    tocar dos sitios.

    El cliente se sobrescribe con una versión mínima: código + nombre visible.
    La bandeja es compartida por todos los técnicos activos y no necesita
    exponer el documento personal/comercial antes de que alguien tome la OT.

    **Lo que añade** es lo que hace falta para *decidir si tomarla*: sede,
    zona y distrito. Sin eso el técnico tendría que tomar la orden a ciegas
    para averiguar dónde queda, y una orden tomada por error ya cambió de
    estado y requiere intervención de despacho para deshacerse.

    **Lo que deliberadamente NO añade** es la dirección exacta: calle,
    referencia y coordenadas. Quien todavía no ha tomado la orden no necesita
    el domicilio del cliente, y `available/` es visible para *todos* los
    técnicos del canal. El distrito ubica lo suficiente para decidir; la
    dirección aparece en el detalle, que solo responde sobre órdenes propias.

    Tampoco se hereda ninguna acción: es un serializador de lectura y la toma
    se pide sobre `claim/`, no editando esta fila.
    """

    customer = AvailableWorkOrderCustomerSerializer(
        source="subscription.customer",
        read_only=True,
    )

    branch = serializers.CharField(
        source="branch.name",
        read_only=True,
    )

    # La orden puede no tener zona asignada.
    zone = serializers.CharField(
        source="zone.name",
        read_only=True,
        allow_null=True,
    )

    # Ubicación aproximada, no domicilio. Sale de la dirección vigente del
    # servicio, igual que el bloque `address` del detalle.
    district = serializers.CharField(
        source="subscription.address.district",
        read_only=True,
    )

    class Meta(WorkOrderListSerializer.Meta):
        fields = WorkOrderListSerializer.Meta.fields + [
            "branch",
            "zone",
            "district",
        ]
        read_only_fields = fields


class WorkOrderTechnicalDataSerializer(serializers.ModelSerializer):
    """Datos técnicos ejecutados en campo — **lectura**.

    Refleja `WorkOrderLiquidation`, que es donde el dominio ya guarda lo que
    se hizo: elemento de red, puerto, serie del equipo, nivel de señal, metros
    de cable y referencia Krill, más la descripción de la solución.

    **No se crea un modelo nuevo ni se duplica ninguno.** La Orden Técnica es
    una sola `WorkOrder`: ATC la consulta y el técnico la trabaja sobre la
    misma fila, y estos datos son su liquidación técnica, no una copia
    paralela. Un segundo modelo «datos del técnico» obligaría a sincronizar
    dos verdades y a decidir cuál gana.

    Hoy es **solo lectura**: el registro de estos datos pasa por
    `liquidate_order()`, que exige que la orden esté ATENDIDA y aplica el
    ciclo de revisión completo. Exponer aquí una escritura que se salte ese
    servicio crearía una segunda vía de liquidación sin revisión. La escritura
    llega cuando la atención y la liquidación entren en alcance; este bloque
    fija desde hoy **los nombres y los tipos** con los que llegará, para que
    la app y la ficha de ATC se escriban una sola vez.

    `review_status` viaja porque decide qué puede hacer el técnico con lo ya
    registrado: mientras está en «Corrección solicitada» tiene su única
    oportunidad de rectificar, y una vez «Validada» queda bloqueada para
    siempre.
    """

    review_status_display = serializers.CharField(
        source="get_review_status_display",
        read_only=True,
    )

    class Meta:
        model = WorkOrderLiquidation
        fields = [
            "liquidated_at",
            "resolution_detail",
            "technical_notes",
            "network_element",
            "network_port",
            "equipment_serial",
            "signal_level_dbm",
            "cable_meters_used",
            "krill_reference",
            "review_status",
            "review_status_display",
        ]
        read_only_fields = fields


class WorkOrderClaimSerializer(serializers.Serializer):
    """Contrato de entrada de la toma: una observación y nada más.

    Es el mismo contrato que `WorkOrderAssignForm` ya define para la
    asignación web, reducido a lo que el técnico puede aportar: en la web
    quien asigna elige el técnico, aquí el técnico es siempre
    `request.user`, así que ese campo no existe.

    **Lo que este serializador no declara es tan importante como lo que
    declara.** `status`, `assigned_technician` y `assigned_at` no son campos,
    de modo que un POST que los incluya no los cuela: DRF los descarta al
    validar y el dominio nunca los ve. El estado destino lo decide la matriz
    de transiciones, el responsable sale de `request.user` y la hora la pone
    `timezone.now()` dentro de `assign_technician()`. Ningún valor del cliente
    participa en esas decisiones.

    Es un `Serializer` plano y no un `ModelSerializer`: no describe ni edita
    la orden, solo transporta la observación con la que el técnico confirma.
    """

    remarks = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        help_text=(
            "Opcional. Queda registrada en la asignación y en el historial "
            "de estados."
        ),
    )


class WorkOrderDetailSerializer(WorkOrderListSerializer):
    """Ficha de una orden concreta.

    Extiende el serializador de la lista en vez de reescribirlo: hereda sus
    campos, su `Meta` y su criterio de choices, y solo suma lo que la fila del
    listado no necesita mostrar. Así el listado no puede romperse desde aquí,
    y un campo que mañana se agregue a la lista aparece también en el detalle
    sin tocar dos sitios.

    Sigue siendo de solo lectura. No se expone ninguna acción de transición
    —tomar, iniciar atención, atender, liquidar—: pasan por los servicios de
    dominio, no por este serializador.
    """

    # La dirección de atención es la de la suscripción. Caso conocido y hoy
    # fuera de alcance: en un traslado externo el técnico se presenta en
    # `TransferDetail.new_address`, no en la dirección vigente del servicio;
    # queda anotado como pendiente funcional, no como olvido.
    address = WorkOrderAddressSerializer(
        source="subscription.address",
        read_only=True,
    )

    branch = serializers.CharField(
        source="branch.name",
        read_only=True,
    )

    # La orden puede no tener zona asignada.
    zone = serializers.CharField(
        source="zone.name",
        read_only=True,
        allow_null=True,
    )

    # Por qué existe la orden. Es catálogo, no texto libre, y puede no estar
    # registrado.
    reason = serializers.CharField(
        source="reason.name",
        read_only=True,
        allow_null=True,
    )

    # Marcas de tiempo de la ejecución. `created_at` (heredado) dice cuándo se
    # registró la necesidad; estas dos, cuándo empezó y terminó el trabajo en
    # campo. Nulas mientras no ocurran.
    started_at = serializers.DateTimeField(read_only=True)
    attended_at = serializers.DateTimeField(read_only=True)

    # Qué acción ofrecer en pantalla, decidido por el dominio y no por el
    # cliente. La propiedad existe justamente para eso: lee
    # `STARTABLE_STATUSES` y el técnico asignado, las mismas condiciones que
    # `start_attention()` verifica. Si la app repitiera esa matriz, un cambio
    # en el dominio dejaría botones que fallan al pulsarlos. La comprobación
    # que manda sigue siendo la del dominio en cada POST.
    can_start_attention = serializers.BooleanField(read_only=True)

    technical_data = serializers.SerializerMethodField()

    class Meta(WorkOrderListSerializer.Meta):
        fields = WorkOrderListSerializer.Meta.fields + [
            "address",
            "detail",
            "branch",
            "zone",
            "reason",
            "started_at",
            "attended_at",
            "can_start_attention",
            "technical_data",
        ]
        read_only_fields = fields

    def get_technical_data(self, order):
        """El bloque técnico, o `null` si todavía no se registró nada.

        `null` y no un bloque de campos vacíos: son estados distintos y el
        cliente debe poder distinguir «el técnico aún no liquidó» de «liquidó
        dejando los campos opcionales en blanco». Un bloque vacío haría ambos
        casos idénticos.
        """
        try:
            liquidation = order.liquidation

        except WorkOrder.liquidation.RelatedObjectDoesNotExist:
            return None

        return WorkOrderTechnicalDataSerializer(liquidation).data
