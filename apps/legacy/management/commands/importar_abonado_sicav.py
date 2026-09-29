import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.customers.models import Customer, CustomerAddress
from apps.legacy.models import (
    LegacyContractSnapshot,
    LegacyRecord,
    LegacyWorkOrderEvidence,
    LegacyWorkOrderMaterial,
    LegacyWorkOrderParticipant,
    LegacyWorkOrderSnapshot,
)
from apps.organization.models import Branch, Zone
from apps.work_orders.models import OrderReason, OrderType

from apps.services.models import (
    BillingPolicy,
    Plan,
    ServiceType,
    Subscription,
    SubscriptionPlanHistory,
)


SENTINEL_DATES = {"01/01/1900", "1900-01-01"}

SUBSCRIPTION_STATUS_MAP = {
    "A": Subscription.Status.ACTIVE,
    "C": Subscription.Status.CUT,
    "R": Subscription.Status.CANCELLED,
    "P": Subscription.Status.INSTALLATION,
    "M": Subscription.Status.INSTALLATION,
    "U": Subscription.Status.CANCELLED,
    Subscription.Status.PRESALE: Subscription.Status.PRESALE,
    Subscription.Status.INSTALLATION: Subscription.Status.INSTALLATION,
    Subscription.Status.ACTIVE: Subscription.Status.ACTIVE,
    Subscription.Status.CUT: Subscription.Status.CUT,
    Subscription.Status.SUSPENDED: Subscription.Status.SUSPENDED,
    Subscription.Status.CANCELLED: Subscription.Status.CANCELLED,
}

CONTRACT_STATUS_MAP = {
    "A": LegacyContractSnapshot.Status.ACTIVE,
    "ACTIVO": LegacyContractSnapshot.Status.ACTIVE,
    "U": LegacyContractSnapshot.Status.CANCELLED,
    "ANULADO": LegacyContractSnapshot.Status.CANCELLED,
    "CANCELADO": LegacyContractSnapshot.Status.CANCELLED,
    "S": LegacyContractSnapshot.Status.SUSPENDED,
    "SUSPENDIDO": LegacyContractSnapshot.Status.SUSPENDED,
    "F": LegacyContractSnapshot.Status.FINISHED,
    "FINALIZADO": LegacyContractSnapshot.Status.FINISHED,
}

CONTRACT_MODALITY_MAP = {
    "V": LegacyContractSnapshot.Modality.SALE,
    "VENTA": LegacyContractSnapshot.Modality.SALE,
    "A": LegacyContractSnapshot.Modality.RENTAL,
    "ALQUILER": LegacyContractSnapshot.Modality.RENTAL,
    "P": LegacyContractSnapshot.Modality.OWNED,
    "PROPIO": LegacyContractSnapshot.Modality.OWNED,
    "C": LegacyContractSnapshot.Modality.LOAN,
    "PRESTAMO": LegacyContractSnapshot.Modality.LOAN,
    "PRÉSTAMO": LegacyContractSnapshot.Modality.LOAN,
}

WORK_ORDER_STATUS_MAP = {
    "A": LegacyWorkOrderSnapshot.Status.ATTENDED,
    "ATENDIDO": LegacyWorkOrderSnapshot.Status.ATTENDED,
    "D": LegacyWorkOrderSnapshot.Status.DERIVED,
    "DERIVADO": LegacyWorkOrderSnapshot.Status.DERIVED,
    "U": LegacyWorkOrderSnapshot.Status.CANCELLED,
    "ANULADO": LegacyWorkOrderSnapshot.Status.CANCELLED,
    "R": LegacyWorkOrderSnapshot.Status.REJECTED,
    "RECHAZADO": LegacyWorkOrderSnapshot.Status.REJECTED,
    "P": LegacyWorkOrderSnapshot.Status.PENDING,
    "PENDIENTE": LegacyWorkOrderSnapshot.Status.PENDING,
    "F": LegacyWorkOrderSnapshot.Status.NOT_FEASIBLE,
    "NO FACTIBLE": LegacyWorkOrderSnapshot.Status.NOT_FEASIBLE,
}

ATTENTION_TYPE_MAP = {
    "S": LegacyWorkOrderSnapshot.AttentionType.SYSTEM,
    "SISTEMA": LegacyWorkOrderSnapshot.AttentionType.SYSTEM,
    "SYSTEM": LegacyWorkOrderSnapshot.AttentionType.SYSTEM,
    "F": LegacyWorkOrderSnapshot.AttentionType.FIELD,
    "FISICA": LegacyWorkOrderSnapshot.AttentionType.FIELD,
    "FÍSICA": LegacyWorkOrderSnapshot.AttentionType.FIELD,
    "FIELD": LegacyWorkOrderSnapshot.AttentionType.FIELD,
}

RESPONSIBILITY_MAP = {
    "CLIENTE": LegacyWorkOrderSnapshot.Responsibility.CUSTOMER,
    "CUSTOMER": LegacyWorkOrderSnapshot.Responsibility.CUSTOMER,
    "EMPRESA": LegacyWorkOrderSnapshot.Responsibility.COMPANY,
    "COMPANY": LegacyWorkOrderSnapshot.Responsibility.COMPANY,
    "OTROS": LegacyWorkOrderSnapshot.Responsibility.OTHER,
    "OTRO": LegacyWorkOrderSnapshot.Responsibility.OTHER,
    "OTHER": LegacyWorkOrderSnapshot.Responsibility.OTHER,
}

