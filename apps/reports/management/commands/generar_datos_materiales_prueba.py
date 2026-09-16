"""
Data de prueba del reporte de materiales.

Sirve para ver las trece columnas con contenido creíble sin tener que recorrer
a mano el ciclo completo -tomar la orden, iniciarla, declarar materiales,
cerrarla- desde el portal del técnico por cada fila que se quiera comprobar.

    python manage.py generar_datos_materiales_prueba
    python manage.py generar_datos_materiales_prueba --sede SED01
    python manage.py generar_datos_materiales_prueba --dry-run
    python manage.py generar_datos_materiales_prueba --limpiar

Los materiales se escriben por `inventory.services.record_work_order_material`,
el mismo camino que usa el técnico desde su API. No se crean a mano con
`objects.create()` a propósito: así la data de prueba pasa por las tres reglas
reales -orden En atención, técnico asignado, material activo- y no puede
producir filas que el sistema nunca generaría en operación.

Es idempotente: cada escenario se reconoce por el número de su orden y volver a
correrlo completa lo que falte en vez de duplicarlo.

Los escenarios están elegidos para que cada columna se vea llena **y vacía**,
que es donde se rompen los reportes:

1. Instalación con tres materiales     -> varias filas de una sola orden
2. Servicio con retiro                 -> la columna Acción en su otro valor
3. Avería sin ficha de campo           -> MAC vacío
4. Orden todavía En atención           -> Atención vacía
5. Corte de otra sede                  -> no debe salir en el reporte
6. Retiro (tipo sin opción propia)     -> solo aparece con «Todo»
"""

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.customers.models import Customer, CustomerAddress
from apps.inventory.models import Material, WorkOrderMaterialMovement
from apps.inventory.services import record_work_order_material
from apps.organization.models import Branch, Zone
from apps.services.models import Plan, ServiceType, Subscription
from apps.work_orders.models import OrderType, WorkOrder, WorkOrderFieldSheet


# Los números de orden de la data de prueba. Llevan prefijo propio para que
# nadie los confunda con órdenes reales y para poder retirarlos de golpe.
PREFIJO = "PRB-"


# Los materiales que usa el escenario, por su código **real**.
#
# El catálogo lo siembra `inventory.0001_initial` y es compartido con la
# operación: el técnico elige de esta misma lista desde su portal. La data de
# prueba se limita a usarlo, nunca a ampliarlo.
#
# La primera versión de este comando creaba los suyos -«RG6», «UTP», «F56»- y
# el resultado fue un catálogo con «CABLE RG-6» dos veces, bajo dos códigos
# distintos, ofreciéndose las dos al técnico en el desplegable. Un comando de
# datos de prueba no puede ensuciar un padrón que se usa en producción.
MATERIALES = (
    "CABLE_RG6",
    "CABLE_UTP",
    "CONECTOR_F56",
    "FIBRA_DROP",
    "SPLITTER_2",
    "AISLADOR",
)

TIPOS = (
    ("INSTALLATION", "INSTALACIÓN"),
    ("CABLE_SERVICES", "SERVICIOS"),
    ("CABLE_FAULT", "AVERÍA CABLE"),
    ("CUT", "CORTE"),
    ("WITHDRAWAL", "RETIRO"),
)

ABONADOS = (
    ("HUAMAN CHUQUILLANQUI", "LIZ PATRICIA", "AV. TAHUANTINSUYO 1651"),
    ("HUAMAN BOLUARTE", "ROLANDO", "JR. REAL 0000"),
    ("YSUHUAYLAS ORELLANA", "MARIA MILAGROS", "JR ESPERANZA 0427"),
    ("AVILA CALDERON", "CRISTIAN ARMANDO", "SAN MARTIN 0924"),
    ("JAUCHA SANCHEZ", "WILMER HERNAN", "PSJE. EVITAMIENTO S/N"),
    ("HOSPINAL SANTILLAN", "EDGAR DANY", "JR. MIGUEL GRAU 0460"),
)


