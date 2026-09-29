from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.accounts.management.commands.cargar_vendedores import (
    VENDEDORES,
    username_for,
)
from apps.accounts.models import User
from apps.services.forms import eligible_sellers_queryset


def run(*args):
    call_command("cargar_vendedores", *args, stdout=StringIO())


class CargarVendedoresTests(TestCase):
    def test_sellers_appear_in_the_seller_list(self):
        run()

        names = set(
            eligible_sellers_queryset().values_list("first_name", flat=True)
        )
        self.assertTrue(set(VENDEDORES) <= names)

    def test_sellers_cannot_log_in(self):
        run()

        seller = User.objects.get(username="vend.ames.jaquelyne")
        self.assertFalse(seller.has_usable_password())
        self.assertEqual(seller.role, User.Role.SALES)
        self.assertTrue(seller.is_salesperson)

    def test_username_drops_accents_and_punctuation(self):
        self.assertEqual(username_for("CASAS BARRERA ROCÍO"), "vend.casas.barrera.rocio")
        self.assertEqual(username_for("EXT . CONCEPCIÓN"), "vend.ext.concepcion")
        self.assertEqual(username_for("NUÑEZ JOHANA"), "vend.nunez.johana")

    def test_running_twice_does_not_duplicate_or_reactivate(self):
        run()
        User.objects.filter(username="vend.rojas.mary").update(is_active=False)

        run()

        self.assertEqual(
            User.objects.filter(username__startswith="vend.").count(),
            len(VENDEDORES),
        )
        self.assertFalse(User.objects.get(username="vend.rojas.mary").is_active)

    def test_existing_account_with_the_same_name_is_reused(self):
        User.objects.create_user(
            username="crivera",
            first_name="Cinthya",
            last_name="Rivera",
            role=User.Role.ATC,
        )

        run()

        self.assertFalse(User.objects.filter(username="vend.rivera.cinthya").exists())
        existing = User.objects.get(username="crivera")
        self.assertTrue(existing.is_salesperson)
        self.assertEqual(existing.role, User.Role.ATC)
        self.assertIn(existing, eligible_sellers_queryset())

    def test_dry_run_saves_nothing(self):
        run("--dry-run")

        self.assertFalse(User.objects.filter(username__startswith="vend.").exists())
