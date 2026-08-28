"""
Serializadores de la API de órdenes de trabajo del técnico.

Solo lectura: la fila del listado y la ficha de detalle. Ninguna acción de
transición se expone aquí: iniciar atención, atender y liquidar llegan en los
días siguientes del bloque y pasarán por los servicios de dominio, no por un
serializador.
"""

from rest_framework import serializers

from apps.work_orders.models import WorkOrder


class WorkOrderCustomerSerializer(serializers.Serializer):
    """Identificación básica del cliente de la orden.

    Lo mínimo para que el técnico sepa a quién va a atender y pueda
    confirmar identidad en puerta. No expone teléfonos, correo ni el resto
    de la ficha: esos datos no son necesarios para reconocer la orden en un
    listado y no deben viajar sin razón.

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


class WorkOrderDetailSerializer(WorkOrderListSerializer):
    """Ficha de una orden concreta.

    Extiende el serializador de la lista en vez de reescribirlo: hereda sus
    campos, su `Meta` y su criterio de choices, y solo suma lo que la fila del
    listado no necesita mostrar. Así el listado del día 2 no puede romperse
    desde aquí, y un campo que mañana se agregue a la lista aparece también en
    el detalle sin tocar dos sitios.

    `created_at` ya venía en la lista, así que no se declara de nuevo: lo que
    pedía la actividad ya está cubierto por herencia.

    Sigue siendo de solo lectura. No se expone ninguna acción de transición
    —iniciar atención, atender, liquidar—: llegan en los días 4 a 6 y pasarán
    por los servicios de dominio, no por este serializador.
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
