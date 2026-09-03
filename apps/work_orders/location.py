"""
Presentación de la ubicación de atención en la ficha de una orden de trabajo.

Regla del negocio (ficha OT, sprint FTTH):

- La dirección textual se muestra siempre; nunca depende del GPS.
- Si existen coordenadas válidas se ofrece "Abrir en Google Maps" apuntando
  a esas coordenadas.
- Si las coordenadas vienen vacías, o son 0 / 0.0000000 en cualquiera de los
  dos ejes, se tratan como inválidas: se muestra "GPS no disponible" y el
  enlace de Maps usa la dirección textual como referencia de búsqueda.
- Esta función NUNCA escribe ni corrige `CustomerAddress`: solo decide cómo
  mostrar lo que ya existe. No sobrescribe ni inventa coordenadas.

Vive en `apps.work_orders` y no en `apps.customers` porque la decisión de
presentación es propia de la ficha OT, no del modelo de dirección del
cliente -mismo criterio que ya siguen los serializadores de la API del
técnico (`WorkOrderAddressSerializer`), que tampoco agregan propiedades a
`CustomerAddress`.
"""

from decimal import Decimal
from urllib.parse import quote

ZERO = Decimal("0")

MAPS_SEARCH_BASE_URL = "https://www.google.com/maps/search/?api=1&query="


def resolve_location_display(address):
    """
    Construye la información de ubicación que la ficha necesita mostrar.

    `address` es una `CustomerAddress` (o `None`, contemplado por si la
    suscripción llegara sin dirección resuelta). Devuelve un diccionario:

    - `text`: dirección textual siempre presente (calle, referencia,
      distrito), lista para mostrarse tal cual.
    - `has_valid_gps`: si hay coordenadas utilizables.
    - `maps_url`: enlace de Google Maps. Por coordenadas cuando son válidas;
      por búsqueda de la dirección textual en caso contrario.
    - `gps_label`: texto fijo para la interfaz ("Abrir en Google Maps" o
      "GPS no disponible"), para no repetir la decisión en la plantilla.
    """
    if address is None:
        return {
            "text": "",
            "has_valid_gps": False,
            "maps_url": "",
            "gps_label": "GPS no disponible",
        }

    text = _format_address_text(address)

    latitude = address.latitude
    longitude = address.longitude

    has_valid_gps = (
        latitude is not None
        and longitude is not None
        and (latitude != ZERO or longitude != ZERO)
    )

    if has_valid_gps:
        maps_url = f"{MAPS_SEARCH_BASE_URL}{latitude},{longitude}"
        gps_label = "Abrir en Google Maps"
    else:
        # Sin coordenadas confiables: la dirección textual es la única
        # referencia, y es la que se usa como término de búsqueda en Maps.
        maps_url = f"{MAPS_SEARCH_BASE_URL}{quote(text)}" if text else ""
        gps_label = "GPS no disponible"

    return {
        "text": text,
        "has_valid_gps": has_valid_gps,
        "maps_url": maps_url,
        "gps_label": gps_label,
    }


def _format_address_text(address):
    parts = [address.address, address.reference, address.district]

    return " - ".join(part for part in parts if part)
