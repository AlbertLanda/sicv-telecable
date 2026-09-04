from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.organization.models import Branch
from apps.services.models import (
    BillingPolicy,
    CommercialCoverageRule,
    InstallationMaterialRule,
    Plan,
    PlanTariff,
    ServiceType,
)
from apps.work_orders.models import OrderReason, OrderResult, OrderType


class Command(BaseCommand):
    help = (
        "Carga/actualiza el catalogo comercial confirmado del SICV sin duplicar "
        "registros. No crea zonas cuya nomenclatura oficial aun no haya sido validada."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Ejecuta todas las validaciones y muestra el resumen, pero revierte los cambios.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        self.stdout.write(self.style.MIGRATE_HEADING("Catalogo comercial SICV"))

        branches = self._get_branches()
        policies = self._get_policies()
        services = self._load_service_types()
        order_catalog_stats = self._load_installation_order_catalog()
        plan_stats = self._load_plans(services, policies)
        tariff_stats = self._load_confirmed_cable_tariffs(branches)
        coverage_stats = self._load_confirmed_coverage(branches)
        material_stats = self._load_installation_rules(branches, services)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Resumen"))
        self.stdout.write(f"  Tipos de servicio: {ServiceType.objects.filter(code__in=services).count()}")
        self.stdout.write(
            "  Catalogo de instalacion: "
            f"{order_catalog_stats['created']} creados / "
            f"{order_catalog_stats['updated']} actualizados"
        )
        self.stdout.write(
            f"  Planes: {plan_stats['created']} creados / {plan_stats['updated']} actualizados"
        )
        self.stdout.write(
            f"  Tarifas Cable confirmadas: {tariff_stats['created']} creadas / "
            f"{tariff_stats['updated']} actualizadas"
        )
        self.stdout.write(
            f"  Reglas de cobertura confirmadas: {coverage_stats['created']} creadas / "
            f"{coverage_stats['updated']} actualizadas"
        )
        self.stdout.write(
            f"  Reglas de metraje: {material_stats['created']} creadas / "
            f"{material_stats['updated']} actualizadas"
        )
        self.stdout.write(
            self.style.WARNING(
                "  Zonas: no se crean automaticamente todavia; falta validar la nomenclatura oficial completa."
            )
        )

        if dry_run:
            transaction.set_rollback(True)
            self.stdout.write(self.style.WARNING("DRY RUN: no se guardo ningun cambio."))
        else:
            self.stdout.write(self.style.SUCCESS("Catalogo comercial cargado correctamente."))

    def _get_branches(self):
        expected = {"HUANCAYO", "JAUJA", "OROYA"}
        branches = {branch.code: branch for branch in Branch.objects.filter(code__in=expected)}
        missing = expected - set(branches)
        if missing:
            raise CommandError(
                "Faltan sedes base. Ejecute primero `python manage.py migrate`. "
                f"No encontradas: {', '.join(sorted(missing))}."
            )
        return branches

    def _get_policies(self):
        codes = {
            "calendar_pp5": "CALENDAR_PP5",
            "anniversary_pp10": "ANNIVERSARY_PP10",
            "calendar_no_discount": "CALENDAR_NO_DISCOUNT",
        }
        policies = {}
        for key, code in codes.items():
            try:
                policies[key] = BillingPolicy.objects.get(code=code)
            except BillingPolicy.DoesNotExist as exc:
                raise CommandError(
                    f"No existe la politica {code}. Ejecute primero `python manage.py migrate`."
                ) from exc
        return policies

    def _load_service_types(self):
        definitions = {
            "INTERNET": {
                "name": "Internet",
                "description": "Servicio de Internet",
                "supports_tv_annexes": False,
                "annex_installation_price": Decimal("0.00"),
                "annex_monthly_price": Decimal("0.00"),
                "is_active": True,
            },
            "CABLE": {
                "name": "Cable",
                "description": "Servicio de television por cable",
                "supports_tv_annexes": True,
                "annex_installation_price": Decimal("5.00"),
                "annex_monthly_price": Decimal("5.00"),
                "is_active": True,
            },
            "DUO": {
                "name": "Duo",
                "description": "Internet + television por cable",
                "supports_tv_annexes": True,
                "annex_installation_price": Decimal("5.00"),
                "annex_monthly_price": Decimal("5.00"),
                "is_active": True,
            },
        }

        result = {}
        for code, defaults in definitions.items():
            service, _ = ServiceType.objects.update_or_create(code=code, defaults=defaults)
            service.full_clean()
            service.save()
            result[code] = service

        self.stdout.write(self.style.SUCCESS("✓ Tipos de servicio: INTERNET / CABLE / DUO"))
        return result

    def _load_installation_order_catalog(self):
        """Carga el catalogo minimo que el alta comercial necesita para crear OT."""
        stats = {"created": 0, "updated": 0}

        order_type, created = OrderType.objects.update_or_create(
            code="INSTALLATION",
            defaults={
                "name": "Instalacion",
                "description": "Instalacion inicial de un servicio contratado.",
                "is_active": True,
            },
        )
        stats["created" if created else "updated"] += 1

        reason, created = OrderReason.objects.update_or_create(
            order_type=order_type,
            code="NEW_CLIENT",
            defaults={
                "name": "Cliente nuevo",
                "classification": OrderReason.Classification.TECHNICAL,
                "is_active": True,
            },
        )
        reason.full_clean()
        reason.save()
        stats["created" if created else "updated"] += 1

        for code, name, is_success in (
            ("SUCCESSFUL", "Instalacion exitosa", True),
            ("NOT_COMPLETED", "Instalacion no ejecutada", False),
        ):
            result, created = OrderResult.objects.update_or_create(
                order_type=order_type,
                code=code,
                defaults={
                    "name": name,
                    "is_success": is_success,
                    "is_active": True,
                },
            )
            result.full_clean()
            result.save()
            stats["created" if created else "updated"] += 1

        order_type.full_clean()
        order_type.save()
        self.stdout.write(
            self.style.SUCCESS(
                "✓ Catalogo OT de instalacion: INSTALLATION / NEW_CLIENT / resultados"
            )
        )
        return stats

    def _load_plans(self, services, policies):
        # Solo se cargan velocidades/precios que fueron confirmados con ATC o
        # mediante los folletos revisados durante el levantamiento.
        plan_rows = [
            # 2025 - Economico
            ("INT-2025-ECO-100", "Internet 100 Mbps - Economico 2025", "INTERNET", 2025, Plan.Category.ECONOMIC, 100, "50.00", "calendar_pp5"),
            ("DUO-2025-ECO-100", "Duo 100 Mbps - Economico 2025", "DUO", 2025, Plan.Category.ECONOMIC, 100, "70.00", "calendar_pp5"),
            # 2025 - Estandar
            ("INT-2025-STD-300", "Internet 300 Mbps - Estandar 2025", "INTERNET", 2025, Plan.Category.STANDARD, 300, "65.00", "calendar_pp5"),
            ("DUO-2025-STD-300", "Duo 300 Mbps - Estandar 2025", "DUO", 2025, Plan.Category.STANDARD, 300, "85.00", "calendar_pp5"),
            ("INT-2025-STD-600", "Internet 600 Mbps - Estandar 2025", "INTERNET", 2025, Plan.Category.STANDARD, 600, "75.00", "calendar_pp5"),
            ("DUO-2025-STD-600", "Duo 600 Mbps - Estandar 2025", "DUO", 2025, Plan.Category.STANDARD, 600, "95.00", "calendar_pp5"),
            ("INT-2025-STD-800", "Internet 800 Mbps - Estandar 2025", "INTERNET", 2025, Plan.Category.STANDARD, 800, "85.00", "calendar_pp5"),
            ("DUO-2025-STD-800", "Duo 800 Mbps - Estandar 2025", "DUO", 2025, Plan.Category.STANDARD, 800, "105.00", "calendar_pp5"),
            ("INT-2025-STD-1000", "Internet 1000 Mbps - Estandar 2025", "INTERNET", 2025, Plan.Category.STANDARD, 1000, "120.00", "calendar_pp5"),
            ("DUO-2025-STD-1000", "Duo 1000 Mbps - Estandar 2025", "DUO", 2025, Plan.Category.STANDARD, 1000, "140.00", "calendar_pp5"),
            # 2026 - Economico
            ("INT-2026-ECO-200", "Internet 200 Mbps - Economico 2026", "INTERNET", 2026, Plan.Category.ECONOMIC, 200, "50.00", "calendar_pp5"),
            ("DUO-2026-ECO-200", "Duo 200 Mbps - Economico 2026", "DUO", 2026, Plan.Category.ECONOMIC, 200, "70.00", "calendar_pp5"),
            # 2026 - Estandar
            ("INT-2026-STD-400", "Internet 400 Mbps - Estandar 2026", "INTERNET", 2026, Plan.Category.STANDARD, 400, "69.00", "anniversary_pp10"),
            ("DUO-2026-STD-400", "Duo 400 Mbps - Estandar 2026", "DUO", 2026, Plan.Category.STANDARD, 400, "89.00", "anniversary_pp10"),
            ("INT-2026-STD-600", "Internet 600 Mbps - Estandar 2026", "INTERNET", 2026, Plan.Category.STANDARD, 600, "79.00", "anniversary_pp10"),
            ("DUO-2026-STD-600", "Duo 600 Mbps - Estandar 2026", "DUO", 2026, Plan.Category.STANDARD, 600, "99.00", "anniversary_pp10"),
            ("INT-2026-STD-800", "Internet 800 Mbps - Estandar 2026", "INTERNET", 2026, Plan.Category.STANDARD, 800, "89.00", "anniversary_pp10"),
            ("DUO-2026-STD-800", "Duo 800 Mbps - Estandar 2026", "DUO", 2026, Plan.Category.STANDARD, 800, "109.00", "anniversary_pp10"),
            ("INT-2026-STD-1000", "Internet 1000 Mbps - Estandar 2026", "INTERNET", 2026, Plan.Category.STANDARD, 1000, "119.00", "anniversary_pp10"),
            ("DUO-2026-STD-1000", "Duo 1000 Mbps - Estandar 2026", "DUO", 2026, Plan.Category.STANDARD, 1000, "139.00", "anniversary_pp10"),
            # Super Economico se mantiene con la misma regla desde 2024.
            ("INT-2024-SUPER-50", "Internet 50 Mbps - Super Economico 2024", "INTERNET", 2024, Plan.Category.SUPER_ECONOMIC, 50, "35.00", "calendar_no_discount"),
            ("INT-2025-SUPER-50", "Internet 50 Mbps - Super Economico 2025", "INTERNET", 2025, Plan.Category.SUPER_ECONOMIC, 50, "35.00", "calendar_no_discount"),
            ("INT-2026-SUPER-50", "Internet 50 Mbps - Super Economico 2026", "INTERNET", 2026, Plan.Category.SUPER_ECONOMIC, 50, "35.00", "calendar_no_discount"),
        ]

        stats = {"created": 0, "updated": 0}
        for code, name, service_code, generation, category, speed, price, policy_key in plan_rows:
            defaults = {
                "name": name,
                "service_type": services[service_code],
                "generation": generation,
                "commercial_category": category,
                "billing_policy": policies[policy_key],
                "speed_mbps": speed,
                "technology": "FTTH",
                "monthly_price": Decimal(price),
                "included_tv_points": 2 if service_code == "DUO" else 0,
                "requires_geographic_tariff": False,
                "is_active": True,
            }
            plan, created = Plan.objects.update_or_create(code=code, defaults=defaults)
            plan.full_clean()
            plan.save()
            stats["created" if created else "updated"] += 1

        # Cable se modela como servicio independiente cuya mensualidad/instalacion
        # se resuelve por sede/zona. No se le asigna categoria comercial.
        cable, created = Plan.objects.update_or_create(
            code="CABLE-GENERAL",
            defaults={
                "name": "Cable - tarifa geografica",
                "service_type": services["CABLE"],
                "generation": None,
                "commercial_category": "",
                "billing_policy": policies["calendar_no_discount"],
                "speed_mbps": None,
                "technology": "CATV",
                "monthly_price": Decimal("0.00"),
                "included_tv_points": 2,
                "requires_geographic_tariff": True,
                "is_active": True,
            },
        )
        cable.full_clean()
        cable.save()
        stats["created" if created else "updated"] += 1

        self.stdout.write(self.style.SUCCESS("✓ Planes 2025/2026 y Super Economico confirmados"))
        return stats

    def _load_confirmed_cable_tariffs(self, branches):
        # La Oroya no se carga aqui porque su tarifa depende de la zona y aun
        # falta validar la lista/nomenclatura oficial completa de zonas.
        cable_plan = Plan.objects.get(code="CABLE-GENERAL")
        valid_from = date(2026, 8, 27)
        rows = [
            (branches["JAUJA"], Decimal("50.00"), Decimal("50.00")),
            (branches["HUANCAYO"], Decimal("50.00"), Decimal("50.00")),
        ]

        stats = {"created": 0, "updated": 0}
        for branch, installation_fee, monthly_fee in rows:
            tariff, created = PlanTariff.objects.update_or_create(
                plan=cable_plan,
                branch=branch,
                zone=None,
                valid_from=valid_from,
                defaults={
                    "installation_fee": installation_fee,
                    "monthly_fee": monthly_fee,
                    "valid_until": None,
                    "is_active": True,
                },
            )
            tariff.full_clean()
            tariff.save()
            stats["created" if created else "updated"] += 1

        self.stdout.write(self.style.SUCCESS("✓ Tarifas Cable confirmadas para Jauja y Huancayo"))
        return stats

    def _load_confirmed_coverage(self, branches):
        # Regla confirmada a nivel de toda La Oroya: en 2026 la categoria
        # Estandar es obligatoria. Las reglas zonales de Jauja/Huancayo se
        # cargaran cuando se valide el catalogo oficial de zonas.
        rule, created = CommercialCoverageRule.objects.update_or_create(
            generation=2026,
            commercial_category=Plan.Category.STANDARD,
            branch=branches["OROYA"],
            zone=None,
            valid_from=date(2026, 8, 27),
            defaults={
                "availability": CommercialCoverageRule.Availability.REQUIRED,
                "valid_until": None,
                "is_active": True,
            },
        )
        rule.full_clean()
        rule.save()
        self.stdout.write(self.style.SUCCESS("✓ Cobertura 2026 confirmada: La Oroya = Estandar obligatorio"))
        return {"created": int(created), "updated": int(not created)}

    def _load_installation_rules(self, branches, services):
        valid_from = date(2026, 8, 27)
        rows = []

        # UTP: Internet y Duo, todas las sedes.
        for service_code in ("INTERNET", "DUO"):
            rows.append(("UTP", service_code, None, "30.00", "2.00"))

        # RG6 confirmado para Cable/CATV. La aplicacion automatica a la parte
        # CATV de Duo se deja pendiente hasta confirmacion operativa explicita.
        rows.append(("RG6", "CABLE", None, "50.00", "1.00"))

        # Drop: regla por sede para Internet, Duo y Cable.
        free_drop_by_branch = {
            "JAUJA": "100.00",
            "OROYA": "100.00",
            "HUANCAYO": "300.00",
        }
        for branch_code, free_meters in free_drop_by_branch.items():
            for service_code in ("INTERNET", "DUO", "CABLE"):
                rows.append(("DROP", service_code, branches[branch_code], free_meters, "1.00"))

        stats = {"created": 0, "updated": 0}
        for material, service_code, branch, free_meters, excess_price in rows:
            rule, created = InstallationMaterialRule.objects.update_or_create(
                material=material,
                service_type=services[service_code],
                branch=branch,
                valid_from=valid_from,
                defaults={
                    "free_meters": Decimal(free_meters),
                    "excess_price_per_meter": Decimal(excess_price),
                    "valid_until": None,
                    "is_active": True,
                },
            )
            rule.full_clean()
            rule.save()
            stats["created" if created else "updated"] += 1

        self.stdout.write(self.style.SUCCESS("✓ Reglas de instalacion UTP / RG6 / Drop"))
        return stats
