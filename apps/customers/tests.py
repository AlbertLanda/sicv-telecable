from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.contracts.models import Contract
from apps.organization.models import Branch, Zone
from apps.services.models import Plan, ServiceType, Subscription
from apps.work_orders.models import (
    OrderCause,
    OrderReason,
    OrderResult,
    OrderSubtype,
    OrderType,
    WorkOrder,
    WorkOrderAssignment,
    WorkOrderStatusHistory,
)

from .models import Customer, CustomerAddress
from .services.activity import MAX_RECENT_EVENTS


User = get_user_model()


class CustomerUIConsultaTests(TestCase):

    def setUp(self):
        self.branch = Branch.objects.create(
            code="LIM",
            name="Sede Lima",
        )

        self.zone = Zone.objects.create(
            branch=self.branch,
            name="Zona Centro",
        )

        self.user = User.objects.create_user(
            username="colaborador",
            password="123",
            role=User.Role.ATC,
            branch=self.branch,
        )

        self.technician = User.objects.create_user(
            username="tecnico",
            password="123",
            role=User.Role.TECHNICIAN,
            branch=self.branch,
        )

        self.service_type = ServiceType.objects.create(
            code="INTERNET",
            name="Internet",
        )

        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="PLAN100",
            name="Plan 100 Mbps",
            speed_mbps=100,
        )

        self.customer = Customer.objects.create(
            code="CLI-0001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="12345678",
            person_type=Customer.PersonType.NATURAL,
            first_name="Juan",
            paternal_surname="Perez",
            maternal_surname="Gomez",
            phone="987654321",
            secondary_phone="912345678",
            email="juan@example.com",
        )

        self.customer_2 = Customer.objects.create(
            code="CLI-0002",
            branch=self.branch,
            document_type=Customer.DocumentType.RUC,
            document_number="20123456789",
            person_type=Customer.PersonType.LEGAL,
            business_name="Empresa Telecable SAC",
            phone="987111222",
        )

        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Av. Principal 123",
            reference="Frente al parque",
            district="Huancayo",
            meter_number="MED-001",
            electrical_supply_number="SUM-001",
            latitude="-12.0651",
            longitude="-75.2049",
            gps_link="https://maps.google.com/",
            is_primary=True,
        )

        self.address_2 = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Jr. Secundario 456",
            reference="Cerca del mercado",
            district="El Tambo",
            is_primary=False,
        )

        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=1,
            installation_date=date(2026, 1, 15),
        )

        self.subscription_2 = Subscription.objects.create(
            customer=self.customer,
            address=self.address_2,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.SUSPENDED,
            service_number=2,
        )

        self.contract = Contract.objects.create(
            contract_number="CTR-0001",
            customer=self.customer,
            subscription=self.subscription,
            start_date=date(2026, 1, 15),
            status=Contract.Status.ACTIVE,
        )

        self.order_type = OrderType.objects.create(
            code="INSTALL",
            name="Instalación",
        )

        self.order_subtype = OrderSubtype.objects.create(
            order_type=self.order_type,
            code="STANDARD",
            name="Instalación estándar",
        )

        self.order_reason = OrderReason.objects.create(
            order_type=self.order_type,
            code="NEW",
            name="Nuevo servicio",
        )

        self.order_cause = OrderCause.objects.create(
            order_type=self.order_type,
            code="CLIENT_REQUEST",
            name="Solicitud del cliente",
        )

        self.order_result = OrderResult.objects.create(
            order_type=self.order_type,
            code="SUCCESS",
            name="Instalación exitosa",
            is_success=True,
        )

        self.work_order = WorkOrder.objects.create(
            order_number="OT-0001",
            subscription=self.subscription,
            order_type=self.order_type,
            subtype=self.order_subtype,
            reason=self.order_reason,
            cause=self.order_cause,
            result=self.order_result,
            branch=self.branch,
            zone=self.zone,
            status=WorkOrder.Status.ATTENDED,
            assigned_technician=self.technician,
            created_by=self.user,
        )

        self.other_subscription = Subscription.objects.create(
            customer=self.customer_2,
            address=CustomerAddress.objects.create(
                customer=self.customer_2,
                zone=self.zone,
                address="Av. Empresa 789",
                district="Huancayo",
                is_primary=True,
            ),
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
        )

        self.other_work_order = WorkOrder.objects.create(
            order_number="OT-0002",
            subscription=self.other_subscription,
            order_type=self.order_type,
            subtype=self.order_subtype,
            reason=self.order_reason,
            branch=self.branch,
            zone=self.zone,
            status=WorkOrder.Status.PENDING,
            created_by=self.user,
        )

        self.search_url = reverse("customers:search")
        self.detail_url = reverse(
            "customers:detail",
            kwargs={"pk": self.customer.pk},
        )

        self.client.login(
            username="colaborador",
            password="123",
        )

    # ------------------------------------------------------------------
    # ACCESO Y PERMISOS
    # ------------------------------------------------------------------

    def test_usuario_autenticado_puede_abrir_busqueda(self):
        response = self.client.get(self.search_url)

        self.assertEqual(response.status_code, 200)

    def test_usuario_anonimo_es_redirigido_al_login(self):
        self.client.logout()

        response = self.client.get(self.search_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_usuario_anonimo_no_puede_ver_ficha(self):
        self.client.logout()

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 302)

    # ------------------------------------------------------------------
    # BÚSQUEDA
    # ------------------------------------------------------------------

    def test_busqueda_por_dni(self):
        response = self.client.get(
            self.search_url,
            {
                "document_type": Customer.DocumentType.DNI,
                "document_number": "12345678"
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Juan")
        self.assertEqual(response.context["customer_found"], self.customer)

    def test_busqueda_por_ruc(self):
        response = self.client.get(
            self.search_url,
            {
                "document_type": Customer.DocumentType.RUC,
                "document_number": "20123456789"
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Empresa Telecable SAC")
        self.assertEqual(response.context["customer_found"], self.customer_2)

    def test_busqueda_sin_coincidencias(self):
        response = self.client.get(
            self.search_url,
            {
                "document_type": Customer.DocumentType.DNI,
                "document_number": "99999999"
            },
        )

        self.assertEqual(len(response.context["customers"]), 0)
        self.assertIsNone(response.context["customer_found"])

    def test_busqueda_vacia_lista_los_clientes_de_la_sede(self):
        """
        Sin criterio, la pantalla es el padrón de la sede activa.

        Reemplaza a la regla anterior, que devolvía una lista vacía y
        obligaba a buscar para ver algo: el operador abre la pantalla y ya
        tiene delante los abonados que puede atender.
        """
        response = self.client.get(
            self.search_url,
            {
                "document_type": "",
                "document_number": ""
            },
        )

        self.assertGreater(len(response.context["customers"]), 0)

    def test_busqueda_conserva_criterio(self):
        response = self.client.get(
            self.search_url,
            {
                "document_type": Customer.DocumentType.DNI,
                "document_number": "12345678",
            },
        )

        self.assertEqual(
            response.context["current_document_number"],
            "12345678",
        )
        self.assertEqual(
            response.context["current_document_type"],
            Customer.DocumentType.DNI,
        )

        self.assertContains(response, "12345678")

    def test_busqueda_post_no_permite_modificacion(self):
        response = self.client.post(
            self.search_url,
            {
                "document_type": Customer.DocumentType.DNI,
                "document_number": "12345678"
            },
        )

        self.assertEqual(response.status_code, 405)

    # ------------------------------------------------------------------
    # FICHA DEL CLIENTE
    # ------------------------------------------------------------------

    def test_ficha_muestra_datos_principales(self):
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CLI-0001")
        self.assertContains(response, "12345678")
        self.assertContains(response, "Juan")
        self.assertContains(response, "Perez")
        self.assertContains(response, "Gomez")
        self.assertContains(response, "987654321")

    def test_ficha_muestra_todas_las_direcciones(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Av. Principal 123")
        self.assertContains(response, "Jr. Secundario 456")

    def test_ficha_identifica_direccion_principal(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Av. Principal 123")

        addresses = list(response.context["addresses"])

        self.assertEqual(addresses[0], self.address)
        self.assertTrue(addresses[0].is_primary)

    def test_ficha_muestra_suministro_electrico_separado_del_medidor(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "MED-001")
        self.assertContains(response, "SUM-001")
        self.assertNotEqual(self.address.meter_number, self.address.electrical_supply_number)

    def test_ficha_muestra_suscripciones(self):
        response = self.client.get(self.detail_url)

        subscriptions = list(response.context["subscriptions"])

        self.assertEqual(len(subscriptions), 2)
        self.assertIn(self.subscription, subscriptions)
        self.assertIn(self.subscription_2, subscriptions)

    def test_ficha_muestra_plan(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Plan 100 Mbps")

    def test_ficha_muestra_tipo_de_servicio(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Internet")

    def test_ficha_muestra_estado_activo(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Activo")

    def test_ficha_muestra_estado_suspendido(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Suspendido")

    # ------------------------------------------------------------------
    # CONTRATOS
    # ------------------------------------------------------------------

    def test_ficha_muestra_contrato(self):
        response = self.client.get(self.detail_url)

        contracts = list(response.context["contracts"])

        self.assertIn(self.contract, contracts)
        self.assertContains(response, "CTR-0001")

    # ------------------------------------------------------------------
    # ÓRDENES
    # ------------------------------------------------------------------

    def test_ficha_muestra_orden_asociada(self):
        response = self.client.get(self.detail_url)

        work_orders = list(response.context["work_orders"])

        self.assertIn(self.work_order, work_orders)
        self.assertContains(response, "OT-0001")

    def test_ficha_muestra_tipo_de_orden(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Instalación")

    def test_ficha_muestra_subtipo_de_orden(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Instalación estándar")

    def test_ficha_muestra_motivo_de_orden(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Nuevo servicio")

    def test_ficha_muestra_resultado_de_orden(self):
        response = self.client.get(self.detail_url)

        self.assertContains(response, "Instalación exitosa")

    def test_orden_de_otro_cliente_no_aparece(self):
        response = self.client.get(self.detail_url)

        work_orders = list(response.context["work_orders"])

        self.assertIn(self.work_order, work_orders)
        self.assertNotIn(self.other_work_order, work_orders)
        self.assertContains(response, "OT-0001")
        self.assertNotContains(response, "OT-0002")

    def test_ficha_muestra_estado_atendida_de_orden(self):

        self.assertEqual(self.work_order.status, WorkOrder.Status.ATTENDED)

        response = self.client.get(self.detail_url)

        work_orders = list(response.context["work_orders"])
        self.assertIn(self.work_order, work_orders)
        self.assertContains(response, "Atendida")

    # ------------------------------------------------------------------
    # CASOS ESPECIALES
    # ------------------------------------------------------------------

    def test_cliente_sin_suscripciones_no_genera_error(self):
        customer = Customer.objects.create(
            code="CLI-SIN-SERV",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="88888888",
            person_type=Customer.PersonType.NATURAL,
            first_name="Cliente",
            paternal_surname="SinServicio",
        )

        url = reverse(
            "customers:detail",
            kwargs={"pk": customer.pk},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["subscriptions"]),
            [],
        )

    def test_cliente_inexistente_devuelve_404(self):
        url = reverse(
            "customers:detail",
            kwargs={"pk": 999999},
        )

        response = self.client.get(url)

        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------
    # SOLO LECTURA
    # ------------------------------------------------------------------

    def test_consultar_ficha_no_modifica_suscripcion(self):
        original_status = self.subscription.status

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)

        self.subscription.refresh_from_db()

        self.assertEqual(
            self.subscription.status,
            original_status,
        )

    def test_consultar_ficha_no_modifica_work_order(self):
        original_status = self.work_order.status

        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)

        self.work_order.refresh_from_db()

        self.assertEqual(
            self.work_order.status,
            original_status,
        )


class CustomerRegistrationFlowTests(TestCase):
    """
    Cubre el flujo funcional obligatorio del ajuste:

    - DNI / CE / Pasaporte -> persona natural.
    - RUC -> persona jurídica.
    - Reglas de obligatoriedad de razón social vs. datos personales.
    - Registro duplicado sigue bloqueado.
    - Registro de una segunda dirección y unicidad de "principal".
    - La vista previa visual de OT no crea ninguna WorkOrder.
    """

    def setUp(self):
        self.branch = Branch.objects.create(
            code="LIM",
            name="Sede Lima",
        )

        self.zone = Zone.objects.create(
            branch=self.branch,
            name="Zona Centro",
        )

        self.user = User.objects.create_user(
            username="colaborador2",
            password="123",
            role=User.Role.ATC,
            branch=self.branch,
        )

        self.client.login(
            username="colaborador2",
            password="123",
        )

        self.create_url = reverse("customers:create")
        self.general_create_url = reverse("customers:general_create")

    # ------------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------------

    def _iniciar_registro(
        self,
        document_type,
        document_number,
        first_name="",
        paternal_surname="",
        maternal_surname="",
    ):
        """
        Ejecuta la Pantalla 3 (datos mínimos) y devuelve la respuesta.
        """

        return self.client.post(
            self.create_url,
            {
                "document_type": document_type,
                "document_number": document_number,
                "first_name": first_name,
                "paternal_surname": paternal_surname,
                "maternal_surname": maternal_surname,
            },
        )

    def _completar_datos_generales(
        self,
        business_name="",
        phone="987000000",
        email="cliente@example.com",
    ):
        """
        Ejecuta la Pantalla 4 (datos generales) y devuelve la respuesta.
        Asume que la sesión ya tiene "customer_registration" cargada.
        """

        return self.client.post(
            self.general_create_url,
            {
                "branch": self.branch.pk,
                "business_name": business_name,
                "phone": phone,
                "secondary_phone": "",
                "email": email,
            },
        )

    # ------------------------------------------------------------------
    # DNI / CE / PASAPORTE -> PERSONA NATURAL
    # ------------------------------------------------------------------

    def test_dni_utiliza_flujo_de_persona_natural(self):
        response = self._iniciar_registro(
            Customer.DocumentType.DNI,
            "45678912",
            first_name="Maria",
            paternal_surname="Lopez",
        )

        self.assertRedirects(response, self.general_create_url)

        response = self._completar_datos_generales()

        self.assertEqual(response.status_code, 302)

        customer = Customer.objects.get(document_number="45678912")

        self.assertEqual(
            customer.person_type,
            Customer.PersonType.NATURAL,
        )
        self.assertEqual(customer.first_name, "Maria")
        self.assertEqual(customer.paternal_surname, "Lopez")

    def test_ce_utiliza_flujo_de_persona_natural(self):
        response = self._iniciar_registro(
            Customer.DocumentType.CE,
            "CE-000111",
            first_name="John",
            paternal_surname="Smith",
        )

        self.assertRedirects(response, self.general_create_url)

        self._completar_datos_generales()

        customer = Customer.objects.get(document_number="CE-000111")

        self.assertEqual(
            customer.person_type,
            Customer.PersonType.NATURAL,
        )

    def test_pasaporte_utiliza_flujo_de_persona_natural(self):
        response = self._iniciar_registro(
            Customer.DocumentType.PASSPORT,
            "PA-998877",
            first_name="Ana",
            paternal_surname="Diaz",
        )

        self.assertRedirects(response, self.general_create_url)

        self._completar_datos_generales()

        customer = Customer.objects.get(document_number="PA-998877")

        self.assertEqual(
            customer.person_type,
            Customer.PersonType.NATURAL,
        )

    # ------------------------------------------------------------------
    # RUC -> PERSONA JURÍDICA
    # ------------------------------------------------------------------

    def test_ruc_utiliza_flujo_de_persona_juridica(self):
        response = self._iniciar_registro(
            Customer.DocumentType.RUC,
            "20555666771",
        )

        self.assertRedirects(response, self.general_create_url)

        response = self._completar_datos_generales(
            business_name="Corporación Andina SAC",
        )

        self.assertEqual(response.status_code, 302)

        customer = Customer.objects.get(document_number="20555666771")

        self.assertEqual(
            customer.person_type,
            Customer.PersonType.LEGAL,
        )
        self.assertEqual(
            customer.business_name,
            "Corporación Andina SAC",
        )

    def test_ruc_exige_razon_social(self):
        self._iniciar_registro(
            Customer.DocumentType.RUC,
            "20555666772",
        )

        response = self._completar_datos_generales(
            business_name="",
        )

        # No debe redirigir: el formulario vuelve a mostrarse con error.
        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "business_name",
            "La razón social es obligatoria para una persona jurídica.",
        )

        self.assertFalse(
            Customer.objects.filter(
                document_number="20555666772"
            ).exists()
        )

    def test_ruc_no_exige_apellidos_personales_para_registrar_empresa(self):
        response = self._iniciar_registro(
            Customer.DocumentType.RUC,
            "20555666773",
            first_name="",
            paternal_surname="",
        )

        # La Pantalla 3 debe aceptar el RUC sin datos personales.
        self.assertRedirects(response, self.general_create_url)

        response = self._completar_datos_generales(
            business_name="Distribuidora Central EIRL",
        )

        self.assertEqual(response.status_code, 302)

        customer = Customer.objects.get(document_number="20555666773")

        self.assertEqual(customer.first_name, "")
        self.assertEqual(customer.paternal_surname, "")
        self.assertEqual(
            customer.business_name,
            "Distribuidora Central EIRL",
        )

    # ------------------------------------------------------------------
    # PERSONA NATURAL: DATOS PERSONALES OBLIGATORIOS
    # ------------------------------------------------------------------

    def test_persona_natural_exige_nombres_y_apellido_paterno(self):
        response = self._iniciar_registro(
            Customer.DocumentType.DNI,
            "45678999",
            first_name="",
            paternal_surname="",
        )

        # No debe avanzar a la Pantalla 4: el formulario de la
        # Pantalla 3 vuelve a mostrarse con errores.
        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "first_name",
            "Los nombres son obligatorios para persona natural.",
        )
        self.assertFormError(
            response.context["form"],
            "paternal_surname",
            (
                "El apellido paterno es obligatorio para "
                "persona natural."
            ),
        )

    # ------------------------------------------------------------------
    # COHERENCIA DOCUMENTO / TIPO DE PERSONA
    # ------------------------------------------------------------------

    def test_tipo_de_persona_se_deriva_siempre_del_documento(self):
        """
        No existe ningún campo en el formulario de la Pantalla 4 que
        permita elegir libremente el tipo de persona: siempre se
        calcula a partir del tipo de documento registrado en la
        Pantalla 3 (Customer.person_type_for_document).
        """

        self._iniciar_registro(
            Customer.DocumentType.DNI,
            "45671234",
            first_name="Carlos",
            paternal_surname="Vega",
        )

        response = self.client.get(self.general_create_url)

        self.assertNotIn("person_type", response.context["form"].fields)

    # ------------------------------------------------------------------
    # DUPLICADOS
    # ------------------------------------------------------------------

    def test_registro_duplicado_de_cliente_continua_bloqueado(self):
        Customer.objects.create(
            code="CLI-DUP",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="11223344",
            person_type=Customer.PersonType.NATURAL,
            first_name="Pedro",
            paternal_surname="Ramos",
        )

        response = self._iniciar_registro(
            Customer.DocumentType.DNI,
            "11223344",
            first_name="Pedro",
            paternal_surname="Ramos",
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "document_number",
            (
                "Ya existe un cliente registrado con este "
                "tipo y número de documento."
            ),
        )

    def test_registro_duplicado_con_cliente_inactivo_tambien_bloqueado(self):
        """
        Customer.Meta.constraints define unique_customer_document sobre
        document_type + document_number sin condición de is_active: un
        cliente inactivo con el mismo documento igual impide el alta en
        base de datos. La Pantalla 3 debe reflejar exactamente esa
        restricción y bloquear el registro con un mensaje claro, en vez
        de dejarlo pasar y reventar en la Pantalla 4 con un error
        genérico de integridad.
        """

        Customer.objects.create(
            code="CLI-INACTIVO",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="99887766",
            person_type=Customer.PersonType.NATURAL,
            first_name="Ana",
            paternal_surname="Torres",
            is_active=False,
        )

        response = self._iniciar_registro(
            Customer.DocumentType.DNI,
            "99887766",
            first_name="Ana",
            paternal_surname="Torres",
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "document_number",
            (
                "Ya existe un cliente registrado con este "
                "tipo y número de documento."
            ),
        )

    # ------------------------------------------------------------------
    # SECUENCIA GUIADA: DATOS GENERALES -> DIRECCIÓN -> SUSCRIPCIÓN
    #
    # BUSCAR/REGISTRAR CLIENTE -> REGISTRAR DIRECCIÓN -> SELECCIONAR
    # SERVICIO Y PLAN -> CREAR SUSCRIPCIÓN -> CONTRATO -> ORDEN DE
    # INSTALACIÓN. Este bloque cubre que, dentro de ese flujo guiado, el
    # alta no se corte en la ficha del cliente en ningún paso intermedio.
    # ------------------------------------------------------------------

    def test_datos_generales_continua_a_direcciones(self):
        """
        Al completar la Pantalla 4 (datos generales), el flujo guiado
        continúa directo al registro de dirección, no a la ficha del
        cliente.
        """

        self._iniciar_registro(
            Customer.DocumentType.DNI,
            "45678913",
            first_name="Elena",
            paternal_surname="Rios",
        )

        response = self.client.post(
            self.general_create_url,
            {
                "branch": self.branch.pk,
                "business_name": "",
                "phone": "987000001",
                "secondary_phone": "",
                "email": "elena@example.com",
                "action": "address",
            },
        )

        customer = Customer.objects.get(document_number="45678913")

        self.assertRedirects(
            response,
            reverse(
                "customers:address_create",
                kwargs={"customer_pk": customer.pk},
            ),
        )

    def test_direccion_continua_a_seleccionar_servicio_y_plan(self):
        """
        Al registrar la dirección dentro de la secuencia guiada (llegada
        desde la Pantalla 4 con action=address), el siguiente paso es
        seleccionar servicio y plan -services:subscription_create-, no
        la ficha del cliente.
        """

        self._iniciar_registro(
            Customer.DocumentType.DNI,
            "45678914",
            first_name="Marco",
            paternal_surname="Diaz",
        )

        self.client.post(
            self.general_create_url,
            {
                "branch": self.branch.pk,
                "business_name": "",
                "phone": "987000002",
                "secondary_phone": "",
                "email": "marco@example.com",
                "action": "address",
            },
        )

        customer = Customer.objects.get(document_number="45678914")

        address_create_url = reverse(
            "customers:address_create",
            kwargs={"customer_pk": customer.pk},
        )

        response = self.client.post(
            address_create_url,
            {
                "zone": self.zone.pk,
                "address": "Av. Tercera 300",
                "reference": "",
                "district": "Huancayo",
                "meter_number": "",
                "latitude": "",
                "longitude": "",
                "gps_link": "",
                "is_primary": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "services:subscription_create",
                kwargs={"customer_pk": customer.pk},
            ),
        )

    def test_direccion_para_otro_servicio_continua_a_seleccionar_servicio_y_plan(
        self,
    ):
        """
        Mejora solicitada 02/09: desde el resumen previo a la
        contratación, "+ Otro servicio (nueva dirección)" enlaza a
        customers:address_create con ?flow=another_service. Al abrir
        esa pantalla se deja la misma marca de sesión que usa la
        secuencia guiada, así que registrar la dirección continúa
        directo a seleccionar servicio y plan, no a la ficha del
        cliente -aunque no se venga de la Pantalla 4 en esta sesión-.
        """

        customer = Customer.objects.create(
            code="CLI-OTRO-SERVICIO",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="45678916",
            person_type=Customer.PersonType.NATURAL,
            first_name="Lucia",
            paternal_surname="Vega",
        )

        address_create_url = reverse(
            "customers:address_create",
            kwargs={"customer_pk": customer.pk},
        )

        # Simula abrir la pantalla desde el enlace del resumen de
        # suscripción, que agrega ?flow=another_service.
        self.client.get(
            address_create_url,
            {"flow": "another_service"},
        )

        response = self.client.post(
            address_create_url,
            {
                "zone": self.zone.pk,
                "address": "Av. Quinta 500",
                "reference": "",
                "district": "Huancayo",
                "meter_number": "",
                "latitude": "",
                "longitude": "",
                "gps_link": "",
                "is_primary": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "services:subscription_create",
                kwargs={"customer_pk": customer.pk},
            ),
        )

    def test_agregar_direccion_fuera_del_flujo_guiado_vuelve_a_la_ficha(self):
        """
        Fuera de la secuencia guiada -por ejemplo, agregar una segunda
        dirección desde la ficha de un cliente ya existente, sin haber
        pasado por la Pantalla 4 en esta sesión- el comportamiento no
        cambia: se vuelve a la ficha del cliente.
        """

        customer = Customer.objects.create(
            code="CLI-ADDR-FICHA",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="45678915",
            person_type=Customer.PersonType.NATURAL,
            first_name="Pedro",
            paternal_surname="Salas",
        )

        address_create_url = reverse(
            "customers:address_create",
            kwargs={"customer_pk": customer.pk},
        )

        response = self.client.post(
            address_create_url,
            {
                "zone": self.zone.pk,
                "address": "Av. Cuarta 400",
                "reference": "",
                "district": "Huancayo",
                "meter_number": "",
                "latitude": "",
                "longitude": "",
                "gps_link": "",
                "is_primary": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("customers:detail", kwargs={"pk": customer.pk}),
        )

    # ------------------------------------------------------------------
    # DIRECCIONES
    # ------------------------------------------------------------------

    def test_registro_de_segunda_direccion_funciona(self):
        customer = Customer.objects.create(
            code="CLI-ADDR",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="55667788",
            person_type=Customer.PersonType.NATURAL,
            first_name="Luis",
            paternal_surname="Torres",
        )

        CustomerAddress.objects.create(
            customer=customer,
            zone=self.zone,
            address="Av. Primera 100",
            district="Huancayo",
            is_primary=True,
        )

        address_create_url = reverse(
            "customers:address_create",
            kwargs={"customer_pk": customer.pk},
        )

        response = self.client.post(
            address_create_url,
            {
                "zone": self.zone.pk,
                "address": "Av. Segunda 200",
                "reference": "",
                "district": "Huancayo",
                "meter_number": "",
                "latitude": "",
                "longitude": "",
                "gps_link": "",
                "is_primary": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(customer.addresses.count(), 2)

    def test_marcar_nueva_direccion_principal_deja_solo_una_principal(self):
        customer = Customer.objects.create(
            code="CLI-ADDR2",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="55667799",
            person_type=Customer.PersonType.NATURAL,
            first_name="Rosa",
            paternal_surname="Flores",
        )

        first_address = CustomerAddress.objects.create(
            customer=customer,
            zone=self.zone,
            address="Av. Primera 100",
            district="Huancayo",
            is_primary=True,
        )

        address_create_url = reverse(
            "customers:address_create",
            kwargs={"customer_pk": customer.pk},
        )

        self.client.post(
            address_create_url,
            {
                "zone": self.zone.pk,
                "address": "Av. Segunda 200",
                "reference": "",
                "district": "Huancayo",
                "meter_number": "",
                "latitude": "",
                "longitude": "",
                "gps_link": "",
                "is_primary": "on",
            },
        )

        first_address.refresh_from_db()

        self.assertFalse(first_address.is_primary)

        primary_addresses = customer.addresses.filter(is_primary=True)

        self.assertEqual(primary_addresses.count(), 1)
        self.assertEqual(
            primary_addresses.first().address,
            "Av. Segunda 200",
        )


class CustomerCodeGenerationTests(TestCase):
    """
    Código de abonado por sede (mejora solicitada 02/09):
    PREFIJO01-ACORRELATIVO, p. ej. HY01-A0000001 para el primer
    cliente de Huancayo. Ver Customer.generate_code().
    """

    def setUp(self):
        # get_or_create: las 3 sedes reales ya vienen sembradas por
        # apps/organization/migrations/0002_seed_sedes_reales.py, que
        # también corre sobre la base de datos de pruebas. No se
        # recrean para no chocar con su restricción de unicidad.
        self.huancayo, _ = Branch.objects.get_or_create(
            code="HUANCAYO",
            defaults={"name": "Huancayo"},
        )

        self.jauja, _ = Branch.objects.get_or_create(
            code="JAUJA",
            defaults={"name": "Jauja"},
        )

        self.oroya, _ = Branch.objects.get_or_create(
            code="OROYA",
            defaults={"name": "La Oroya"},
        )

        self.user = User.objects.create_user(
            username="colaborador_codigo",
            password="123",
            role=User.Role.ATC,
            branch=self.huancayo,
        )

        self.client.login(
            username="colaborador_codigo",
            password="123",
        )

        self.create_url = reverse("customers:create")
        self.general_create_url = reverse("customers:general_create")

    # ------------------------------------------------------------------
    # HELPER: registra un cliente completo (Pantalla 3 + Pantalla 4)
    # ------------------------------------------------------------------

    def _registrar_cliente(self, branch, document_number, first_name):
        self.client.post(
            self.create_url,
            {
                "document_type": Customer.DocumentType.DNI,
                "document_number": document_number,
                "first_name": first_name,
                "paternal_surname": "Apellido",
                "maternal_surname": "",
            },
        )

        self.client.post(
            self.general_create_url,
            {
                "branch": branch.pk,
                "business_name": "",
                "phone": "987000000",
                "secondary_phone": "",
                "email": f"{document_number}@example.com",
            },
        )

        return Customer.objects.get(document_number=document_number)

    # ------------------------------------------------------------------
    # PREFIJOS POR SEDE
    # ------------------------------------------------------------------

    def test_codigo_usa_el_prefijo_de_huancayo(self):
        customer = self._registrar_cliente(
            self.huancayo,
            "70000001",
            "Rosa",
        )

        self.assertEqual(customer.code, "HY01-A0000001")

    def test_codigo_usa_el_prefijo_de_jauja(self):
        customer = self._registrar_cliente(
            self.jauja,
            "70000002",
            "Luis",
        )

        self.assertEqual(customer.code, "JA01-A0000001")

    def test_codigo_usa_el_prefijo_de_la_oroya(self):
        customer = self._registrar_cliente(
            self.oroya,
            "70000003",
            "Ana",
        )

        self.assertEqual(customer.code, "OR01-A0000001")

    # ------------------------------------------------------------------
    # CORRELATIVO POR SEDE
    # ------------------------------------------------------------------

    def test_correlativo_incrementa_dentro_de_la_misma_sede(self):
        primero = self._registrar_cliente(
            self.huancayo,
            "70000004",
            "Carlos",
        )
        segundo = self._registrar_cliente(
            self.huancayo,
            "70000005",
            "Diana",
        )

        self.assertEqual(primero.code, "HY01-A0000001")
        self.assertEqual(segundo.code, "HY01-A0000002")

    def test_correlativo_es_independiente_por_sede(self):
        huancayo_cliente = self._registrar_cliente(
            self.huancayo,
            "70000006",
            "Elena",
        )
        jauja_cliente = self._registrar_cliente(
            self.jauja,
            "70000007",
            "Fabio",
        )

        # Cada sede arranca su propio correlativo en 1, aunque ya
        # existan clientes registrados en otra sede.
        self.assertEqual(huancayo_cliente.code, "HY01-A0000001")
        self.assertEqual(jauja_cliente.code, "JA01-A0000001")

    def test_correlativo_no_se_repite_si_el_ultimo_cliente_de_la_sede_esta_inactivo(
        self,
    ):
        primero = self._registrar_cliente(
            self.huancayo,
            "70000008",
            "Gustavo",
        )

        primero.is_active = False
        primero.save(update_fields=["is_active"])

        segundo = self._registrar_cliente(
            self.huancayo,
            "70000009",
            "Hilda",
        )

        self.assertEqual(segundo.code, "HY01-A0000002")

    # ------------------------------------------------------------------
    # SEDE SIN PREFIJO CONFIGURADO
    # ------------------------------------------------------------------

    def test_sede_sin_prefijo_configurado_no_rompe_el_alta(self):
        """
        Una sede que no está en el mapeo de prefijos oficiales (por
        ejemplo, una sede de prueba) no debe impedir el registro: se
        deriva un prefijo de su propio código en vez de fallar.
        """

        otra_sede = Branch.objects.create(
            code="LIMA_NORTE",
            name="Lima Norte",
        )

        customer = self._registrar_cliente(
            otra_sede,
            "70000010",
            "Irene",
        )

        self.assertEqual(customer.code, "LI01-A0000001")


class CustomerWorkOrderUIPreviewTests(TestCase):
    """
    Cubre la preparación visual del formulario de OT: debe mostrarse
    correctamente y, sobre todo, NO debe crear ninguna WorkOrder.
    """

    def setUp(self):
        self.branch = Branch.objects.create(
            code="HYO",
            name="Sede Huancayo",
        )

        self.zone = Zone.objects.create(
            branch=self.branch,
            name="Zona Norte",
        )

        self.user = User.objects.create_user(
            username="colaborador3",
            password="123",
            role=User.Role.ATC,
            branch=self.branch,
        )

        self.service_type = ServiceType.objects.create(
            code="INTERNET2",
            name="Internet",
        )

        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="PLAN200",
            name="Plan 200 Mbps",
            speed_mbps=200,
        )

        self.customer = Customer.objects.create(
            code="CLI-OTPREV",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="66778899",
            person_type=Customer.PersonType.NATURAL,
            first_name="Sofia",
            paternal_surname="Rios",
        )

        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Jr. Preview 123",
            district="Huancayo",
            is_primary=True,
        )

        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=1,
        )

        self.order_type = OrderType.objects.create(
            code="AVERIA",
            name="Avería",
        )

        self.preview_url = reverse(
            "customers:work_order_ui_preview",
            kwargs={"pk": self.customer.pk},
        )

        self.client.login(
            username="colaborador3",
            password="123",
        )

    def test_vista_previa_de_ot_se_muestra_correctamente(self):
        response = self.client.get(self.preview_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CLI-OTPREV")
        self.assertContains(response, "Avería")

    def test_vista_previa_de_ot_no_crea_ninguna_orden(self):
        initial_count = WorkOrder.objects.count()

        response = self.client.get(self.preview_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkOrder.objects.count(), initial_count)

    def test_vista_previa_de_ot_no_acepta_post(self):
        response = self.client.post(self.preview_url, {})

        self.assertEqual(response.status_code, 405)
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_usuario_anonimo_no_accede_a_la_vista_previa(self):
        self.client.logout()

        response = self.client.get(self.preview_url)

        self.assertEqual(response.status_code, 302)

class CustomerRecentActivityTests(TestCase):
    """
    Pruebas del Bloque F (resumen operativo + actividad reciente) descrito
    en la actividad "Implementación del historial integral y trazabilidad
    operativa del cliente". Cubre los escenarios mínimos 3-5, 7, 11-20 de
    la sección 10 del PDF de actividad.
    """

    def setUp(self):
        self.branch = Branch.objects.create(code="LIM2", name="Sede Lima 2")
        self.zone = Zone.objects.create(branch=self.branch, name="Zona Sur")

        self.user = User.objects.create_user(
            username="atc_historial",
            password="123",
            role=User.Role.ATC,
            branch=self.branch,
        )

        self.technician = User.objects.create_user(
            username="tecnico_historial",
            password="123",
            role=User.Role.TECHNICIAN,
            branch=self.branch,
        )

        self.service_type = ServiceType.objects.create(
            code="INTERNET2",
            name="Internet",
        )

        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="PLAN200",
            name="Plan 200 Mbps",
            speed_mbps=200,
        )

        self.customer = Customer.objects.create(
            code="CLI-HIST-01",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="45678912",
            person_type=Customer.PersonType.NATURAL,
            first_name="Ana",
            paternal_surname="Torres",
            maternal_surname="Lopez",
            phone="911222333",
        )

        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Calle Los Pinos 100",
            district="Huancayo",
            is_primary=True,
        )

        self.order_type = OrderType.objects.create(
            code="AVERIA2",
            name="Avería",
        )

        self.detail_url = reverse(
            "customers:detail",
            kwargs={"pk": self.customer.pk},
        )

        self.client.login(username="atc_historial", password="123")

    # ------------------------------------------------------------------
    # ESTADOS VACÍOS (escenarios 3, 7, 16)
    # ------------------------------------------------------------------

    def test_ficha_sin_ninguna_fuente_muestra_estado_vacio_de_actividad(self):
        response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "No se registran actividades recientes para este cliente.",
        )
        self.assertEqual(
            response.context["operational_summary"]["total_subscriptions"], 0
        )
        self.assertEqual(
            response.context["operational_summary"]["total_contracts"], 0
        )
        self.assertEqual(response.context["recent_activity"], [])

    # ------------------------------------------------------------------
    # SUSCRIPCIONES Y CONTRATOS (escenarios 4, 5, 6)
    # ------------------------------------------------------------------

    def test_evento_de_suscripcion_aparece_en_actividad_reciente(self):
        Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=10,
        )

        response = self.client.get(self.detail_url)

        events = response.context["recent_activity"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "SUBSCRIPTION")
        self.assertEqual(response.context["operational_summary"]["total_subscriptions"], 1)

    def test_varias_suscripciones_aparecen_asociadas_correctamente(self):
        for number in range(2):
            Subscription.objects.create(
                customer=self.customer,
                address=self.address,
                service_type=self.service_type,
                plan=self.plan,
                status=Subscription.Status.ACTIVE,
                service_number=20 + number,
            )

        response = self.client.get(self.detail_url)

        self.assertEqual(
            response.context["operational_summary"]["total_subscriptions"], 2
        )
        subscription_events = [
            event
            for event in response.context["recent_activity"]
            if event.event_type == "SUBSCRIPTION"
        ]
        self.assertEqual(len(subscription_events), 2)

    def test_evento_de_contrato_aparece_en_actividad_reciente(self):
        subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=30,
        )

        Contract.objects.create(
            contract_number="CTR-HIST-01",
            customer=self.customer,
            subscription=subscription,
            start_date=date(2026, 1, 1),
            status=Contract.Status.ACTIVE,
        )

        response = self.client.get(self.detail_url)

        contract_events = [
            event
            for event in response.context["recent_activity"]
            if event.event_type == "CONTRACT"
        ]
        self.assertEqual(len(contract_events), 1)
        self.assertEqual(contract_events[0].reference, "CTR-HIST-01")

    # ------------------------------------------------------------------
    # ÓRDENES DE TRABAJO: creación, asignación, cambio de estado
    # (escenarios 11, 12, 13)
    # ------------------------------------------------------------------

    def _crear_orden(self, number="OT-HIST-01", status=WorkOrder.Status.PENDING):
        subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=len(number),
        )

        return WorkOrder.objects.create(
            order_number=number,
            subscription=subscription,
            order_type=self.order_type,
            branch=self.branch,
            zone=self.zone,
            status=status,
            created_by=self.user,
        )

    def test_evento_creacion_de_ot_aparece_en_actividad_reciente(self):
        order = self._crear_orden()

        response = self.client.get(self.detail_url)

        created_events = [
            event
            for event in response.context["recent_activity"]
            if event.event_type == "WORK_ORDER_CREATED"
        ]
        self.assertEqual(len(created_events), 1)
        self.assertEqual(created_events[0].reference, order.order_number)

    def test_evento_de_asignacion_aparece_con_tecnico_y_fecha(self):
        order = self._crear_orden(status=WorkOrder.Status.ASSIGNED)

        WorkOrderAssignment.objects.create(
            work_order=order,
            technician=self.technician,
            assigned_by=self.user,
            assigned_at=timezone.now(),
        )

        response = self.client.get(self.detail_url)

        assignment_events = [
            event
            for event in response.context["recent_activity"]
            if event.event_type == "WORK_ORDER_ASSIGNMENT"
        ]
        self.assertEqual(len(assignment_events), 1)
        self.assertIn(str(self.technician), assignment_events[0].detail)

    def test_cambio_de_estado_aparece_con_la_transicion_correspondiente(self):
        order = self._crear_orden(status=WorkOrder.Status.ATTENDED)

        WorkOrderStatusHistory.objects.create(
            work_order=order,
            previous_status=WorkOrder.Status.IN_PROGRESS,
            new_status=WorkOrder.Status.ATTENDED,
            changed_by=self.user,
        )

        response = self.client.get(self.detail_url)

        status_events = [
            event
            for event in response.context["recent_activity"]
            if event.event_type == "WORK_ORDER_STATUS"
        ]
        self.assertEqual(len(status_events), 1)
        self.assertIn("→", status_events[0].detail)

    # ------------------------------------------------------------------
    # ORDEN TEMPORAL Y LÍMITE (escenarios 14, 15)
    # ------------------------------------------------------------------

    def test_eventos_se_muestran_del_mas_reciente_al_mas_antiguo(self):
        subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=40,
        )

        older = WorkOrder.objects.create(
            order_number="OT-OLD",
            subscription=subscription,
            order_type=self.order_type,
            branch=self.branch,
            zone=self.zone,
            status=WorkOrder.Status.PENDING,
            created_by=self.user,
        )
        older.created_at = timezone.now() - timedelta(days=2)
        older.save(update_fields=["created_at"])

        newer = WorkOrder.objects.create(
            order_number="OT-NEW",
            subscription=subscription,
            order_type=self.order_type,
            branch=self.branch,
            zone=self.zone,
            status=WorkOrder.Status.PENDING,
            created_by=self.user,
        )
        newer.created_at = timezone.now()
        newer.save(update_fields=["created_at"])

        response = self.client.get(self.detail_url)

        events = response.context["recent_activity"]
        references = [event.reference for event in events]

        self.assertLess(
            references.index("OT-NEW"),
            references.index("OT-OLD"),
        )

    def test_actividad_reciente_no_supera_el_limite_definido(self):
        subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=50,
        )

        # Genera más eventos que el límite (MAX_RECENT_EVENTS) combinando
        # dos fuentes distintas para superar el tope de 20.
        for index in range(15):
            WorkOrder.objects.create(
                order_number=f"OT-LIM-{index:03d}",
                subscription=subscription,
                order_type=self.order_type,
                branch=self.branch,
                zone=self.zone,
                status=WorkOrder.Status.PENDING,
                created_by=self.user,
            )

        for index in range(15):
            Subscription.objects.create(
                customer=self.customer,
                address=self.address,
                service_type=self.service_type,
                plan=self.plan,
                status=Subscription.Status.ACTIVE,
                service_number=100 + index,
            )

        response = self.client.get(self.detail_url)

        self.assertLessEqual(len(response.context["recent_activity"]), MAX_RECENT_EVENTS)

    # ------------------------------------------------------------------
    # SIN ACTIVIDAD (escenario 16, distinto de "sin ninguna fuente")
    # ------------------------------------------------------------------

    def test_cliente_sin_eventos_muestra_estado_vacio_sin_error(self):
        # Cliente sin suscripciones, contratos ni órdenes de trabajo.
        otro_cliente = Customer.objects.create(
            code="CLI-HIST-02",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="55667788",
            person_type=Customer.PersonType.NATURAL,
            first_name="Luis",
            paternal_surname="Ramos",
            maternal_surname="Diaz",
        )

        url = reverse("customers:detail", kwargs={"pk": otro_cliente.pk})

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["recent_activity"], [])
        self.assertContains(
            response,
            "No se registran actividades recientes para este cliente.",
        )

    # ------------------------------------------------------------------
    # PERMISOS DE NUEVA OT Y ASIGNACIÓN (escenarios 17, 18, 19)
    # ------------------------------------------------------------------

    def test_usuario_con_permiso_ve_accion_nueva_ot(self):
        permission = Permission.objects.get(codename="add_workorder")
        self.user.user_permissions.add(permission)

        response = self.client.get(self.detail_url)

        self.assertContains(response, "Nueva orden de trabajo")

    def test_usuario_sin_permiso_no_ve_accion_nueva_ot(self):
        response = self.client.get(self.detail_url)

        self.assertNotContains(response, "Nueva orden de trabajo")

    def test_usuario_sin_permiso_de_asignacion_no_ve_accion_restringida(self):
        order = self._crear_orden(status=WorkOrder.Status.PENDING)

        response = self.client.get(self.detail_url)

        self.assertContains(response, order.order_number)
        self.assertNotContains(response, "Asignar</a>")
        self.assertNotContains(response, "Reasignar</a>")

    def test_usuario_con_permiso_de_asignacion_ve_accion(self):
        permission = Permission.objects.get(codename="assign_workorder")
        self.user.user_permissions.add(permission)

        self._crear_orden(status=WorkOrder.Status.PENDING)

        response = self.client.get(self.detail_url)

        self.assertContains(response, "Asignar")

    # ------------------------------------------------------------------
    # CONSULTAS SIN N+1 EVIDENTE (escenario 20)
    # ------------------------------------------------------------------

    def test_ficha_no_genera_n_mas_1_evidente_con_varias_fuentes(self):
        for index in range(5):
            subscription = Subscription.objects.create(
                customer=self.customer,
                address=self.address,
                service_type=self.service_type,
                plan=self.plan,
                status=Subscription.Status.ACTIVE,
                service_number=200 + index,
            )

            Contract.objects.create(
                contract_number=f"CTR-N1-{index:03d}",
                customer=self.customer,
                subscription=subscription,
                start_date=date(2026, 1, 1),
                status=Contract.Status.ACTIVE,
            )

            order = WorkOrder.objects.create(
                order_number=f"OT-N1-{index:03d}",
                subscription=subscription,
                order_type=self.order_type,
                branch=self.branch,
                zone=self.zone,
                status=WorkOrder.Status.ASSIGNED,
                assigned_technician=self.technician,
                created_by=self.user,
            )

            WorkOrderAssignment.objects.create(
                work_order=order,
                technician=self.technician,
                assigned_by=self.user,
                assigned_at=timezone.now(),
            )

            WorkOrderStatusHistory.objects.create(
                work_order=order,
                previous_status=WorkOrder.Status.PENDING,
                new_status=WorkOrder.Status.ASSIGNED,
                changed_by=self.user,
            )

        from django.test.utils import CaptureQueriesContext
        from django.db import connection

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(self.detail_url)

        self.assertEqual(response.status_code, 200)
        # Límite generoso pero acotado: evita que la ficha vuelva a crecer
        # linealmente con la cantidad de suscripciones/contratos/OT
        # (regresión de N+1). No es un conteo exacto de queries, sino un
        # techo razonable acorde a la sección 7 del PDF de actividad.
        self.assertLess(len(ctx.captured_queries), 40)