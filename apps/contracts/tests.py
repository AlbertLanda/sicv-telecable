import io
import tempfile
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer, CustomerAddress
from apps.organization import branding
from apps.organization.models import Branch, Zone
from apps.payments.models import Issuer
from apps.services.models import Plan, ServiceType, Subscription
from apps.work_orders.models import OrderReason, OrderType, WorkOrder

from PIL import Image as PILImage, ImageDraw
from reportlab.platypus import KeepTogether, Table

from .clausulas import titulo_del_contrato
from .document import datos_del_contrato
from .forms import InstallationWorkOrderForm
from .pdf import (
    SEPARACION_DEL_SELLO,
    _cuerpo_del_contrato,
    _estilos,
    _firmas,
    render_contract,
)
from .models import Contract, ContractSignature
from .signatures import (
    borrar_firma,
    contrato_de_la_orden,
    firma_del_contrato,
    firmar_contrato,
)


User = get_user_model()


class ContractCreateTests(TestCase):
    """Alta del contrato de servicio.

    La pantalla declara lo que se firma -servicio, plan, modalidad, cuotas-
    y no solo a qué suscripción se engancha. Lo que se prueba aquí es esa
    cadena: que servicio manda sobre plan, que los dos tienen que coincidir
    con la suscripción que se contrata, y que los datos de cuenta se piden
    exactamente donde el servicio los necesita.
    """

    # Los diez campos de la pantalla, en el orden del sistema anterior.
    # Se declara aquí y no dentro de una prueba porque dos pruebas lo
    # necesitan: la que comprueba el formulario completo y la que comprueba
    # que los campos retirados no volvieron.
    CAMPOS_ESPERADOS = [
        "service_type",
        "plan",
        "modality",
        "installments",
        "start_date",
        "playhub_email",
        "playhub_phone",
    ]

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

        # APPS y sus planes los siembra la migración de catálogo: son los que
        # el contrato ofrece de verdad, así que las pruebas de cuenta PlayHub
        # usan esos y no un servicio inventado para la ocasión.
        self.apps_service_type = ServiceType.objects.get(code="APPS")
        self.apps_plan = Plan.objects.get(code="APP-PREMIUM")

        self.apps_subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.apps_service_type,
            plan=self.apps_plan,
            status=Subscription.Status.PRESALE,
            service_number=1,
        )

        self.create_url = reverse(
            "contracts:contract_create",
            kwargs={
                "customer_pk": self.customer.pk,
            },
        )

    def datos_validos(self, **cambios):
        """Un POST que la pantalla acepta, con lo que cada prueba cambie."""

        datos = {
            "service_type": self.service_type.pk,
            "plan": self.plan.pk,
            "modality": Contract.Modality.SALE,
            "installments": 1,
            "start_date": "2026-08-20",
            "playhub_email": "",
            "playhub_phone": "",
        }

        datos.update(cambios)

        return datos

    def datos_de_apps(self, **cambios):
        """El mismo POST, pero sobre el servicio que se entrega por cuenta."""

        datos = self.datos_validos(
            service_type=self.apps_service_type.pk,
            plan=self.apps_plan.pk,
        )

        datos.update(cambios)

        return datos

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
    # CAMPOS DE LA PANTALLA
    # -------------------------------------------------------------

    def test_formulario_pide_exactamente_los_campos_de_la_pantalla(self):
        response = self.client.get(self.create_url)

        self.assertEqual(
            list(response.context["form"].fields),
            self.CAMPOS_ESPERADOS,
        )

    def test_formulario_no_pide_fin_medicion_equipo_ni_plantilla(self):
        """Los cuatro campos retirados del formulario del sistema anterior.

        Fin y ultimo corte los mueve la operacion del servicio, no el alta.
        Equipo consta en la orden de instalacion. Medicion y plantilla no
        describen nada que el SICV registre.
        """

        campos = self.client.get(self.create_url).context["form"].fields

        for retirado in (
            "end_date",
            "measurement",
            "equipment",
            "template",
            "notes",
        ):
            self.assertNotIn(retirado, campos)

    def test_codigo_y_numero_no_son_campos_del_formulario(self):
        response = self.client.get(self.create_url)

        form = response.context["form"]

        self.assertNotIn("contract_number", form.fields)
        self.assertNotIn("code", form.fields)

    def test_codigo_y_numero_se_muestran_con_el_valor_que_les_toca(self):
        response = self.client.get(self.create_url)

        self.assertEqual(response.context["next_contract_code"], 1)
        self.assertEqual(response.context["next_contract_number"], "CONT-000001")

        self.assertContains(response, "CONT-000001")

    def test_estado_no_es_un_campo_del_formulario(self):
        """Un contrato nuevo nace activo, y eso no se elige.

        El estado cambia después -suspendido, cancelado, finalizado- por lo
        que pasa con el servicio. Ofrecerlo al registrar permitía crear un
        contrato ya cancelado, que no es un contrato sino un registro sin
        uso.
        """

        response = self.client.get(self.create_url)

        self.assertNotIn("status", response.context["form"].fields)
        self.assertNotContains(response, '<select name="status"')

    def test_estado_se_muestra_bloqueado_en_activo(self):
        response = self.client.get(self.create_url)

        self.assertEqual(
            response.context["form"].instance.get_status_display(),
            "Activo",
        )

        self.assertContains(response, 'value="Activo"')

    def test_modalidad_llega_en_venta(self):
        response = self.client.get(self.create_url)

        form = response.context["form"]

        self.assertEqual(form["modality"].value(), Contract.Modality.SALE)

        # Y sin opción vacía: la modalidad de un contrato nuevo siempre es
        # una de las cuatro, así que ofrecer «seleccione...» solo daba la
        # opción de dejarla sin poner.
        self.assertNotIn(
            "",
            [valor for valor, _ in form.fields["modality"].choices],
        )

    def test_inicio_llega_con_la_fecha_de_hoy(self):
        response = self.client.get(self.create_url)

        hoy = timezone.localdate()

        self.assertEqual(
            response.context["form"].initial["start_date"],
            hoy,
        )

        # Y llega escrita como el navegador la entiende. En el formato local
        # -21/09/2026- un `<input type="date">` descarta el valor y el campo
        # se ve vacio aunque el formulario lo traiga puesto.
        self.assertContains(response, f'value="{hoy:%Y-%m-%d}"')

    # -------------------------------------------------------------
    # CASCADA SERVICIO -> PLAN -> SUSCRIPCIÓN
    # -------------------------------------------------------------

    def test_catalogo_de_planes_por_servicio_viaja_a_la_pagina(self):
        response = self.client.get(self.create_url)

        catalogo = response.context["plans_by_service_type"]

        self.assertIn(
            self.plan.pk,
            [plan["id"] for plan in catalogo[self.service_type.pk]],
        )

        # Los siete planes de APPS que siembra la migración: el combo de
        # plan tiene que poder ofrecerlos sin volver al servidor.
        self.assertEqual(len(catalogo[self.apps_service_type.pk]), 7)

    def test_catalogo_de_servicios_dice_cual_pide_cuenta_playhub(self):
        response = self.client.get(self.create_url)

        configuracion = response.context["service_type_config"]

        self.assertTrue(
            configuracion[self.apps_service_type.pk]["requires_playhub_account"]
        )
        self.assertFalse(
            configuracion[self.service_type.pk]["requires_playhub_account"]
        )

    def test_catalogo_de_suscripciones_trae_su_servicio_y_su_plan(self):
        response = self.client.get(self.create_url)

        catalogo = {
            item["id"]: item
            for item in response.context["subscriptions_catalog"]
        }

        self.assertEqual(
            catalogo[self.subscription.pk]["service_type"],
            self.service_type.pk,
        )
        self.assertEqual(
            catalogo[self.subscription.pk]["plan"],
            self.plan.pk,
        )
        # La suscripción se identifica por su código, que es lo que el
        # campo bloqueado muestra.
        self.assertEqual(
            catalogo[self.subscription.pk]["label"],
            str(self.subscription.pk),
        )

    def test_la_pantalla_abre_en_duo_con_su_primer_plan(self):
        """Sin suscripción a cuestas, el alta arranca en el servicio que más
        se contrata, con el plan que encabeza su combo."""

        duo = ServiceType.objects.create(code="DUO", name="DUO")

        primero = Plan.objects.create(
            service_type=duo,
            code="DUO-2026-600",
            name="PLAN DUO ESTANDAR 600MG - 2026",
            generation=2026,
            speed_mbps=600,
        )

        Plan.objects.create(
            service_type=duo,
            code="DUO-2025-300",
            name="Duo 300 Mbps - 2025",
            generation=2025,
            speed_mbps=300,
        )

        response = self.client.get(self.create_url)

        initial = response.context["form"].initial

        self.assertEqual(initial["service_type"], duo.pk)
        self.assertEqual(initial["plan"], primero.pk)

        # Y es el primero del combo, no cualquiera de los dos.
        self.assertEqual(
            response.context["plans_by_service_type"][duo.pk][0]["id"],
            primero.pk,
        )

    def test_la_suscripcion_que_llega_por_enlace_manda_sobre_el_defecto(self):
        ServiceType.objects.create(code="DUO", name="DUO")

        response = self.client.get(
            f"{self.create_url}?subscription={self.subscription.pk}"
        )

        self.assertEqual(
            response.context["form"].initial["service_type"],
            self.service_type.pk,
        )

    def test_preselecciona_servicio_y_plan_de_la_suscripcion(self):
        response = self.client.get(
            f"{self.create_url}?subscription={self.subscription.pk}"
        )

        initial = response.context["form"].initial

        self.assertEqual(initial["service_type"], self.service_type.pk)
        self.assertEqual(initial["plan"], self.plan.pk)

    def test_plan_de_otro_servicio_es_rechazado(self):
        response = self.client.post(
            self.create_url,
            self.datos_validos(plan=self.apps_plan.pk),
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "plan",
            "El plan seleccionado no pertenece al servicio elegido.",
        )

        self.assertEqual(Contract.objects.count(), 0)

    # -------------------------------------------------------------
    # SUSCRIPCIÓN RESUELTA POR EL SISTEMA
    # -------------------------------------------------------------

    def test_la_suscripcion_no_es_un_campo_del_formulario(self):
        response = self.client.get(self.create_url)

        self.assertNotIn("subscription", response.context["form"].fields)
        self.assertNotContains(response, '<select name="subscription"')

    def test_la_suscripcion_se_muestra_bloqueada_al_abrir(self):
        response = self.client.get(
            f"{self.create_url}?subscription={self.subscription.pk}"
        )

        self.assertEqual(
            response.context["resolved_subscription_label"],
            str(self.subscription.pk),
        )

        self.assertContains(response, 'id="suscripcion-resuelta"')

    def test_sin_suscripcion_el_campo_dice_ninguno(self):
        """La palabra del sistema anterior: el campo está vacío porque no
        hay nada que poner, no porque falte escribirlo."""

        duo = ServiceType.objects.create(code="DUO", name="DUO")

        Plan.objects.create(
            service_type=duo,
            code="DUO-600",
            name="PLAN DUO ESTANDAR 600MG",
            speed_mbps=600,
        )

        # La pantalla abre en DUO y este cliente solo tiene internet.
        response = self.client.get(self.create_url)

        self.assertEqual(
            response.context["resolved_subscription_label"],
            "Ninguno",
        )

        self.assertContains(response, 'value="Ninguno"')

    def test_el_contrato_se_engancha_a_la_suscripcion_del_plan_elegido(self):
        otro_plan = Plan.objects.create(
            service_type=self.service_type,
            code="PLAN200",
            name="Plan 200 Mbps",
            speed_mbps=200,
        )

        otra_suscripcion = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=otro_plan,
            status=Subscription.Status.PRESALE,
            service_number=2,
        )

        self.client.post(
            self.create_url,
            self.datos_validos(plan=otro_plan.pk),
        )

        contrato = Contract.objects.get()

        self.assertEqual(contrato.subscription, otra_suscripcion)
        self.assertEqual(contrato.plan, otro_plan)

    def test_sin_suscripcion_disponible_avisa_y_no_crea_contrato(self):
        """APPS tiene suscripción; el plan que se elige aquí, no."""

        otro_plan_apps = Plan.objects.get(code="APP-TELECABLE")

        response = self.client.post(
            self.create_url,
            self.datos_de_apps(plan=otro_plan_apps.pk),
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            None,
            (
                "Este cliente no tiene una suscripción en Preventa "
                "disponible para el servicio y plan elegidos. "
                "Regístrela antes de contratar."
            ),
        )

        self.assertEqual(Contract.objects.count(), 0)

    def test_la_resolucion_no_cruza_clientes(self):
        """La suscripción de otro cliente no entra, aunque calce el plan."""

        otro_cliente = Customer.objects.create(
            code="CLI-0009",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="10101010",
            person_type=Customer.PersonType.NATURAL,
            first_name="Luis",
            paternal_surname="Vargas",
        )

        otra_direccion = CustomerAddress.objects.create(
            customer=otro_cliente,
            zone=self.zone,
            address="Jr. Ajeno 999",
            district="Huancayo",
            is_primary=True,
        )

        plan_sin_suscripcion_propia = Plan.objects.create(
            service_type=self.service_type,
            code="PLAN300",
            name="Plan 300 Mbps",
            speed_mbps=300,
        )

        suscripcion_ajena = Subscription.objects.create(
            customer=otro_cliente,
            address=otra_direccion,
            service_type=self.service_type,
            plan=plan_sin_suscripcion_propia,
            status=Subscription.Status.PRESALE,
            service_number=1,
        )

        response = self.client.post(
            self.create_url,
            self.datos_validos(plan=plan_sin_suscripcion_propia.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Contract.objects.count(), 0)
        self.assertFalse(suscripcion_ajena.contracts.exists())

    def test_el_modelo_sigue_exigiendo_que_los_tres_coincidan(self):
        """La resolución hace imposible el desajuste desde la pantalla.

        El invariante se prueba igual contra el modelo: es lo que protege al
        contrato de un alta hecha por otra vía -el admin, un script- y lo
        que sostiene que servicio y plan del contrato signifiquen algo.
        """

        contrato = Contract(
            contract_number="CONT-000009",
            customer=self.customer,
            subscription=self.subscription,
            service_type=self.apps_service_type,
            plan=self.apps_plan,
            modality=Contract.Modality.SALE,
            start_date=date(2026, 8, 20),
        )

        with self.assertRaises(ValidationError):
            contrato.full_clean()

    # -------------------------------------------------------------
    # SUSCRIPCIONES QUE SE OFRECEN
    # -------------------------------------------------------------

    def catalogo_de_suscripciones(self):
        """Los identificadores que la pantalla considera contratables."""

        response = self.client.get(self.create_url)

        return [
            item["id"]
            for item in response.context["subscriptions_catalog"]
        ]

    def test_una_suscripcion_en_preventa_es_contratable(self):
        self.assertIn(self.subscription.pk, self.catalogo_de_suscripciones())

    def test_una_suscripcion_activa_no_es_contratable(self):
        active_subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=2,
        )

        self.assertNotIn(
            active_subscription.pk,
            self.catalogo_de_suscripciones(),
        )

    def test_una_suscripcion_ya_contratada_no_es_contratable(self):
        """Un contrato por suscripción.

        Si siguiera en el grupo contratable, la resolución elegiría una que
        el propio contrato rechaza después por duplicada.
        """

        Contract.objects.create(
            contract_number="CONT-000001",
            customer=self.customer,
            subscription=self.subscription,
            service_type=self.service_type,
            plan=self.plan,
            modality=Contract.Modality.SALE,
            start_date=date(2026, 8, 1),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )

        self.assertNotIn(
            self.subscription.pk,
            self.catalogo_de_suscripciones(),
        )

    def test_la_suscripcion_de_otro_cliente_no_es_contratable(self):
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

        self.assertNotIn(
            other_subscription.pk,
            self.catalogo_de_suscripciones(),
        )

    # -------------------------------------------------------------
    # CREACIÓN CORRECTA
    # -------------------------------------------------------------

    def test_crear_contrato_desde_suscripcion_presale(self):
        response = self.client.post(
            self.create_url,
            self.datos_validos(),
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

    def test_contrato_guarda_el_servicio_que_se_firmo(self):
        self.client.post(self.create_url, self.datos_validos(installments=6))

        contract = Contract.objects.get(subscription=self.subscription)

        self.assertEqual(contract.service_type, self.service_type)
        self.assertEqual(contract.plan, self.plan)
        self.assertEqual(contract.modality, Contract.Modality.SALE)
        self.assertEqual(contract.installments, 6)

        # La última activación la estampa la activación del servicio, que no
        # es esta pantalla.
        self.assertIsNone(contract.last_activation_date)

    def test_cuotas_menores_a_una_son_rechazadas(self):
        response = self.client.post(
            self.create_url,
            self.datos_validos(installments=0),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("installments", response.context["form"].errors)
        self.assertEqual(Contract.objects.count(), 0)

    def test_modalidad_es_obligatoria(self):
        response = self.client.post(
            self.create_url,
            self.datos_validos(modality=""),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("modality", response.context["form"].errors)
        self.assertEqual(Contract.objects.count(), 0)

    # -------------------------------------------------------------
    # NÚMERO AUTOMÁTICO
    # -------------------------------------------------------------

    def test_numero_de_contrato_se_genera_automaticamente(self):
        response = self.client.post(
            self.create_url,
            self.datos_validos(),
        )

        self.assertEqual(response.status_code, 302)

        contract = Contract.objects.get(
            subscription=self.subscription
        )

        self.assertEqual(
            contract.contract_number,
            "CONT-000001",
        )

    def test_numero_enviado_a_mano_no_se_respeta(self):
        """El número lo pone el sistema, aunque el POST traiga otro."""

        self.client.post(
            self.create_url,
            self.datos_validos(contract_number="CONT-999999"),
        )

        contract = Contract.objects.get(subscription=self.subscription)

        self.assertEqual(contract.contract_number, "CONT-000001")

    # -------------------------------------------------------------
    # ESTADO
    # -------------------------------------------------------------

    def test_contrato_se_crea_activo(self):
        """Y lo pone el sistema: el POST no trae estado."""

        self.client.post(
            self.create_url,
            self.datos_validos(),
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
    # CUENTA PLAYHUB
    # -------------------------------------------------------------

    def test_apps_exige_correo_y_celular_playhub(self):
        response = self.client.post(
            self.create_url,
            self.datos_de_apps(),
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "playhub_email",
            "Indique el correo PlayHub del abonado.",
        )
        self.assertFormError(
            response.context["form"],
            "playhub_phone",
            "Indique el celular PlayHub del abonado.",
        )

        self.assertEqual(Contract.objects.count(), 0)

    def test_apps_guarda_la_cuenta_playhub(self):
        response = self.client.post(
            self.create_url,
            self.datos_de_apps(
                playhub_email="abonado@correo.com",
                playhub_phone="987654321",
            ),
        )

        self.assertEqual(response.status_code, 302)

        contract = Contract.objects.get(subscription=self.apps_subscription)

        self.assertEqual(contract.playhub_email, "abonado@correo.com")
        self.assertEqual(contract.playhub_phone, "987654321")

    def test_servicio_sin_cuenta_no_acepta_datos_playhub(self):
        response = self.client.post(
            self.create_url,
            self.datos_validos(playhub_email="abonado@correo.com"),
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            "playhub_email",
            (
                "Los datos PlayHub solo corresponden a servicios "
                "que se entregan a una cuenta."
            ),
        )

        self.assertEqual(Contract.objects.count(), 0)

    # -------------------------------------------------------------
    # CONTRATO DUPLICADO
    # -------------------------------------------------------------

    def test_no_permite_segundo_contrato_activo_para_misma_suscripcion(self):
        Contract.objects.create(
            contract_number="CONT-000001",
            customer=self.customer,
            subscription=self.subscription,
            service_type=self.service_type,
            plan=self.plan,
            modality=Contract.Modality.SALE,
            start_date=date(2026, 8, 1),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )

        response = self.client.post(
            self.create_url,
            self.datos_validos(),
        )

        self.assertEqual(response.status_code, 200)

        self.assertFormError(
            response.context["form"],
            None,
            (
                "Este cliente no tiene una suscripción en Preventa "
                "disponible para el servicio y plan elegidos. "
                "Regístrela antes de contratar."
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

    # -------------------------------------------------------------
    # RESUMEN DE CONTRATACIÓN (día 02/09)
    # -------------------------------------------------------------

    def test_crear_contrato_redirige_al_resumen(self):
        response = self.client.post(
            self.create_url,
            self.datos_validos(),
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
            service_type=self.service_type,
            plan=self.plan,
            modality=Contract.Modality.SALE,
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

    def test_resumen_muestra_modalidad_y_cuotas_del_contrato(self):
        contract = Contract.objects.create(
            contract_number="CONT-000001",
            customer=self.customer,
            subscription=self.subscription,
            service_type=self.service_type,
            plan=self.plan,
            modality=Contract.Modality.RENTAL,
            installments=6,
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

        self.assertContains(response, "Alquiler")
        self.assertContains(response, "Cuotas")

    def test_resumen_muestra_la_cuenta_playhub_contratada(self):
        contract = Contract.objects.create(
            contract_number="CONT-000002",
            customer=self.customer,
            subscription=self.apps_subscription,
            service_type=self.apps_service_type,
            plan=self.apps_plan,
            modality=Contract.Modality.SALE,
            playhub_email="abonado@correo.com",
            playhub_phone="987654321",
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

        self.assertContains(response, "abonado@correo.com")
        self.assertContains(response, "987654321")

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
            service_type=self.service_type,
            plan=self.plan,
            modality=Contract.Modality.SALE,
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

        initial = response.context["form"].initial

        self.assertEqual(initial["service_type"], self.service_type.pk)
        self.assertEqual(initial["plan"], self.plan.pk)

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
            self.datos_validos(),
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
            service_type=self.subscription.service_type,
            plan=self.subscription.plan,
            modality=Contract.Modality.SALE,
            start_date=date(2026, 9, 3),
            status=Contract.Status.ACTIVE,
            is_active=True,
        )

        self.installation_type = OrderType.objects.create(
            code="INSTALLATION",
            name="Instalación",
        )

        self.seller = User.objects.create_user(
            username="vendedor_ot",
            password="123",
            role=User.Role.SALES,
            branch=self.branch,
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

    def grant_view_workorder_permission(self):
        permission = Permission.objects.get(
            codename="view_workorder",
            content_type__app_label="work_orders",
        )

        self.user.user_permissions.add(permission)

    def login_user_without_workorder_permissions(self):
        self.user.role = User.Role.SALES
        self.user.save(update_fields=["role"])

        self.user.user_permissions.clear()

        self.client.logout()
        self.client.login(
            username="colaborador_ot",
            password="123",
        )

    # -------------------------------------------------------------
    # ACCESO / PERMISOS
    # -------------------------------------------------------------

    def test_usuario_anonimo_no_puede_generar_la_orden(self):
        self.client.logout()

        response = self.client.post(self.generate_url)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_usuario_sin_permiso_recibe_403(self):
        self.login_user_without_workorder_permissions()

        response = self.client.post(self.generate_url)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_get_muestra_el_formulario(self):
        """
        Revisión del 03/09: "Generar Orden de Instalación" ya no crea la
        orden en el mismo clic -ahora navega (GET) a un formulario propio
        (InstallationWorkOrderCreateView, ahora un FormView) y solo la
        crea al confirmarlo (POST)-.
        """

        self.grant_add_workorder_permission()

        response = self.client.get(self.generate_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(WorkOrder.objects.count(), 0)
        self.assertIsInstance(
            response.context["form"],
            InstallationWorkOrderForm,
        )
        self.assertEqual(response.context["contract"], self.contract)
        self.assertEqual(response.context["customer"], self.customer)
        self.assertEqual(response.context["subscription"], self.subscription)
        self.assertContains(response, self.plan.name)
        self.assertContains(response, self.address.address)

    def test_get_redirige_al_resumen_si_ya_hay_instalacion_abierta(self):
        """
        Abrir la URL del formulario directamente -sin pasar por el botón,
        ya oculto en el resumen- tampoco debe ofrecer un formulario
        condenado a fallar cuando ya existe una instalación abierta.
        """

        self.grant_add_workorder_permission()

        self.client.post(self.generate_url)

        response = self.client.get(self.generate_url, follow=True)

        self.assertRedirects(response, self.summary_url)
        self.assertContains(response, "ya tiene una orden de instalación abierta")
        self.assertEqual(WorkOrder.objects.count(), 1)

    def test_el_contrato_no_ofrece_la_orden_de_instalacion(self):
        """El contrato es el documento comercial, no el trabajo de campo.

        La orden se crea desde «Nueva orden de trabajo», que es la puerta
        común a todas. La vista de generación sigue existiendo y sirviendo
        por su URL: lo que se retiró es su presencia en esta pantalla.
        """

        self.grant_add_workorder_permission()

        response = self.client.get(self.summary_url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Generar Orden de Instalación")
        self.assertNotContains(response, "Orden de instalación")
        self.assertNotIn("installation_order", response.context)

    # -------------------------------------------------------------
    # GENERACIÓN CORRECTA
    # -------------------------------------------------------------

    def test_genera_la_orden_de_instalacion_y_redirige_al_comprobante(self):
        self.grant_add_workorder_permission()

        response = self.client.post(self.generate_url)

        order = WorkOrder.objects.get(subscription=self.subscription)

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

    def test_post_con_datos_del_formulario_los_persiste_en_la_orden(self):
        """Los datos comerciales válidos llegan a la OT; instalación es FIELD."""

        self.grant_add_workorder_permission()

        reason = OrderReason.objects.create(
            order_type=self.installation_type,
            code="NUEVA-CONEXION",
            name="Nueva conexión",
            is_active=True,
        )

        response = self.client.post(
            self.generate_url,
            {
                "reason": reason.pk,
                "priority": WorkOrder.Priority.HIGH,
                "attention_type": WorkOrder.AttentionType.FIELD,
                "seller": self.seller.pk,
                "detail": "Coordinar con el abonado antes de las 9am.",
            },
        )

        order = WorkOrder.objects.get(subscription=self.subscription)

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

        self.assertEqual(order.reason, reason)
        self.assertEqual(order.priority, WorkOrder.Priority.HIGH)
        self.assertEqual(order.attention_type, WorkOrder.AttentionType.FIELD)
        self.assertEqual(order.seller, self.seller)
        self.assertEqual(
            order.detail,
            "Coordinar con el abonado antes de las 9am.",
        )

    def test_formulario_rechaza_instalacion_system_noc(self):
        """Una instalación SYSTEM no debe crear una OT invisible para la app."""
        self.grant_add_workorder_permission()

        response = self.client.post(
            self.generate_url,
            {"attention_type": WorkOrder.AttentionType.SYSTEM},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"],
            "attention_type",
            "Escoja una opción válida. SYSTEM no es una de las opciones disponibles.",
        )
        self.assertFalse(
            WorkOrder.objects.filter(subscription=self.subscription).exists()
        )

    def test_post_sin_tipo_de_atencion_aplica_campo_por_defecto(self):
        """
        Si ATC no envía el tipo, la instalación queda en Campo.
        """

        self.grant_add_workorder_permission()

        self.client.post(self.generate_url, {})

        order = WorkOrder.objects.get(subscription=self.subscription)

        self.assertEqual(order.attention_type, WorkOrder.AttentionType.FIELD)

    def test_no_construye_la_orden_por_fuera_del_servicio(self):
        self.grant_add_workorder_permission()

        self.client.post(self.generate_url)

        order = WorkOrder.objects.get(subscription=self.subscription)

        self.assertTrue(order.order_number)

    def test_segunda_solicitud_no_duplica_la_orden(self):
        self.grant_add_workorder_permission()

        self.client.post(self.generate_url)
        response = self.client.post(self.generate_url, follow=True)

        self.assertEqual(
            WorkOrder.objects.filter(subscription=self.subscription).count(),
            1,
        )

        self.assertContains(response, "ya tiene una orden de instalación abierta")

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

    # -------------------------------------------------------------
    # ORDEN CREADA: CANCELAR, IMPRIMIR Y VER ORDEN
    # -------------------------------------------------------------

    def test_orden_ofrece_cancelar_imprimir_y_ver_orden_con_permiso(self):
        self.grant_add_workorder_permission()
        self.grant_view_workorder_permission()

        self.client.post(self.generate_url)

        order = WorkOrder.objects.get(subscription=self.subscription)

        receipt_url = reverse(
            "contracts:installation_order_receipt",
            kwargs={
                "customer_pk": self.customer.pk,
                "pk": self.contract.pk,
            },
        )

        response = self.client.get(receipt_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cancelar")
        self.assertContains(response, "Imprimir")
        self.assertContains(response, "Ver orden")
        self.assertNotContains(response, ">Liquidar<")

        detail_url = reverse(
            "work_orders:detail",
            kwargs={"pk": order.pk},
        )

        self.assertContains(response, detail_url)

    def test_orden_no_ofrece_ver_orden_sin_permiso(self):
        self.client.post(self.generate_url)

        order = WorkOrder.objects.get(subscription=self.subscription)

        receipt_url = reverse(
            "contracts:installation_order_receipt",
            kwargs={
                "customer_pk": self.customer.pk,
                "pk": self.contract.pk,
            },
        )

        self.login_user_without_workorder_permissions()

        response = self.client.get(receipt_url)

        self.assertNotContains(response, "Ver orden")

        detail_url = reverse(
            "work_orders:detail",
            kwargs={"pk": order.pk},
        )

        self.assertNotContains(response, detail_url)

    def test_cancelar_de_la_orden_vuelve_a_la_ficha_del_cliente_sin_alterarla(self):
        self.grant_add_workorder_permission()

        self.client.post(self.generate_url)

        order = WorkOrder.objects.get(subscription=self.subscription)

        receipt_url = reverse(
            "contracts:installation_order_receipt",
            kwargs={
                "customer_pk": self.customer.pk,
                "pk": self.contract.pk,
            },
        )

        response = self.client.get(receipt_url)

        self.assertContains(
            response,
            reverse("customers:detail", kwargs={"pk": self.customer.pk}),
        )

        order.refresh_from_db()

        self.assertEqual(order.status, WorkOrder.Status.PENDING)

    # -------------------------------------------------------------
    # DATOS QUE DEBE MOSTRAR LA ORDEN DE INSTALACIÓN
    # -------------------------------------------------------------

    def test_orden_muestra_los_datos_requeridos(self):
        self.grant_add_workorder_permission()

        self.customer.phone = "987654321"
        self.customer.save(update_fields=["phone"])

        self.address.electrical_supply_code = "SUM-000123"
        self.address.save(update_fields=["electrical_supply_code"])

        reason = OrderReason.objects.create(
            order_type=self.installation_type,
            code="NUEVA-CONEXION",
            name="Nueva conexión",
            is_active=True,
        )

        self.client.post(
            self.generate_url,
            {
                "reason": reason.pk,
                "priority": WorkOrder.Priority.HIGH,
                "attention_type": WorkOrder.AttentionType.FIELD,
                "seller": self.seller.pk,
                "detail": "Coordinar con el abonado antes de las 9am.",
            },
        )

        order = WorkOrder.objects.get(subscription=self.subscription)

        receipt_url = reverse(
            "contracts:installation_order_receipt",
            kwargs={
                "customer_pk": self.customer.pk,
                "pk": self.contract.pk,
            },
        )

        response = self.client.get(receipt_url)

        self.assertContains(response, str(self.customer))
        self.assertContains(response, self.customer.code)
        self.assertContains(response, self.address.address)
        self.assertContains(response, "SUM-000123")
        self.assertContains(response, order.get_status_display())
        self.assertContains(
            response,
            timezone.localtime(order.created_at).strftime("%d/%m/%Y"),
        )
        self.assertContains(
            response,
            "Coordinar con el abonado antes de las 9am.",
        )
        self.assertContains(response, self.plan.name)
        self.assertContains(response, "987654321")
        self.assertContains(response, reason.name)
        self.assertContains(response, order.get_priority_display())
        self.assertContains(response, order.get_attention_type_display())
        self.assertContains(response, self.seller.username)

    def test_orden_muestra_gps_no_disponible_sin_coordenadas(self):
        self.grant_add_workorder_permission()

        self.client.post(self.generate_url)

        receipt_url = reverse(
            "contracts:installation_order_receipt",
            kwargs={
                "customer_pk": self.customer.pk,
                "pk": self.contract.pk,
            },
        )

        response = self.client.get(receipt_url)

        self.assertContains(response, "GPS no disponible")
        self.assertNotContains(response, "Abrir en Google Maps")

    def test_orden_muestra_boton_de_maps_con_gps_valido(self):
        self.grant_add_workorder_permission()

        self.address.latitude = Decimal("-6.231234")
        self.address.longitude = Decimal("-77.871234")
        self.address.save(update_fields=["latitude", "longitude"])

        self.client.post(self.generate_url)

        receipt_url = reverse(
            "contracts:installation_order_receipt",
            kwargs={
                "customer_pk": self.customer.pk,
                "pk": self.contract.pk,
            },
        )

        response = self.client.get(receipt_url)

        self.assertContains(response, "Abrir en Google Maps")
        self.assertContains(response, "-6.231234")
        self.assertContains(response, "-77.871234")

    def test_orden_muestra_gps_no_disponible_con_coordenadas_en_cero(self):
        self.grant_add_workorder_permission()

        self.address.latitude = Decimal("0.0000000")
        self.address.longitude = Decimal("0.0000000")
        self.address.save(update_fields=["latitude", "longitude"])

        self.client.post(self.generate_url)

        receipt_url = reverse(
            "contracts:installation_order_receipt",
            kwargs={
                "customer_pk": self.customer.pk,
                "pk": self.contract.pk,
            },
        )

        response = self.client.get(receipt_url)

        self.assertContains(response, "GPS no disponible")
        self.assertNotContains(response, "Abrir en Google Maps")


class ContratoDeReferenciaMixin:
    """El contrato de Jauja sobre el que se prueba todo lo que es papel.

    Es el escenario del contrato firmado que ATC entregó como referencia, y
    lo comparten las pruebas del documento y las de su firma: son el mismo
    contrato visto en dos momentos -antes de firmarlo y después-, así que
    montarlo dos veces sería tener dos contratos que pueden separarse.
    """

    def setUp(self):
        # Jauja, porque es la sede del contrato firmado que sirve de
        # referencia: sus oficinas y su jurisdicción están confirmadas. Las
        # tres sedes las siembra una migración, así que aquí se toma la que
        # ya existe en vez de crear una segunda con el mismo código.
        self.branch, _ = Branch.objects.get_or_create(
            code="JAUJA",
            defaults={"name": "Jauja"},
        )

        self.zone, _ = Zone.objects.get_or_create(
            branch=self.branch,
            name="Sausa",
        )

        self.user = User.objects.create_user(
            username="atc_documento",
            password="123",
            role=User.Role.ATC,
            branch=self.branch,
        )

        self.client.login(username="atc_documento", password="123")

        # La empresa emisora también la siembra una migración de cobranza:
        # es la misma razón social con la que se factura, y el contrato no
        # puede decir otra.
        self.issuer, _ = Issuer.objects.get_or_create(
            code="INV",
            defaults={
                "business_name": (
                    "INVERSIONES EN TELECOMUNICACIONES DIGITALES S.A.C."
                ),
                "ruc": "20603110456",
            },
        )

        self.service_type = ServiceType.objects.create(
            code="DUO-DOC",
            name="DUO",
            supports_tv_annexes=True,
        )

        self.plan = Plan.objects.create(
            service_type=self.service_type,
            code="DUO-DOC-600",
            name="PLAN DUO ESTANDAR 600MG - 2026",
            speed_mbps=600,
            monthly_price=Decimal("99.00"),
            included_tv_points=2,
        )

        self.customer = Customer.objects.create(
            code="JA01-A0000001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="71692678",
            person_type=Customer.PersonType.NATURAL,
            first_name="Kevin",
            paternal_surname="Rivera",
            maternal_surname="Ravichagua",
        )

        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Jr. Abraham Valdelomar 235",
            district="Sausa",
            is_primary=True,
        )

        self.subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service_type,
            plan=self.plan,
            status=Subscription.Status.ACTIVE,
            service_number=1,
            base_installation_fee=Decimal("150.00"),
            base_monthly_fee=Decimal("99.00"),
            installation_date=date(2026, 9, 15),
        )

        self.contract = Contract.objects.create(
            contract_number="CONT-000001",
            customer=self.customer,
            subscription=self.subscription,
            service_type=self.service_type,
            plan=self.plan,
            modality=Contract.Modality.SALE,
            installments=1,
            start_date=date(2026, 9, 14),
            status=Contract.Status.ACTIVE,
        )

        self.document_url = reverse(
            "contracts:contract_document",
            kwargs={
                "customer_pk": self.customer.pk,
                "pk": self.contract.pk,
            },
        )


class ContractDocumentTests(ContratoDeReferenciaMixin, TestCase):
    """El contrato de abonado que se imprime y se firma.

    Se reparte como en cobranza: aquí los datos del papel -que se comprueban
    sin abrir un PDF-, el dibujo -que salga y que aguante lo que falte- y la
    entrega -que el navegador reciba el archivo donde toca-.
    """

    def datos(self):
        return datos_del_contrato(self.contract)

    def dibujar(self):
        buffer = BytesIO()
        nombre = render_contract(self.contract, buffer)

        return nombre, buffer.getvalue()

    # -------------------------------------------------------------
    # LO QUE DICE EL PAPEL
    # -------------------------------------------------------------

    def test_el_papel_trae_los_datos_del_abonado(self):
        datos = self.datos()

        self.assertEqual(datos["numero"], "CONT-000001")
        self.assertEqual(datos["codigo_abonado"], "JA01-A0000001")
        self.assertEqual(datos["cliente"], "Kevin Rivera Ravichagua")
        self.assertEqual(datos["documento_tipo"], "DNI")
        self.assertEqual(datos["documento_numero"], "71692678")
        self.assertEqual(
            datos["direccion"],
            "Jr. Abraham Valdelomar 235, Sausa",
        )

    def test_el_papel_trae_el_servicio_y_el_plan_contratados(self):
        datos = self.datos()

        self.assertEqual(
            datos["servicio"],
            "DUO – PLAN DUO ESTANDAR 600MG - 2026",
        )

        # La velocidad la promete la cláusula de OSIPTEL: sin ella, el 70%
        # garantizado no se puede medir contra nada.
        self.assertEqual(datos["velocidad"], 600)

    def test_el_papel_trae_las_tarifas_contratadas(self):
        datos = self.datos()

        self.assertEqual(datos["instalacion"], Decimal("150.00"))
        self.assertEqual(datos["mensualidad"], Decimal("99.00"))

    def test_el_papel_trae_la_fecha_de_suscripcion_en_palabras(self):
        """El cierre del contrato se firma con la fecha escrita."""

        datos = self.datos()

        self.assertEqual(datos["fecha_suscripcion"], date(2026, 9, 14))
        self.assertEqual(datos["dia"], 14)
        self.assertEqual(datos["mes"], "setiembre")
        self.assertEqual(datos["anio"], 2026)

    def test_sin_pagos_la_ultima_fecha_de_pago_va_en_blanco(self):
        self.assertIsNone(self.datos()["ultima_fecha_de_pago"])

    def test_el_papel_trae_la_empresa_que_contrata(self):
        datos = self.datos()

        self.assertEqual(
            datos["empresa"].business_name,
            "INVERSIONES EN TELECOMUNICACIONES DIGITALES S.A.C.",
        )
        self.assertEqual(datos["empresa"].ruc, "20603110456")

    def test_la_sede_del_abonado_decide_oficinas_y_jurisdiccion(self):
        datos = self.datos()

        self.assertIn("Jr. Huancayo 215", datos["oficinas"])
        self.assertEqual(datos["telefono"], "064 466080")
        self.assertEqual(datos["ciudad"], "Jauja")

    def mudar_a(self, codigo):
        """Pone al abonado en otra sede, la que ya existe con ese código.

        Se cambia el abonado de sede y no el código de la suya: las tres las
        siembra una migración, y renombrar una chocaría con la que ya está.
        """

        self.customer.branch = Branch.objects.get(code=codigo)
        self.customer.save(update_fields=["branch"])

    def test_huancayo_imprime_sus_oficinas_y_su_jurisdiccion(self):
        """Cada sede tiene su contrato oficial y no se parecen en esto."""

        self.mudar_a("HUANCAYO")

        datos = self.datos()

        self.assertIn("Jr. Huaytapallana 214", datos["oficinas"])
        self.assertIn("Calle Real 1147", datos["oficinas"])
        self.assertEqual(datos["telefono"], "064 466080")
        self.assertEqual(datos["ciudad"], "Huancayo")

        _, subtitulo = titulo_del_contrato(datos)
        self.assertIn("HUANCAYO", subtitulo)

    def test_la_oroya_contrata_y_litiga_como_yauli(self):
        """El papel de esa sede dice «Yauli – La Oroya», no «La Oroya».

        La ciudad manda en tres sitios -el subtítulo, los tribunales de la
        cláusula undécima y dónde se suscribe-, así que el nombre de la sede
        en el sistema no sirve para esto.
        """

        self.mudar_a("OROYA")

        datos = self.datos()

        self.assertIn("AV. Miguel Grau 1025", datos["oficinas"])
        self.assertIn("Santa Rosa de Saccos", datos["oficinas"])
        self.assertEqual(datos["telefono"], "064 466080")
        self.assertEqual(datos["ciudad"], "Yauli – La Oroya")

        _, subtitulo = titulo_del_contrato(datos)
        self.assertIn("YAULI – LA OROYA", subtitulo)

    def test_las_tres_sedes_dibujan_su_contrato(self):
        """El documento de cada sede sale entero, no solo el de referencia."""

        for codigo in ("JAUJA", "HUANCAYO", "OROYA"):
            with self.subTest(sede=codigo):
                self.mudar_a(codigo)

                _, contenido = self.dibujar()

                self.assertTrue(contenido.startswith(b"%PDF-"))

    def test_una_sede_sin_datos_no_inventa_oficinas_ni_jurisdiccion(self):
        """Mejor un espacio en blanco que una jurisdicción equivocada."""

        self.branch.code = "SEDE-NUEVA"
        self.branch.save(update_fields=["code"])

        datos = self.datos()

        self.assertEqual(datos["oficinas"], "")
        self.assertEqual(datos["telefono"], "")

        # La ciudad cae al nombre de la sede: es lo único que se sabe.
        self.assertEqual(datos["ciudad"], "Jauja")

    def test_la_cuenta_playhub_solo_donde_el_servicio_la_pide(self):
        self.assertIsNone(self.datos()["playhub"])

        self.service_type.requires_playhub_account = True
        self.service_type.save(update_fields=["requires_playhub_account"])

        self.contract.playhub_email = "abonado@correo.com"
        self.contract.playhub_phone = "987654321"
        self.contract.save(update_fields=["playhub_email", "playhub_phone"])

        self.assertEqual(
            self.datos()["playhub"],
            ("abonado@correo.com", "987654321"),
        )

    # -------------------------------------------------------------
    # LA FIRMA DE LA EMPRESA
    # -------------------------------------------------------------

    def test_el_papel_trae_el_sello_de_quien_contrata(self):
        """La empresa no firma en el móvil: su firma va impresa siempre."""

        sello = self.datos()["firma_empresa"]

        self.assertIsNotNone(sello)
        self.assertTrue(sello.startswith(CABECERA_PNG))

    def test_una_razon_social_sin_sello_deja_su_espacio_en_blanco(self):
        """Lo que no se tiene se deja para firmar a mano, no se inventa."""

        self.issuer.code = "OTRA"
        self.issuer.save(update_fields=["code"])

        self.assertIsNone(self.datos()["firma_empresa"])

        _, contenido = self.dibujar()
        self.assertTrue(contenido.startswith(b"%PDF-"))

    def test_bajo_la_linea_sigue_leyendose_quien_contrata(self):
        """El sello es un escaneo; el pie de firma es el dato.

        Los dos dicen la razón social, y es a propósito: una fotocopia del
        contrato puede dejar el sello ilegible, y el nombre de quien contrata
        no puede depender de cómo salga una imagen.
        """

        tabla = _firmas(self.datos(), _estilos())

        bajo_la_linea = tabla._cellvalues[1][0]

        self.assertEqual(
            [parrafo.text for parrafo in bajo_la_linea],
            [
                "<b>LA EMPRESA</b>",
                "INVERSIONES EN TELECOMUNICACIONES DIGITALES S.A.C.",
            ],
        )

    def test_el_sello_no_se_apoya_en_la_linea_sino_encima(self):
        """Un tampón se estampa despegado; el trazo a mano sí toca la línea."""

        tabla = _firmas(self.datos(), _estilos())
        hueco_empresa = tabla._cellvalues[0][0]

        _, y, _, alto = hueco_empresa._medidas_del_trazo()

        self.assertEqual(y, SEPARACION_DEL_SELLO)
        # Sube sin crecer: el bloque de firmas ocupa lo mismo que siempre.
        self.assertLessEqual(y + alto, hueco_empresa.height + 0.01)

    def test_el_sello_se_apoya_en_la_linea_de_la_empresa(self):
        """En su columna, no en la del abonado: cada parte firma en su sitio."""

        tabla = _firmas(self.datos(), _estilos())

        sobre_la_linea = tabla._cellvalues[0]

        self.assertIsNotNone(sobre_la_linea[0]._firma)   # la empresa
        self.assertIsNone(sobre_la_linea[2]._firma)      # el abonado, sin firmar

    # -------------------------------------------------------------
    # EL PAPEL SE DIBUJA
    # -------------------------------------------------------------

    def test_dibuja_el_contrato(self):
        nombre, contenido = self.dibujar()

        self.assertEqual(nombre, "CONT-000001.pdf")
        self.assertTrue(contenido.startswith(b"%PDF-"))
        self.assertGreater(len(contenido), 5000)

    def test_el_contrato_lleva_el_logotipo_de_la_marca(self):
        """La cabecera es la marca, no su nombre escrito a mano."""

        _, con_logo = self.dibujar()

        with tempfile.TemporaryDirectory() as vacio:
            with override_settings(MEDIA_ROOT=vacio):
                _, sin_logo = self.dibujar()

        self.assertGreater(len(con_logo), len(sin_logo))

    def test_la_cabecera_usa_el_logotipo_apaisado(self):
        """La franja de la cabecera es ancha y baja: el isotipo cuadrado ahí
        sale como un sello suelto."""

        with tempfile.TemporaryDirectory() as carpeta:
            from PIL import Image as PilImage

            solo_isotipo = Path(carpeta) / f"{branding.STEM}.png"
            PilImage.new("RGB", (80, 80), (10, 60, 120)).save(solo_isotipo)

            with override_settings(MEDIA_ROOT=carpeta):
                _, sin_apaisado = self.dibujar()

            apaisado = Path(carpeta) / f"{branding.STEM_APAISADO}.png"
            PilImage.new("RGB", (200, 50), (10, 60, 120)).save(apaisado)

            with override_settings(MEDIA_ROOT=carpeta):
                _, con_apaisado = self.dibujar()

        # Con el isotipo a solas la cabecera va sin dibujo; solo aparece
        # cuando está el apaisado, que es el que pide el contrato.
        self.assertGreater(len(con_apaisado), len(sin_apaisado))

    def test_sin_el_archivo_del_logotipo_el_contrato_igual_sale(self):
        """Nadie se queda sin su contrato porque falte un dibujo."""

        with tempfile.TemporaryDirectory() as vacio:
            with override_settings(MEDIA_ROOT=vacio):
                _, contenido = self.dibujar()

        self.assertTrue(contenido.startswith(b"%PDF-"))

    def test_sin_empresa_emisora_el_contrato_igual_sale(self):
        """Un despliegue a medio configurar no deja la oficina parada.

        Sale con el hueco de la razón social a la vista, que es lo que hay
        que completar, en vez de reventar al imprimir.
        """

        # No se borra: los talonarios de cobranza la protegen. Se le cambia
        # el código, que es lo que el documento usa para encontrarla.
        self.issuer.code = "OTRA"
        self.issuer.save(update_fields=["code"])

        _, contenido = self.dibujar()

        self.assertTrue(contenido.startswith(b"%PDF-"))

    def test_un_plan_sin_velocidad_igual_sale(self):
        """Telefonía y fibra oscura no tienen Mbps que prometer."""

        self.plan.speed_mbps = None
        self.plan.save(update_fields=["speed_mbps"])

        _, contenido = self.dibujar()

        self.assertTrue(contenido.startswith(b"%PDF-"))

    def test_con_cuenta_playhub_igual_sale(self):
        self.service_type.requires_playhub_account = True
        self.service_type.save(update_fields=["requires_playhub_account"])

        self.contract.playhub_email = "abonado@correo.com"
        self.contract.playhub_phone = "987654321"
        self.contract.save(update_fields=["playhub_email", "playhub_phone"])

        _, contenido = self.dibujar()

        self.assertTrue(contenido.startswith(b"%PDF-"))

    # -------------------------------------------------------------
    # LA ENTREGA
    # -------------------------------------------------------------

    def test_usuario_anonimo_no_puede_imprimir_el_contrato(self):
        self.client.logout()

        response = self.client.get(self.document_url)

        self.assertEqual(response.status_code, 302)

    def test_no_entrega_el_contrato_de_otro_cliente(self):
        otro = Customer.objects.create(
            code="JA01-A0000002",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="10101010",
            person_type=Customer.PersonType.NATURAL,
            first_name="Otro",
            paternal_surname="Cliente",
        )

        response = self.client.get(
            reverse(
                "contracts:contract_document",
                kwargs={
                    # El contrato no es de este cliente.
                    "customer_pk": otro.pk,
                    "pk": self.contract.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_con_ver_llega_al_visor_del_navegador(self):
        """`?ver=1` es lo que hace que se vea en la pestaña de al lado."""

        response = self.client.get(f"{self.document_url}?ver=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("inline", response["Content-Disposition"])
        self.assertIn("CONT-000001.pdf", response["Content-Disposition"])

    def test_sin_ver_se_descarga(self):
        response = self.client.get(self.document_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])

    # -------------------------------------------------------------
    # DESDE DÓNDE SE IMPRIME
    # -------------------------------------------------------------

    def test_la_vista_del_contrato_ofrece_imprimirlo(self):
        response = self.client.get(
            reverse(
                "contracts:contract_summary",
                kwargs={
                    "customer_pk": self.customer.pk,
                    "pk": self.contract.pk,
                },
            )
        )

        self.assertContains(response, f"{self.document_url}?ver=1")
        self.assertContains(response, "Imprimir contrato")
        self.assertContains(response, 'target="_blank"')

    def test_la_ficha_del_abonado_ofrece_imprimirlo(self):
        response = self.client.get(
            reverse("customers:detail", kwargs={"pk": self.customer.pk})
        )

        self.assertContains(response, f"{self.document_url}?ver=1")

    def test_el_numero_de_contrato_abre_el_contrato(self):
        """Hacer clic en el nombre de un registro tiene que abrirlo."""

        resumen = reverse(
            "contracts:contract_summary",
            kwargs={
                "customer_pk": self.customer.pk,
                "pk": self.contract.pk,
            },
        )

        ficha = self.client.get(
            reverse("customers:detail", kwargs={"pk": self.customer.pk})
        )

        self.assertContains(ficha, resumen)

    def test_lo_que_no_va_en_papel_queda_fuera_de_la_impresion(self):
        """Imprimir la vista deja la hoja del contrato y nada más.

        Las pestañas del abonado, la barra de acciones y los propios botones
        son formas de moverse por el sistema: en una hoja impresa no
        significan nada.
        """

        response = self.client.get(
            reverse(
                "contracts:contract_summary",
                kwargs={
                    "customer_pk": self.customer.pk,
                    "pk": self.contract.pk,
                },
            )
        )

        contenido = response.content.decode("utf-8")

        for escondido in (
            ".tc-toolbar,",
            ".tc-tabs,",
            ".no-print {",
        ):
            self.assertIn(escondido, contenido)

        self.assertIn("tc-card-footer border-top no-print", contenido)


# Los cuatro primeros bytes de un PNG. Se comprueban para afirmar que lo
# guardado es el dibujo y no el nombre del archivo que lo trajo.
CABECERA_PNG = bytes.fromhex("89504e47")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="sicv-firmas-"))
class ContractSignatureTests(ContratoDeReferenciaMixin, TestCase):
    """La firma que el abonado dibuja en campo, sobre su contrato.

    Se prueba lo mismo que del resto del papel y en el mismo orden: qué dato
    queda guardado, qué sale impreso con él y qué pasa cuando no hay firma,
    que es el estado en que nace todo contrato.
    """

    def setUp(self):
        super().setUp()

        self.tecnico = User.objects.create_user(
            username="tecnico_firma",
            password="123",
            role=User.Role.TECHNICIAN,
            branch=self.branch,
        )

    def trazo(self, ancho=600, alto=200):
        """Un PNG con fondo transparente, como el que sale del lienzo."""

        lienzo = PILImage.new("RGBA", (ancho, alto), (255, 255, 255, 0))
        ImageDraw.Draw(lienzo).line(
            [(20, alto - 40), (ancho // 3, 30), (ancho // 2, alto - 30), (ancho - 20, 40)],
            fill=(16, 24, 64, 255),
            width=6,
        )

        archivo = BytesIO()
        lienzo.save(archivo, format="PNG")

        return SimpleUploadedFile(
            "firma.png",
            archivo.getvalue(),
            content_type="image/png",
        )

    def firmar(self):
        return firmar_contrato(
            self.contract,
            self.trazo(),
            usuario=self.tecnico,
            orden=None,
        )

    # -------------------------------------------------------------
    # LO QUE QUEDA GUARDADO
    # -------------------------------------------------------------

    def test_un_contrato_nuevo_nace_sin_firma(self):
        self.assertIsNone(firma_del_contrato(self.contract))
        self.assertIsNone(datos_del_contrato(self.contract)["firma_abonado"])

    def test_la_firma_guarda_quien_firmo_y_cuando(self):
        firma = self.firmar()

        self.assertEqual(firma.contract, self.contract)
        self.assertEqual(firma.signer_name, "Kevin Rivera Ravichagua")
        self.assertEqual(firma.captured_by, self.tecnico)
        self.assertIsNotNone(firma.signed_at)

    def test_el_nombre_del_firmante_queda_congelado(self):
        """El papel dice quién firmó ese día, no cómo se llama hoy.

        Si mañana ATC corrige el nombre del abonado, el contrato que ya se
        firmó no puede reescribir hacia atrás quién estuvo delante.
        """

        self.firmar()

        self.customer.first_name = "Kevin Junior"
        self.customer.save(update_fields=["first_name"])

        self.assertEqual(
            firma_del_contrato(self.contract).signer_name,
            "Kevin Rivera Ravichagua",
        )

    def test_volver_a_firmar_reemplaza_el_trazo_anterior(self):
        """El abonado firma una vez: lo que vale es el trazo que aceptó."""

        primera = self.firmar()
        ruta_anterior = primera.image.name

        segunda = firmar_contrato(
            self.contract,
            self.trazo(ancho=500, alto=180),
            usuario=self.tecnico,
        )

        self.assertEqual(ContractSignature.objects.count(), 1)
        self.assertEqual(segunda.pk, primera.pk)
        self.assertFalse(default_storage.exists(ruta_anterior))

    def test_rechazar_la_firma_devuelve_el_contrato_a_sin_firmar(self):
        firma = self.firmar()
        ruta = firma.image.name

        self.assertTrue(borrar_firma(self.contract))

        self.assertIsNone(firma_del_contrato(self.contract))
        self.assertFalse(default_storage.exists(ruta))

    def test_borrar_lo_que_no_esta_firmado_no_es_un_error(self):
        self.assertFalse(borrar_firma(self.contract))

    def test_sin_dibujo_no_hay_firma_que_registrar(self):
        with self.assertRaises(ValidationError):
            firmar_contrato(self.contract, None, usuario=self.tecnico)

    def test_la_firma_es_del_contrato_y_no_de_la_orden(self):
        """Se llega a ella desde la orden, pero pertenece al contrato.

        La orden es dónde y cuándo se recogió; el documento firmado es el
        contrato, y así sigue siendo el mismo se mire desde campo o desde
        SICV.
        """

        orden_tipo, _ = OrderType.objects.get_or_create(
            code="INSTALLATION",
            defaults={"name": "Instalación"},
        )
        orden = WorkOrder.objects.create(
            order_number="OT-FIRMA-1",
            subscription=self.subscription,
            order_type=orden_tipo,
            branch=self.branch,
            zone=self.zone,
            created_by=self.user,
        )

        firma = firmar_contrato(
            self.contract,
            self.trazo(),
            usuario=self.tecnico,
            orden=orden,
        )

        self.assertEqual(firma.work_order, orden)
        self.assertEqual(contrato_de_la_orden(orden), self.contract)

    # -------------------------------------------------------------
    # LO QUE SALE IMPRESO
    # -------------------------------------------------------------

    def test_el_papel_lleva_el_trazo_cuando_esta_firmado(self):
        self.firmar()

        firma = datos_del_contrato(self.contract)["firma_abonado"]

        self.assertIsNotNone(firma)
        self.assertTrue(firma["imagen"].startswith(CABECERA_PNG))
        self.assertEqual(firma["firmante"], "Kevin Rivera Ravichagua")

    def test_el_contrato_firmado_se_dibuja(self):
        self.firmar()

        buffer = BytesIO()
        render_contract(self.contract, buffer)
        firmado = buffer.getvalue()

        self.assertTrue(firmado.startswith(b"%PDF-"))

        # El trazo es una imagen incrustada: el documento firmado pesa más
        # que el mismo contrato en blanco.
        borrar_firma(self.contract)
        en_blanco = BytesIO()
        render_contract(self.contract, en_blanco)

        self.assertGreater(len(firmado), len(en_blanco.getvalue()))

    # -------------------------------------------------------------
    # LO QUE VE ATC
    # -------------------------------------------------------------

    def test_la_vista_del_contrato_dice_si_esta_firmado(self):
        """ATC tiene que saberlo sin abrir el PDF para comprobarlo."""

        resumen = reverse(
            "contracts:contract_summary",
            kwargs={"customer_pk": self.customer.pk, "pk": self.contract.pk},
        )

        self.assertContains(self.client.get(resumen), "Pendiente de firma")

        self.firmar()

        self.assertContains(self.client.get(resumen), "Firmada el")

    def test_la_ficha_del_abonado_marca_los_contratos_firmados(self):
        ficha = reverse("customers:detail", kwargs={"pk": self.customer.pk})

        self.assertNotContains(self.client.get(ficha), "Firmado</span>")

        self.firmar()

        self.assertContains(self.client.get(ficha), "Firmado")

    def test_el_contrato_impreso_desde_sicv_es_el_firmado_en_campo(self):
        """El mismo documento por los dos canales: no hay copia de oficina."""

        self.firmar()

        response = self.client.get(f"{self.document_url}?ver=1")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            b"".join(response.streaming_content).startswith(b"%PDF-")
        )

    def test_el_papel_dice_donde_esta_el_hueco_de_la_firma(self):
        """El visor del técnico coloca la firma donde lo diga el documento.

        El sitio se decide una sola vez, al dibujar el contrato. Si el
        navegador lo calculara por su cuenta, dos fórmulas distintas podrían
        dejar el trazo donde el papel no lo espera.
        """

        hueco = {}
        render_contract(self.contract, BytesIO(), ancla=hueco)

        self.assertEqual(hueco["pagina"], 4)
        self.assertGreater(hueco["ancho"], 0)
        self.assertGreater(hueco["alto"], 0)

        # Está en la mitad derecha de la hoja, que es la del abonado.
        self.assertGreater(hueco["x"], hueco["pagina_ancho"] / 2 - hueco["ancho"])

    def test_el_hueco_se_publica_aunque_nadie_haya_firmado(self):
        """Es el espacio, no la firma: existe antes de que haya trazo."""

        hueco = {}
        render_contract(self.contract, BytesIO(), ancla=hueco)

        self.assertIn("pagina", hueco)
        self.assertIsNone(firma_del_contrato(self.contract))

    def test_la_firma_se_guarda_donde_el_tecnico_la_dejo(self):
        firmar_contrato(
            self.contract,
            self.trazo(),
            usuario=self.tecnico,
            colocacion={"x": 12.5, "y": 4.0, "ancho": 90.0},
        )

        firma = firma_del_contrato(self.contract)

        self.assertEqual(firma.offset_x, 12.5)
        self.assertEqual(firma.offset_y, 4.0)
        self.assertEqual(firma.width, 90.0)
        self.assertEqual(
            datos_del_contrato(self.contract)["firma_abonado"]["colocacion"],
            {"x": 12.5, "y": 4.0, "ancho": 90.0},
        )

    def test_una_firma_sin_ajustar_no_guarda_colocacion(self):
        """Sin ajuste, el papel la centra sobre la línea por su cuenta."""

        self.firmar()

        self.assertIsNone(firma_del_contrato(self.contract).colocacion)
        self.assertIsNone(
            datos_del_contrato(self.contract)["firma_abonado"]["colocacion"]
        )

    def test_rehacer_la_firma_olvida_la_colocacion_anterior(self):
        """Un trazo nuevo empieza centrado, como el primero."""

        firmar_contrato(
            self.contract,
            self.trazo(),
            usuario=self.tecnico,
            colocacion={"x": 30.0, "y": 10.0, "ancho": 120.0},
        )

        self.firmar()

        self.assertIsNone(firma_del_contrato(self.contract).colocacion)

    def test_el_contrato_con_la_firma_movida_se_dibuja(self):
        firmar_contrato(
            self.contract,
            self.trazo(),
            usuario=self.tecnico,
            colocacion={"x": -20.0, "y": 25.0, "ancho": 150.0},
        )

        buffer = BytesIO()
        render_contract(self.contract, buffer)

        self.assertTrue(buffer.getvalue().startswith(b"%PDF-"))

    def test_el_trazo_no_se_separa_de_la_linea_que_firma(self):
        """Una firma sola al pie de una hoja no es la firma de nada.

        ReportLab parte las tablas por filas, y el bloque de firmas son dos:
        el trazo arriba y la línea con el nombre debajo. Partido, el contrato
        salía con la firma del abonado al final de una página y con a quién
        pertenece al principio de la siguiente. Va entero o pasa de página
        entero.
        """

        self.firmar()

        bloques = [
            flowable
            for flowable in _cuerpo_del_contrato(
                datos_del_contrato(self.contract),
                _estilos(),
            )
            if isinstance(flowable, KeepTogether)
        ]

        self.assertEqual(len(bloques), 1)
        self.assertTrue(
            any(isinstance(pieza, Table) for pieza in bloques[0]._content)
        )

    def test_una_firma_muy_ancha_no_se_sale_de_su_columna(self):
        """Cada quien firma como firma; la hoja tiene un ancho fijo."""

        firmar_contrato(
            self.contract,
            self.trazo(ancho=2000, alto=120),
            usuario=self.tecnico,
        )

        buffer = BytesIO()
        render_contract(self.contract, buffer)

        self.assertTrue(buffer.getvalue().startswith(b"%PDF-"))


class TemplateCommentTests(TestCase):
    """Ningún comentario de plantilla se imprime en la pantalla.

    `{# ... #}` solo funciona dentro de una línea. Partido en dos, lo que
    sigue deja de ser un comentario y sale impreso: la plantilla no falla,
    simplemente le dice al operador cosas que nadie escribió para él. Ya pasó
    dos veces en esta jornada, así que se comprueba en vez de recordarlo.

    Vive en contracts por ser donde apareció, pero recorre las plantillas de
    todo el proyecto: el error no es de un módulo, es de la sintaxis.
    """

    def test_ninguna_plantilla_deja_un_comentario_abierto(self):
        raiz = Path(__file__).resolve().parent.parent.parent

        abiertos = []

        for plantilla in raiz.glob("**/*.html"):
            if "venv" in plantilla.parts:
                continue

            contenido = io.open(plantilla, encoding="utf-8").read()

            for numero, linea in enumerate(contenido.splitlines(), 1):
                if "{#" in linea and "#}" not in linea:
                    abiertos.append(
                        f"{plantilla.relative_to(raiz)}:{numero}"
                    )

        self.assertEqual(
            abiertos,
            [],
            "Comentarios `{# #}` sin cerrar en su línea: se imprimen en la "
            "pantalla. Use {% comment %} para varias líneas.",
        )
