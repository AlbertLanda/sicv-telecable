"""Importa zonas operativas de una sede desde un TXT simple."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.organization.models import Branch, Zone


def normalize_zone_name(value):
    return " ".join((value or "").strip().split())


class Command(BaseCommand):
    help = (
        "Importa zonas desde un TXT UTF-8 con una zona por línea. "
        "No elimina zonas existentes y puede ejecutarse repetidamente."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "archivo",
            help="Ruta al TXT con una zona por línea",
        )
        parser.add_argument(
            "--sede",
            required=True,
            help="Nombre exacto de la sede destino",
        )
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
            available = ", ".join(
                Branch.objects.order_by("name").values_list("name", flat=True)
            )
            raise CommandError(
                f"No existe la sede «{branch_name}». "
                f"Sedes disponibles: {available or 'ninguna'}."
            ) from exc
        except Branch.MultipleObjectsReturned as exc:
            raise CommandError(
                f"Existe más de una sede con el nombre «{branch_name}»."
            ) from exc

        try:
            lines = file_path.read_text(encoding="utf-8-sig").splitlines()
        except UnicodeDecodeError as exc:
            raise CommandError("El archivo debe estar codificado en UTF-8.") from exc

        counters = {
            "processed": 0,
            "empty": 0,
            "created": 0,
            "existing": 0,
            "reactivated": 0,
        }
        seen = set()

        for raw_line in lines:
            counters["processed"] += 1
            name = normalize_zone_name(raw_line)

            if not name:
                counters["empty"] += 1
                continue

            key = name.casefold()
            if key in seen:
                counters["existing"] += 1
                continue
            seen.add(key)

            zone = (
                Zone.objects
                .filter(branch=branch, name__iexact=name)
                .first()
            )

            if zone is None:
                Zone.objects.create(
                    branch=branch,
                    name=name,
                    is_active=True,
                )
                counters["created"] += 1
                continue

            if not zone.is_active:
                zone.name = name
                zone.is_active = True
                zone.save(update_fields=["name", "is_active", "updated_at"])
                counters["reactivated"] += 1
            else:
                counters["existing"] += 1

        if dry_run:
            transaction.set_rollback(True)

        mode = "SIMULACIÓN" if dry_run else "IMPORTACIÓN"
        self.stdout.write(
            self.style.SUCCESS(f"{mode} ZONAS - sede {branch.name}")
        )
        self.stdout.write(f"Procesadas: {counters['processed']}")
        self.stdout.write(f"Vacías ignoradas: {counters['empty']}")
        self.stdout.write(f"Creadas: {counters['created']}")
        self.stdout.write(f"Ya existentes: {counters['existing']}")
        self.stdout.write(f"Reactivadas: {counters['reactivated']}")