DOCUMENT_TYPE_MAP = {
    "D": Customer.DocumentType.DNI,
    "DNI": Customer.DocumentType.DNI,
    "R": Customer.DocumentType.RUC,
    "RUC": Customer.DocumentType.RUC,
    "E": Customer.DocumentType.CE,
    "CE": Customer.DocumentType.CE,
    "P": Customer.DocumentType.PASSPORT,
    "PASSPORT": Customer.DocumentType.PASSPORT,
}


@dataclass
class ImportStats:
    customers: int = 0
    addresses: int = 0
    subscriptions: int = 0
    plan_history: int = 0
    reused: int = 0
    contracts: int = 0
    work_orders: int = 0
    participants: int = 0
    materials: int = 0
    evidences: int = 0
    warnings: int = 0


class Command(BaseCommand):
    help = (
        "Importa el bloque maestro de un expediente SICAV (abonado, "
        "direcciones, suscripciones e historial de planes). Usa LegacyRecord "
        "para idempotencia y permite --dry-run para validar sin persistir."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--archivo",
            required=True,
            help="Ruta al expediente JSON. No debe almacenarse en el repositorio.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Valida y ejecuta toda la importación dentro de una transacción que se revierte.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        path = Path(options["archivo"]).expanduser()
        dry_run = options["dry_run"]

        if not path.is_file():
            raise CommandError(f"No existe el archivo: {path}")

        data = self._load_json(path)
        self._validate_envelope(data)

        self.stats = ImportStats()
        self.stdout.write(self.style.MIGRATE_HEADING("Importación SICAV · bloque maestro"))
        if dry_run:
            self.stdout.write(self.style.WARNING("Modo DRY-RUN: todos los cambios se revertirán."))

        customer = self._import_customer(data["customer"])
        addresses = self._import_addresses(data.get("addresses", []), customer)
        subscriptions = self._import_subscriptions(
            data.get("subscriptions", []),
            customer,
            addresses,
        )
        self._import_plan_history(
            data.get("plan_history", []),
            customer,
            subscriptions,
        )
        self._import_contracts(
            data.get("contracts", []),
            customer,
            subscriptions,
        )
        self._import_work_orders(
            data.get("work_orders", []),
            customer,
            subscriptions,
        )

        self._print_summary()

        if dry_run:
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING("DRY-RUN: no se guardó ningún cambio."))
        else:
            self.stdout.write(self.style.SUCCESS("Bloque maestro SICAV importado correctamente."))

    def _load_json(self, path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError as exc:
            raise CommandError("El expediente debe estar codificado en UTF-8.") from exc
        except json.JSONDecodeError as exc:
            raise CommandError(
                f"JSON inválido en línea {exc.lineno}, columna {exc.colno}: {exc.msg}"
            ) from exc

    def _validate_envelope(self, data):
        if not isinstance(data, dict):
            raise CommandError("El expediente debe ser un objeto JSON.")
        if data.get("schema_version") != 1:
            raise CommandError("schema_version debe ser 1.")
        if str(data.get("source", "SICAV")).upper() != LegacyRecord.Source.SICAV:
            raise CommandError("Este comando solo admite source=SICAV.")
        if not isinstance(data.get("customer"), dict):
            raise CommandError("El expediente debe incluir un objeto customer.")

        for key in (
            "addresses",
            "subscriptions",
            "plan_history",
            "contracts",
            "work_orders",
        ):
            value = data.get(key, [])
            if not isinstance(value, list):
                raise CommandError(f"{key} debe ser una lista.")

    def _payloads(self, item):
        raw = item.get("raw")
        normalized = item.get("normalized")
        if normalized is None:
            normalized = {
                key: value
                for key, value in item.items()
                if key not in {"raw", "normalized"}
            }
        if raw is None:
            raw = item
        if not isinstance(raw, dict) or not isinstance(normalized, dict):
            raise CommandError("raw y normalized deben ser objetos JSON.")
        return raw, normalized

    def _legacy_id(self, item, label):
        value = item.get("legacy_id")
        if value is None and isinstance(item.get("normalized"), dict):
            value = item["normalized"].get("legacy_id")
        value = str(value or "").strip()
        if not value:
            raise CommandError(f"{label}: falta legacy_id.")
        return value

    def _existing_target(self, entity_type, legacy_id, raw_payload):
        record = LegacyRecord.objects.filter(
            source=LegacyRecord.Source.SICAV,
            entity_type=entity_type,
            legacy_id=legacy_id,
        ).select_related("target_content_type").first()

        if record is None:
            return None

        if record.raw_payload != raw_payload:
            raise CommandError(
                f"{entity_type} {legacy_id}: el payload original difiere del "
                "ya importado. No se sobrescribe historia; revise el expediente."
            )

        target = record.target_object
        if target is None:
            raise CommandError(
                f"{entity_type} {legacy_id}: existe el rastro legacy pero no "
                "su objeto SICV asociado."
            )

        self.stats.reused += 1
        return target

    def _record_legacy(
        self,
        *,
        entity_type,
        legacy_id,
        raw_payload,
        normalized_payload,
        target,
        customer=None,
        subscription=None,
    ):
        content_type = ContentType.objects.get_for_model(
            target,
            for_concrete_model=False,
        )
        record = LegacyRecord(
            source=LegacyRecord.Source.SICAV,
            entity_type=entity_type,
            legacy_id=legacy_id,
            customer=customer,
            subscription=subscription,
            target_content_type=content_type,
            target_object_id=target.pk,
            raw_payload=raw_payload,
            normalized_payload=normalized_payload,
            review_status=LegacyRecord.ReviewStatus.REVIEW,
        )
        record.full_clean()
        record.save()
        return record

    def _import_customer(self, item):
        legacy_id = self._legacy_id(item, "customer")
        raw, values = self._payloads(item)

        existing = self._existing_target(
            LegacyRecord.EntityType.CUSTOMER,
            legacy_id,
            raw,
        )
        if existing is not None:
            if not isinstance(existing, Customer):
                raise CommandError(f"customer {legacy_id}: el destino no es Customer.")
            return existing

        branch_code = self._required(values, "branch_code", "customer")
        try:
            branch = Branch.objects.get(code__iexact=str(branch_code).strip())
        except Branch.DoesNotExist as exc:
            raise CommandError(
                f"customer {legacy_id}: no existe la sede {branch_code!r}."
            ) from exc

        document_type = self._document_type(
            self._required(values, "document_type", "customer")
        )
        document_number = str(
            self._required(values, "document_number", "customer")
        ).strip()
        code = str(self._required(values, "code", "customer")).strip()

        collision = Customer.objects.filter(code=code).first()
        if collision is None:
            collision = Customer.objects.filter(
                document_type=document_type,
                document_number=document_number,
            ).first()
        if collision is not None:
            raise CommandError(
                f"customer {legacy_id}: ya existe un cliente SICV con código "
                f"o documento coincidente ({collision.code}) pero sin vínculo "
                "LegacyRecord. Revíselo antes de importar."
            )

        person_type = values.get("person_type")
        if not person_type:
            person_type = Customer.person_type_for_document(document_type)
        person_type = str(person_type).upper()

        customer = Customer(
            code=code,
            branch=branch,
            document_type=document_type,
            document_number=document_number,
            person_type=person_type,
            first_name=str(values.get("first_name") or "").strip(),
            paternal_surname=str(values.get("paternal_surname") or "").strip(),
            maternal_surname=str(values.get("maternal_surname") or "").strip(),
            business_name=str(values.get("business_name") or "").strip(),
            phone=str(values.get("phone") or "").strip(),
            secondary_phone=str(values.get("secondary_phone") or "").strip(),
            email=str(values.get("email") or "").strip(),
            is_active=bool(values.get("is_active", True)),
        )
        self._save_validated(customer, f"customer {legacy_id}")
        self._record_legacy(
            entity_type=LegacyRecord.EntityType.CUSTOMER,
            legacy_id=legacy_id,
            raw_payload=raw,
            normalized_payload=values,
            target=customer,
            customer=customer,
        )
        self.stats.customers += 1
        return customer

    def _import_addresses(self, items, customer):
        result = {}
        for item in items:
            legacy_id = self._legacy_id(item, "address")
            raw, values = self._payloads(item)

            existing = self._existing_target(
                LegacyRecord.EntityType.ADDRESS,
                legacy_id,
                raw,
            )
            if existing is not None:
                if not isinstance(existing, CustomerAddress):
                    raise CommandError(
                        f"address {legacy_id}: el destino no es CustomerAddress."
                    )
                if existing.customer_id != customer.pk:
                    raise CommandError(
                        f"address {legacy_id}: pertenece a otro cliente."
                    )
                result[legacy_id] = existing
                continue

            zone = self._resolve_zone(
                customer.branch,
                values.get("zone_name"),
                legacy_id,
            )
            address = CustomerAddress(
                customer=customer,
                zone=zone,
                address=str(
                    self._required(values, "address", f"address {legacy_id}")
                ).strip(),
                reference=str(values.get("reference") or "").strip(),
                district=str(
                    self._required(values, "district", f"address {legacy_id}")
                ).strip(),
                meter_number=str(values.get("meter_number") or "").strip(),
                electrical_supply_code=str(
                    values.get("electrical_supply_code") or ""
                ).strip(),
                latitude=self._decimal_or_none(
                    values.get("latitude"),
                    f"address {legacy_id}.latitude",
                ),
                longitude=self._decimal_or_none(
                    values.get("longitude"),
                    f"address {legacy_id}.longitude",
                ),
                gps_link=str(values.get("gps_link") or "").strip(),
                is_primary=bool(values.get("is_primary", True)),
                is_active=bool(values.get("is_active", True)),
            )
            self._save_validated(address, f"address {legacy_id}")
            self._record_legacy(
                entity_type=LegacyRecord.EntityType.ADDRESS,
                legacy_id=legacy_id,
                raw_payload=raw,
                normalized_payload=values,
                target=address,
                customer=customer,
            )
            self.stats.addresses += 1
            result[legacy_id] = address
        return result

    def _import_subscriptions(self, items, customer, addresses):
        result = {}
        for item in items:
            legacy_id = self._legacy_id(item, "subscription")
            raw, values = self._payloads(item)

            existing = self._existing_target(
                LegacyRecord.EntityType.SUBSCRIPTION,
                legacy_id,
                raw,
            )
            if existing is not None:
                if not isinstance(existing, Subscription):
                    raise CommandError(
                        f"subscription {legacy_id}: el destino no es Subscription."
                    )
                if existing.customer_id != customer.pk:
                    raise CommandError(
                        f"subscription {legacy_id}: pertenece a otro cliente."
                    )
                result[legacy_id] = existing
                continue

            address_legacy_id = str(
                self._required(
                    values,
                    "address_legacy_id",
                    f"subscription {legacy_id}",
                )
            )
            address = addresses.get(address_legacy_id)
            if address is None:
                raise CommandError(
                    f"subscription {legacy_id}: no se encontró address "
                    f"{address_legacy_id!r} en el expediente."
                )

            service_type = self._service_type(
                self._required(
                    values,
                    "service_type_code",
                    f"subscription {legacy_id}",
                ),
                legacy_id,
            )
            plan = self._plan(values, service_type, legacy_id)

            status_raw = str(
                self._required(values, "status", f"subscription {legacy_id}")
            ).upper()
            try:
                status = SUBSCRIPTION_STATUS_MAP[status_raw]
            except KeyError as exc:
                raise CommandError(
                    f"subscription {legacy_id}: estado no soportado {status_raw!r}."
                ) from exc

            service_number = int(values.get("service_number") or 1)
            collision = Subscription.objects.filter(
                customer=customer,
                service_type=service_type,
                service_number=service_number,
            ).first()
            if collision is not None:
                raise CommandError(
                    f"subscription {legacy_id}: ya existe la combinación "
                    "cliente/servicio/número sin vínculo LegacyRecord."
                )

            base_monthly_fee = self._decimal_or_none(
                values.get("base_monthly_fee"),
                f"subscription {legacy_id}.base_monthly_fee",
            )
            if base_monthly_fee is None:
                base_monthly_fee = plan.monthly_price
                if base_monthly_fee == Decimal("0.00"):
                    self._warn(
                        f"subscription {legacy_id}: el precio base quedó en "
                        "S/ 0.00 porque el expediente no lo indicó y el plan "
                        "aún no tiene tarifa configurada."
                    )

            billing_policy = self._billing_policy(
                values.get("billing_policy_code"),
                plan,
                legacy_id,
            )

            subscription = Subscription(
                customer=customer,
                address=address,
                service_type=service_type,
                plan=plan,
                billing_policy=billing_policy,
                status=status,
                service_number=service_number,
                billing_cycle=self._int_or_none(
                    values.get("billing_cycle"),
                    f"subscription {legacy_id}.billing_cycle",
                ),
                base_installation_fee=self._decimal_or_zero(
                    values.get("base_installation_fee"),
                    f"subscription {legacy_id}.base_installation_fee",
                ),
                base_monthly_fee=base_monthly_fee,
                initial_tv_courtesy_granted=int(
                    values.get("initial_tv_courtesy_granted") or 0
                ),
                annex_count=int(values.get("annex_count") or 0),
                installation_date=self._date_or_none(
                    values.get("installation_date"),
                    f"subscription {legacy_id}.installation_date",
                ),
                cut_date=self._date_or_none(
                    values.get("cut_date"),
                    f"subscription {legacy_id}.cut_date",
                ),
                reconnection_date=self._date_or_none(
                    values.get("reconnection_date"),
                    f"subscription {legacy_id}.reconnection_date",
                ),
                is_active=bool(values.get("is_active", True)),
            )
            self._save_validated(subscription, f"subscription {legacy_id}")
            self._record_legacy(
                entity_type=LegacyRecord.EntityType.SUBSCRIPTION,
                legacy_id=legacy_id,
                raw_payload=raw,
                normalized_payload=values,
                target=subscription,
                customer=customer,
                subscription=subscription,
            )
            self.stats.subscriptions += 1
            result[legacy_id] = subscription
        return result

    def _import_plan_history(self, items, customer, subscriptions):
        for item in items:
            legacy_id = self._legacy_id(item, "plan_history")
            raw, values = self._payloads(item)

            existing = self._existing_target(
                LegacyRecord.EntityType.PLAN_HISTORY,
                legacy_id,
                raw,
            )
            if existing is not None:
                if not isinstance(existing, SubscriptionPlanHistory):
                    raise CommandError(
                        f"plan_history {legacy_id}: destino incorrecto."
                    )
                continue

            subscription_id = str(
                self._required(
                    values,
                    "subscription_legacy_id",
                    f"plan_history {legacy_id}",
                )
            )
            subscription = subscriptions.get(subscription_id)
            if subscription is None:
                raise CommandError(
                    f"plan_history {legacy_id}: suscripción {subscription_id!r} "
                    "no encontrada en el expediente."
                )

            service_type = None
            service_code = values.get("service_type_code")
            if service_code:
                service_type = self._service_type(service_code, legacy_id)

            plan = None
            if values.get("plan_code") or values.get("plan_name"):
                if service_type is None:
                    raise CommandError(
                        f"plan_history {legacy_id}: indique service_type_code "
                        "para resolver el plan histórico."
                    )
                plan = self._plan(values, service_type, legacy_id)

            billing_policy = None
            policy_code = values.get("billing_policy_code")
            if policy_code:
                try:
                    billing_policy = BillingPolicy.objects.get(
                        code__iexact=str(policy_code).strip()
                    )
                except BillingPolicy.DoesNotExist as exc:
                    raise CommandError(
                        f"plan_history {legacy_id}: política "
                        f"{policy_code!r} inexistente."
                    ) from exc

            history = SubscriptionPlanHistory(
                subscription=subscription,
                service_type=service_type,
                plan=plan,
                service_name_snapshot=str(
                    values.get("service_name_snapshot") or ""
                ).strip(),
                plan_name_snapshot=str(
                    self._required(
                        values,
                        "plan_name_snapshot",
                        f"plan_history {legacy_id}",
                    )
                ).strip(),
                start_date=self._required_date(
                    values.get("start_date"),
                    f"plan_history {legacy_id}.start_date",
                ),
                end_date=self._date_or_none(
                    values.get("end_date"),
                    f"plan_history {legacy_id}.end_date",
                ),
                monthly_fee_snapshot=self._decimal_or_none(
                    values.get("monthly_fee_snapshot"),
                    f"plan_history {legacy_id}.monthly_fee_snapshot",
                ),
                billing_policy=billing_policy,
                billing_policy_name_snapshot=str(
                    values.get("billing_policy_name_snapshot") or ""
                ).strip(),
                source=SubscriptionPlanHistory.Source.SICAV,
                source_reference=str(
                    values.get("source_reference") or legacy_id
                ).strip(),
                is_validated=bool(values.get("is_validated", False)),
                validation_notes=str(
                    values.get("validation_notes") or ""
                ).strip(),
            )
            self._save_validated(history, f"plan_history {legacy_id}")
            self._record_legacy(
                entity_type=LegacyRecord.EntityType.PLAN_HISTORY,
                legacy_id=legacy_id,
                raw_payload=raw,
                normalized_payload=values,
                target=history,
                customer=customer,
                subscription=subscription,
            )
            self.stats.plan_history += 1

    def _import_contracts(self, items, customer, subscriptions):
        for item in items:
            legacy_id = self._legacy_id(item, "contract")
            raw, values = self._payloads(item)

            existing = self._existing_target(
                LegacyRecord.EntityType.CONTRACT,
                legacy_id,
                raw,
            )
            if existing is not None:
                if not isinstance(existing, LegacyContractSnapshot):
                    raise CommandError(
                        f"contract {legacy_id}: destino histórico incorrecto."
                    )
                continue

            subscription = self._subscription_from_expedient(
                values,
                subscriptions,
                f"contract {legacy_id}",
            )

            service_type = None
            service_code = str(values.get("service_type_code") or "").strip()
            if service_code:
                service_type = self._service_type(service_code, legacy_id)

            plan = None
            plan_code = str(values.get("plan_code") or "").strip()
            if plan_code:
                if service_type is None:
                    raise CommandError(
                        f"contract {legacy_id}: plan_code requiere "
                        "service_type_code."
                    )
                plan = self._plan(values, service_type, legacy_id)

            status_raw = str(values.get("status") or "").strip()
            status = self._mapped_or_unknown(
                CONTRACT_STATUS_MAP,
                status_raw,
                LegacyContractSnapshot.Status.UNKNOWN,
                f"contract {legacy_id}: estado {status_raw!r} sin mapear",
            )
            modality_raw = str(values.get("modality") or "").strip()
            modality = self._mapped_or_unknown(
                CONTRACT_MODALITY_MAP,
                modality_raw,
                LegacyContractSnapshot.Modality.UNKNOWN,
                f"contract {legacy_id}: modalidad {modality_raw!r} sin mapear",
            )

            contract = LegacyContractSnapshot(
                customer=customer,
                subscription=subscription,
                service_type=service_type,
                plan=plan,
                legacy_contract_number=str(
                    values.get("contract_number") or ""
                ).strip(),
                service_name_snapshot=str(
                    values.get("service_name_snapshot") or ""
                ).strip(),
                plan_name_snapshot=str(
                    values.get("plan_name_snapshot") or ""
                ).strip(),
                equipment_snapshot=str(
                    values.get("equipment_snapshot") or ""
                ).strip(),
                status=status,
                legacy_status=str(
                    values.get("legacy_status") or status_raw
                ).strip(),
                modality=modality,
                installments=self._int_or_none(
                    values.get("installments"),
                    f"contract {legacy_id}.installments",
                ),
                start_date=self._required_date(
                    values.get("start_date"),
                    f"contract {legacy_id}.start_date",
                ),
                end_date=self._date_or_none(
                    values.get("end_date"),
                    f"contract {legacy_id}.end_date",
                ),
                last_activation_date=self._date_or_none(
                    values.get("last_activation_date"),
                    f"contract {legacy_id}.last_activation_date",
                ),
                last_cut_date=self._date_or_none(
                    values.get("last_cut_date"),
                    f"contract {legacy_id}.last_cut_date",
                ),
                notes=str(values.get("notes") or "").strip(),
                is_validated=bool(values.get("is_validated", False)),
                validation_notes=str(
                    values.get("validation_notes") or ""
                ).strip(),
            )
            self._save_validated(contract, f"contract {legacy_id}")
            self._record_legacy(
                entity_type=LegacyRecord.EntityType.CONTRACT,
                legacy_id=legacy_id,
                raw_payload=raw,
                normalized_payload=contract.normalized_snapshot(),
                target=contract,
                customer=customer,
                subscription=subscription,
            )
            self.stats.contracts += 1

    def _import_work_orders(self, items, customer, subscriptions):
        imported = {}
        pending_links = []

        for item in items:
            legacy_id = self._legacy_id(item, "work_order")
            raw, values = self._payloads(item)

            existing = self._existing_target(
                LegacyRecord.EntityType.WORK_ORDER,
                legacy_id,
                raw,
            )
            if existing is not None:
                if not isinstance(existing, LegacyWorkOrderSnapshot):
                    raise CommandError(
                        f"work_order {legacy_id}: destino histórico incorrecto."
                    )
                imported[legacy_id] = existing
                if values.get("derived_from_legacy_id"):
                    pending_links.append(
                        (existing, str(values["derived_from_legacy_id"]))
                    )
                continue

            subscription = self._subscription_from_expedient(
                values,
                subscriptions,
                f"work_order {legacy_id}",
            )

            order_type = None
            order_type_code = str(
                values.get("order_type_code") or ""
            ).strip()
            if order_type_code:
                try:
                    order_type = OrderType.objects.get(
                        code__iexact=order_type_code
                    )
                except OrderType.DoesNotExist as exc:
                    raise CommandError(
                        f"work_order {legacy_id}: no existe OrderType "
                        f"{order_type_code!r}. Cargue/mapee el catálogo."
                    ) from exc
            else:
                self._warn(
                    f"work_order {legacy_id}: sin order_type_code; se "
                    "conserva solo la etiqueta histórica."
                )

            reason = None
            reason_code = str(values.get("reason_code") or "").strip()
            if reason_code:
                if order_type is None:
                    raise CommandError(
                        f"work_order {legacy_id}: reason_code requiere "
                        "order_type_code."
                    )
                try:
                    reason = OrderReason.objects.get(
                        order_type=order_type,
                        code__iexact=reason_code,
                    )
                except OrderReason.DoesNotExist as exc:
                    raise CommandError(
                        f"work_order {legacy_id}: motivo {reason_code!r} "
                        f"no existe en {order_type.code}."
                    ) from exc

            branch = subscription.customer.branch
            branch_code = str(values.get("branch_code") or "").strip()
            if branch_code:
                try:
                    branch = Branch.objects.get(code__iexact=branch_code)
                except Branch.DoesNotExist as exc:
                    raise CommandError(
                        f"work_order {legacy_id}: sede {branch_code!r} inexistente."
                    ) from exc

            zone = subscription.address.zone
            zone_name = str(values.get("zone_name") or "").strip()
            if zone_name:
                zone = self._resolve_zone(branch, zone_name, legacy_id)

            status_raw = str(values.get("status") or "").strip()
            status = self._mapped_or_unknown(
                WORK_ORDER_STATUS_MAP,
                status_raw,
                LegacyWorkOrderSnapshot.Status.UNKNOWN,
                f"work_order {legacy_id}: estado {status_raw!r} sin mapear",
            )
            attention_raw = str(
                values.get("attention_type") or ""
            ).strip()
            attention_type = self._mapped_or_unknown(
                ATTENTION_TYPE_MAP,
                attention_raw,
                LegacyWorkOrderSnapshot.AttentionType.UNKNOWN,
                f"work_order {legacy_id}: atención {attention_raw!r} sin mapear",
            )
            responsibility_raw = str(
                values.get("responsibility") or ""
            ).strip()
            responsibility = self._mapped_or_unknown(
                RESPONSIBILITY_MAP,
                responsibility_raw,
                LegacyWorkOrderSnapshot.Responsibility.UNKNOWN,
                f"work_order {legacy_id}: responsabilidad "
                f"{responsibility_raw!r} sin mapear",
                warn_empty=False,
            )

            order = LegacyWorkOrderSnapshot(
                customer=customer,
                subscription=subscription,
                order_type=order_type,
                reason=reason,
                branch=branch,
                zone=zone,
                legacy_order_number=str(
                    values.get("order_number") or ""
                ).strip(),
                order_type_name_snapshot=str(
                    values.get("order_type_name_snapshot") or ""
                ).strip(),
                reason_name_snapshot=str(
                    values.get("reason_name_snapshot") or ""
                ).strip(),
                legacy_type_code=str(
                    values.get("legacy_type_code") or ""
                ).strip(),
                status=status,
                legacy_status=str(
                    values.get("legacy_status") or status_raw
                ).strip(),
                attention_type=attention_type,
                responsibility=responsibility,
                detail=str(values.get("detail") or "").strip(),
                attention_detail=str(
                    values.get("attention_detail") or ""
                ).strip(),
                technical_notes=str(
                    values.get("technical_notes") or ""
                ).strip(),
                issued_at=self._datetime_or_none(
                    values.get("issued_at"),
                    f"work_order {legacy_id}.issued_at",
                ),
                attended_at=self._datetime_or_none(
                    values.get("attended_at"),
                    f"work_order {legacy_id}.attended_at",
                ),
                nap=str(values.get("nap") or "").strip(),
                terminal=str(values.get("terminal") or "").strip(),
                equipment_code=str(
                    values.get("equipment_code") or ""
                ).strip(),
                seal_number=str(values.get("seal_number") or "").strip(),
                is_validated=bool(values.get("is_validated", False)),
                validation_notes=str(
                    values.get("validation_notes") or ""
                ).strip(),
            )
            self._save_validated(order, f"work_order {legacy_id}")

            self._import_work_order_children(order, values, legacy_id)

            self._record_legacy(
                entity_type=LegacyRecord.EntityType.WORK_ORDER,
                legacy_id=legacy_id,
                raw_payload=raw,
                normalized_payload=order.normalized_snapshot(),
                target=order,
                customer=customer,
                subscription=subscription,
            )
            self.stats.work_orders += 1
            imported[legacy_id] = order

            if values.get("derived_from_legacy_id"):
                pending_links.append(
                    (order, str(values["derived_from_legacy_id"]))
                )

        for order, parent_legacy_id in pending_links:
            parent = imported.get(parent_legacy_id)
            if parent is None:
                parent_record = LegacyRecord.objects.filter(
                    source=LegacyRecord.Source.SICAV,
                    entity_type=LegacyRecord.EntityType.WORK_ORDER,
                    legacy_id=parent_legacy_id,
                ).first()
                parent = parent_record.target_object if parent_record else None

            if not isinstance(parent, LegacyWorkOrderSnapshot):
                raise CommandError(
                    f"work_order derivada: no se encontró la OT origen "
                    f"{parent_legacy_id!r}. La relación no se infiere."
                )

            if order.derived_from_id != parent.pk:
                order.derived_from = parent
                self._save_validated(
                    order,
                    f"work_order derivada {order.pk}",
                )
                record = LegacyRecord.objects.get(
                    source=LegacyRecord.Source.SICAV,
                    entity_type=LegacyRecord.EntityType.WORK_ORDER,
                    target_object_id=order.pk,
                    target_content_type=ContentType.objects.get_for_model(
                        order,
                        for_concrete_model=False,
                    ),
                )
                LegacyRecord.objects.filter(pk=record.pk).update(
                    normalized_payload=order.normalized_snapshot()
                )

    def _import_work_order_children(self, order, values, legacy_id):
        participants = values.get("participants", [])
        materials = values.get("materials", [])
        evidences = values.get("evidences", [])

        for key, rows in (
            ("participants", participants),
            ("materials", materials),
            ("evidences", evidences),
        ):
            if not isinstance(rows, list):
                raise CommandError(
                    f"work_order {legacy_id}.{key} debe ser una lista."
                )

        for row in participants:
            participant = LegacyWorkOrderParticipant(
                work_order=order,
                legacy_user_code=str(
                    row.get("legacy_user_code") or ""
                ).strip(),
                name_snapshot=str(row.get("name_snapshot") or "").strip(),
                role_snapshot=str(row.get("role_snapshot") or "").strip(),
                started_at=self._datetime_or_none(
                    row.get("started_at"),
                    f"work_order {legacy_id}.participant.started_at",
                ),
                ended_at=self._datetime_or_none(
                    row.get("ended_at"),
                    f"work_order {legacy_id}.participant.ended_at",
                ),
                notes=str(row.get("notes") or "").strip(),
            )
            self._save_validated(
                participant,
                f"work_order {legacy_id}.participant",
            )
            self.stats.participants += 1

        for row in materials:
            quantity = self._decimal_or_none(
                row.get("quantity"),
                f"work_order {legacy_id}.material.quantity",
            )
            if quantity is None or quantity == Decimal("0"):
                continue
            if quantity < 0:
                raise CommandError(
                    f"work_order {legacy_id}: cantidad de material negativa."
                )
            movement = str(
                row.get("movement_type")
                or LegacyWorkOrderMaterial.MovementType.USED
            ).strip().upper()
            valid_movements = {
                choice.value for choice in LegacyWorkOrderMaterial.MovementType
            }
            if movement not in valid_movements:
                raise CommandError(
                    f"work_order {legacy_id}: movimiento de material "
                    f"{movement!r} no soportado."
                )

            material = LegacyWorkOrderMaterial(
                work_order=order,
                legacy_material_code=str(
                    row.get("legacy_material_code") or ""
                ).strip(),
                name_snapshot=str(
                    self._required(
                        row,
                        "name_snapshot",
                        f"work_order {legacy_id}.material",
                    )
                ).strip(),
                quantity=quantity,
                unit_snapshot=str(row.get("unit_snapshot") or "").strip(),
                movement_type=movement,
                notes=str(row.get("notes") or "").strip(),
            )
            self._save_validated(
                material,
                f"work_order {legacy_id}.material",
            )
            self.stats.materials += 1

        for row in evidences:
            reference = self._safe_legacy_reference(
                row.get("legacy_reference"),
                f"work_order {legacy_id}.evidence",
            )
            evidence = LegacyWorkOrderEvidence(
                work_order=order,
                original_name=str(row.get("original_name") or "").strip(),
                legacy_reference=reference,
                description=str(row.get("description") or "").strip(),
            )
            self._save_validated(
                evidence,
                f"work_order {legacy_id}.evidence",
            )
            self.stats.evidences += 1

    def _subscription_from_expedient(self, values, subscriptions, label):
        subscription_id = str(
            self._required(values, "subscription_legacy_id", label)
        )
        subscription = subscriptions.get(subscription_id)
        if subscription is not None:
            return subscription

        record = LegacyRecord.objects.filter(
            source=LegacyRecord.Source.SICAV,
            entity_type=LegacyRecord.EntityType.SUBSCRIPTION,
            legacy_id=subscription_id,
        ).first()
        target = record.target_object if record else None
        if not isinstance(target, Subscription):
            raise CommandError(
                f"{label}: suscripción legacy {subscription_id!r} "
                "no encontrada."
            )
        return target

    def _resolve_zone(self, branch, zone_name, legacy_id):
        zone_name = str(zone_name or "").strip()
        if not zone_name:
            return None

        matches = Zone.objects.filter(
            branch=branch,
            name__iexact=zone_name,
        )
        if matches.count() == 1:
            return matches.first()
        if matches.exists():
            raise CommandError(
                f"address {legacy_id}: la zona {zone_name!r} es ambigua."
            )

        self._warn(
            f"address {legacy_id}: la zona {zone_name!r} no existe en SICV; "
            "se conserva en LegacyRecord pero la dirección queda sin Zone. "
            "No se crean zonas automáticamente."
        )
        return None

    def _service_type(self, code, legacy_id):
        try:
            return ServiceType.objects.get(code__iexact=str(code).strip())
        except ServiceType.DoesNotExist as exc:
            raise CommandError(
                f"{legacy_id}: no existe ServiceType {code!r}."
            ) from exc

    def _plan(self, values, service_type, legacy_id):
        plan_code = str(values.get("plan_code") or "").strip()
        plan_name = str(
            values.get("plan_name") or values.get("plan_name_snapshot") or ""
        ).strip()

        queryset = Plan.objects.filter(service_type=service_type)
        if plan_code:
            try:
                return queryset.get(code__iexact=plan_code)
            except Plan.DoesNotExist as exc:
                raise CommandError(
                    f"{legacy_id}: no existe Plan {plan_code!r} para "
                    f"{service_type.code}."
                ) from exc

        if not plan_name:
            raise CommandError(
                f"{legacy_id}: indique plan_code o plan_name."
            )

        matches = queryset.filter(name__iexact=plan_name)
        if matches.count() != 1:
            raise CommandError(
                f"{legacy_id}: el nombre de plan {plan_name!r} produjo "
                f"{matches.count()} coincidencias. Use plan_code."
            )
        return matches.first()

    def _billing_policy(self, explicit_code, plan, legacy_id):
        if not explicit_code:
            return plan.billing_policy
        try:
            return BillingPolicy.objects.get(
                code__iexact=str(explicit_code).strip()
            )
        except BillingPolicy.DoesNotExist as exc:
            raise CommandError(
                f"subscription {legacy_id}: política "
                f"{explicit_code!r} inexistente."
            ) from exc

    def _document_type(self, value):
        key = str(value or "").strip().upper()
        try:
            return DOCUMENT_TYPE_MAP[key]
        except KeyError as exc:
            raise CommandError(
                f"Tipo de documento SICAV no soportado: {value!r}."
            ) from exc

    def _required(self, values, key, label):
        value = values.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise CommandError(f"{label}: falta {key}.")
        return value

    def _date_or_none(self, value, label):
        if value is None:
            return None
        value = str(value).strip()
        if not value or value in SENTINEL_DATES:
            return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        raise CommandError(
            f"{label}: fecha inválida {value!r}; use YYYY-MM-DD o DD/MM/YYYY."
        )

    def _required_date(self, value, label):
        result = self._date_or_none(value, label)
        if result is None:
            raise CommandError(f"{label}: la fecha es obligatoria y no puede ser 1900.")
        return result

    def _datetime_or_none(self, value, label):
        if value is None:
            return None
        value = str(value).strip()
        if not value or value in SENTINEL_DATES:
            return None

        parsed = None
        for fmt in (
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
        ):
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue

        if parsed is None:
            raise CommandError(
                f"{label}: fecha/hora inválida {value!r}."
            )

        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(
                parsed,
                timezone.get_current_timezone(),
            )
        return parsed

    def _mapped_or_unknown(
        self,
        mapping,
        raw_value,
        unknown_value,
        warning,
        *,
        warn_empty=True,
    ):
        key = str(raw_value or "").strip().upper()
        if not key:
            if warn_empty:
                self._warn(warning)
            return unknown_value
        mapped = mapping.get(key)
        if mapped is None:
            self._warn(warning)
            return unknown_value
        return mapped

    def _safe_legacy_reference(self, value, label):
        reference = str(value or "").strip()
        lowered = reference.lower()
        forbidden = (
            "token=",
            "session=",
            "cookie=",
            "authorization=",
            "bearer ",
        )
        if any(fragment in lowered for fragment in forbidden):
            raise CommandError(
                f"{label}: la referencia parece contener credenciales o "
                "tokens de sesión y no puede persistirse."
            )
        return reference

    def _decimal_or_none(self, value, label):
        if value is None or str(value).strip() == "":
            return None
        try:
            return Decimal(str(value).strip())
        except (InvalidOperation, ValueError) as exc:
            raise CommandError(f"{label}: decimal inválido {value!r}.") from exc

    def _decimal_or_zero(self, value, label):
        result = self._decimal_or_none(value, label)
        return result if result is not None else Decimal("0.00")

    def _int_or_none(self, value, label):
        if value is None or str(value).strip() == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise CommandError(f"{label}: entero inválido {value!r}.") from exc

    def _save_validated(self, instance, label):
        try:
            instance.full_clean()
            instance.save()
        except ValidationError as exc:
            raise CommandError(f"{label}: {exc}") from exc

    def _warn(self, message):
        self.stats.warnings += 1
        self.stdout.write(self.style.WARNING(f"ADVERTENCIA: {message}"))

    def _print_summary(self):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Resumen bloque maestro"))
        self.stdout.write(f"  Abonados creados: {self.stats.customers}")
        self.stdout.write(f"  Direcciones creadas: {self.stats.addresses}")
        self.stdout.write(f"  Suscripciones creadas: {self.stats.subscriptions}")
        self.stdout.write(f"  Tramos de plan creados: {self.stats.plan_history}")
        self.stdout.write(f"  Contratos históricos: {self.stats.contracts}")
        self.stdout.write(f"  Órdenes históricas: {self.stats.work_orders}")
        self.stdout.write(f"  Participantes OT: {self.stats.participants}")
        self.stdout.write(f"  Materiales OT: {self.stats.materials}")
        self.stdout.write(f"  Evidencias OT: {self.stats.evidences}")
        self.stdout.write(f"  Registros ya importados: {self.stats.reused}")
        self.stdout.write(f"  Advertencias: {self.stats.warnings}")
