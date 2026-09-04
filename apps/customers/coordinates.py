"""
Qué cuenta como una coordenada GPS válida en el sistema.

Este módulo existe para que la regla viva en **un solo sitio**. Hoy la
ubicación de un punto de servicio la escriben y la leen tres frentes
distintos:

- la consulta de suministro del alta comercial, que trae las coordenadas de
  Distriluz;
- la ficha del cliente que consulta ATC en modo lectura;
- la ficha de la Orden Técnica que trabaja el técnico en campo.

Si cada uno decidiera por su cuenta cuándo hay GPS, bastaría con que uno fuera
más permisivo para que el técnico recibiera un pin en el mar mientras ATC ve el
mismo dato como vacío.

**El caso que motiva el módulo es real, no hipotético.** Distriluz responde
`0` en `gpsx`/`gpsy` cuando el suministro no tiene georreferencia, y `"0"` es
una cadena no vacía: cualquier comprobación por presencia —`if latitude and
longitude`— la acepta, construye un enlace de Google Maps a `0,0` y lo guarda
como coordenada oficial. `0,0` es un punto en el golfo de Guinea, a 9.000 km
de Chachapoyas. Para el técnico que abre el mapa en la puerta del cliente eso
no es un dato pobre: es un dato falso que parece bueno.

**La dirección textual nunca se sustituye por coordenadas.** Es el dato que
siempre viaja y el único que permite llegar cuando el GPS falta. Las
coordenadas son un extra que se acompaña, no un reemplazo: por eso este módulo
solo decide sobre ellas y jamás toca `address`, `reference` ni `district`.
"""

from decimal import Decimal, InvalidOperation


# Formato del enlace de mapa. Se declara aquí, junto a la regla que decide si
# hay coordenadas, para que nunca se pueda construir un enlace sobre un par
# que este módulo considera inválido.
GPS_LINK_TEMPLATE = (
    "https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
)

# Límites del planeta. No es una regla de negocio: una latitud de 999 no es
# una coordenada, y el modelo la admite porque `DecimalField(max_digits=10,
# decimal_places=7)` llega hasta 999.9999999.
LATITUDE_RANGE = (Decimal("-90"), Decimal("90"))
LONGITUDE_RANGE = (Decimal("-180"), Decimal("180"))


def normalize_coordinate(value, limits=None):
    """Devuelve la coordenada como `Decimal`, o `None` si no es una coordenada.

    Se descarta —convirtiéndolo en `None`, nunca en `0`— todo lo siguiente:

    - vacío en cualquiera de sus formas: `None`, `""`, `"   "`;
    - cero en cualquiera de sus escrituras: `0`, `"0"`, `0.0`,
      `Decimal("0.0000000")`, `"-0.00"`. Es el centinela de «sin dato» de
      Distriluz y el valor que deja un campo numérico sin llenar;
    - lo que no es un número: `"N/D"`, `"-"`, `"null"`;
    - lo que está fuera del planeta, si se pasan `limits`.

    Acepta cadenas, enteros, flotantes y `Decimal` porque los tres orígenes
    difieren: el servicio SOAP entrega texto, el modelo entrega `Decimal` y un
    formulario puede entregar cualquiera de los dos.
    """
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return None

    try:
        # `str()` antes de `Decimal` para que un float como 0.1 no arrastre su
        # representación binaria a la comparación.
        number = Decimal(str(value))

    except (InvalidOperation, TypeError, ValueError):
        return None

    if not number.is_finite():
        return None

    if number == 0:
        return None

    if limits is not None:
        minimum, maximum = limits

        if number < minimum or number > maximum:
            return None

    return number


def normalize_coordinate_pair(latitude, longitude):
    """Normaliza el par y lo devuelve completo o vacío: `(lat, lon)` o `(None, None)`.

    **El par es indivisible.** Si una de las dos coordenadas no es válida, la
    otra tampoco se publica, aunque por sí sola parezca razonable. Media
    coordenada no ubica nada, y servirla invitaría a que alguien construyera un
    mapa con el valor que falta puesto a cero — que es exactamente el problema
    que este módulo evita.
    """
    normalized_latitude = normalize_coordinate(latitude, LATITUDE_RANGE)
    normalized_longitude = normalize_coordinate(longitude, LONGITUDE_RANGE)

    if normalized_latitude is None or normalized_longitude is None:
        return None, None

    return normalized_latitude, normalized_longitude


def build_gps_link(latitude, longitude):
    """Enlace de mapa para un par válido; cadena vacía si no lo es.

    Es la **única** forma legítima de construir el enlace: no se puede
    producir uno sin pasar por la validación del par. Devolver `""` en lugar de
    un enlace roto o a `0,0` es deliberado: una cadena vacía se pinta como
    «sin GPS», y un enlace inválido se pinta como un botón que lleva al lugar
    equivocado.
    """
    normalized_latitude, normalized_longitude = normalize_coordinate_pair(
        latitude,
        longitude,
    )

    if normalized_latitude is None:
        return ""

    return GPS_LINK_TEMPLATE.format(
        latitude=normalized_latitude,
        longitude=normalized_longitude,
    )


def location_payload(address):
    """Bloque de ubicación de una dirección, ya saneado.

    Punto de consumo único para cualquier capa que publique la ubicación de un
    punto de servicio —la API del técnico hoy, la ficha de ATC y el resumen del
    contrato cuando lo adopten—, de modo que las tres publiquen exactamente lo
    mismo.

    La dirección textual, la referencia y el distrito viajan siempre y tal
    cual: son el dato que permite llegar. Las coordenadas viajan solo si el par
    es válido, y `gps_link` solo si hay par.

    `gps_link` se **deriva** de las coordenadas en lugar de servirse desde la
    base de datos: el enlace almacenado pudo construirse antes de esta regla
    —sobre un `0,0`, por ejemplo— y sería la vía por la que el dato falso
    volvería a aparecer. Con coordenadas válidas el enlace se recalcula igual
    que lo haría cualquiera, así que no se pierde nada.
    """
    latitude, longitude = normalize_coordinate_pair(
        address.latitude,
        address.longitude,
    )

    return {
        "address": address.address,
        "reference": address.reference,
        "district": address.district,
        "latitude": latitude,
        "longitude": longitude,
        "gps_link": build_gps_link(latitude, longitude),
    }
