"""
Emite la mensualidad del periodo indicado para las suscripciones activas.

Se ejecuta una vez por mes. Es idempotente -la restricción única de
(suscripción, periodo) lo garantiza-, así que si se corta a la mitad se
vuelve a lanzar y completa lo que falte sin duplicar deuda.
"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.organization.models import Branch
from apps.payments.services import first_day_of, generate_monthly_charges


class Command(BaseCommand):
    help = (
        "Genera la mensualidad de las suscripciones activas para un periodo, "
        "sin duplicar cargos ya emitidos."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--periodo",
            help=(
                "Mes a facturar en formato AAAA-MM. "
                "Por defecto, el mes en curso."
            ),
        )
        parser.add_argument(
            "--sede",
            help="Código de sede. Por defecto se facturan todas.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra lo que se emitiría y revierte los cambios.",
        )

    def handle(self, *args, **options):
        period = self._resolve_period(options.get("periodo"))
        branch = self._resolve_branch(options.get("sede"))
        dry_run = options["dry_run"]

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Cargos mensuales · periodo {period:%m/%Y}"
                + (f" · sede {branch.code}" if branch else "")
            )
        )

        result = generate_monthly_charges(period, branch=branch, dry_run=dry_run)

        for charge in result["created"]:
            self.stdout.write(
                f"  + {charge.customer} · {charge.description} · "
                f"S/ {charge.amount} · vence {charge.due_date:%d/%m/%Y}"
            )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Resumen"))
        self.stdout.write(f"  Emitidos: {len(result['created'])}")
        self.stdout.write(f"  Omitidos: {result['skipped']}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN: no se guardó ningún cargo.")
            )

    def _resolve_period(self, raw):
        if not raw:
            return first_day_of(timezone.localdate())

        try:
            return first_day_of(datetime.strptime(raw, "%Y-%m").date())
        except ValueError:
            raise CommandError(
                f"Periodo inválido: «{raw}». Se espera AAAA-MM, por ejemplo 2026-09."
            )

    def _resolve_branch(self, code):
        if not code:
            return None

        branch = Branch.objects.filter(code=code).first()

        if branch is None:
            raise CommandError(f"No existe una sede con código «{code}».")

        return branch
