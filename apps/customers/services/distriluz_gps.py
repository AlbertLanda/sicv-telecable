"""
Consulta del servicio móvil de Distriluz (ConsultaGeneral).

Este cliente se usa únicamente como adaptador de ubicación del domicilio:
recibe un código de suministro eléctrico y normaliza dirección + coordenadas.
No expone ni persiste nombre/documento del titular del suministro porque esos
datos no son necesarios para el flujo comercial de Telecable.

El servicio observado es SOAP/ASMX y legacy. Se mantiene aislado en este
módulo para que un cambio de proveedor no obligue a modificar formularios,
modelos ni la API del técnico.
"""

import xml.etree.ElementTree as ET

import requests
from django.conf import settings

from apps.customers.coordinates import build_gps_link, normalize_coordinate_pair

from .distriluz import SupplyLookupError

DEFAULT_DISTRILUZ_MOVIL_URL = (
    "http://oficinavirtual.distriluz.com.pe:62150"
    "/wsconsultamovil/servicioconsultas.asmx"
)
DISTRILUZ_MOVIL_NAMESPACE = "http://www.distriluz.com.pe/"


def _get_url():
    return (
        getattr(settings, "DISTRILUZ_GPS_URL", DEFAULT_DISTRILUZ_MOVIL_URL)
        or DEFAULT_DISTRILUZ_MOVIL_URL
    )


def _get_timeout():
    try:
        return float(
            getattr(settings, "DISTRILUZ_GPS_TIMEOUT", 12) or 12
        )
    except (TypeError, ValueError):
        return 12.0


def _build_soap_envelope(supply_code):
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body>"
        '<ConsultaGeneral xmlns="http://www.distriluz.com.pe/">'
        f"<idNroServicio>{supply_code}</idNroServicio>"
        "</ConsultaGeneral>"
        "</soap:Body>"
        "</soap:Envelope>"
    )


def _parse_response(xml_text):
    """Reconstruye el arreglo plano clave/valor devuelto por el SOAP."""
    root = ET.fromstring(xml_text)
    namespaces = {"ns": DISTRILUZ_MOVIL_NAMESPACE}

    result = root.find(".//ns:ConsultaGeneralResult", namespaces)
    if result is None:
        return {}

    strings = [
        node.text for node in result.findall("ns:string", namespaces)
    ]

    data = {}
    for index in range(0, len(strings), 2):
        key = (strings[index] or "").strip().lower()
        value = strings[index + 1] if index + 1 < len(strings) else ""

        if key:
            data[key] = (value or "").strip()

    return data


def consultar_suministro_gps(supply_code):
    """Obtiene ubicación del domicilio asociado a un suministro eléctrico.

    Devuelve únicamente los datos que el SICV necesita para localizar el
    domicilio y que ATC pueda confirmarlos antes de guardarlos:

    - supply_code
    - address
    - district / province / department
    - latitude / longitude
    - gps_link

    Las coordenadas pasan por la regla única de `apps.customers.coordinates`.
    El centinela 0 / 0.0000000, un par incompleto, un valor no numérico o una
    coordenada fuera de rango se convierten en `None`. De esta forma el dato
    inválido ya no entra a CustomerAddress ni genera un enlace falso a 0,0.
    """
    supply_code = (supply_code or "").strip()

    if not supply_code:
        raise SupplyLookupError(
            "Ingrese un código de suministro."
        )

    if not supply_code.isdigit():
        raise SupplyLookupError(
            "El código de suministro debe contener solo dígitos."
        )

    soap_envelope = _build_soap_envelope(supply_code)

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f"{DISTRILUZ_MOVIL_NAMESPACE}ConsultaGeneral",
    }

    try:
        response = requests.post(
            _get_url(),
            data=soap_envelope.encode("utf-8"),
            headers=headers,
            timeout=_get_timeout(),
        )
    except requests.RequestException as exc:
        raise SupplyLookupError(
            "No fue posible consultar el suministro en el servicio de "
            "Distriluz. Inténtelo nuevamente.",
            status_code=502,
        ) from exc

    if not response.ok:
        raise SupplyLookupError(
            "Distriluz no respondió correctamente a la consulta.",
            status_code=502,
        )

    try:
        data = _parse_response(response.text)
    except ET.ParseError as exc:
        raise SupplyLookupError(
            "Distriluz devolvió una respuesta inválida.",
            status_code=502,
        ) from exc

    address = data.get("direccion", "")

    if not address:
        raise SupplyLookupError(
            "No se encontró información para el suministro.",
            status_code=404,
        )

    district = (
        data.get("direccioncomplementaria")
        or data.get("distrito")
        or ""
    )

    latitude, longitude = normalize_coordinate_pair(
        data.get("gpsy") or data.get("latitud"),
        data.get("gpsx") or data.get("longitud"),
    )
    gps_link = build_gps_link(latitude, longitude)

    return {
        "supply_code": supply_code,
        "address": address,
        "district": district,
        "province": data.get("provincia", ""),
        "department": data.get("departamento", ""),
        "latitude": latitude,
        "longitude": longitude,
        "gps_link": gps_link,
    }
