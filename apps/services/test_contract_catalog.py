"""El catálogo que el contrato de servicio ofrece.

Lo siembra una migración, así que existe en toda base y en el propio banco de
pruebas. Se comprueba aquí porque es un dato de negocio con nombre propio: si
un plan desaparece o cambia de nombre, el contrato deja de poder ofrecer lo
que la empresa vende, y eso no se nota en ninguna otra prueba.
"""

from django.test import TestCase

from .models import Plan, ServiceType


class ContractServiceCatalogTests(TestCase):

    def test_los_servicios_del_contrato_estan_sembrados(self):
        esperados = {
            "TELEFONO": "SERVICIO DE TELÉFONO",
            "FIBRA_OSCURA": "FIBRA OSCURA",
            "TRANSPORTE_DATOS": "TRANSPORTE DE DATOS",
            "APPS": "APPS",
        }

        for codigo, nombre in esperados.items():
            servicio = ServiceType.objects.get(code=codigo)

            self.assertEqual(servicio.name, nombre)
            self.assertTrue(servicio.is_active)

    def test_solo_apps_pide_cuenta_playhub(self):
        """La bandera vive en el servicio, no en una lista de códigos.

        El formulario del contrato pregunta al servicio si necesita cuenta.
        Si mañana otro servicio se entrega igual, basta activarle la bandera
        en Configurar > Servicios.
        """

        self.assertTrue(
            ServiceType.objects.get(code="APPS").requires_playhub_account
        )

        con_cuenta = set(
            ServiceType.objects
            .filter(requires_playhub_account=True)
            .values_list("code", flat=True)
        )

        self.assertEqual(con_cuenta, {"APPS"})

    def test_los_planes_de_telefonia_fibra_y_transporte(self):
        esperados = {
            "TELEFONO": {
                "SERVICIO DE TELÉFONO - RDSVM",
                "SERVICIO DE TELÉFONO - UGEL",
                "TELÉFONO TUNANMARCA",
            },
            "FIBRA_OSCURA": {
                "ARRENDAMIENTO FIBRA OSCURA XIRRUS TEC",
            },
            "TRANSPORTE_DATOS": {
                "TRANSPORTE DE DATOS 10 MB - OPTICAL NETWORKS",
            },
        }

        for codigo, nombres in esperados.items():
            planes = set(
                Plan.objects
                .filter(service_type__code=codigo, is_active=True)
                .values_list("name", flat=True)
            )

            self.assertEqual(planes, nombres)

    def test_los_siete_planes_de_apps(self):
        planes = set(
            Plan.objects
            .filter(service_type__code="APPS", is_active=True)
            .values_list("name", flat=True)
        )

        self.assertEqual(
            planes,
            {
                "APP ESTANDAR",
                "APP PREMIUM",
                "APP PREMIUM - ST",
                "APP PREMIUM PLUS",
                "APP PREMIUM PLUS - RPR",
                "APP PREMIUM PLUS - ST",
                "APP TELECABLE",
            },
        )

    def test_los_planes_nuevos_nacen_sin_precio_ni_politica(self):
        """Lo que no está confirmado no se inventa.

        Una mensualidad sembrada al azar saldría en la cotización como si
        fuera la oficial. Cero y «sin política» se leen como lo que son: algo
        que falta configurar en Configurar > Planes.
        """

        planes = Plan.objects.filter(
            service_type__code__in=[
                "TELEFONO",
                "FIBRA_OSCURA",
                "TRANSPORTE_DATOS",
                "APPS",
            ]
        )

        self.assertEqual(planes.count(), 12)

        for plan in planes:
            self.assertEqual(plan.monthly_price, 0)
            self.assertIsNone(plan.billing_policy_id)
            self.assertFalse(plan.requires_geographic_tariff)
            self.assertEqual(plan.included_tv_points, 2)

    def test_transporte_de_datos_conserva_su_velocidad(self):
        plan = Plan.objects.get(code="TD-ON-10MB")

        self.assertEqual(plan.speed_mbps, 10)
