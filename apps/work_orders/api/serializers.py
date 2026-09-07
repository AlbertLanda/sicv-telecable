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
        return super().to_representation(location_payload(address))


class WorkOrderPlanSerializer(serializers.Serializer):
    """Plan contratado en la suscripción que origina la orden."""

    code = serializers.CharField(source="plan.code", read_only=True)
    name = serializers.CharField(source="plan.name", read_only=True)
    service_type = serializers.CharField(
        source="service_type.name",
        read_only=True,
    )
    speed_mbps = serializers.IntegerField(
        source="plan.speed_mbps",
        read_only=True,
        allow_null=True,
    )
    technology = serializers.CharField(source="plan.technology", read_only=True)
    included_tv_points = serializers.IntegerField(
        source="initial_tv_courtesy_granted",
        read_only=True,
    )
    annex_count = serializers.IntegerField(read_only=True)
    total_tv_points = serializers.IntegerField(read_only=True)
    base_installation_fee = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True,
    )
    base_monthly_fee = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True,
    )
    annex_monthly_charge = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True,
    )
    total_monthly_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True,
    )
    generation = serializers.IntegerField(
        source="plan.generation",
        read_only=True,
        allow_null=True,
    )
    commercial_category = serializers.CharField(
        source="plan.commercial_category",
        read_only=True,
    )
    commercial_category_display = serializers.CharField(
        source="plan.get_commercial_category_display",
        read_only=True,
    )
    monthly_price = serializers.DecimalField(
        source="plan.monthly_price",
        max_digits=10,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    billing_policy = serializers.CharField(
        source="billing_policy.name",
        read_only=True,
        allow_null=True,
    )
    tariff = serializers.SerializerMethodField()

    def get_tariff(self, subscription):
        tariff = subscription.tariff
        if tariff is None:
            return None
        return {
            "installation_fee": str(tariff.installation_fee),
            "monthly_fee": str(tariff.monthly_fee),
            "branch": tariff.branch.name,
            "zone": tariff.zone.name if tariff.zone_id else None,
        }


class WorkOrderListSerializer(serializers.ModelSerializer):
    """Fila del listado «Mis órdenes».

    `scheduled_at` continúa representando un compromiso con hora exacta.
    `scheduled_date` representa el compromiso de día sin hora y `agenda_date`
    ofrece al cliente un único día operativo para ordenar o pintar la agenda.
    Los tres campos son de lectura: programar sigue siendo una operación del
    portal administrativo, nunca un PATCH desde el canal técnico.
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
    agenda_date = serializers.DateField(read_only=True, allow_null=True)

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
            "scheduled_date",
            "agenda_date",
            "created_at",
        ]
        read_only_fields = fields


class AvailableWorkOrderSerializer(WorkOrderListSerializer):
    """Fila de la bandeja de órdenes disponibles, antes de ser tomada."""

    customer = AvailableWorkOrderCustomerSerializer(
        source="subscription.customer",
        read_only=True,
    )
    branch = serializers.CharField(
        source="branch.name",
        read_only=True,
    )
    zone = serializers.CharField(
        source="zone.name",
        read_only=True,
        allow_null=True,
    )
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
    """Datos técnicos ejecutados en campo — lectura."""

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
    """Contrato de entrada de la toma: una observación y nada más."""

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
    """Ficha de una orden concreta, siempre de solo lectura."""

    address = WorkOrderAddressSerializer(
        source="subscription.address",
        read_only=True,
    )
    branch = serializers.CharField(
        source="branch.name",
        read_only=True,
    )
    zone = serializers.CharField(
        source="zone.name",
        read_only=True,
        allow_null=True,
    )
    reason = serializers.CharField(
        source="reason.name",
        read_only=True,
        allow_null=True,
    )
    started_at = serializers.DateTimeField(read_only=True)
    attended_at = serializers.DateTimeField(read_only=True)
    can_start_attention = serializers.BooleanField(read_only=True)
    plan_details = WorkOrderPlanSerializer(
        source="subscription",
        read_only=True,
    )
    technical_data = serializers.SerializerMethodField()

    class Meta(WorkOrderListSerializer.Meta):
        fields = WorkOrderListSerializer.Meta.fields + [
            "address",
            "plan_details",
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
        try:
            liquidation = order.liquidation
        except WorkOrder.liquidation.RelatedObjectDoesNotExist:
            return None
        return WorkOrderTechnicalDataSerializer(liquidation).data
