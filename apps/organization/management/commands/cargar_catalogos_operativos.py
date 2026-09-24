"""Carga los catálogos operativos oficiales versionados del SICV."""

from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


CATALOG_SPECS = (
    ("zonas", "Jauja", "organization/data/catalogs/zonas_jauja.txt", 25),
    ("zonas", "Huancayo", "organization/data/catalogs/zonas_huancayo.txt", 9),
    ("zonas", "La Oroya", "organization/data/catalogs/zonas_la_oroya.txt", 41),
    ("naps", "Jauja", "work_orders/data/catalogs/naps_jauja.txt", 1113),
    ("naps", "Huancayo", "work_orders/data/catalogs/naps_huancayo.txt", 830),
    ("naps", "La Oroya", "work_orders/data/catalogs/naps_la_oroya.txt", 590),
)


class Command(BaseCommand):
    help = (
        "Carga o actualiza las zonas y NAP oficiales incluidas en el repositorio. "
        "Es idempotente y puede ejecutarse en una base nueva o ya inicializada."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Valida todos los catálogos y revierte cualquier cambio.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        apps_dir = Path(__file__).resolve().parents[3]

        self.stdout.write(
            self.style.MIGRATE_HEADING("Catálogos operativos SICV")
        )

        for catalog_type, branch_name, relative_path, expected_rows in CATALOG_SPECS:
            file_path = apps_dir / relative_path
            self._validate_catalog_file(
                file_path,
                expected_rows=expected_rows,
            )

            command_name = (
                "importar_zonas"
                if catalog_type == "zonas"
                else "importar_naps"
            )
            call_command(
                command_name,
                str(file_path),
                sede=branch_name,
                dry_run=dry_run,
                stdout=self.stdout,
            )

        if dry_run:
            transaction.set_rollback(True)
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN: los catálogos fueron validados y no se guardaron cambios."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Catálogos operativos cargados correctamente: "
                    "75 zonas y 2533 NAP oficiales."
                )
            )

    def _validate_catalog_file(self, file_path, *, expected_rows):
        if not file_path.exists() or not file_path.is_file():
            raise CommandError(
                f"Falta el catálogo versionado: {file_path}"
            )

        try:
            lines = file_path.read_text(
                encoding="utf-8-sig"
            ).splitlines()
        except UnicodeDecodeError as exc:
            raise CommandError(
                f"El catálogo debe estar en UTF-8: {file_path}"
            ) from exc

        actual_rows = sum(1 for line in lines if line.strip())
        if actual_rows != expected_rows:
            raise CommandError(
                f"Catálogo incompleto o alterado: {file_path.name}. "
                f"Esperadas {expected_rows} filas y se encontraron {actual_rows}."
            )
