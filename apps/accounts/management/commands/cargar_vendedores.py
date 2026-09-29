import re
import unicodedata

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import User
from apps.services.forms import seller_is_eligible


# Vendedores vigentes, escritos tal como los muestra el sistema anterior.
# Se conservan así -apellido primero en la mayoría, «EXT . CONCEPCIÓN» incluido-
# porque en la migración manual el operador copia al vendedor desde la ficha
# de SICAV y tiene que encontrarlo en SICV con el mismo texto.
VENDEDORES = (
    "AMES JAQUELYNE",
    "ARELLANO ELISA",
    "CARHUANCHO MARIA",
    "CARLOS ISABELITA",
    "CASAS BARRERA ROCÍO",
    "CASO VICENTE KATTERIN JENNYFER",
    "CONDOR URETA LIZETH ISABEL",
    "DE LA CRUZ KATERIN",
    "DEL PINO STEFAN",
    "DIEGO ENRIQUEZ",
    "EXT . CONCEPCIÓN",
    "FLORES YURELLY",
    "MAURATE ALDAIR",
    "MERCEDES",
    "NUÑEZ JOHANA",
    "NUÑEZ ROSITA",
    "OMONTE GRACIELA",
    "PARCO SANDRA",
    "POMA ANGIE",
    "QUIROZ NICOLE",
    "QUISPE CYNTHIA",
    "RIVERA CINTHYA",
    "ROJAS MARY",
    "ROMERO CARLA",
    "VALLE MERITZ",
    "WILDER CUTE",
)


def name_words(name):
    """`CASAS BARRERA ROCÍO` -> `["casas", "barrera", "rocio"]`."""
    ascii_name = (
        unicodedata.normalize("NFKD", name or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    return re.findall(r"[a-z0-9]+", ascii_name)


def username_for(name):
    """`CASAS BARRERA ROCÍO` -> `vend.casas.barrera.rocio`."""
    return "vend." + ".".join(name_words(name))


def comparable(name):
    """Nombre para detectar duplicados, sin importar tildes ni el orden.

    El sistema anterior escribe el apellido primero y una cuenta del SICV lo
    guarda al revés: «PARCO SANDRA» y «Sandra Parco» son la misma persona.
    """
    return tuple(sorted(name_words(name)))


class Command(BaseCommand):
    help = (
        "Registra a los vendedores vigentes como usuarios de Ventas sin acceso "
        "al sistema, para poder atribuirles ventas. No modifica a los que ya existen."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra lo que haría, pero revierte los cambios.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        self.stdout.write(self.style.MIGRATE_HEADING("Vendedores SICV"))

        # Un vendedor que ya tiene cuenta con su nombre -un ATC que también
        # vende, por ejemplo- no se duplica: se le atribuyen las ventas a esa.
        existing_names = {
            comparable(user.get_full_name()): user
            for user in User.objects.all()
            if user.get_full_name()
        }

        created, marked, skipped = [], [], []

        for name in VENDEDORES:
            username = username_for(name)

            if User.objects.filter(username=username).exists():
                skipped.append(f"{name} (ya existe como {username})")
                continue

            same_name = existing_names.get(comparable(name))
            if same_name:
                # Conserva su rol y su estado; solo se le habilita para vender.
                if not same_name.is_salesperson and not seller_is_eligible(same_name):
                    same_name.is_salesperson = True
                    same_name.save(update_fields=["is_salesperson", "updated_at"])
                    marked.append(f"{name} ({same_name.username})")
                else:
                    skipped.append(f"{name} (ya existe con el usuario {same_name.username})")
                continue

            # Sin contraseña: la cuenta sirve para la atribución comercial,
            # no para entrar. Si alguno debe usar el SICV, un administrador le
            # asigna contraseña después.
            user = User(
                username=username,
                first_name=name,
                role=User.Role.SALES,
                is_salesperson=True,
                is_active=True,
            )
            user.set_unusable_password()
            user.full_clean()
            user.save()
            created.append(f"{name} ({username})")

        for line in created:
            self.stdout.write(f"  + {line}")
        for line in marked:
            self.stdout.write(f"  * {line}: cuenta existente, ahora participa como vendedor")
        for line in skipped:
            self.stdout.write(self.style.WARNING(f"  = {line}"))

        self.stdout.write("")
        self.stdout.write(
            f"Resumen: {len(created)} creados / {len(marked)} habilitados como "
            f"vendedor / {len(skipped)} sin cambios."
        )

        if dry_run:
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING("DRY RUN: no se guardó ningún cambio."))
        else:
            self.stdout.write(self.style.SUCCESS("Vendedores cargados correctamente."))
