from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.customers.models import (
    Customer,
    CustomerAddress,
    IncompleteRegistrationDiscard,
)
from apps.customers.onboarding import (
    customer_onboarding_state,
    discard_incomplete_registration,
)
from apps.organization.models import Branch, Zone
from apps.services.models import Plan, ServiceType, Subscription


User = get_user_model()


class CustomerOnboardingTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            code="HUANCAYO",
            name="Huancayo",
        )
        self.zone = Zone.objects.create(
            branch=self.branch,
            name="Centro",
        )
        self.user = User.objects.create_user(
            username="atc_onboarding",
            password="123",
            role=User.Role.ATC,
            branch=self.branch,
        )
        self.customer = Customer.objects.create(
            code="HY01-A0000001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="71111111",
            person_type=Customer.PersonType.NATURAL,
            first_name="Alta",
            paternal_surname="Pendiente",
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Av. Pendiente 100",
            district="Huancayo",
            is_primary=True,
        )
        self.service = ServiceType.objects.create(
            code="INTERNET-ONBOARD",
            name="Internet onboarding",
        )
        self.plan = Plan.objects.create(
            service_type=self.service,
            code="PLAN-ONBOARD",
            name="Plan onboarding",
            monthly_price=69,
        )

    def test_without_subscription_the_next_step_is_service_and_plan(self):
        state = customer_onboarding_state(self.customer)

        self.assertTrue(state["incomplete"])
        self.assertEqual(state["stage"], "SUBSCRIPTION")
        self.assertEqual(
            state["next_url"],
            reverse(
                "services:subscription_create",
                kwargs={"customer_pk": self.customer.pk},
            ),
        )

    def test_presale_without_contract_resumes_at_contract(self):
        subscription = Subscription.objects.create(
            customer=self.customer,
            address=self.address,
            service_type=self.service,
            plan=self.plan,
            status=Subscription.Status.PRESALE,
        )

        state = customer_onboarding_state(self.customer)

        self.assertTrue(state["incomplete"])
        self.assertEqual(state["stage"], "CONTRACT")
        self.assertEqual(state["subscription"], subscription)
        self.assertIn(
            f"subscription={subscription.pk}",
            state["next_url"],
        )

    def test_discarding_a_purely_provisional_registration_releases_its_code(self):
        previous_code = self.customer.code

        audit = discard_incomplete_registration(
            customer=self.customer,
            user=self.user,
            reason="El abonado decidió no continuar con el alta.",
        )

        self.assertFalse(
            Customer.objects.filter(code=previous_code).exists()
        )
        self.assertEqual(audit.released_customer_code, previous_code)
        self.assertEqual(audit.discarded_by, self.user)
        self.assertTrue(
            IncompleteRegistrationDiscard.objects.filter(pk=audit.pk).exists()
        )
        self.assertEqual(
            Customer.generate_code(self.branch),
            previous_code,
        )
