import csv
from datetime import timedelta
from io import BytesIO, StringIO
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from apps.payments.cash import reverse_movement
from apps.payments.models import CashEntry, Issuer
from apps.payments.tests.base import PaymentsTestCase
from apps.payments.tests.test_cash_sessions import CashFixture
from .banking import (HEADERS, MAX_BYTES, annotate_line, confirm_match, create_account, deposit_candidates,
                      import_statement, parse_statement, payment_candidates, release_match)
from .models import BankAccount, BankLine, BankMatch, BankStatement, CompanyAccess


class BankingFixture(CashFixture):
    def setup_banking(self):
        self.setup_cash()
        self.admin = type(self.actor).objects.create_user(username="bank-admin", role="ADMIN", branch=self.branch)
        self.account = create_account(actor=self.admin, issuer_id=self.issuer.pk, bank="Banco TEST", number="00012345", label="Recaudación de prueba")
        CompanyAccess.objects.create(user=self.reviewer, issuer=self.issuer, updated_by=self.admin)

    def csv(self, rows=None, **overrides):
        values = dict(id_movimiento="BANK-1", fecha=str(timezone.localdate()), operacion="0000042", descripcion="Abono de prueba",
                      moneda="PEN", ingreso="80.00", salida="", cuenta=self.account.number)
        values.update(overrides)
        output = StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(HEADERS)
        for item in rows or [values]:
            writer.writerow([item[key] for key in HEADERS])
        return output.getvalue().encode("utf-8-sig")

    def bank_import(self, **kwargs):
        return import_statement(actor=self.reviewer, account_id=self.account.pk, filename="synthetic.csv", raw=self.csv(**kwargs))

    def bank_payment(self, **kwargs):
        return self.payment(method="TRANSFER", reference="0000042", **kwargs)

    def match(self, line, target, kind="PAYMENT", **kwargs):
        values = dict(actor=self.reviewer, line_id=line.pk, kind=kind, target_id=target.pk, note="Cuenta, operación y sustento verificados")
        values.update(kwargs)
        return confirm_match(**values)


