"""
Pruebas de renderizado de la ficha del cliente que consulta ATC.

Existen por un fallo real: el día 5 se agregó a `customers/detail.html` un
comentario con `{# … #}` de cuatro líneas. Django solo interpreta esa sintaxis
en una línea, así que el bloque se pintó como texto **dentro del campo
Latitud** y estuvo visible en pantalla. La suite completa —536 pruebas— pasó
sin detectarlo, porque ninguna renderizaba esta plantilla: toda la cobertura de
la regla de ubicación estaba en la capa Python.

De ahí las dos cosas que se fijan aquí:

1. **Que la plantilla no filtre texto de comentarios**, en general y no solo
   el caso concreto que falló.
2. **Que la regla de coordenadas se cumpla en el HTML que ATC ve**, no solo en
   el diccionario que devuelve `location_payload()`. Es el último tramo: un
   `0,0` correctamente saneado en Python y luego pintado desde el campo crudo
   en la plantilla volvería a mostrar el enlace al golfo de Guinea.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.customers.models import Customer, CustomerAddress
from apps.organization.models import Branch, Zone

User = get_user_model()


class CustomerDetailLocationRenderTests(TestCase):
    """La ubicación tal como llega al navegador de ATC."""

    # Texto del enlace al mapa en la plantilla. Si el enlace aparece, ATC lo
    # va a pulsar; por eso la aserción es sobre lo que se pinta y no sobre una
    # variable de contexto.
    MAP_BUTTON_TEXT = "Ver ubicación GPS"

    def setUp(self):
        self.branch = Branch.objects.create(code="SED01", name="Sede Central")
        self.zone = Zone.objects.create(branch=self.branch, name="Zona Norte")

        self.customer = Customer.objects.create(
            code="CLI001",
            branch=self.branch,
            document_type=Customer.DocumentType.DNI,
            document_number="45678912",
            first_name="Juan",
            paternal_surname="Pérez",
            maternal_surname="Ramos",
        )

        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            zone=self.zone,
            address="Av. Los Álamos 123",
            reference="Frente al parque",
            district="Chachapoyas",
            is_primary=True,
        )

        self.user = User.objects.create_user(
            username="atc_ficha",
            password="test1234",
        )

        self.client.login(username="atc_ficha", password="test1234")

        self.url = reverse(
            "customers:detail",
            kwargs={"pk": self.customer.pk},
        )

    def render(self, **address_fields):
        """Devuelve el HTML de la ficha con la dirección ajustada."""
        if address_fields:
            for field, value in address_fields.items():
                setattr(self.address, field, value)

            self.address.save()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        return response.content.decode("utf-8")

    def test_the_template_does_not_leak_comment_syntax(self):
        """Ningún marcador de comentario debe llegar al navegador.

        La comprobación es genérica a propósito: no busca el texto que falló
        el día 5, sino **cualquier** marcador de comentario en la salida. Un
        `{# … #}` multilínea nuevo, en este archivo o en los que extiende,
        volvería a filtrarse y esta prueba lo atraparía sin que nadie tenga
        que acordarse de mirar la pantalla.
        """
        body = self.render()

        for marker in ("{#", "#}", "{% comment", "{% endcomment"):
            with self.subTest(marcador=marker):
                # `assertFalse` con mensaje propio en lugar de `assertNotIn`:
                # este último volcaría la página completa —más de 20 000
                # caracteres— en el fallo, y quien lo lea en CI necesita saber
                # qué marcador se filtró, no el HTML entero.
                self.assertFalse(
                    marker in body,
                    msg=(
                        f"El marcador de comentario «{marker}» llegó al HTML. "
                        "Recuerde que «{# … #}» solo funciona en una línea: "
                        "para varias use «{% comment %} … {% endcomment %}»."
                    ),
                )

    def test_zero_coordinates_are_rendered_as_missing_without_a_map_link(self):
        """`0 / 0.0000000` guardado en base no se pinta como ubicación.

        Es el caso que deja una consulta de suministro sin georreferencia. ATC
        debe ver que no hay GPS —y no un botón que lleva al golfo de Guinea—
        aunque la fila de la base traiga ceros y un enlace almacenado.
        """
        body = self.render(
            latitude=Decimal("0.0000000"),
            longitude=Decimal("0.0000000"),
            gps_link="https://www.google.com/maps/search/?api=1&query=0.0,0.0",
        )

        self.assertNotIn(self.MAP_BUTTON_TEXT, body)
        self.assertNotIn("0.0000000", body)
        self.assertIn("No registrada", body)

    def test_valid_coordinates_are_rendered_with_their_map_link(self):
        """Con GPS real, ATC sí ve las coordenadas y el botón del mapa.

        La contraparte de la prueba anterior: sanear no puede significar
        esconder lo que sí es válido.
        """
        body = self.render(
            latitude=Decimal("-6.2290000"),
            longitude=Decimal("-77.8730000"),
        )

        self.assertIn(self.MAP_BUTTON_TEXT, body)
        self.assertIn("-6.2290000", body)
        self.assertIn("-77.8730000", body)

    def test_the_textual_address_is_always_rendered(self):
        """Sin GPS, la dirección y el distrito siguen en pantalla.

        Es lo que permite atender igual, y la razón por la que descartar
        coordenadas falsas no deja a nadie sin información útil.
        """
        body = self.render(
            latitude=Decimal("0"),
            longitude=Decimal("0"),
        )

        self.assertIn("Av. Los Álamos 123", body)
        self.assertIn("Chachapoyas", body)
        self.assertIn("Frente al parque", body)
