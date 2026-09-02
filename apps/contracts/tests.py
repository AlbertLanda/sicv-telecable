from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone
from apps.services.models import Plan, ServiceType, Subscription
from apps.work_orders.models import OrderType, WorkOrder

from .models import Contract


User = get_user_model()


class ContractCreateTests(TestCase):

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

        self.client.login(
            username="colaborador",
            password="123",
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
        )

        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Av. Principal 123",
            district="Huancayo",
            is_primary=True,
        )

        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
            service_number=1,
        )

        self.create_url = reverse(
            "contracts:contract_create",
            kwargs={
                "customer_pk": self.customer.pk,
            },
        )

    # -------------------------------------------------------------
    # ACCESO
    # -------------------------------------------------------------

    def test_usuario_autenticado_puede_abrir_formulario(self):
        response = self.client.get(self.create_url)

        self.assertEqual(response.status_code, 200)

    def test_usuario_anonimo_no_puede_crear_contrato(self):
        self.client.logout()

        response = self.client.get(self.create_url)

        self.assertEqual(response.status_code, 302)

    # -------------------------------------------------------------
    # FORMULARIO
    # -------------------------------------------------------------

    def test_formulario_solo_muestra_suscripciones_presale_del_cliente(self):
        response = self.client.get(self.create_url)

        form = response.context["form"]

        subscriptions = list(
            form.fields["subscription"].queryset
        )

        self.assertIn(
            self.subscription,
            subscriptions,
        )

    def test_formulario_no_muestra_suscripcion_activa(self):
        active_subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=2,
        )

        response = self.client.get(self.create_url)

        subscriptions = list(
            response.context["form"]
            .fields["subscription"]
            .queryset
        )

        self.assertNotIn(
            active_subscription,
            subscriptions,
        )

    def test_formulario_no_muestra_suscripcion_de_otro_cliente(self):
        other_customer = Customer.objects.create(
            code="CLI-0002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="87654321",
            person_type=Customer.PersonType.NATURAL,
            first_name="Maria",
            paternal_surname="Lopez",
        )

        other_address = CustomerAddress.objects.create(
            customer=other_customer,
            zone=self.zone,
            address="Jr. Secundario 456",
            district="Huancayo",
            is_primary=True,
        )

        other_subscription = Subscription.objects.create(
            customer=other_customer,
            address=other_address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
            service_number=1,
        )

        response = self.client.get(self.create_url)

        subscriptions = list(
            response.context["form"]
            .fields["subscription"]
            .queryset
        )

        self.assertNotIn(
            other_subscription,
            subscriptions,
        )

    # -------------------------------------------------------------
    # CREACIÓN CORRECTA
    # -------------------------------------------------------------

    def test_crear_contrato_desde_suscripcion_presale(self):
        response = self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "",
                "notes": "Contrato de prueba",
            },
        )

        self.assertEqual(response.status_code, 302)

        contract = Contract.objects.get(
            subscription=self.subscription
        )

        self.assertEqual(
            contract.customer,
            self.customer,
        )

        self.assertEqual(
            contract.subscription,
            self.subscription,
        )

        self.assertEqual(
            contract.start_date,
            date(2026, 8, 20),
        )

        self.assertEqual(
            contract.notes,
            "Contrato de prueba",
        )

    # -------------------------------------------------------------
    # NÚMERO AUTOMÁTICO
    # -------------------------------------------------------------

    def test_numero_de_contrato_se_genera_automaticamente(self):
        response = self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 302)

        contract = Contract.objects.get(
            subscription=self.subscription
        )

        self.assertEqual(
            contract.contract_number,
            "CONT-000001",
        )

    # -------------------------------------------------------------
    # ESTADO INICIAL
    # -------------------------------------------------------------

    def test_contrato_se_crea_activo(self):
        self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "",
                "notes": "",
            },
        )

        contract = Contract.objects.get(
            subscription=self.subscription
        )

        self.assertEqual(
            contract.status,
            Contract.Status.ACTIVE,
        )

        self.assertTrue(contract.is_active)

    # -------------------------------------------------------------
    # VALIDACIÓN DE FECHAS
    # -------------------------------------------------------------

    def test_fecha_final_no_puede_ser_anterior_a_fecha_inicio(self):
        response = self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "2026-08-19",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "end_date",
            (
                "La fecha de finalización no puede "
                "ser anterior a la fecha de inicio."
            ),
        )

        self.assertFalse(
            Contract.objects.filter(
                subscription=self.subscription
            ).exists()
        )

    def test_fecha_final_no_puede_ser_menor_a_6_meses_desde_el_inicio(self):
        response = self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                # Poco más de 3 meses después del inicio: menos que el
                # mínimo exigido de 6 meses.
                "end_date": "2026-12-01",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "end_date",
            (
                "El contrato debe tener una vigencia mínima de 6 "
                "meses. Con esta fecha de inicio, la fecha de "
                "finalización debe ser 20/02/2027 o posterior."
            ),
        )

        self.assertFalse(
            Contract.objects.filter(
                subscription=self.subscription
            ).exists()
        )

    def test_fecha_final_con_exactamente_6_meses_es_valida(self):
        response = self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "2027-02-20",
                "notes": "",
            },
        )

        self.assertRedirects(
            response,
            reverse(
                "contracts:contract_summary",
                kwargs={
                    "customer_pk": self.customer.pk,
                    "pk": Contract.objects.get(
                        subscription=self.subscription
                    ).pk,
                },
            ),
        )

        contract = Contract.objects.get(subscription=self.subscription)

        self.assertEqual(contract.end_date, date(2027, 2, 20))

    # -------------------------------------------------------------
    # CONTRATO DUPLICADO
    # -------------------------------------------------------------

    def test_no_permite_segundo_contrato_activo_para_misma_suscripcion(self):
        Contract.objects.create(
            contract_number="CONT-000001",
            customer=self.customer,
            subscription=self.subscription,
            start_date=date(2026, 8, 1),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )

        response = self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "subscription",
            (
                "La suscripción seleccionada ya tiene "
                "un contrato activo registrado."
            ),
        )

        self.assertEqual(
            Contract.objects.filter(
                subscription=self.subscription,
                is_active=True,
            ).count(),
            1,
        )

    # -------------------------------------------------------------
    # SUSCRIPCIÓN DE OTRO CLIENTE
    # -------------------------------------------------------------

    def test_no_permite_suscripcion_de_otro_cliente(self):
        other_customer = Customer.objects.create(
            code="CLI-0002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="87654321",
            person_type=Customer.PersonType.NATURAL,
            first_name="Maria",
            paternal_surname="Lopez",
        )

        other_address = CustomerAddress.objects.create(
            customer=other_customer,
            zone=self.zone,
            address="Jr. Secundario 456",
            district="Huancayo",
            is_primary=True,
        )

        other_subscription = Subscription.objects.create(
            customer=other_customer,
            address=other_address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
            service_number=1,
        )

        response = self.client.post(
            self.create_url,
            {
                "subscription": other_subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "subscription",
            "Escoja una opción válida. Esa opción no está entre las disponibles.",
        )

        self.assertEqual(
            Contract.objects.count(),
            0,
        )

    # -------------------------------------------------------------
    # RESUMEN DE CONTRATACIÓN (día 02/09)
    # -------------------------------------------------------------

    def test_crear_contrato_redirige_al_resumen(self):
        response = self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "",
                "notes": "",
            },
        )

        contract = Contract.objects.get(
            subscription=self.subscription
        )

        self.assertRedirects(
            response,
            reverse(
                "contracts:contract_summary",
                kwargs={
                    "customer_pk": self.customer.pk,
                    "pk": contract.pk,
                },
            ),
        )

    def test_resumen_muestra_cliente_servicio_plan_y_contrato(self):
        contract = Contract.objects.create(
            contract_number="CONT-000001",
            customer=self.customer,
            subscription=self.subscription,
            start_date=date(2026, 8, 20),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )

        response = self.client.get(
            reverse(
                "contracts:contract_summary",
                kwargs={
                    "customer_pk": self.customer.pk,
                    "pk": contract.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, contract.contract_number)
        self.assertContains(response, self.plan.name)
        self.assertContains(response, self.service_type.name)
        self.assertContains(response, self.address.address)

    def test_resumen_no_accesible_con_contrato_de_otro_cliente(self):
        other_customer = Customer.objects.create(
            code="CLI-0003",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="11223344",
            person_type=Customer.PersonType.NATURAL,
            first_name="Carlos",
            paternal_surname="Ramos",
        )

        other_address = CustomerAddress.objects.create(
            customer=other_customer,
            zone=self.zone,
            address="Calle Otra 789",
            district="Huancayo",
            is_primary=True,
        )

        other_subscription = Subscription.objects.create(
            customer=other_customer,
            address=other_address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
            service_number=1,
        )

        other_contract = Contract.objects.create(
            contract_number="CONT-000002",
            customer=other_customer,
            subscription=other_subscription,
            start_date=date(2026, 8, 20),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )

        response = self.client.get(
            reverse(
                "contracts:contract_summary",
                kwargs={
                    # customer_pk no corresponde al dueño real del contrato.
                    "customer_pk": self.customer.pk,
                    "pk": other_contract.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 404)

    # -------------------------------------------------------------
    # PRESELECCIÓN DE SUSCRIPCIÓN DESDE EL RESUMEN (día 02/09)
    # -------------------------------------------------------------

    def test_formulario_preselecciona_suscripcion_recibida_por_query_param(self):
        response = self.client.get(
            f"{self.create_url}?subscription={self.subscription.pk}"
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.context["form"].initial.get("subscription"),
            str(self.subscription.pk),
        )

        self.assertEqual(
            response.context["preselected_subscription"],
            self.subscription,
        )

        self.assertContains(response, self.plan.name)

    def test_no_preselecciona_suscripcion_de_otro_cliente(self):
        other_customer = Customer.objects.create(
            code="CLI-0004",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="55667788",
            person_type=Customer.PersonType.NATURAL,
            first_name="Ana",
            paternal_surname="Torres",
        )

        other_address = CustomerAddress.objects.create(
            customer=other_customer,
            zone=self.zone,
            address="Jr. Ajena 111",
            district="Huancayo",
            is_primary=True,
        )

        other_subscription = Subscription.objects.create(
            customer=other_customer,
            address=other_address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
            service_number=1,
        )

        response = self.client.get(
            f"{self.create_url}?subscription={other_subscription.pk}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["preselected_subscription"])

    # -------------------------------------------------------------
    # SUSCRIPCIÓN NO PRESALE
    # -------------------------------------------------------------

    def test_no_permite_contrato_para_suscripcion_activa(self):
        self.subscription.status = Subscription.Status.ACTIVE
        self.subscription.save()

        response = self.client.post(
            self.create_url,
            {
                "subscription": self.subscription.pk,
                "start_date": "2026-08-20",
                "end_date": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            Contract.objects.count(),
            0,
        )

class InstallationWorkOrderCreateTests(TestCase):
    """
    Acción "Generar Orden de Instalación" del resumen de contratación
    (día 03/09 del sprint FTTH). Cubre InstallationWorkOrderCreateView,
    que consume create_installation_work_order() sin reimplementar sus
    reglas: aquí solo se prueba que la vista respeta la autorización,
    llama al servicio con los datos correctos y traduce sus resultados
    (éxito o ValidationError) a mensajes y redirecciones. Las reglas
    de negocio en sí (idempotencia, catálogo, sede/zona) ya están
    cubiertas en apps.work_orders.tests.
    """

    def setUp(self):
        self.branch = Branch.objects.create(
            code="LIM2",
            name="Sede Lima 2",
        )

        self.zone = Zone.objects.create(
            branch=self.branch,
            name="Zona Centro 2",
        )

        self.user = User.objects.create_user(
            username="colaborador_ot",
            password="123",
            role=User.Role.ATC,
            branch=self.branch,
        )

        self.service_type = ServiceType.objects.create(
            code="INTERNET-OT",
            name="Internet",
        )

        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="PLAN100-OT",
            name="Plan 100 Mbps",
            speed_mbps=100,
        )

        self.customer = Customer.objects.create(
            code="CLI-OT-0001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="99988877",
            person_type=Customer.PersonType.NATURAL,
            first_name="Rosa",
            paternal_surname="Quispe",
            maternal_surname="Huaman",
        )

        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Jr. Las Flores 456",
            district="Huancayo",
            is_primary=True,
        )

        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
            service_number=1,
        )

        self.contract = Contract.objects.create(
            contract_number="CONT-OT-000001",
            customer=self.customer,
            subscription=self.subscription,
            start_date=date(2026, 9, 3),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )

        self.installation_type = OrderType.objects.create(
            code="INSTALLATION",
            name="Instalación",
        )

        self.summary_url = reverse(
            "contracts:contract_summary",
            kwargs={
                "customer_pk": self.customer.pk,
                "pk": self.contract.pk,
            },
        )

        self.generate_url = reverse(
            "contracts:generate_installation_order",
            kwargs={
                "customer_pk": self.customer.pk,
                "pk": self.contract.pk,
            },
        )

        self.client.login(
            username="colaborador_ot",
            password="123",
        )

    def grant_add_workorder_permission(self):
        permission = Permission.objects.get(
            codename="add_workorder",
            content_type__app_label="work_orders",
        )

        self.user.user_permissions.add(permission)

    # -------------------------------------------------------------
    # ACCESO / PERMISOS
    # -------------------------------------------------------------

    def test_usuario_anonimo_no_puede_generar_la_orden(self):
        self.client.logout()

        response = self.client.post(self.generate_url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_usuario_sin_permiso_recibe_403(self):
        response = self.client.post(self.generate_url)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_get_no_esta_permitido(self):
        self.grant_add_workorder_permission()

        response = self.client.get(self.generate_url)

        self.assertEqual(response.status_code, 405)

    def test_resumen_oculta_el_boton_sin_permiso(self):
        response = self.client.get(self.summary_url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_request_installation_order"])
        self.assertNotContains(response, "Generar Orden de Instalación")

    def test_resumen_muestra_el_boton_con_permiso(self):
        self.grant_add_workorder_permission()

        response = self.client.get(self.summary_url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_request_installation_order"])
        self.assertContains(response, "Generar Orden de Instalación")

    # -------------------------------------------------------------
    # GENERACIÓN CORRECTA
    # -------------------------------------------------------------

    def test_genera_la_orden_de_instalacion_y_redirige_al_comprobante(self):
        self.grant_add_workorder_permission()

        response = self.client.post(self.generate_url)

        order = WorkOrder.objects.get(subscription=self.subscription)

        # Tras generar la orden, el siguiente paso es su comprobante,
        # dentro del propio namespace de contracts -no una URL de
        # work_orders-: ver InstallationWorkOrderCreateView.post() y
        # InstallationOrderReceiptView.
        self.assertRedirects(
            response,
            reverse(
                "contracts:installation_order_receipt",
                kwargs={
                    "customer_pk": self.customer.pk,
                    "pk": self.contract.pk,
                },
            ),
        )

        self.assertEqual(order.order_type, self.installation_type)
        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertEqual(order.attention_type, WorkOrder.AttentionType.FIELD)
        self.assertEqual(order.created_by, self.user)
        self.assertEqual(order.branch, self.branch)
        self.assertEqual(order.zone, self.zone)

    def test_no_construye_la_orden_por_fuera_del_servicio(self):
        """
        No hay ningún WorkOrder.objects.create() en la vista: el
        correlativo, el estado inicial y el autor deben salir
        exclusivamente de create_installation_work_order().
        """

        self.grant_add_workorder_permission()

        self.client.post(self.generate_url)

        order = WorkOrder.objects.get(subscription=self.subscription)

        # El formato del correlativo lo decide generate_order_number()
        # dentro del servicio; aquí solo se confirma que se emitió uno.
        self.assertTrue(order.order_number)

    def test_resumen_muestra_la_orden_generada(self):
        self.grant_add_workorder_permission()

        self.client.post(self.generate_url)

        response = self.client.get(self.summary_url)

        order = WorkOrder.objects.get(subscription=self.subscription)

        self.assertContains(response, order.order_number)
        self.assertContains(response, "Pendiente")

    def test_segunda_solicitud_no_duplica_la_orden(self):
        self.grant_add_workorder_permission()

        self.client.post(self.generate_url)
        response = self.client.post(self.generate_url, follow=True)

        self.assertEqual(
            WorkOrder.objects.filter(subscription=self.subscription).count(),
            1,
        )

        self.assertContains(response, "ya tiene una orden de instalación abierta")

    def test_resumen_bloquea_boton_si_ya_hay_instalacion_abierta(self):
        self.grant_add_workorder_permission()

        self.client.post(self.generate_url)

        response = self.client.get(self.summary_url)

        self.assertFalse(response.context["can_generate_installation_order"])
        self.assertNotContains(response, "Generar Orden de Instalación")

    # -------------------------------------------------------------
    # SUSCRIPCIÓN / CONTRATO DE OTRO CLIENTE
    # -------------------------------------------------------------

    def test_no_genera_orden_para_contrato_de_otro_cliente(self):
        self.grant_add_workorder_permission()

        other_customer = Customer.objects.create(
            code="CLI-OT-0002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="11122233",
            person_type=Customer.PersonType.NATURAL,
            first_name="Carlos",
            paternal_surname="Ramos",
        )

        url_con_cliente_ajeno = reverse(
            "contracts:generate_installation_order",
            kwargs={
                "customer_pk": other_customer.pk,
                "pk": self.contract.pk,
            },
        )

        response = self.client.post(url_con_cliente_ajeno)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(WorkOrder.objects.count(), 0)
