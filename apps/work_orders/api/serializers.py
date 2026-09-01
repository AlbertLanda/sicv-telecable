"""
Serializadores de la API de órdenes de trabajo del técnico.

Solo lectura. Ninguna acción de transición se expone aquí: la toma de la orden
llega el viernes y pasará por los servicios de dominio, no por un serializador.

Tres formas de respuesta, cada una con lo que su pantalla necesita y nada más:

- `AvailableWorkOrderSerializer` — la bandeja de disponibles, antes de tomar.
- `WorkOrderListSerializer` — la fila de «Mis órdenes», ya tomada.
- `WorkOrderDetailSerializer` — la ficha de una orden propia.
"""

from rest_framework import serializers

from apps.work_orders.models import WorkOrder


class WorkOrderCustomerSerializer(serializers.Serializer):
    """Identificación básica del cliente de la orden.

    Lo mínimo para que el técnico sepa a quién va a atender y pueda confirmar
    identidad en puerta. No expone teléfonos, correo ni el resto de la ficha:
    esos datos no son necesarios para reconocer la orden en un listado y no
    deben viajar sin razón.

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
    por la misma razón que `WorkOrderCustomerSerializer`: `apps/customers` no
    se toca, y la forma de la respuesta se decide aquí, en el canal técnico.

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

    class Meta(WorkOrderListSerializer.Meta):
        fields = WorkOrderListSerializer.Meta.fields + [
            "address",
            "detail",
            "branch",
            "zone",
        ]
        read_only_fields = fields
