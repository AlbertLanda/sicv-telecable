"""
Data de prueba de cobranza para un abonado real de la base.

Sirve para ver las cuatro pantallas -deudas, nueva deuda, cobrar y compromiso-
con contenido creible, sin tener que esperar a que corra un ciclo mensual.

Es idempotente en lo que importa: la mensualidad de un mes ya emitido no se
duplica -lo impide la restriccion de (suscripcion, periodo)- y los cobros solo
se registran si el abonado todavia no tiene ninguno. Volver a correrlo
completa lo que falte en vez de inflar la deuda.

    python manage.py generar_datos_cobranza_prueba
    python manage.py generar_datos_cobranza_prueba --abonado JA01-A0000001
    python manage.py generar_datos_cobranza_prueba --meses 6 --dry-run
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.customers.models import Customer
from apps.payments.models import Charge, Payment
from apps.payments.services import (
    create_manual_charge,
    first_day_of,
    generate_monthly_charges,
    grant_commitment,
    register_payment,
)
from apps.services.models import Subscription


DEFAULT_CUSTOMER_CODE = "JA01-A0000001"
DEFAULT_MONTHS = 4


class Command(BaseCommand):
    help = (
        "Genera deudas, cobros y un compromiso de pago de prueba para un "
        "abonado existente, sin duplicar lo que ya estuviera emitido."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--abonado",
            default=DEFAULT_CUSTOMER_CODE,
            help=f"Código del abonado. Por defecto {DEFAULT_CUSTOMER_CODE}.",
        )
        parser.add_argument(
            "--meses",
            type=int,
            default=DEFAULT_MONTHS,
            help=(
                "Cuántos meses de mensualidad emitir, contando hacia atrás "
                f"desde el mes en curso. Por defecto {DEFAULT_MONTHS}."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra lo que haría y revierte los cambios.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        code = options["abonado"]
        months = options["meses"]
        dry_run = options["dry_run"]

        if months < 1:
            raise CommandError("--meses debe ser al menos 1.")

        customer = self._get_customer(code)
        subscription = self._prepare_subscription(customer)

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Datos de cobranza de prueba · {customer} ({customer.code})"
            )
        )
        self.stdout.write(
            f"  Suscripción: {subscription.plan.name} · "
            f"S/ {subscription.total_monthly_price}/mes · "
            f"instalada {subscription.installation_date:%d/%m/%Y}"
        )

        charges = self._issue_monthly_charges(subscription, months)
        extra = self._issue_manual_charge(customer)
        payments = self._register_payments(customer)
        commitment = self._grant_commitment(customer)

        self._report(charges, extra, payments, commitment, customer)

        if dry_run:
            transaction.set_rollback(True)
            self.stdout.write(
                self.style.WARNING("DRY RUN: no se guardó nada.")
            )

    # ------------------------------------------------------------------
    # Escenario
    # ------------------------------------------------------------------

    def _get_customer(self, code):
        customer = Customer.objects.filter(code=code).first()

        if customer is None:
            raise CommandError(
                f"No existe un abonado con código «{code}». "
                f"Revise el padrón o pase --abonado."
            )

        return customer

    def _prepare_subscription(self, customer):
        """Deja una suscripción lista para facturar.

        El ciclo solo emite mensualidades de suscripciones ACTIVE, con
        política de cobro, con fecha de instalación y con mensualidad mayor a
        cero. Una suscripción en instalación y con tarifa en cero -como
        quedan las recién registradas- no genera nada, y la pantalla de
        deudas se veria vacia sin explicar por que.
        """
        subscription = (
            customer.subscriptions.filter(billing_policy__isnull=False)
            .select_related("plan", "billing_policy", "service_type")
            .order_by("service_number", "pk")
            .first()
        )

        if subscription is None:
            raise CommandError(
                f"{customer} no tiene ninguna suscripción con política de "
                f"cobro. Asígnele una antes de generar deudas."
            )

        today = timezone.localdate()
        changed = []

        if subscription.status != Subscription.Status.ACTIVE:
            subscription.status = Subscription.Status.ACTIVE
            changed.append("estado ACTIVE")

        if subscription.installation_date is None:
            # Instalada hace unos meses, para que las mensualidades hacia
            # atras tengan con que justificarse.
            subscription.installation_date = today.replace(day=15) - timedelta(
                days=150
            )
            changed.append("fecha de instalación")

        if not subscription.base_monthly_fee:
            subscription.base_monthly_fee = subscription.plan.monthly_price
            changed.append(
                f"mensualidad S/ {subscription.plan.monthly_price}"
            )

        if changed:
            subscription.save()
            self.stdout.write(
                f"  Ajustes en la suscripción: {', '.join(changed)}."
            )

        return subscription

    def _issue_monthly_charges(self, subscription, months):
        """Emite las mensualidades usando el mismo ciclo que produccion.

        Se llama a generate_monthly_charges y no se escriben cargos a mano:
        asi la data de prueba sale con los vencimientos, el pronto pago y la
        fecha de corte que la politica realmente calcula, y no con unos
        inventados aqui que no representarian nada.
        """
        today = timezone.localdate()
        period = first_day_of(today)
        created = []

        for _ in range(months):
            result = generate_monthly_charges(period)
            created.extend(
                charge
                for charge in result["created"]
                if charge.subscription_id == subscription.pk
            )
            period = first_day_of(period - timedelta(days=1))

        return created

    def _issue_manual_charge(self, customer):
        """Un cargo que el ciclo no genera, para que la lista no sea uniforme."""
        already = Charge.objects.filter(
            customer=customer,
            concept=Charge.Concept.REACTIVATION,
        ).first()

        if already:
            return None

        today = timezone.localdate()

        return create_manual_charge(
            customer=customer,
            concept=Charge.Concept.REACTIVATION,
            description="RECONEXIÓN DE SERVICIO",
            amount=Decimal("20.00"),
            due_date=today + timedelta(days=15),
            issued_on=today - timedelta(days=5),
            auto_update=False,
        )

    def _register_payments(self, customer):
        """Cobra las dos mensualidades más antiguas.

        Deja el historial y los comprobantes con contenido, y la deuda con lo
        reciente todavia abierto. Si el abonado ya tiene cobros no se agregan
        mas: el comando se puede volver a correr sin inventar caja.
        """
        if Payment.objects.filter(customer=customer).exists():
            return []

        oldest = list(
            Charge.objects.filter(customer=customer)
            .outstanding()
            .order_by("due_date")[:2]
        )

        if not oldest:
            return []

        cashier = self._pick_user()
        collector = User.objects.filter(
            role=User.Role.SALES, is_active=True
        ).first()

        registered = []

        for index, charge in enumerate(oldest):
            payment, receipt = register_payment(
                customer=customer,
                amount=charge.balance,
                method=(
                    Payment.Method.CASH if index == 0 else Payment.Method.YAPE
                ),
                branch=customer.branch,
                user=cashier,
                collector=collector,
                reference="" if index == 0 else "00099887",
                note="Cobro de prueba generado por comando.",
                allocations=[(charge, charge.balance)],
            )
            registered.append((payment, receipt))

        return registered

    def _grant_commitment(self, customer):
        """Un compromiso vigente sobre la deuda más vieja que quede abierta."""
        if customer.payment_commitments.exists():
            return None

        pending = (
            Charge.objects.filter(customer=customer)
            .outstanding()
            .order_by("due_date")
            .first()
        )

        if pending is None:
            return None

        return grant_commitment(
            customer=customer,
            charges=[pending],
            committed_date=timezone.localdate() + timedelta(days=7),
            reason="El abonado se compromete a pagar el viernes.",
            user=self._pick_user(),
            authorized_by=User.objects.filter(
                role__in=(User.Role.SUPERVISOR, User.Role.ADMIN),
                is_active=True,
            ).first(),
        )

    def _pick_user(self):
        """Un usuario al que atribuir los movimientos de prueba."""
        user = (
            User.objects.filter(is_active=True, is_superuser=True).first()
            or User.objects.filter(is_active=True).first()
        )

        if user is None:
            raise CommandError(
                "No hay ningún usuario activo al que atribuir los cobros."
            )

        return user

    # ------------------------------------------------------------------
    # Salida
    # ------------------------------------------------------------------

    def _report(self, charges, extra, payments, commitment, customer):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Deudas emitidas"))

        for charge in sorted(charges, key=lambda item: item.due_date):
            self.stdout.write(
                f"  {charge.issued_on:%d/%m/%Y} · {charge.description} · "
                f"{charge.period_label} · S/ {charge.amount} · "
                f"vence {charge.due_date:%d/%m/%Y}"
            )

        if extra:
            self.stdout.write(
                f"  {extra.issued_on:%d/%m/%Y} · {extra.description} · "
                f"S/ {extra.amount} · vence {extra.due_date:%d/%m/%Y}"
            )

        if payments:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Cobros registrados"))
            for payment, receipt in payments:
                self.stdout.write(
                    f"  {receipt.full_number} · {payment.get_method_display()} · "
                    f"S/ {payment.amount}"
                )

        if commitment:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Compromiso de pago"))
            self.stdout.write(
                f"  paga el {commitment.committed_date:%d/%m/%Y} · "
                f"S/ {commitment.amount}"
            )

        self.stdout.write("")
        outstanding = (
            Charge.objects.filter(customer=customer).outstanding().count()
        )
        total = sum(
            charge.balance
            for charge in Charge.objects.filter(customer=customer).outstanding()
        )
        self.stdout.write(
            f"  Deuda abierta: {outstanding} cargo(s) · S/ {total}"
        )
