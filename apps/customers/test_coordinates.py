"""
Pruebas de la regla única de coordenadas GPS.

Son pruebas de unidad puras —sin base de datos ni HTTP— porque lo que se fija
es una decisión de una sola línea: **cuándo un par de números es una ubicación
y cuándo es un dato faltante disfrazado**.

El caso que motiva el módulo es real: Distriluz responde `0` en `gpsx`/`gpsy`
cuando el suministro no tiene georreferencia, y `"0"` es una cadena no vacía,
así que cualquier comprobación por presencia la acepta y construye un enlace a
`0,0` — un punto en el golfo de Guinea, a 9.000 km de Chachapoyas.
"""

from decimal import Decimal

from django.test import SimpleTestCase

from apps.customers.coordinates import (
    LATITUDE_RANGE,
    build_gps_link,
    location_payload,
    normalize_coordinate,
    normalize_coordinate_pair,
)
from apps.customers.models import CustomerAddress


class NormalizeCoordinateTests(SimpleTestCase):
    """Qué pasa la validación y qué no, valor por valor."""

    def test_real_coordinates_are_returned_as_decimal(self):
        """Una coordenada válida se devuelve como `Decimal`, no como texto.

        Los tres orígenes entregan tipos distintos —el SOAP texto, el modelo
        `Decimal`, un formulario cualquiera de los dos— y todos deben terminar
        en el mismo tipo para poder compararse y formatearse igual.
        """
        for value in ("-6.2290000", -6.229, Decimal("-6.2290000")):
            with self.subTest(valor=repr(value)):
                self.assertEqual(
                    normalize_coordinate(value),
                    Decimal("-6.229"),
                )

    def test_zero_in_every_form_is_rejected(self):
        """El centinela de «sin dato» de Distriluz, en todas sus escrituras.

        Es el corazón de la regla: `0` no es «la coordenada cero», es «no hay
        coordenada». Se devuelve `None` y nunca `0`, para que ninguna capa
        posterior pueda confundirlo con una ubicación.
        """
        for value in (
            0,
            "0",
            0.0,
            "0.0",
            "0.0000000",
            "-0.00",
            Decimal("0E-7"),
        ):
            with self.subTest(valor=repr(value)):
                self.assertIsNone(normalize_coordinate(value))

    def test_empty_values_are_rejected(self):
        """Vacío en cualquiera de sus formas, incluido el blanco en cadena."""
        for value in (None, "", "   ", "\t"):
            with self.subTest(valor=repr(value)):
                self.assertIsNone(normalize_coordinate(value))

    def test_non_numeric_values_are_rejected(self):
        """Lo que no es número no revienta: se descarta.

        Un servicio externo puede responder «N/D» o «null» en el mismo campo
        donde otras veces manda un número. Que eso no levante una excepción es
        parte del contrato: la consulta de un suministro sin GPS no es un
        error, es un suministro sin GPS.
        """
        for value in ("N/D", "-", "null", "abc", "6,229", object()):
            with self.subTest(valor=repr(value)):
                self.assertIsNone(normalize_coordinate(value))

    def test_values_outside_the_planet_are_rejected_when_limited(self):
        """999 no es una latitud, y el modelo la admitiría.

        `DecimalField(max_digits=10, decimal_places=7)` llega hasta
        999.9999999, así que el propio campo no protege de un número
        imposible. No es una regla de negocio: es la definición de coordenada.
        """
        for value in ("999.9999999", "-91", "90.0000001"):
            with self.subTest(valor=value):
                self.assertIsNone(
                    normalize_coordinate(value, LATITUDE_RANGE),
                )

        # Los extremos exactos sí son válidos.
        self.assertEqual(
            normalize_coordinate("-90", LATITUDE_RANGE),
            Decimal("-90"),
        )

    def test_extra_precision_is_trimmed_to_the_stored_precision(self):
        """8 decimales se recortan a 7, los que el modelo almacena.

        Es el caso real del autocompletado: Distriluz responde `gpsx`/`gpsy`
        con 8 decimales y el campo es `decimal_places=7`, así que sin este
        recorte el valor atraviesa la normalización sin objeción —no es cero,
        es numérico, cae dentro del planeta— y lo rechaza después el
        `DecimalValidator` del modelo, ya dentro del formulario de alta. El
        operador veía las coordenadas llenas con un error rojo debajo y tenía
        que borrar un dígito a mano en cada campo.

        Se comprueba el número de decimales explícitamente porque `Decimal`
        compara por valor: `Decimal("-11.78610260") == Decimal("-11.7861026")`
        es cierto, así que un `assertEqual` solo no distinguiría si el recorte
        ocurrió.
        """
        for value, expected in (
            ("-11.78610260", "-11.7861026"),
            ("-75.49002020", "-75.4900202"),
            # El octavo decimal redondea, no se trunca.
            ("-6.22900005", "-6.2290001"),
            ("-6.22900004", "-6.2290000"),
        ):
            with self.subTest(valor=value):
                result = normalize_coordinate(value)

                self.assertEqual(result, Decimal(expected))
                self.assertEqual(-result.as_tuple().exponent, 7)

    def test_precision_is_trimmed_before_the_zero_rule_is_applied(self):
        """Un valor que redondea a cero es «sin GPS», no una ubicación.

        `0.00000004` no es cero, así que pasaría la regla del centinela si el
        recorte se aplicara después de validar. Al redondear se convertiría en
        `0.0000000` y se publicaría como coordenada — el mismo dato falso que
        el módulo evita, entrando por la puerta del redondeo.
        """
        for value in ("0.00000004", "-0.00000004", "0.0000000499"):
            with self.subTest(valor=value):
                self.assertIsNone(normalize_coordinate(value))

    def test_absurdly_large_numbers_do_not_raise(self):
        """Lo que no cabe en el campo se descarta, no revienta.

        `quantize` señala el desborde con `InvalidOperation` en lugar de
        truncar. Sin `limits` no hay rango que filtre antes, así que el
        contrato de «no levantar excepciones» tiene que sostenerse aquí.
        """
        for value in ("1E+40", "-1E+40", "9" * 40):
            with self.subTest(valor=value):
                self.assertIsNone(normalize_coordinate(value))