class Command(BaseCommand):
    help = (
        "Genera órdenes con materiales declarados para poder comprobar las "
        "trece columnas del reporte de materiales."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sede",
            default=None,
            help=(
                "Código de la sede donde se crean las órdenes. Por defecto, "
                "la primera sede activa."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Describe lo que haría sin escribir nada.",
        )
        parser.add_argument(
            "--limpiar",
            action="store_true",
            help=f"Borra la data de prueba anterior (órdenes «{PREFIJO}…»).",
        )

    # --- entrada ---------------------------------------------------------

    def handle(self, *args, **options):
        self.seco = options["dry_run"]

        if options["limpiar"]:
            return self.limpiar()

        sede = self.resolver_sede(options["sede"])
        otra = self.resolver_otra_sede(sede)

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Data de prueba del reporte de materiales — {sede.name}"
            )
        )

        if self.seco:
            self.stdout.write(
                self.style.WARNING("  --dry-run: no se escribe nada.")
            )

        with transaction.atomic():
            catalogo = self.resolver_catalogo()
            tipos = self.sembrar_tipos()
            tecnicos = self.resolver_tecnicos(sede)
            autor = self.resolver_autor(sede)

            creadas = self.sembrar_escenarios(
                sede=sede,
                otra_sede=otra,
                catalogo=catalogo,
                tipos=tipos,
                tecnicos=tecnicos,
                autor=autor,
            )

            if self.seco:
                transaction.set_rollback(True)

        self.resumir(creadas, sede, otra)

    # --- resolución del escenario ---------------------------------------

    def resolver_sede(self, codigo):
        if codigo:
            sede = Branch.objects.filter(code=codigo).first()
            if sede is None:
                raise CommandError(f"No existe la sede «{codigo}».")
            return sede

        sede = Branch.objects.filter(is_active=True).order_by("code").first()
        if sede is None:
            raise CommandError(
                "No hay ninguna sede activa. Cree una antes de sembrar data."
            )
        return sede

    def resolver_otra_sede(self, sede):
        """Una segunda sede, para comprobar que el reporte no la trae.

        Si el padrón solo tiene una, el escenario de sede ajena se omite: es
        preferible a inventar una sede que no existe en la operación.
        """
        return (
            Branch.objects.filter(is_active=True)
            .exclude(pk=sede.pk)
            .order_by("code")
            .first()
        )

    def resolver_tecnicos(self, sede):
        tecnicos = list(
            User.objects.filter(
                role=User.Role.TECHNICIAN, is_active=True
            ).order_by("username")[:2]
        )

        if not tecnicos:
            raise CommandError(
                "No hay técnicos activos. El reporte necesita uno para poder "
                "declarar materiales: los movimientos solo los escribe el "
                "técnico asignado a la orden."
            )

        return tecnicos

    def resolver_autor(self, sede):
        """Quién figura como creador de las órdenes de prueba."""
        autor = (
            User.objects.filter(is_active=True, is_superuser=True).first()
            or User.objects.filter(is_active=True).first()
        )

        if autor is None:
            raise CommandError("No hay ningún usuario activo en el sistema.")

        return autor

    # --- catálogos -------------------------------------------------------

    def resolver_catalogo(self):
        """Los materiales del catálogo real. No se crea ninguno.

        Si falta alguno, el comando se detiene en vez de inventarlo: un
        material que la operación no tiene no puede aparecer en un reporte que
        existe para cuadrar el almacén.
        """
        catalogo = {}

        for codigo in MATERIALES:
            material = Material.objects.filter(code=codigo, is_active=True).first()

            if material is None:
                raise CommandError(
                    f"No existe el material «{codigo}» en el catálogo. "
                    "Lo siembra la migración inventory.0001_initial: "
                    "compruebe que las migraciones están aplicadas."
                )

            catalogo[codigo] = material

        return catalogo

    def sembrar_tipos(self):
        tipos = {}

        for codigo, nombre in TIPOS:
            tipo, creado = OrderType.objects.get_or_create(
                code=codigo, defaults={"name": nombre}
            )
            tipos[codigo] = tipo

            if creado:
                self.stdout.write(f"  + tipo de orden {codigo} — {nombre}")

        return tipos

    def servicio_y_plan(self):
        service_type, _ = ServiceType.objects.get_or_create(
            code="CABLE", defaults={"name": "Cable"}
        )
        plan, _ = Plan.objects.get_or_create(
            service_type=service_type,
            code="PRB-PLAN",
            defaults={"name": "Plan de prueba", "monthly_price": Decimal("60.00")},
        )
        return service_type, plan

    # --- abonados y órdenes ----------------------------------------------

    def abonado(self, indice, sede):
        """Un abonado de prueba con su domicilio y su suscripción."""
        apellidos, nombres, direccion = ABONADOS[indice % len(ABONADOS)]
        codigo = f"{PREFIJO}{sede.code}-{indice:04d}"

        service_type, plan = self.servicio_y_plan()

        customer, _ = Customer.objects.get_or_create(
            code=codigo,
            defaults={
                "branch": sede,
                "document_type": Customer.DocumentType.DNI,
                "document_number": f"90{indice:06d}",
                "first_name": nombres,
                "paternal_surname": apellidos,
            },
        )

        address, _ = CustomerAddress.objects.get_or_create(
            customer=customer,
            address=direccion,
            defaults={
                "zone": self.zona(sede),
                "district": "El Tambo",
                "is_primary": True,
            },
        )

        subscription, _ = Subscription.objects.get_or_create(
            customer=customer,
            address=address,
            service_type=service_type,
            defaults={"plan": plan, "status": Subscription.Status.ACTIVE},
        )

        return subscription

    def zona(self, sede):
        zona, _ = Zone.objects.get_or_create(
            branch=sede, name="Zona de prueba"
        )
        return zona

    def orden(self, *, numero, subscription, tipo, sede, tecnico, autor, estado):
        """Una orden de prueba en el estado pedido.

        El estado se fija directamente en vez de recorrer las transiciones
        oficiales porque aquí no se está probando el workflow: se está
        preparando el escenario que el reporte tiene que saber leer. La
        declaración de materiales sí pasa por su servicio real.
        """
        orden, creada = WorkOrder.objects.get_or_create(
            order_number=numero,
            defaults={
                "subscription": subscription,
                "order_type": tipo,
                "branch": sede,
                "zone": self.zona(sede),
                "attention_type": WorkOrder.AttentionType.FIELD,
                "status": WorkOrder.Status.IN_PROGRESS,
                "assigned_technician": tecnico,
                "created_by": autor,
                "detail": "Orden de prueba del reporte de materiales.",
                "started_at": timezone.now(),
            },
        )

        return orden, creada

    def cerrar(self, orden, estado):
        """Deja la orden en su estado final, con su fecha de atención.

        Se escribe con `update()` para no disparar `change_status()`: el
        escenario necesita órdenes ya cerradas, no comprobar otra vez unas
        transiciones que tienen sus propias pruebas.
        """
        if estado == WorkOrder.Status.IN_PROGRESS:
            return

        WorkOrder.objects.filter(pk=orden.pk).update(
            status=estado,
            attended_at=timezone.now(),
        )
        orden.refresh_from_db()

    def ficha(self, orden, tecnico, mac):
        WorkOrderFieldSheet.objects.update_or_create(
            work_order=orden,
            defaults={
                "nap": "NAP-014",
                "terminal": "5",
                "equipment_code": mac,
                "seal_number": "P-0099",
                "updated_by": tecnico,
            },
        )

    def material(self, orden, material, cantidad, sentido, tecnico):
        """Declara un material por el mismo camino que el técnico.

        `record_work_order_material()` exige orden En atención y técnico
        asignado, así que se llama antes de cerrarla.
        """
        record_work_order_material(
            work_order=orden,
            material=material,
            movement_type=sentido,
            quantity=Decimal(cantidad),
            user=tecnico,
            remarks="Declarado por la data de prueba.",
        )

    # --- los escenarios ---------------------------------------------------

    def sembrar_escenarios(
        self, *, sede, otra_sede, catalogo, tipos, tecnicos, autor
    ):
        instalado = WorkOrderMaterialMovement.MovementType.INSTALLED
        retirado = WorkOrderMaterialMovement.MovementType.REMOVED

        principal = tecnicos[0]
        segundo = tecnicos[-1]

        creadas = []

        # 1. Instalación con tres materiales: una orden, varias filas.
        creadas += self.escenario(
            numero=f"{PREFIJO}0001",
            descripcion="Instalación con tres materiales",
            subscription=self.abonado(1, sede),
            tipo=tipos["INSTALLATION"],
            sede=sede,
            tecnico=principal,
            autor=autor,
            mac="AA:BB:CC:DD:EE:01",
            estado=WorkOrder.Status.LIQUIDATED,
            materiales=[
                (catalogo["CABLE_RG6"], "16.00", instalado),
                (catalogo["CONECTOR_F56"], "4.00", instalado),
                (catalogo["SPLITTER_2"], "1.00", instalado),
            ],
        )

        # 2. Servicio con retiro: la columna Acción en su otro valor.
        creadas += self.escenario(
            numero=f"{PREFIJO}0002",
            descripcion="Servicio con material retirado",
            subscription=self.abonado(2, sede),
            tipo=tipos["CABLE_SERVICES"],
            sede=sede,
            tecnico=principal,
            autor=autor,
            mac="AA:BB:CC:DD:EE:02",
            estado=WorkOrder.Status.LIQUIDATED,
            materiales=[
                (catalogo["CABLE_UTP"], "5.00", instalado),
                (catalogo["SPLITTER_2"], "1.00", retirado),
            ],
        )

        # 3. Avería sin ficha de campo: la columna MAC vacía. Es el caso real
        #    más frecuente, porque nada obliga al técnico a llenar la ficha.
        creadas += self.escenario(
            numero=f"{PREFIJO}0003",
            descripcion="Avería sin ficha de campo (MAC vacío)",
            subscription=self.abonado(3, sede),
            tipo=tipos["CABLE_FAULT"],
            sede=sede,
            tecnico=segundo,
            autor=autor,
            mac=None,
            estado=WorkOrder.Status.LIQUIDATED,
            materiales=[
                (catalogo["AISLADOR"], "3.00", instalado),
            ],
        )

        # 4. Orden todavía En atención: la columna Atención vacía.
        creadas += self.escenario(
            numero=f"{PREFIJO}0004",
            descripcion="Orden en atención (sin fecha de atención)",
            subscription=self.abonado(4, sede),
            tipo=tipos["INSTALLATION"],
            sede=sede,
            tecnico=segundo,
            autor=autor,
            mac="AA:BB:CC:DD:EE:04",
            estado=WorkOrder.Status.IN_PROGRESS,
            materiales=[
                (catalogo["FIBRA_DROP"], "120.00", instalado),
            ],
        )

        # 5. Retiro: un tipo sin opción propia en el desplegable. Solo debe
        #    aparecer con «Todo», y es el escenario que demuestra por qué
        #    «Todo» no puede ser la suma de las seis opciones visibles.
        creadas += self.escenario(
            numero=f"{PREFIJO}0005",
            descripcion="Retiro — tipo sin opción propia, solo sale en «Todo»",
            subscription=self.abonado(5, sede),
            tipo=tipos["WITHDRAWAL"],
            sede=sede,
            tecnico=principal,
            autor=autor,
            mac="AA:BB:CC:DD:EE:05",
            estado=WorkOrder.Status.LIQUIDATED,
            materiales=[
                (catalogo["SPLITTER_2"], "2.00", retirado),
                (catalogo["CABLE_RG6"], "30.00", retirado),
            ],
        )

        # 6. Otra sede: no debe salir en el reporte de la sede activa.
        if otra_sede is not None:
            creadas += self.escenario(
                numero=f"{PREFIJO}0006",
                descripcion=f"Corte en {otra_sede.name} — NO debe aparecer",
                subscription=self.abonado(6, otra_sede),
                tipo=tipos["CUT"],
                sede=otra_sede,
                tecnico=principal,
                autor=autor,
                mac="AA:BB:CC:DD:EE:06",
                estado=WorkOrder.Status.LIQUIDATED,
                materiales=[
                    (catalogo["CONECTOR_F56"], "1.00", retirado),
                ],
            )

        return creadas

    def escenario(
        self,
        *,
        numero,
        descripcion,
        subscription,
        tipo,
        sede,
        tecnico,
        autor,
        mac,
        estado,
        materiales,
    ):
        orden, creada = self.orden(
            numero=numero,
            subscription=subscription,
            tipo=tipo,
            sede=sede,
            tecnico=tecnico,
            autor=autor,
            estado=estado,
        )

        if not creada and orden.field_material_movements.exists():
            self.stdout.write(f"  = {numero} ya existía — {descripcion}")
            return []

        if not creada:
            # Existía pero sin materiales -por ejemplo, una corrida anterior
            # interrumpida-. Se devuelve a En atención para poder declararlos:
            # `record_work_order_material()` los rechaza en cualquier otro
            # estado, y es justo la regla que la data de prueba no debe
            # esquivar.
            WorkOrder.objects.filter(pk=orden.pk).update(
                status=WorkOrder.Status.IN_PROGRESS,
                assigned_technician=tecnico,
            )
            orden.refresh_from_db()

        if mac:
            self.ficha(orden, tecnico, mac)

        for material, cantidad, sentido in materiales:
            self.material(orden, material, cantidad, sentido, tecnico)

        self.cerrar(orden, estado)

        self.stdout.write(
            self.style.SUCCESS(
                f"  + {numero} — {descripcion} ({len(materiales)} material/es)"
            )
        )

        return [(orden, descripcion, len(materiales))]

    # --- limpieza y resumen ----------------------------------------------

    def limpiar(self):
        ordenes = WorkOrder.objects.filter(order_number__startswith=PREFIJO)
        clientes = Customer.objects.filter(code__startswith=PREFIJO)

        movimientos = WorkOrderMaterialMovement.objects.filter(
            work_order__in=ordenes
        )

        self.stdout.write(
            self.style.MIGRATE_HEADING("Limpiando data de prueba")
        )
        self.stdout.write(f"  movimientos: {movimientos.count()}")
        self.stdout.write(f"  órdenes:     {ordenes.count()}")
        self.stdout.write(f"  abonados:    {clientes.count()}")

        if self.seco:
            self.stdout.write(self.style.WARNING("  --dry-run: no se borra."))
            return

        with transaction.atomic():
            movimientos.delete()
            WorkOrderFieldSheet.objects.filter(work_order__in=ordenes).delete()
            ordenes.delete()
            Subscription.objects.filter(customer__in=clientes).delete()
            CustomerAddress.objects.filter(customer__in=clientes).delete()
            clientes.delete()

        self.stdout.write(self.style.SUCCESS("Data de prueba retirada."))

    def resumir(self, creadas, sede, otra_sede):
        # Se cuenta por sede: el reporte solo muestra una, y anunciar el total
        # de las dos dejaría al operador buscando una fila que nunca va a
        # aparecer en la pantalla que tiene delante.
        propias = sum(
            cantidad for orden, _, cantidad in creadas if orden.branch_id == sede.pk
        )
        ajenas = sum(
            cantidad for orden, _, cantidad in creadas if orden.branch_id != sede.pk
        )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{len(creadas)} orden/es nuevas"))
        self.stdout.write(f"{propias} fila/s en el reporte de {sede.name}")

        if ajenas:
            self.stdout.write(f"{ajenas} fila/s en otra sede, fuera del reporte")
        self.stdout.write("")
        self.stdout.write("Para verlo:")
        self.stdout.write(
            f"  1. elija la sede «{sede.name}» en la barra superior"
        )
        self.stdout.write("  2. Reportes › Materiales")
        self.stdout.write(
            "  3. ponga «Desde» en hoy y exporte con «Todo» en los cuatro "
            "formatos"
        )

        if otra_sede is not None:
            self.stdout.write("")
            self.stdout.write(
                f"La orden de {otra_sede.name} NO debe aparecer mientras la "
                f"sede activa sea {sede.name}."
            )
