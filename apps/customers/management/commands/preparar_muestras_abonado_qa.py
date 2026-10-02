import json
import os
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.customers.models import Customer
from apps.customers.qa_samples import prepare_customer_samples


class Command(BaseCommand):
    help = "Agrega muestras identificadas al abonado indicado, exclusivamente en Azure QA."

    def add_arguments(self, parser):
        parser.add_argument("--customer-code", required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--if-present", action="store_true")
        parser.add_argument("--status-output")
        parser.add_argument("--billing-examples", action="store_true")

    def handle(self, *args, **options):
        if os.environ.get("WEBSITE_SITE_NAME") != "sicv-telecable-qa":
            raise CommandError("Comando exclusivo de sicv-telecable-qa.")
        status = {"sample": "customer_tabs_v1", "prepared": False}
        if options["if_present"] and not Customer.objects.filter(code=options["customer_code"]).exists():
            self.stdout.write("Abonado no presente: no se agregaron muestras.")
        else:
            try:
                actor = get_user_model().objects.get(username=options["actor"])
                data, created = prepare_customer_samples(customer_code=options["customer_code"], actor=actor)
                billing_data, billing_created = None, False
                if options["billing_examples"]:
                    from apps.customers.qa_billing_examples import prepare_billing_examples
                    billing_data, billing_created = prepare_billing_examples(
                        customer_code=options["customer_code"], actor=actor,
                    )
            except (ValidationError, Customer.DoesNotExist, get_user_model().DoesNotExist) as error:
                raise CommandError(str(error)) from error
            status.update(prepared=True, created=created, **{
                key: len(data[key]) for key in ("charges", "payments", "receipts", "orders")
            })
            self.stdout.write("Muestras QA preparadas." if created else "Muestras ya cargadas: se conservaron sin cambios.")
            if billing_data:
                status["billing_examples"] = {
                    "prepared": True, "created": billing_created,
                    "cases": len(billing_data["cases"]),
                    **{key: len(billing_data[key]) for key in ("charges", "payments", "receipts")},
                }
        if options["status_output"]:
            path = Path(options["status_output"])
            path.parent.mkdir(parents=True, exist_ok=True)
            # Marca pública de la carga, sin nombres, códigos ni importes del abonado.
            path.write_text(json.dumps(status))
        self.stdout.write(json.dumps(status))