class BankingTests(BankingFixture, PaymentsTestCase):
    def setUp(self):
        super().setUp()
        self.setup_banking()

    def test_import_is_evidence_only_preserves_ids_and_original_and_is_idempotent(self):
        raw = self.csv()
        batch = self.bank_import()
        self.assertEqual(bytes(batch.original), raw)
        self.assertEqual(self.bank_import().pk, batch.pk)
        self.assertEqual(BankLine.objects.count(), 1)
        self.assertEqual(batch.lines.get().operation, "0000042")
        self.assertEqual(self.account.number, "00012345")
        self.assertFalse(BankMatch.objects.exists())
        self.assertFalse(self.customer.payments.exists())

    def test_overlapping_csv_uses_same_lines_and_conflict_rolls_back_entire_batch(self):
        first = self.bank_import()
        second = self.bank_import(ingreso="80")
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(second.new_count, 0)
        self.assertEqual(first.lines.get().pk, second.lines.get().pk)
        with self.assertRaises(ValidationError):
            self.bank_import(ingreso="81")
        self.assertEqual(BankStatement.objects.count(), 2)
        self.assertEqual(BankLine.objects.get().amount, 80)

    def test_strict_schema_money_date_currency_account_and_duplicate_ids(self):
        for data in [dict(moneda="USD"), dict(cuenta="99999999"), dict(fecha="10/10/2026"),
                     dict(fecha=str(timezone.localdate() + timedelta(days=1))), dict(fecha="1900-01-01"),
                     dict(ingreso="1,000.00"), dict(ingreso="NaN"), dict(ingreso="1.001"), dict(ingreso="-80"),
                     dict(salida="1"), dict(id_movimiento=""), dict(operacion="")]:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                self.bank_import(**data)
        for raw in [b"", b"\xef\xbb\xbf", b"\n \n", b"x" * (MAX_BYTES + 1), b"bad headers", b"\xff\xfe\x00"]:
            with self.assertRaises(ValidationError):
                parse_statement(raw, self.account)
        data = self.csv().decode('utf-8-sig').splitlines()
        with self.assertRaises(ValidationError):
            parse_statement(('\n'.join(data + data[1:])).encode(), self.account)
        self.assertFalse(BankLine.objects.exists())

    def test_suggestion_does_not_auto_confirm_and_ambiguous_payments_are_both_shown(self):
        one, two = self.bank_payment(), self.bank_payment()
        line = self.bank_import().lines.get()
        self.assertEqual({p.pk for p in payment_candidates(line)}, {one.pk, two.pk})
        self.assertFalse(BankMatch.objects.exists())
        self.match(line, one)
        self.assertEqual(BankMatch.objects.count(), 1)

    def test_match_and_release_preserve_history_and_block_void_until_release(self):
        payment = self.bank_payment()
        line = self.bank_import().lines.get()
        match = self.match(line, payment)
        with self.assertRaises(ValidationError):
            payment.void(user=self.admin, reason="Corrección")
        release_match(actor=self.reviewer, match_id=match.pk, reason="Vínculo incorrecto")
        payment.void(user=self.admin, reason="Corrección posterior")
        match.refresh_from_db()
        self.assertFalse(match.active)
        self.assertEqual(match.snapshot["line"]["operation"], "0000042")
        self.assertEqual(line.events.count(), 2)

    def test_a_payment_cannot_be_matched_twice_even_across_accounts(self):
        payment = self.bank_payment()
        self.match(self.bank_import().lines.get(), payment)
        account = create_account(actor=self.admin, issuer_id=self.issuer.pk, bank="Banco TEST", number="00067890", label="Otra cuenta")
        batch = import_statement(actor=self.reviewer, account_id=account.pk, filename="other.csv", raw=self.csv(cuenta=account.number))
        with self.assertRaises(ValidationError):
            self.match(batch.lines.get(), payment)

    def test_wrong_amount_cash_voided_pending_and_foreign_issuer_are_rejected(self):
        line = self.bank_import().lines.get()
        for payment in [self.payment(), self.bank_payment(amount=79), self.bank_payment(settled=False)]:
            with self.assertRaises(ValidationError):
                self.match(line, payment)
        payment = self.bank_payment()
        payment.void(user=self.admin, reason="Prueba")
        with self.assertRaises(ValidationError):
            self.match(line, payment)
        foreign = Issuer.objects.create(code="BANK-OTHER", business_name="Otra empresa", ruc="20000000002")
        self.sequence.issuer = foreign
        self.sequence.save(update_fields=["issuer"])
        with self.assertRaises(ValidationError):
            self.match(line, self.bank_payment())

    def test_deposit_matches_bank_inflow_and_cannot_reverse_until_released(self):
        session = self.open()
        entry = self.movement(session, kind="DEPOSIT", amount=80, bank=self.account.bank, account=self.account.number, reference="0000042")
        line = self.bank_import().lines.get()
        self.assertEqual([e.pk for e in deposit_candidates(line)], [entry.pk])
        match = self.match(line, entry, kind="DEPOSIT")
        with self.assertRaises(ValidationError):
            reverse_movement(session_id=session.pk, entry_id=entry.pk, actor=self.actor, reason="Corregir")
        release_match(actor=self.reviewer, match_id=match.pk, reason="Verificado error")
        reverse_movement(session_id=session.pk, entry_id=entry.pk, actor=self.actor, reason="Dinero regularizado")
        with self.assertRaises(ValidationError):
            self.match(line, entry, kind="DEPOSIT")

    def test_unidentified_debits_keep_pending_even_with_observation(self):
        line = self.bank_import(ingreso="", salida="80").lines.get()
        annotate_line(actor=self.reviewer, line_id=line.pk, note="Comisión pendiente de sustento")
        self.assertFalse(line.matches.filter(active=True).exists())
        with self.assertRaises(ValidationError):
            self.match(line, self.bank_payment())

    def test_company_access_revocation_blocks_import_match_source_and_export(self):
        payment = self.bank_payment()
        batch = self.bank_import()
        CompanyAccess.objects.filter(user=self.reviewer).update(enabled=False)
        with self.assertRaises(PermissionDenied):
            self.bank_import(id_movimiento="NEXT")
        with self.assertRaises(PermissionDenied):
            self.match(batch.lines.get(), payment)
        self.client.force_login(self.reviewer)
        for url in [reverse("accounting:bank_account", args=[self.account.pk]), reverse("accounting:bank_export", args=[self.account.pk]),
                    reverse("accounting:bank_source", args=[self.account.pk, batch.pk])]:
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_cash_attribution_preserved_when_series_issuer_changes(self):
        self.open()
        payment = self.bank_payment()
        line = self.bank_import().lines.get()
        self.sequence.issuer = None
        self.sequence.save()
        self.match(line, payment)
        self.assertEqual(BankMatch.objects.get().snapshot["issuer_id"], self.issuer.pk)

    def test_web_import_review_release_exports_literal_text_and_source(self):
        payment = self.bank_payment()
        self.client.force_login(self.reviewer)
        url = reverse("accounting:bank_account", args=[self.account.pk])
        raw = self.csv(descripcion='=HYPERLINK("test")')
        response = self.client.post(url, {"file": SimpleUploadedFile("bank.csv", raw, content_type="text/csv")})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(url), "Movimientos bancarios")
        line = BankLine.objects.get()
        detail = reverse("accounting:bank_line", args=[self.account.pk, line.pk])
        self.assertContains(self.client.get(detail), "Coincidencias sugeridas")
        response = self.client.post(detail, {"action": "match", "kind": "PAYMENT", "target_id": payment.pk, "note": "Cuenta verificada"})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(detail), "Conciliado")
        response = self.client.get(reverse("accounting:bank_export", args=[self.account.pk]))
        book = load_workbook(BytesIO(b"".join(response.streaming_content)))
        self.assertEqual(book["Conciliación"]["E4"].data_type, "s")
        self.assertEqual(book["Conciliación"]["E4"].value, '=HYPERLINK("test")')
        self.assertEqual(book["Conciliación"]["F4"].value, 80)
        batch = BankStatement.objects.get()
        response = self.client.get(reverse("accounting:bank_source", args=[self.account.pk, batch.pk]))
        self.assertEqual(b"".join(response.streaming_content), raw)
        response = self.client.post(detail, {"action": "release", "match_id": BankMatch.objects.get().pk, "reason": "Revisión nueva"})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(detail), "Deshecho")

    def test_unknown_target_shows_error_without_server_error(self):
        line = self.bank_import().lines.get()
        self.client.force_login(self.reviewer)
        response = self.client.post(reverse("accounting:bank_line", args=[self.account.pk, line.pk]),
                                    {"action": "match", "kind": "PAYMENT", "target_id": 9999999, "note": "Revisar"})
        self.assertContains(response, "El registro indicado no está disponible")

    def test_account_configuration_permission_duplicate_and_csrf(self):
        with self.assertRaises(PermissionDenied):
            create_account(actor=self.reviewer, issuer_id=self.issuer.pk, bank="Banco", number="0009999", label="Prueba")
        with self.assertRaises(ValidationError):
            create_account(actor=self.admin, issuer_id=self.issuer.pk, bank="Banco TEST", number="00012345", label="Duplicada")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("accounting:bank_workspace")), "Configurar cuenta bancaria")
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(reverse("accounting:bank_workspace"), {}).status_code, 403)

    def test_atc_has_no_banking_access_and_original_hash_checked(self):
        self.client.force_login(self.actor)
        self.assertEqual(self.client.get(reverse("accounting:bank_workspace")).status_code, 403)
        batch = self.bank_import()
        BankStatement.objects.filter(pk=batch.pk).update(original=b"changed")
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(reverse("accounting:bank_source", args=[self.account.pk, batch.pk])).status_code, 404)
