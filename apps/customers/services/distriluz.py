"""
Consulta de información de un suministro eléctrico en Distriluz.

Se utiliza para obtener automáticamente la dirección asociada
a un número de suministro desde la Oficina Virtual de Distriluz.
"""

import re

import requests
from django.conf import settings


class SupplyLookupError(Exception):
    """
    Error controlado durante la consulta del suministro.
    """

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


DISTRIILUZ_URL = (
    "https://servicios.distriluz.com.pe/"
    "OficinaVirtual/Home/InfoSuministro"
)


def _get_timeout():
    try:
        return float(
            getattr(settings, "DISTRILUZ_TIMEOUT", 10) or 10
        )
    except (TypeError, ValueError):
        return 10.0


def _get_verification_token():
    """
    Obtiene el token antiforgery desde la página de Distriluz.
    """

    try:
        session = requests.Session()

        response = session.get(
            "https://servicios.distriluz.com.pe/"
            "OficinaVirtual/Home/MiContacto",
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/152.0.0.0 Safari/537.36"
                ),
            },
            timeout=_get_timeout(),
        )
    except requests.RequestException:
        raise SupplyLookupError(
            "No fue posible conectarse con el servicio de "
            "Distriluz. Inténtelo nuevamente.",
            status_code=502,
        )

    if not response.ok:
        raise SupplyLookupError(
            "El servicio de Distriluz no respondió correctamente.",
            status_code=502,
        )

    match = re.search(
        r'name="__RequestVerificationToken"[^>]*value="([^"]+)"',
        response.text,
    )

    if not match:
        raise SupplyLookupError(
            "No fue posible obtener el token de seguridad de "
            "Distriluz.",
            status_code=502,
        )

    return session, match.group(1)


def consultar_suministro(numero_suministro):
    """
    Consulta un número de suministro y devuelve sus datos básicos,
    incluyendo la dirección.
    """

    numero_suministro = (
        (numero_suministro or "")
        .strip()
    )

    if not numero_suministro:
        raise SupplyLookupError(
            "Ingrese un número de suministro."
        )

    if not numero_suministro.isdigit():
        raise SupplyLookupError(
            "El número de suministro debe contener solo dígitos."
        )

    session, verification_token = _get_verification_token()

    try:
        response = session.post(
            DISTRIILUZ_URL,
            data={
                "Parametros[IdNroServicio]": numero_suministro,
                "__RequestVerificationToken": verification_token,
            },
            headers={
                "Accept": (
                    "application/json, text/javascript, */*; q=0.01"
                ),
                "Content-Type": (
                    "application/x-www-form-urlencoded; charset=UTF-8"
                ),
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/152.0.0.0 Safari/537.36"
                ),
            },
            timeout=_get_timeout(),
        )
    except requests.RequestException:
        raise SupplyLookupError(
            "No fue posible consultar el suministro en Distriluz. "
            "Verifique su conexión e inténtelo nuevamente.",
            status_code=502,
        )

    if not response.ok:
        raise SupplyLookupError(
            "Distriluz no respondió correctamente a la consulta.",
            status_code=502,
        )

    try:
        payload = response.json()
    except ValueError:
        raise SupplyLookupError(
            "Distriluz devolvió una respuesta inválida.",
            status_code=502,
        )

    if not isinstance(payload, dict):
        raise SupplyLookupError(
            "Distriluz devolvió una respuesta inválida.",
            status_code=502,
        )

    if payload.get("IdError") not in (0, "0", None):
        raise SupplyLookupError(
            payload.get("Mensaje")
            or "No se encontró información para el suministro.",
            status_code=404,
        )

    datos = payload.get("Datos") or {}

    if not datos:
        raise SupplyLookupError(
            "No se encontró información para el suministro.",
            status_code=404,
        )

    direccion = (
        datos.get("Direccion")
        or ""
    ).strip()

    if not direccion:
        raise SupplyLookupError(
            "El suministro fue encontrado, pero no tiene "
            "una dirección disponible.",
            status_code=404,
        )

    return {
        "supply_number": numero_suministro,
        "address": (datos.get("Direccion") or "").strip(),
        "company_id": (datos.get("IdEmpresa") or "").strip(),
        "uunn_id": (datos.get("IdUUNN") or "").strip(),
        "sector_id": (datos.get("IdSector") or "").strip(),
        "first_name": (datos.get("Nombres") or "").strip(),
        "paternal_surname": (datos.get("APaterno") or "").strip(),
        "maternal_surname": (datos.get("AMaterno") or "").strip(),
    }