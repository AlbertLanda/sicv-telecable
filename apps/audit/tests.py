from django.test import TestCase

from apps.accounts.models import User
from apps.audit.models import AuditEvent


class AuditModelTests(TestCase):
    def test_event_string_contains_actor_and_description(self):
        user = User.objects.create_user(username="auditor_test")
        event = AuditEvent.objects.create(
            actor=user,
            method="POST",
            route_name="customers:create",
            path="/customers/create/",
            status_code=302,
            description="Registró un cliente",
        )

        self.assertIn("auditor_test", str(event))
        self.assertIn("Registró un cliente", str(event))
