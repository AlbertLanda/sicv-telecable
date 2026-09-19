"""La forma del movimiento de material tal como lo lee otro sistema.

Este módulo **es el contrato**. Lo que aquí se declara es lo que logística
programa del otro lado, así que cada campo que se quita o se renombra rompe un
sistema en producción que no se despliega junto con este. Ver
docs/api_logistics_materials.md.

Tres decisiones lo gobiernan:

**Identificadores estables, no nombres.** Cada cosa que el otro sistema tiene
que cruzar viaja por su llave -`technician_id`, `material_code`,
`branch_code`- y no por su etiqueta. El nombre viaja al lado, pero para que un
humano pueda leer el JSON cuando el cuadre no cierre; cruzar por nombre
funciona hasta el primer homónimo, la primera tilde corregida en el admin o el
primer cambio de apellido, y falla en silencio.

**Los `choices` viajan dos veces.** El código estable es con lo que el otro
sistema decide; la etiqueta es lo que pinta. Es el mismo criterio del canal
técnico, y evita que logística mantenga su propia tabla de traducciones.

**Nada que el almacén no necesite.** No viajan la dirección del domicilio ni
el nombre del abonado con su documento: un cuadre de mochila se hace con
técnico, material y cantidad. `customer_code` sí va, porque es lo que permite
abrir una fila del cuadre y llegar a la orden concreta cuando falta material.
"""

from rest_framework import serializers

from apps.inventory.models import WorkOrderMaterialMovement


class MaterialMovementSerializer(serializers.Serializer):
    """Un movimiento de material, con su orden y su técnico resueltos."""

    id = serializers.IntegerField(read_only=True)

    # --- qué se movió ----------------------------------------------------

    movement_type = serializers.CharField(read_only=True)
    movement_type_display = serializers.CharField(
        source="get_movement_type_display",
        read_only=True,
    )

    # El sentido, ya resuelto, para que el otro sistema no tenga que conocer
    # el valor concreto de `MovementType`. Retirado y utilizado son flujos
    # opuestos y pozos de stock distintos: lo instalado descuenta la mochila
    # del técnico, lo retirado ingresa al almacén como recuperado. Netearlos
    # da un número sin significado físico.
    is_removal = serializers.SerializerMethodField()

    quantity = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    material_code = serializers.CharField(source="material.code", read_only=True)
    material_name = serializers.CharField(source="material.name", read_only=True)
    unit_of_measure = serializers.CharField(
        source="material.unit_of_measure",
        read_only=True,
    )
    unit_of_measure_display = serializers.CharField(
        source="material.get_unit_of_measure_display",
        read_only=True,
    )

    remarks = serializers.CharField(read_only=True)

    # --- quién lo movió --------------------------------------------------

    technician_id = serializers.IntegerField(
        source="work_order.assigned_technician_id",
        read_only=True,
    )
    technician_username = serializers.SerializerMethodField()
    technician_name = serializers.SerializerMethodField()

    # --- en qué orden ----------------------------------------------------

    order_number = serializers.CharField(
        source="work_order.order_number",
        read_only=True,
    )
    order_type_code = serializers.SerializerMethodField()
    order_type_name = serializers.SerializerMethodField()
    order_status = serializers.CharField(source="work_order.status", read_only=True)
    order_status_display = serializers.CharField(
        source="work_order.get_status_display",
        read_only=True,
    )

    branch_code = serializers.SerializerMethodField()
    branch_name = serializers.SerializerMethodField()

    customer_code = serializers.CharField(
        source="work_order.subscription.customer.code",
        read_only=True,
    )

    # Código/MAC general de la ficha técnica de la OT. Este dato pertenece a
    # la orden completa y puede repetirse en varias filas de material de una
    # misma atención. NO identifica ni serializa el material concreto de esta
    # fila; el modelo WorkOrderMaterialMovement todavía no guarda serial por
    # movimiento. Se conserva el nombre `equipment_code` por compatibilidad
    # del contrato JSON.
    equipment_code = serializers.SerializerMethodField()

    # --- cuándo ----------------------------------------------------------

    issued_at = serializers.DateTimeField(
        source="work_order.created_at",
        read_only=True,
    )
    attended_at = serializers.DateTimeField(
        source="work_order.attended_at",
        read_only=True,
    )

    # --- en qué punto del ciclo está -------------------------------------
    #
    # Viaja el estado, no una decisión ya tomada. Descontar stock contra una
    # declaración que el técnico todavía puede corregir obliga a reversar
    # asientos; esperar a la validación deja al almacén sin ver el material en
    # tránsito. Con el estado en cada fila, logística muestra todo y consolida
    # solo lo validado, que es una política suya y no de este sistema.

    is_liquidated = serializers.SerializerMethodField()
    liquidation_status = serializers.SerializerMethodField()
    liquidation_status_display = serializers.SerializerMethodField()

    # --- para sincronizar -------------------------------------------------
    #
    # `changed_at` representa el cambio más reciente que afecte lo que viaja
    # en la fila: el movimiento, la OT o su liquidación/revisión. Lo anota la
    # vista y es el sello que el otro sistema guarda como marca de agua para
    # pedir «solo lo que cambió desde...».
    updated_at = serializers.DateTimeField(read_only=True)
    changed_at = serializers.DateTimeField(read_only=True)

    # --- resolución de lo opcional ---------------------------------------
    #
    # Todo lo que puede faltar se resuelve en un método y se lee como cadena
    # vacía, nunca como error. Un movimiento de una orden sin tipo, sin ficha
    # de campo o sin técnico asignado sigue siendo material que salió del
    # almacén y tiene que llegar al cuadre; que la fila reviente por un dato
    # accesorio perdería justo el material que se está buscando.

    def get_is_removal(self, movement):
        return (
            movement.movement_type
            == WorkOrderMaterialMovement.MovementType.REMOVED
        )

    def get_technician_username(self, movement):
        technician = movement.work_order.assigned_technician

        return technician.username if technician else ""

    def get_technician_name(self, movement):
        technician = movement.work_order.assigned_technician

        if not technician:
            return ""

        return technician.get_full_name() or technician.username

    def get_order_type_code(self, movement):
        order = movement.work_order

        return order.order_type.code if order.order_type_id else ""

    def get_order_type_name(self, movement):
        order = movement.work_order

        return order.order_type.name if order.order_type_id else ""

    def get_branch_code(self, movement):
        branch = movement.work_order.branch

        return branch.code if branch else ""

    def get_branch_name(self, movement):
        branch = movement.work_order.branch

        return branch.name if branch else ""

    def get_equipment_code(self, movement):
        sheet = getattr(movement.work_order, "field_sheet", None)

        return sheet.equipment_code if sheet else ""

    def get_is_liquidated(self, movement):
        return getattr(movement.work_order, "liquidation", None) is not None

    def get_liquidation_status(self, movement):
        liquidation = getattr(movement.work_order, "liquidation", None)

        return liquidation.review_status if liquidation else ""

    def get_liquidation_status_display(self, movement):
        liquidation = getattr(movement.work_order, "liquidation", None)

        return liquidation.get_review_status_display() if liquidation else ""
