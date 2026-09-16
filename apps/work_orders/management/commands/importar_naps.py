"""Importa cajas NAP desde una exportación tabulada del SICV anterior."""

import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.organization.models import Branch
from apps.work_orders.nap_catalog import NetworkAccessPoint


CODE_AT_END_RE = re.compile(r"(?P<code>\d+)\s*$")


def normalize_label(value):
    return " ".join((value or "").strip().split())


def looks_empty_legacy_label(label):
    compact = label.replace("-", "").strip()
    return not compact


class Command(BaseCommand):
    help = (
        "Importa NAP desde un TXT con columnas ID_ANTIGUO y nombre separadas "
        "por tabulación. Los registros vacíos/incompletos se ignoran."
    )

    def add_arguments(self, parser):
        parser.add_argument("archivo", help="Ruta al TXT exportado del sistema anterior")
        parser.add_argument("--sede", required=True, help="Nombre exacto de la sede destino")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Valida y muestra el resumen sin guardar cambios",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        file_path = Path(options["archivo"])
        branch_name = options["sede"].strip()
        dry_run = options["dry_run"]

        if not file_path.exists() or not file_path.is_file():
            raise CommandError(f"No existe el archivo: {file_path}")

        try:
            branch = Branch.objects.get(name__iexact=branch_name)
        except Branch.DoesNotExist as exc:
            available = ", ".join(Branch.objects.order_by("name").values_list("name", flat=True))
            raise CommandError(
                f"No existe la sede «{branch_name}». Sedes disponibles: {available or 'ninguna'}."
            ) from exc
        except Branch.MultipleObjectsReturned as exc:
            raise CommandError(
                f"Existe más de una sede con el nombre «{branch_name}». Use un nombre único."
            ) from exc

        other_branch_names = [
            normalize_label(name).upper()
            for name in Branch.objects.exclude(pk=branch.pk).values_list("name", flat=True)
            if normalize_label(name)
        ]

        counters = {
            "processed": 0,
            "empty": 0,
            "incomplete": 0,
            "other_branch": 0,
            "created": 0,
            "updated": 0,
            "conflicts": 0,
        }

        try:
            lines = file_path.read_text(encoding="utf-8-sig").splitlines()
        except UnicodeDecodeError as exc:
            raise CommandError("El archivo debe estar codificado en UTF-8.") from exc

        for raw_line in lines:
            if not raw_line.strip():
                continue

            counters["processed"] += 1
            parts = raw_line.split("\t", 1)
            if len(parts) != 2:
                counters["incomplete"] += 1
                continue

            legacy_raw, label_raw = parts
            label = normalize_label(label_raw)

            if looks_empty_legacy_label(label):
                counters["empty"] += 1
                continue

            try:
                legacy_id = int(legacy_raw.strip())
            except (TypeError, ValueError):
                counters["incomplete"] += 1
                continue

            upper_label = label.upper()
            if any(
                upper_label == other_name or upper_label.startswith(f"{other_name} -")
                for other_name in other_branch_names
            ):
                counters["other_branch"] += 1
                continue

            match = CODE_AT_END_RE.search(label)
            if not match:
                counters["incomplete"] += 1
                continue
            code = match.group("code")

            by_legacy = NetworkAccessPoint.objects.filter(legacy_id=legacy_id).first()
            if by_legacy is not None and by_legacy.branch_id != branch.pk:
                counters["conflicts"] += 1
                continue

            by_code = NetworkAccessPoint.objects.filter(branch=branch, code=code).first()
            if by_code is not None and by_legacy is not None and by_code.pk != by_legacy.pk:
                counters["conflicts"] += 1
                continue
            if by_code is not None and by_legacy is None and by_code.legacy_id not in (None, legacy_id):
                counters["conflicts"] += 1
                continue

            nap = by_legacy or by_code
            if nap is None:
                NetworkAccessPoint.objects.create(
                    legacy_id=legacy_id,
                    branch=branch,
                    code=code,
                    name=label,
                    is_active=True,
                )
                counters["created"] += 1
                continue

            changed = False
            for field, value in {
                "legacy_id": legacy_id,
                "code": code,
                "name": label,
                "is_active": True,
            }.items():
                if getattr(nap, field) != value:
                    setattr(nap, field, value)
                    changed = True
            if changed:
                nap.save(update_fields=["legacy_id", "code", "name", "is_active", "updated_at"])
                counters["updated"] += 1

        if dry_run:
            transaction.set_rollback(True)

        mode = "SIMULACIÓN" if dry_run else "IMPORTACIÓN"
        self.stdout.write(self.style.SUCCESS(f"{mode} NAP - sede {branch.name}"))
        self.stdout.write(f"Procesadas: {counters['processed']}")
        self.stdout.write(f"Vacías ignoradas: {counters['empty']}")
        self.stdout.write(f"Incompletas ignoradas: {counters['incomplete']}")
        self.stdout.write(f"Otra sede ignoradas: {counters['other_branch']}")
        self.stdout.write(f"Creadas: {counters['created']}")
        self.stdout.write(f"Actualizadas: {counters['updated']}")
        self.stdout.write(f"Conflictos ignorados: {counters['conflicts']}")
