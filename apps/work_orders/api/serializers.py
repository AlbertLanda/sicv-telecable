"""
Serializadores de la API de órdenes de trabajo del técnico.

Solo lectura. Ninguna acción de transición se expone aquí: iniciar atención,
atender y liquidar llegan en los días siguientes del bloque y pasarán por los
servicios de dominio, no por un serializador.
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
