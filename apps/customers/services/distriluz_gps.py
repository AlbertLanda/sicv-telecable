"""
Consulta del servicio movil de Distriluz (ConsultaGeneral).

A diferencia de InfoSuministro (services/distriluz.py), que solo
entrega la direccion asociada a un numero de suministro, este
servicio SOAP del sistema de consulta movil de Distriluz devuelve en
una sola llamada: direccion, distrito y coordenadas GPS -- sin
necesidad de geocodificar la direccion con un servicio externo
(Nominatim/OpenStreetMap).

Se reutiliza SupplyLookupError (definida en services/distriluz.py)
para que las vistas puedan seguir capturando un unico tipo de
excepcion sin importar qué servicio de Distriluz se haya usado.
"""

import xml.etree.ElementTree as ET

import requests
from django.conf import settings

from .distriluz import SupplyLookupError

DISTRILUZ_MOVIL_URL = (
    "http://oficinavirtual.distriluz.com.pe:62150"
    "/wsconsultamovil/servicioconsultas.asmx"
)

DISTRILUZ_MOVIL_NAMESPACE = "http://www.distriluz.com.pe/"


def _get_timeout():
    try:
        return float(
            getattr(settings, "DISTRILUZ_GPS_TIMEOUT", 12) or 12
        )
    except (TypeError, ValueError):
        return 12.0


def _build_soap_envelope(numero_suministro):
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xsd="http://www.w3.org/2001/XMLSchema" '
        'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body>"
        '<ConsultaGeneral xmlns="http://www.distriluz.com.pe/">'
        f"<idNroServicio>{numero_suministro}</idNroServicio>"
        "</ConsultaGeneral>"
        "</soap:Body>"
        "</soap:Envelope>"
    )


def _parse_response(xml_text):
    """
    El servicio devuelve un arreglo plano de <string> con pares
    clave/valor alternados (no un objeto con nombres de campo), por
    lo que se reconstruye un diccionario dinamico en vez de indexar
    por posicion fija -- mas tolerante si Distriluz cambia el orden
    de los campos.
    """

    root = ET.fromstring(xml_text)
    namespaces = {"ns": DISTRILUZ_MOVIL_NAMESPACE}

    result = root.find(".//ns:ConsultaGeneralResult", namespaces)
    if result is None:
        return {}

    strings = [
        nodo.text for nodo in result.findall("ns:string", namespaces)
    ]

    datos = {}
    for i in range(0, len(strings), 2):
        clave = (strings[i] or "").strip().lower()
        valor = strings[i + 1] if i + 1 < len(strings) else ""
        datos[clave] = (valor or "").strip()

    return datos


def consultar_suministro_gps(numero_suministro):
    """
    Consulta el servicio movil de Distriluz (ConsultaGeneral) para
    un numero de suministro y devuelve:

    - address (direccion)
    - district (distrito)
    - province / department
    - latitude / longitude
    - gps_link (enlace de Google Maps armado con las coordenadas)

    Lanza SupplyLookupError ante cualquier fallo controlado (numero
    invalido, sin conexion, respuesta invalida o suministro no
    encontrado), igual que consultar_suministro() en distriluz.py.
    """

    numero_suministro = (numero_suministro or "").strip()

    if not numero_suministro:
        raise SupplyLookupError(
            "Ingrese un numero de suministro."
        )

    if not numero_suministro.isdigit():
        raise SupplyLookupError(
            "El numero de suministro debe contener solo digitos."
        )

    soap_envelope = _build_soap_envelope(numero_suministro)

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": f"{DISTRILUZ_MOVIL_NAMESPACE}ConsultaGeneral",
    }

    try:
        response = requests.post(
            DISTRILUZ_MOVIL_URL,
            data=soap_envelope.encode("utf-8"),
            headers=headers,
            timeout=_get_timeout(),
        )
    except requests.RequestException:
        raise SupplyLookupError(
            "No fue posible consultar el suministro en el servicio "
            "de Distriluz. Verifique su conexion e intentelo "
            "nuevamente.",
            status_code=502,
        )

    if not response.ok:
        raise SupplyLookupError(
            "Distriluz no respondio correctamente a la consulta.",
            status_code=502,
        )

    try:
        datos = _parse_response(response.text)
    except ET.ParseError:
        raise SupplyLookupError(
            "Distriluz devolvio una respuesta invalida.",
            status_code=502,
        )

    direccion = datos.get("direccion", "")

    if not direccion:
        raise SupplyLookupError(
            "No se encontro informacion para el suministro.",
            status_code=404,
        )

    distrito = (
        datos.get("direccioncomplementaria")
        or datos.get("distrito")
        or ""
    )

    latitud = datos.get("gpsy") or datos.get("latitud") or ""
    longitud = datos.get("gpsx") or datos.get("longitud") or ""

    gps_link = ""
    if latitud and longitud:
        gps_link = (
            "https://www.google.com/maps/search/?api=1"
            f"&query={latitud},{longitud}"
        )

    return {
        "supply_number": numero_suministro,
        "address": direccion,
        "district": distrito,
        "province": datos.get("provincia", ""),
        "department": datos.get("departamento", ""),
        "latitude": latitud,
        "longitude": longitud,
        "gps_link": gps_link,
        "titular_name": datos.get("nombre", ""),
        "document_number": datos.get("documento", ""),
    }