from django.db import IntegrityError, transaction
from django.test import TestCase

from .models import Equipment


class EquipmentModelTests(TestCase):

    def test_crear_equipment_con_datos_validos(self):
        equipment = Equipment.objects.create(
            equipment_type=Equipment.EquipmentType.ROUTER,
            brand="TP-Link",
            model="Archer C6",
            serial_or_mac="00:1A:2B:3C:4D:5E",
            status=Equipment.Status.IN_STOCK,
        )

        self.assertIsNotNone(equipment.pk)

    def test_numero_serie_mac_duplicado_lanza_error(self):
        Equipment.objects.create(
            equipment_type=Equipment.EquipmentType.ROUTER,
            brand="TP-Link",
            model="Archer C6",
            serial_or_mac="00:1A:2B:3C:4D:5E",
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Equipment.objects.create(
                    equipment_type=Equipment.EquipmentType.ONT,
                    brand="Huawei",
                    model="HG8245",
                    serial_or_mac="00:1A:2B:3C:4D:5E",
                )

    def test_str_representa_equipo_legible(self):
        equipment = Equipment.objects.create(
            equipment_type=Equipment.EquipmentType.ROUTER,
            brand="TP-Link",
            model="Archer C6",
            serial_or_mac="00:1A:2B:3C:4D:5E",
        )

        self.assertIn("TP-Link", str(equipment))
        self.assertIn("Archer C6", str(equipment))
        self.assertNotIn("Equipment object", str(equipment))