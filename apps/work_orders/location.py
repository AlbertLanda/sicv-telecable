"""
Presentación de la ubicación de atención en la ficha de una orden de trabajo.

La validación de coordenadas NO vive aquí. Se reutiliza la regla única de
`apps.customers.coordinates.location_payload()`, compartida con la API del
técnico y la ficha del cliente. Este módulo únicamente adapta ese bloque a la
presentación de la OT:

- la dirección textual se muestra siempre;
- con GPS válido, Maps abre las coordenadas exactas;
- sin GPS válido, se informa «GPS no disponible» y la ficha sigue ofreciendo
  Maps mediante una búsqueda por la dirección textual;
- nunca se corrigen ni inventan coordenadas ni se modifica CustomerAddress.
"""

from urllib.parse import quote

from apps.customers.coordinates import location_payload


MAPS_SEARCH_BASE_URL = "https://www.google.com/maps/search/?api=1&query="


def resolve_location_display(address):
    """Construye el bloque de ubicación que consume la ficha de la OT."""
    if address is None:
        return {
            "text": "",
            "has_valid_gps": False,
            "maps_url": "",
            "gps_label": "GPS no disponible",
            "maps_label": "Buscar dirección en Google Maps",
        }

    payload = location_payload(address)
    text = _format_address_text(payload)
    has_valid_gps = (
        payload["latitude"] is not None
        and payload["longitude"] is not None
    )

    if has_valid_gps:
        maps_url = payload["gps_link"]
        gps_label = "GPS disponible"
        maps_label = "Abrir en Google Maps"
    else:
        # Cuando el proveedor no trae georreferencia confiable, el técnico
        # conserva una acción útil: Maps busca la dirección textual completa.
        maps_url = f"{MAPS_SEARCH_BASE_URL}{quote(text)}" if text else ""
        gps_label = "GPS no disponible"
        maps_label = "Buscar dirección en Google Maps"

    return {
        "text": text,
        "has_valid_gps": has_valid_gps,
        "maps_url": maps_url,
        "gps_label": gps_label,
        "maps_label": maps_label,
    }


def _format_address_text(payload):
    parts = [
        payload.get("address", ""),
        payload.get("reference", ""),
        payload.get("district", ""),
    ]

    return " - ".join(part for part in parts if part)