class NormalizeCoordinatePairTests(SimpleTestCase):
    """El par es indivisible."""

    def test_a_valid_pair_survives_complete(self):
        self.assertEqual(
            normalize_coordinate_pair("-6.2290000", "-77.8730000"),
            (Decimal("-6.229"), Decimal("-77.873")),
        )

    def test_half_a_pair_is_discarded_entirely(self):
        """Si una falla, la otra tampoco se publica.

        Media coordenada no ubica nada, y servirla invitaría a que alguien
        compusiera un mapa con el valor que falta puesto a cero — el mismo
        problema por otra vía.
        """
        for latitude, longitude in (
            ("-6.2290000", "0"),
            ("0", "-77.8730000"),
            ("-6.2290000", ""),
            (None, "-77.8730000"),
            ("-6.2290000", "N/D"),
        ):
            with self.subTest(lat=latitude, lon=longitude):
                self.assertEqual(
                    normalize_coordinate_pair(latitude, longitude),
                    (None, None),
                )

    def test_longitude_uses_its_own_range(self):
        """Una longitud de -120 es válida; una latitud de -120 no.

        Los rangos son distintos y no se comparte uno solo por comodidad.
        """
        self.assertEqual(
            normalize_coordinate_pair("-6.2290000", "-120.5"),
            (Decimal("-6.229"), Decimal("-120.5")),
        )

        self.assertEqual(
            normalize_coordinate_pair("-120.5", "-77.8730000"),
            (None, None),
        )


class BuildGpsLinkTests(SimpleTestCase):
    """No hay forma de construir un enlace sobre un par inválido."""

    def test_link_is_built_for_a_valid_pair(self):
        """El enlace conserva la precisión con la que llegó la coordenada.

        Los 7 decimales del campo del modelo viajan tal cual en lugar de
        recortarse: es el dato oficial del suministro y el mapa lo acepta
        igual.
        """
        link = build_gps_link("-6.2290000", "-77.8730000")

        self.assertEqual(
            link,
            "https://www.google.com/maps/search/?api=1"
            "&query=-6.2290000,-77.8730000",
        )

    def test_no_link_for_zero_or_missing_coordinates(self):
        """Cadena vacía, nunca un enlace a `0,0`.

        Una cadena vacía se pinta como «sin GPS». Un enlace inválido se pinta
        como un botón que lleva al lugar equivocado, y esa es la diferencia
        entre un dato que falta y un dato que engaña.
        """
        for latitude, longitude in (
            ("0", "0"),
            ("0.0000000", "0.0000000"),
            (None, None),
            ("", ""),
            ("-6.2290000", "0"),
        ):
            with self.subTest(lat=latitude, lon=longitude):
                self.assertEqual(build_gps_link(latitude, longitude), "")


class AddressLocationTests(SimpleTestCase):
    """Lo que las fichas muestran de una dirección.

    Se trabaja sobre instancias sin guardar: las propiedades y
    `location_payload()` son cálculo puro sobre los campos, no consultas.
    """

    def address(self, **fields):
        defaults = {
            "address": "Av. Los Álamos 123",
            "reference": "Frente al parque",
            "district": "Chachapoyas",
        }
        defaults.update(fields)

        return CustomerAddress(**defaults)

    def test_stored_zeros_are_not_published(self):
        """El caso de Distriluz, tal como queda guardado en la dirección.

        Los campos almacenados conservan lo que llegó —no se reescribe la base
        de datos— y son las propiedades `map_*` las que deciden qué se muestra.
        """
        address = self.address(
            latitude=Decimal("0.0000000"),
            longitude=Decimal("0.0000000"),
            gps_link="https://www.google.com/maps/search/?api=1&query=0.0,0.0",
        )

        self.assertIsNone(address.map_latitude)
        self.assertIsNone(address.map_longitude)
        self.assertEqual(address.map_link, "")

        # El dato crudo sigue intacto: esto es saneo de publicación, no una
        # migración de datos.
        self.assertEqual(address.latitude, Decimal("0.0000000"))

    def test_real_coordinates_are_published_with_their_link(self):
        address = self.address(
            latitude=Decimal("-6.2290000"),
            longitude=Decimal("-77.8730000"),
        )

        self.assertEqual(address.map_latitude, Decimal("-6.229"))
        self.assertEqual(address.map_longitude, Decimal("-77.873"))
        self.assertIn("-6.2290000,-77.8730000", address.map_link)

    def test_location_payload_keeps_the_textual_address(self):
        """El bloque completo: sin GPS, la dirección sigue siendo utilizable."""
        payload = location_payload(
            self.address(latitude=Decimal("0"), longitude=Decimal("0"))
        )

        self.assertEqual(
            payload,
            {
                "address": "Av. Los Álamos 123",
                "reference": "Frente al parque",
                "district": "Chachapoyas",
                "latitude": None,
                "longitude": None,
                "gps_link": "",
            },
        )
