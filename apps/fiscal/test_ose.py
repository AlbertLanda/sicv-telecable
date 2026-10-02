"""Pruebas del contrato, persistencia, recuperación y aislamiento fiscal."""
from dataclasses import replace
from datetime import timedelta
import uuid
from unittest import skipUnless
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections, close_old_connections, IntegrityError, transaction
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.customers.models import Customer
from apps.organization.context_processors import ACTIVE_BRANCH_SESSION_KEY
from apps.organization.models import Branch
from apps.payments.models import Charge, Issuer, Payment, Receipt, ReceiptSequence
from apps.payments.tests.base import PaymentsTestCase
from .models import (DocumentType, FiscalDocument, OseConnection, OseConnectionRevision,
                     OseSimulation, OseSimulationAttempt, OseSimulationEvent, OseSimulatorReceipt)
from .ose_services import (_claim, _finish, prepare_simulation, run_simulation, save_connection)
from .ose_transport import OseEnvelope, OseResponse, payload_bytes, resolve_transport
from .services import cancel_draft, prepare_draft, submit_document


@override_settings(FISCAL_SIMULATION_ENABLED=True, PRODUCTION=False)
class OseStructureTests(PaymentsTestCase):
    def setUp(self):
        super().setUp()
        self.cashier.user_permissions.add(*Permission.objects.filter(content_type__app_label="fiscal"))
        self.issuer = Issuer.objects.create(code="OSETEST", business_name="Emisor de prueba", ruc="20123456789")
        self.charge = Charge.objects.create(customer=self.customer, concept="MONTHLY", amount=80, due_date=timezone.localdate())
        self.document = prepare_draft(actor=self.cashier, branch=self.branch, customer_id=self.customer.pk,
            issuer_id=self.issuer.pk, document_type=DocumentType.SALES_RECEIPT, charge_ids=[self.charge.pk],
            proposed_issue_date=timezone.localdate(), request_key=uuid.uuid4())
        self.config = save_connection(actor=self.cashier, issuer_id=self.issuer.pk, values={"mode": "SIMULATOR"})

    def prepare(self, **overrides):
        values = dict(actor=self.cashier, branch=self.branch, document_id=self.document.pk,
                      scenario="ACCEPTED", request_key=uuid.uuid4())
        values.update(overrides)
        return prepare_simulation(**values)

    def execute(self, simulation, **overrides):
        values = dict(simulation_id=simulation.pk, actor=self.cashier, branch=self.branch)
        values.update(overrides)
        return run_simulation(**values)

    def login_fiscal(self, actor=None):
        self.client.force_login(actor or self.cashier)
        session = self.client.session
        session[ACTIVE_BRANCH_SESSION_KEY] = self.branch.pk
        session.save()

    def expire(self, simulation):
        OseSimulation.objects.filter(pk=simulation.pk).update(lease_until=timezone.now() - timedelta(seconds=1))

    def envelope(self, simulation):
        return OseEnvelope(simulation.public_id, simulation.payload["issuer_ruc"], simulation.payload["document_type"],
            simulation.payload_hash, payload_bytes(simulation.payload), "application/vnd.sicv.ose-simulation+json")

    def test_configuration_versions_references_without_reading_secrets(self):
        save_connection(actor=self.cashier, issuer_id=self.issuer.pk, values={
            "mode": "PENDING", "provider_name": "Por contratar", "test_endpoint": "https://example.com/test",
            "production_endpoint": "https://example.com/prod", "password_setting": "SICV_OSE_TEST_PASSWORD"})
        self.assertEqual(OseConnectionRevision.objects.count(), 2)
        self.assertEqual(self.config.revisions.last().snapshot["mode"], "SIMULATOR")
        with self.assertRaises(ValidationError):
            self.prepare()
        with self.assertRaises(ValidationError):
            submit_document(document=self.document, actor=self.cashier)

    def test_url_credentials_and_raw_secret_values_are_rejected(self):
        for field, value in (("production_endpoint", "https://user:secret@example.com/api"),
                             ("test_endpoint", "http://example.com"),
                             ("test_endpoint", "https://example.com?key=secret"),
                             ("password_setting", "raw-secret"), ("certificate_setting", "certificate.p12")):
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                save_connection(actor=self.cashier, issuer_id=self.issuer.pk, values={field: value})
        self.assertEqual(OseConnectionRevision.objects.count(), 1)

    def test_configuration_audit_failure_rolls_back_configuration(self):
        with patch("apps.fiscal.ose_services.OseConnectionRevision.objects.create", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                save_connection(actor=self.cashier, issuer_id=self.issuer.pk, values={"provider_name": "Cambio"})
        self.config.refresh_from_db()
        self.assertEqual(self.config.provider_name, "")

    def test_same_prepare_request_is_idempotent_and_changed_scenario_rejected(self):
        key = uuid.uuid4()
        first = self.prepare(request_key=key)
        self.assertEqual(first.pk, self.prepare(request_key=key).pk)
        with self.assertRaises(ValidationError):
            self.prepare(request_key=key, scenario="REJECTED")
        self.assertEqual(OseSimulation.objects.count(), 1)
        self.assertEqual(first.events.count(), 1)

    def test_acceptance_never_changes_debt_cash_fiscal_state_or_sequences(self):
        before = (list(Charge.objects.values()), list(ReceiptSequence.objects.values()), Payment.objects.count(), Receipt.objects.count())
        with patch("requests.sessions.Session.request") as network, patch("urllib.request.urlopen") as urlopen:
            simulation = self.execute(self.prepare())
        network.assert_not_called()
        urlopen.assert_not_called()
        self.assertEqual(simulation.state, "ACCEPTED")
        self.assertTrue(simulation.response["simulated"])
        self.assertFalse("cdr" in simulation.response)
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, "DRAFT")
        self.assertEqual(before, (list(Charge.objects.values()), list(ReceiptSequence.objects.values()), Payment.objects.count(), Receipt.objects.count()))

    def test_observed_and_rejected_responses_remain_simulated(self):
        for scenario in ("OBSERVED", "REJECTED"):
            simulation = self.execute(self.prepare(scenario=scenario))
            self.assertEqual(simulation.state, scenario)
            self.assertTrue(simulation.response["simulated"])
            self.assertIn("Sin validez tributaria", simulation.response["message"])

    def test_terminal_repeat_does_not_dispatch_or_create_new_attempt(self):
        simulation = self.execute(self.prepare())
        with patch("apps.fiscal.ose_services.resolve_transport") as resolver:
            repeated = self.execute(simulation)
        resolver.assert_not_called()
        self.assertEqual(repeated.pk, simulation.pk)
        self.assertEqual(simulation.attempts.count(), 1)
        self.assertEqual(OseSimulatorReceipt.objects.count(), 1)

    def test_lost_reply_is_recovered_by_query_without_second_send(self):
        simulation = self.execute(self.prepare(scenario="LOST_REPLY"))
        self.assertEqual(simulation.state, "UNCERTAIN")
        self.assertEqual(OseSimulatorReceipt.objects.count(), 1)
        simulation = self.execute(simulation)
        self.assertEqual(simulation.state, "ACCEPTED")
        self.assertEqual(list(simulation.attempts.values_list("operation", flat=True)), ["SUBMIT", "QUERY"])
        self.assertEqual(OseSimulatorReceipt.objects.count(), 1)

    def test_pending_ticket_requires_queries(self):
        simulation = self.execute(self.prepare(scenario="DELAYED"))
        self.assertEqual(simulation.state, "PROCESSING")
        ticket = simulation.ticket
        simulation = self.execute(simulation)
        self.assertEqual(simulation.state, "PROCESSING")
        simulation = self.execute(simulation)
        self.assertEqual(simulation.state, "ACCEPTED")
        self.assertEqual(simulation.ticket, ticket)
        self.assertEqual(list(simulation.attempts.values_list("operation", flat=True)), ["SUBMIT", "QUERY", "QUERY"])

    def test_definitely_not_received_can_resend_same_reference(self):
        simulation = self.execute(self.prepare(scenario="NOT_SENT"))
        self.assertEqual(simulation.state, "RETRYABLE")
        self.assertEqual(OseSimulatorReceipt.objects.count(), 0)
        simulation = self.execute(simulation)
        self.assertEqual(simulation.state, "ACCEPTED")
        self.assertEqual(list(simulation.attempts.values_list("operation", flat=True)), ["SUBMIT", "SUBMIT"])
        self.assertEqual(OseSimulatorReceipt.objects.get().request_id, simulation.public_id)

    def test_active_attempt_cannot_be_dispatched_twice(self):
        simulation = self.prepare()
        _claim(simulation_id=simulation.pk, actor=self.cashier, branch=self.branch)
        with self.assertRaisesMessage(ValidationError, "ya está en ejecución"):
            self.execute(simulation)
        self.assertEqual(simulation.attempts.count(), 1)
        self.assertEqual(OseSimulatorReceipt.objects.count(), 0)

    def test_interruption_before_receipt_queries_before_resending(self):
        simulation = self.prepare()
        _claim(simulation_id=simulation.pk, actor=self.cashier, branch=self.branch)
        self.expire(simulation)
        simulation = self.execute(simulation)
        self.assertEqual(simulation.state, "RETRYABLE")
        self.assertEqual(list(simulation.attempts.values_list("operation", flat=True)), ["SUBMIT", "QUERY"])
        simulation = self.execute(simulation)
        self.assertEqual(simulation.state, "ACCEPTED")
        self.assertEqual(simulation.attempts.get(number=1).outcome, "ABANDONED")
        self.assertEqual(OseSimulatorReceipt.objects.count(), 1)

    def test_interruption_after_receipt_is_recovered_and_late_reply_ignored(self):
        simulation, attempt = _claim(simulation_id=self.prepare().pk, actor=self.cashier, branch=self.branch)
        reply = resolve_transport(simulation.connection_snapshot, scenario="ACCEPTED", attempt_number=1).submit(self.envelope(simulation))
        self.expire(simulation)
        result = self.execute(simulation)
        self.assertEqual(result.state, "ACCEPTED")
        _finish(simulation_id=simulation.pk, attempt=attempt, actor=self.cashier, result=replace(reply, result="REJECTED"))
        result.refresh_from_db()
        self.assertEqual(result.state, "ACCEPTED")
        self.assertEqual(result.attempts.get(number=1).outcome, "ABANDONED")
        self.assertEqual(result.events.filter(action="RECOVERED").count(), 1)

    def test_wrong_reference_digest_or_unmarked_response_cannot_accept(self):
        for change in ({"request_id": uuid.uuid4()}, {"payload_hash": "wrong"}, {"simulated": False}, {"result": "UNKNOWN"}, {"ticket": ""}):
            simulation, attempt = _claim(simulation_id=self.prepare().pk, actor=self.cashier, branch=self.branch)
            reply = OseResponse(simulation.public_id, simulation.payload_hash, "ACCEPTED", "SIM_OK", "Prueba", "SIM-TICKET")
            result = _finish(simulation_id=simulation.pk, attempt=attempt, actor=self.cashier, result=replace(reply, **change))
            self.assertEqual(result.state, "UNCERTAIN")
            self.assertEqual(result.response, {})

    def test_unexpected_exception_does_not_leak_secrets_or_allow_resend(self):
        simulation = self.prepare()
        with patch("apps.fiscal.ose_services.resolve_transport", side_effect=RuntimeError("password=do-not-store")):
            result = self.execute(simulation)
        self.assertEqual(result.state, "UNCERTAIN")
        self.assertNotIn("do-not-store", str(list(result.attempts.values())))
        self.assertNotIn("do-not-store", str(list(result.events.values())))

    def test_payload_and_config_snapshot_are_immutable(self):
        simulation = self.prepare()
        original = simulation.payload
        self.charge.amount = 100
        self.charge.save()
        save_connection(actor=self.cashier, issuer_id=self.issuer.pk, values={"provider_name": "Otra configuración"})
        simulation.refresh_from_db()
        self.assertEqual(simulation.payload, original)
        self.assertEqual(simulation.connection_snapshot["provider_name"], "")
        simulation.payload = {"simulation_only": True}
        with self.assertRaises(ValidationError):
            simulation.save()
        with self.assertRaises(ValidationError):
            simulation.delete()

    def test_tampered_payload_is_rejected_before_transport(self):
        simulation = self.prepare()
        OseSimulation.objects.filter(pk=simulation.pk).update(payload={"simulation_only": True})
        with self.assertRaises(ValidationError):
            self.execute(simulation)
        self.assertEqual(simulation.attempts.count(), 0)

    def test_production_or_disabled_simulation_cannot_execute(self):
        simulation = self.prepare()
        for config in (dict(PRODUCTION=True), dict(FISCAL_SIMULATION_ENABLED=False)):
            with self.subTest(config=config), override_settings(**config):
                with self.assertRaises(ValidationError):
                    self.execute(simulation)
                with self.assertRaises(ValidationError):
                    self.prepare()
        self.assertEqual(simulation.attempts.count(), 0)

    def test_connection_disabled_blocks_new_attempts(self):
        simulation = self.prepare()
        save_connection(actor=self.cashier, issuer_id=self.issuer.pk, values={"mode": "DISABLED"})
        with self.assertRaises(ValidationError):
            self.execute(simulation)
        self.assertEqual(simulation.attempts.count(), 0)

    def test_cancelled_draft_blocks_new_simulation_and_attempt(self):
        simulation = self.prepare()
        cancel_draft(document_id=self.document.pk, actor=self.cashier, branch=self.branch, reason="Corrección")
        with self.assertRaises(ValidationError):
            self.prepare()
        with self.assertRaises(ValidationError):
            self.execute(simulation)

    def test_service_permissions_and_branch_are_explicit(self):
        limited = self.make_user("ose-limited", permissions=[])
        simulation = self.prepare()
        with self.assertRaises(PermissionDenied):
            self.prepare(actor=limited)
        with self.assertRaises(PermissionDenied):
            self.execute(simulation, actor=limited)
        with self.assertRaises(PermissionDenied):
            save_connection(actor=limited, issuer_id=self.issuer.pk, values={"mode": "SIMULATOR"})
        other = Branch.objects.create(code="OSEOTHER", name="Otra sede")
        with self.assertRaises(ValidationError):
            self.prepare(branch=other)
        with self.assertRaises(ValidationError):
            self.execute(simulation, branch=other)

    def test_invalid_scenario_and_request_key_are_rejected(self):
        for args in ({"scenario": "PRODUCTION"}, {"request_key": "invalid"}):
            with self.assertRaises(ValidationError):
                self.prepare(**args)
        self.assertEqual(OseSimulation.objects.count(), 0)

    def test_simulation_creation_audit_failure_rolls_back(self):
        with patch("apps.fiscal.ose_services.OseSimulationEvent.objects.create", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.prepare()
        self.assertEqual(OseSimulation.objects.count(), 0)

    def test_claim_audit_failure_rolls_back_attempt_and_lease(self):
        simulation = self.prepare()
        with patch("apps.fiscal.ose_services.OseSimulationEvent.objects.create", side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self.execute(simulation)
        simulation.refresh_from_db()
        self.assertEqual(simulation.state, "READY")
        self.assertEqual(simulation.attempts.count(), 0)

    def test_finish_audit_failure_keeps_recoverable_lease_and_remote_receipt(self):
        simulation = self.prepare()
        original = OseSimulationEvent.objects.create
        def audit(**kwargs):
            if kwargs["action"] == "FINISHED":
                raise RuntimeError
            return original(**kwargs)
        with patch("apps.fiscal.ose_services.OseSimulationEvent.objects.create", side_effect=audit):
            with self.assertRaises(RuntimeError):
                self.execute(simulation)
        simulation.refresh_from_db()
        self.assertEqual(simulation.state, "WORKING")
        self.assertEqual(OseSimulatorReceipt.objects.count(), 1)
        self.expire(simulation)
        self.assertEqual(self.execute(simulation).state, "ACCEPTED")

    def test_fake_working_state_without_lease_is_rejected_by_database(self):
        simulation = self.prepare()
        with self.assertRaises(IntegrityError), transaction.atomic():
            OseSimulation.objects.filter(pk=simulation.pk).update(state="WORKING")

    def test_simulator_checks_issuer_type_and_payload_kind(self):
        simulation = self.prepare()
        envelope = self.envelope(simulation)
        transport = resolve_transport(simulation.connection_snapshot, scenario="ACCEPTED", attempt_number=1)
        for changes in ({"issuer_ruc": "20999999999"}, {"document_type": "01"}, {"content_type": "application/zip"}):
            with self.assertRaises(ValueError):
                transport.submit(replace(envelope, **changes))
        self.assertEqual(OseSimulatorReceipt.objects.count(), 0)

    def test_simulator_rejects_unknown_scenario(self):
        with self.assertRaises(ValueError):
            resolve_transport({"mode": "SIMULATOR"}, scenario="UNKNOWN", attempt_number=1)

    def test_real_transport_cannot_be_selected(self):
        with self.assertRaises(ValueError):
            resolve_transport({"mode": "PENDING", "production_endpoint": "https://example.com"}, scenario="ACCEPTED", attempt_number=1)

    def test_web_flow_get_does_not_write_and_post_is_replay_safe(self):
        self.login_fiscal()
        url = reverse("fiscal:ose_simulation_create", args=[self.document.public_id])
        response = self.client.get(url)
        self.assertContains(response, "PRUEBA SIN VALIDEZ TRIBUTARIA")
        self.assertEqual(OseSimulation.objects.count(), 0)
        data = {"scenario": "LOST_REPLY", "request_key": str(response.context["form"]["request_key"].value())}
        first, repeated = self.client.post(url, data), self.client.post(url, data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(first["Location"], repeated["Location"])
        simulation = OseSimulation.objects.get()
        run_url = reverse("fiscal:ose_simulation_run", args=[simulation.public_id])
        self.assertEqual(self.client.get(run_url).status_code, 405)
        self.client.post(run_url)
        response = self.client.post(run_url, follow=True)
        self.assertContains(response, "Aceptación simulada")
        self.assertContains(response, "PRUEBA SIN VALIDEZ TRIBUTARIA")
        self.assertContains(response, "No se ha contactado a SUNAT")
        self.assertEqual(simulation.attempts.count(), 2)

    def test_web_cross_branch_and_permission_checks(self):
        simulation = self.prepare()
        other = Branch.objects.create(code="OSEOTHER", name="Otra sede")
        self.login_fiscal()
        session = self.client.session
        session[ACTIVE_BRANCH_SESSION_KEY] = other.pk
        session.save()
        for name in ("ose_simulation_detail", "ose_simulation_run"):
            self.assertEqual(self.client.post(reverse("fiscal:" + name, args=[simulation.public_id])).status_code, 404 if name.endswith("run") else 405)
        self.assertEqual(self.client.get(reverse("fiscal:ose_simulation_detail", args=[simulation.public_id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("fiscal:ose_simulation_create", args=[self.document.public_id])).status_code, 404)
        limited = self.make_user("ose-web-limited")
        self.login_fiscal(limited)
        self.assertEqual(self.client.post(reverse("fiscal:ose_simulation_run", args=[simulation.public_id])).status_code, 403)
        self.assertEqual(self.client.get(reverse("fiscal:ose_connection", args=[self.issuer.pk])).status_code, 403)

    def test_connection_web_get_no_write_and_post_records_revision(self):
        self.login_fiscal()
        url = reverse("fiscal:ose_connection", args=[self.issuer.pk])
        before = OseConnectionRevision.objects.count()
        self.assertContains(self.client.get(url), "Conexión OSE prevista")
        self.assertEqual(OseConnectionRevision.objects.count(), before)
        response = self.client.post(url, {"mode": "PENDING", "provider_name": "Por contratar"}, follow=True)
        self.assertContains(response, "La emisión real continúa bloqueada")
        self.assertEqual(OseConnectionRevision.objects.count(), before + 1)

    def test_admin_simulation_evidence_is_read_only(self):
        for model in (OseConnection, OseConnectionRevision, OseSimulation, OseSimulationAttempt, OseSimulationEvent, OseSimulatorReceipt):
            registered = admin.site._registry[model]
            self.assertFalse(registered.has_add_permission(None))
            self.assertFalse(registered.has_change_permission(None))
            self.assertFalse(registered.has_delete_permission(None))


@skipUnless(connection.vendor == "postgresql", "Bloqueo concurrente OSE verificado en PostgreSQL CI.")
@override_settings(FISCAL_SIMULATION_ENABLED=True, PRODUCTION=False)
class ConcurrentOseTests(TransactionTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="OSEPG", name="Sede prueba")
        self.customer = Customer.objects.create(code="OSEPG", branch=self.branch, first_name="Prueba", document_number="00000001")
        self.actor = get_user_model().objects.create_superuser(username="osepg", password="test", branch=self.branch)
        self.issuer = Issuer.objects.create(code="OSEPG", business_name="Empresa prueba", ruc="20123456789")
        self.charge = Charge.objects.create(customer=self.customer, concept="MONTHLY", amount=80, due_date=timezone.localdate())
        self.document = prepare_draft(actor=self.actor, branch=self.branch, customer_id=self.customer.pk,
            issuer_id=self.issuer.pk, document_type="03", charge_ids=[self.charge.pk], proposed_issue_date=timezone.localdate(), request_key=uuid.uuid4())
        save_connection(actor=self.actor, issuer_id=self.issuer.pk, values={"mode": "SIMULATOR"})

    def prepare(self, key):
        return prepare_simulation(actor=get_user_model().objects.get(pk=self.actor.pk), branch=Branch.objects.get(pk=self.branch.pk),
            document_id=self.document.pk, scenario="ACCEPTED", request_key=key)

    def race(self, *actions):
        barrier = Barrier(len(actions))
        def run(action):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                barrier.wait(timeout=5)
                try:
                    action()
                    return "ok"
                except ValidationError:
                    return "rejected"
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            futures = [pool.submit(run, action) for action in actions]
            return [future.result(timeout=20) for future in futures]

    def test_same_prepare_from_two_connections_creates_one_test(self):
        key = uuid.uuid4()
        self.assertEqual(self.race(lambda: self.prepare(key), lambda: self.prepare(key)), ["ok", "ok"])
        self.assertEqual(OseSimulation.objects.count(), 1)
        self.assertEqual(OseSimulationEvent.objects.count(), 1)

    def test_two_claims_can_reserve_only_one_dispatch(self):
        simulation = self.prepare(uuid.uuid4())
        def claim():
            _claim(simulation_id=simulation.pk, actor=self.actor, branch=self.branch)
        self.assertCountEqual(self.race(claim, claim), ["ok", "rejected"])
        self.assertEqual(OseSimulationAttempt.objects.count(), 1)

    def test_two_recovery_claims_reserve_only_one_query(self):
        simulation = self.prepare(uuid.uuid4())
        _claim(simulation_id=simulation.pk, actor=self.actor, branch=self.branch)
        OseSimulation.objects.filter(pk=simulation.pk).update(lease_until=timezone.now() - timedelta(seconds=1))
        def claim():
            _claim(simulation_id=simulation.pk, actor=self.actor, branch=self.branch)
        self.assertCountEqual(self.race(claim, claim), ["ok", "rejected"])
        self.assertEqual(OseSimulationAttempt.objects.get(number=2).operation, "QUERY")
        self.assertEqual(OseSimulationAttempt.objects.get(number=1).outcome, "ABANDONED")
        self.assertEqual(OseSimulationEvent.objects.filter(action="RECOVERED").count(), 1)
