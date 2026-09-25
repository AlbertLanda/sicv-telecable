from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.organization.models import Branch, Zone
from apps.technicians.models import TechnicianProfile
from apps.work_orders.api.queries import available_work_orders
from apps.work_orders.forms import WorkOrderCreateForm
from apps.work_orders.incident_noc import (
    close_owned_incident,
    release_incident,
    take_incident,
)
from apps.work_orders.outside_plant import OutsidePlantCreateForm
from apps.work_orders.models import (
    OrderReason,
    OrderResult,
    OrderType,
    OutsidePlantDetail,
    WorkOrder,
    WorkOrderParticipation,
)
from apps.work_orders.services import (
    attend_order,
    create_incident_work_order,
    create_outside_plant_order,
    create_work_order,
    liquidate_order,
    start_order_attention,
)
from apps.work_orders.tests.base import WorkOrderTestCase


class OutsidePlantWorkOrderTests(WorkOrderTestCase):
    def setUp(self):
        super().setUp()

        self.pex_type = OrderType.objects.create(
            code="OUTSIDE_PLANT",
            name="PLANTA EXTERNA",
        )
        self.pex_reason = OrderReason.objects.create(
            order_type=self.pex_type,
            code="FALLEN_POLE",
            name="CAÍDA DE POSTE",
            classification=OrderReason.Classification.TECHNICAL,
        )
        self.pex_solved = OrderResult.objects.create(
            order_type=self.pex_type,
            code="SOLVED",
            name="SOLUCIONADO",
            is_success=True,
        )

        self.pex_technician = User.objects.create_user(
            username="pex1",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=self.branch,
        )
        self.pex_technician.technician_profile.area = TechnicianProfile.Area.PEX
        self.pex_technician.technician_profile.save(
            update_fields=["area", "updated_at"]
        )

        self.pex_support = User.objects.create_user(
            username="pex2",
            password="test1234",
            role=User.Role.TECHNICIAN,
            branch=self.branch,
        )
        self.pex_support.technician_profile.area = TechnicianProfile.Area.PEX
        self.pex_support.technician_profile.save(
            update_fields=["area", "updated_at"]
        )

        self.noc_one = User.objects.create_user(
            username="noc_pex_1",
            password="test1234",
            role=User.Role.NOC,
            branch=self.branch,
        )
        self.noc_two = User.objects.create_user(
            username="noc_pex_2",
            password="test1234",
            role=User.Role.NOC,
            branch=self.branch,
        )

    def create_pex(self, creator=None, route="Av. Red Principal"):
        return create_outside_plant_order(
            created_by=creator or self.atc_user,
            branch=self.branch,
            zone=self.zone,
            route=route,
            reference="Poste frente al parque",
            reason=self.pex_reason,
            detail="Poste caído con afectación de red para prueba.",
            priority=WorkOrder.Priority.HIGH,
        )

    def test_atc_creates_pex_without_customer_or_subscription(self):
        order = self.create_pex()

        self.assertIsNone(order.subscription_id)
        self.assertTrue(order.is_outside_plant)
        self.assertEqual(order.status, WorkOrder.Status.PENDING)
        self.assertEqual(order.outside_plant_detail.origin, OutsidePlantDetail.Origin.ATC)
        self.assertEqual(order.outside_plant_detail.route, "Av. Red Principal")

    def test_noc_can_create_pex_and_origin_is_traced(self):
        order = self.create_pex(creator=self.noc_one)

        self.assertEqual(order.outside_plant_detail.origin, OutsidePlantDetail.Origin.NOC)
        self.assertEqual(order.created_by, self.noc_one)

    def test_only_pex_may_exist_without_subscription(self):
        with self.assertRaises(ValidationError):
            create_work_order(
                subscription=None,
                order_type=self.installation_type,
                created_by=self.atc_user,
                branch=self.branch,
                zone=self.zone,
                reason=self.installation_reason,
            )

    def test_customer_order_form_never_offers_pex(self):
        form = WorkOrderCreateForm(customer=self.customer)

        self.assertNotIn(
            self.pex_type.pk,
            form.fields["order_type"].queryset.values_list("pk", flat=True),
        )


    def test_pex_form_prefers_active_branch_and_scopes_zone_options(self):
        other_branch = Branch.objects.create(
            code="SED02",
            name="Sede Alterna",
        )
        other_zone = Zone.objects.create(
            branch=other_branch,
            name="Zona Alterna",
        )

        form = OutsidePlantCreateForm(
            user=self.atc_user,
            active_branch=other_branch,
        )

        self.assertEqual(form.fields["branch"].initial, other_branch.pk)
        self.assertEqual(
            list(form.fields["zone"].queryset),
            [other_zone],
        )
        self.assertEqual(
            form.fields["zone"].label_from_instance(other_zone),
            "Zona Alterna",
        )

    def test_available_pool_is_split_by_technical_area(self):
        installation = self.create_order()
        pex = self.create_pex()

        internal_numbers = set(
            available_work_orders(
                technician=self.technician,
            ).values_list("order_number", flat=True)
        )
        pex_numbers = set(
            available_work_orders(
                technician=self.pex_technician,
            ).values_list("order_number", flat=True)
        )

        self.assertIn(installation.order_number, internal_numbers)
        self.assertNotIn(pex.order_number, internal_numbers)
        self.assertEqual(pex_numbers, {pex.order_number})

    def test_internal_technician_cannot_receive_pex(self):
        order = self.create_pex()

        with self.assertRaises(ValidationError):
            order.assign_technician(
                self.technician,
                assigned_by=self.technician,
            )

        order.refresh_from_db()
        self.assertIsNone(order.assigned_technician_id)

    def test_pex_technician_can_claim_and_detail_has_network_location(self):
        order = self.create_pex(route="San Agustín de Cajas - Jr. San Martín")
        api = APIClient()
        token, _ = Token.objects.get_or_create(user=self.pex_technician)
        api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        listed = api.get(reverse("work_orders_api:available"))
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item["order_number"] for item in listed.data],
            [order.order_number],
        )
        self.assertIsNone(listed.data[0]["customer"])
        self.assertTrue(listed.data[0]["is_outside_plant"])

        claimed = api.post(
            reverse("work_orders_api:claim", args=[order.pk]),
            {},
            format="json",
        )
        self.assertEqual(claimed.status_code, status.HTTP_200_OK)
        self.assertIsNone(claimed.data["customer"])
        self.assertEqual(
            claimed.data["address"]["address"],
            "San Agustín de Cajas - Jr. San Martín",
        )
        self.assertIsNone(claimed.data["plan_details"])

    def test_field_participant_is_automatic_and_support_is_declared_on_liquidation(self):
        order = self.create_pex()
        order.assign_technician(
            self.pex_technician,
            assigned_by=self.pex_technician,
        )

        start_order_attention(
            order,
            user=self.pex_technician,
            remarks="Inicio de trabajo de red.",
        )

        active = WorkOrderParticipation.objects.get(
            work_order=order,
            user=self.pex_technician,
            source=WorkOrderParticipation.Source.FIELD,
        )
        self.assertIsNone(active.ended_at)

        attend_order(
            order,
            result=self.pex_solved,
            user=self.pex_technician,
            remarks="Red restablecida.",
        )

        active.refresh_from_db()
        self.assertIsNotNone(active.ended_at)

        liquidate_order(
            order,
            user=self.pex_technician,
            resolution_detail="Se repuso poste y se restableció el tramo.",
            participant_users=[self.pex_support],
        )

        support = WorkOrderParticipation.objects.get(
            work_order=order,
            user=self.pex_support,
        )
        self.assertEqual(
            support.source,
            WorkOrderParticipation.Source.LIQUIDATION,
        )
        self.assertIsNotNone(support.ended_at)

    def test_print_view_renders_pex_operational_document(self):
        order = self.create_pex(route="Av. PEX de prueba")

        self.client.force_login(self.atc_user)
        response = self.client.get(
            reverse("work_orders:outside_plant_print", args=[order.pk])
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertContains(response, order.order_number)
        self.assertContains(response, "Av. PEX de prueba")
        self.assertContains(response, "ORDEN DE PLANTA EXTERNA")

    def test_completion_only_offers_participants_from_same_crew(self):
        order = self.create_pex()
        order.assign_technician(
            self.pex_technician,
            assigned_by=self.pex_technician,
        )
        start_order_attention(order, user=self.pex_technician)

        api = APIClient()
        token, _ = Token.objects.get_or_create(user=self.pex_technician)
        api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        response = api.get(
            reverse("work_orders_api:complete", args=[order.pk])
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        option_ids = {
            item["id"] for item in response.data["participant_options"]
        }
        self.assertIn(self.pex_technician.pk, option_ids)
        self.assertIn(self.pex_support.pk, option_ids)
        self.assertNotIn(self.technician.pk, option_ids)


class NocParticipationHandoffTests(WorkOrderTestCase):
    def setUp(self):
        super().setUp()

        self.incident_type, _ = OrderType.objects.get_or_create(
            code="INCIDENT",
            defaults={"name": "INCIDENCIA NOC"},
        )

        self.noc_one = User.objects.create_user(
            username="jordan_noc",
            password="test1234",
            first_name="Jordan",
            role=User.Role.NOC,
            branch=self.branch,
        )
        self.noc_two = User.objects.create_user(
            username="tony_noc",
            password="test1234",
            first_name="Tony",
            role=User.Role.NOC,
            branch=self.branch,
        )

        self.incident = create_incident_work_order(
            subscription=self.subscription,
            created_by=self.atc_user,
            reason_text="Cliente reporta intermitencia.",
        )

    def test_shift_handoff_preserves_both_noc_participants(self):
        order = take_incident(self.incident, self.noc_one)
        order = release_incident(
            order,
            self.noc_one,
            "Fin de turno; continúa otro operador.",
        )
        order = take_incident(order, self.noc_two)
        order = close_owned_incident(
            order,
            self.noc_two,
            attention_detail="Se corrigió la configuración y quedó estable.",
        )

        participations = list(
            order.participations
            .select_related("user")
            .order_by("started_at", "pk")
        )

        self.assertEqual(
            [item.user_id for item in participations],
            [self.noc_one.pk, self.noc_two.pk],
        )
        self.assertTrue(all(item.ended_at is not None for item in participations))
        self.assertTrue(
            all(
                item.source == WorkOrderParticipation.Source.NOC
                for item in participations
            )
        )
