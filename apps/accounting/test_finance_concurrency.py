from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
import uuid

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase
from django.utils import timezone

from apps.customers.models import Customer
from apps.organization.models import Branch
from apps.payments.adjustments import request_adjustment, review_adjustment
from apps.payments.cash import reverse_movement
from apps.payments.collection import collect_payment
from apps.payments.models import CashEntry, Charge, DebtAdjustment, Payment
from .banking import create_account, import_statement
from .models import BankLine, BankMatch, BankStatement
from .test_banking import BankingFixture


@skipUnless(connection.vendor == "postgresql", "Se prueba con bloqueos reales en CI PostgreSQL")
class FinanceConcurrencyTests(BankingFixture, TransactionTestCase):
    def setUp(self):
        self.branch = Branch.objects.create(code="FIN-CON", name="Sede financiera de prueba")
        self.customer = Customer.objects.create(code="FIN-CON", branch=self.branch, first_name="Prueba", document_number="00000001")
        self.setup_banking()

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

    def test_same_csv_imported_once(self):
        self.assertEqual(self.race(self.bank_import, self.bank_import), ["ok", "ok"])
        self.assertEqual(BankStatement.objects.count(), 1)
        self.assertEqual(BankLine.objects.count(), 1)

    def test_overlapping_csv_same_line_does_not_duplicate(self):
        self.assertEqual(self.race(self.bank_import, lambda: self.bank_import(ingreso="80")), ["ok", "ok"])
        self.assertEqual(BankStatement.objects.count(), 2)
        self.assertEqual(BankLine.objects.count(), 1)

    def test_same_payment_cannot_match_two_accounts_concurrently(self):
        payment = self.bank_payment()
        first = self.bank_import().lines.get()
        account = create_account(actor=self.admin, issuer_id=self.issuer.pk, bank="Banco TEST", number="00067890", label="Otra cuenta")
        second = import_statement(actor=self.reviewer, account_id=account.pk, filename="other.csv", raw=self.csv(cuenta=account.number)).lines.get()
        self.assertEqual(sorted(self.race(lambda: self.match(first, payment), lambda: self.match(second, payment))), ["ok", "rejected"])
        self.assertEqual(BankMatch.objects.filter(active=True).count(), 1)

    def test_match_and_payment_void_leave_consistent_state(self):
        payment = self.bank_payment()
        line = self.bank_import().lines.get()
        self.assertEqual(sorted(self.race(lambda: self.match(line, payment), lambda: payment.void(user=self.admin, reason="Prueba"))), ["ok", "rejected"])
        payment.refresh_from_db()
        self.assertEqual(BankMatch.objects.filter(active=True).exists(), payment.status == "REGISTERED")

    def test_match_and_deposit_reversal_leave_consistent_state(self):
        session = self.open()
        entry = self.movement(session, kind="DEPOSIT", amount=80, bank=self.account.bank, account=self.account.number, reference="0000042")
        line = self.bank_import().lines.get()
        results = self.race(lambda: self.match(line, entry, kind="DEPOSIT"), lambda: reverse_movement(
            session_id=session.pk, entry_id=entry.pk, actor=self.actor, reason="Corregir"))
        self.assertEqual(sorted(results), ["ok", "rejected"])
        self.assertNotEqual(BankMatch.objects.filter(active=True).exists(), CashEntry.objects.filter(reversal_of=entry).exists())

    def adjustment(self):
        charge = Charge.objects.create(customer=self.customer, amount=80, concept="OTHER", due_date=timezone.localdate())
        request = request_adjustment(charge_id=charge.pk, actor=self.actor, amount=20, reason="Prueba", reference="TEST-1", request_key=uuid.uuid4())
        return charge, request

    def test_adjustment_approval_and_collection_cannot_use_stale_balance(self):
        charge, request = self.adjustment()
        approve = lambda: review_adjustment(adjustment_id=request.pk, actor=self.reviewer, decision="APPROVED", note="Revisado")
        collect = lambda: collect_payment(request_key=uuid.uuid4(), expected_total=80, customer=self.customer, amount=80,
            method="CASH", branch=self.branch, office=self.office, user=self.actor, series=self.sequence, selected_charge_ids=[charge.pk])
        self.assertEqual(sorted(self.race(approve, collect)), ["ok", "rejected"])
        request.refresh_from_db()
        self.assertEqual(charge.balance_on(), 60 if request.status == "APPROVED" else 0)
        self.assertEqual(Payment.objects.count(), 0 if request.status == "APPROVED" else 1)

    def test_adjustment_review_happens_once(self):
        charge, request = self.adjustment()
        self.assertEqual(sorted(self.race(
            lambda: review_adjustment(adjustment_id=request.pk, actor=self.reviewer, decision="APPROVED", note="Revisado"),
            lambda: review_adjustment(adjustment_id=request.pk, actor=self.admin, decision="REJECTED", note="Rechazado"))), ["ok", "rejected"])
        request.refresh_from_db()
        self.assertEqual(charge.balance_on(), 60 if request.status == "APPROVED" else 80)
