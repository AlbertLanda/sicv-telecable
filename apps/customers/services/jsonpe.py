import requests

from django.conf import settings


class JsonPeError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _get_token():
    token = (
        getattr(settings, "JSONPE_API_TOKEN", "")
        or ""
    ).strip()

    if not token:
        raise JsonPeError(
            "La consulta automática de DNI/RUC no está configurada. "
            "Complete los datos manualmente.",
            status_code=503,
        )

    return token


def _get_base_url():
    return (
        getattr(settings, "JSONPE_API_BASE_URL", "")
        or "https://api.json.pe/api"
    ).rstrip("/")


def _get_timeout():
    try:
        return float(
            getattr(settings, "JSONPE_API_TIMEOUT", 8)
            or 8
        )
    except (TypeError, ValueError):
        return 8.0


def _post(endpoint, payload):
    url = f"{_get_base_url()}/{endpoint}"

    try:
        response = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {_get_token()}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=_get_timeout(),
        )

    except requests.RequestException as exc:
        raise JsonPeError(
            "No fue posible conectarse al servicio de consulta "
            "de DNI/RUC. Complete los datos manualmente o "
            "inténtelo nuevamente.",
            status_code=502,
        ) from exc

    if response.status_code in (401, 403):
        raise JsonPeError(
            "El servicio de consulta rechazó las credenciales "
            "configuradas. Contacte al administrador.",
            status_code=502,
        )

    if response.status_code == 429:
        raise JsonPeError(
            "Se alcanzó el límite de consultas disponible. "
            "Complete los datos manualmente o inténtelo más tarde.",
            status_code=502,
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise JsonPeError(
            "El servicio de consulta devolvió una respuesta inválida.",
            status_code=502,
        ) from exc

    if not isinstance(data, dict):
        raise JsonPeError(
            "El servicio de consulta devolvió una respuesta inválida.",
            status_code=502,
        )

    if not response.ok or not data.get("success"):
        message = (
            data.get("message")
            or "No se encontraron datos para el documento ingresado."
        )

        status_code = (
            404
            if response.status_code in (400, 404)
            else 502
        )

        raise JsonPeError(
            message,
            status_code=status_code,
        )

    payload_data = data.get("data")

    if not isinstance(payload_data, dict):
        raise JsonPeError(
            "El servicio de consulta devolvió datos inválidos.",
            status_code=502,
        )

    return payload_data


def consultar_dni(numero):
    numero = (numero or "").strip()

    if not numero.isdigit() or len(numero) != 8:
        raise JsonPeError(
            "El DNI debe tener exactamente 8 dígitos numéricos."
        )

    data = _post(
        "dni",
        {"dni": numero},
    )

    nombres = (data.get("nombres") or "").strip()
    paterno = (
        data.get("apellido_paterno")
        or ""
    ).strip()
    materno = (
        data.get("apellido_materno")
        or ""
    ).strip()

    if not (nombres or paterno or materno):
        raise JsonPeError(
            "No se encontraron datos para el DNI ingresado.",
            status_code=404,
        )

    return {
        "first_name": nombres,
        "paternal_surname": paterno,
        "maternal_surname": materno,
    }


def consultar_ruc(numero):
    numero = (numero or "").strip()

    if not numero.isdigit() or len(numero) != 11:
        raise JsonPeError(
            "El RUC debe tener exactamente 11 dígitos numéricos."
        )

    data = _post(
        "ruc",
        {"ruc": numero},
    )

    business_name = (
        data.get("nombre_o_razon_social")
        or ""
    ).strip()

    if not business_name:
        raise JsonPeError(
            "No se encontraron datos para el RUC ingresado.",
            status_code=404,
        )

    return {
        "business_name": business_name,
        "status": (data.get("estado") or "").strip(),
        "condition": (data.get("condicion") or "").strip(),
        "address": (data.get("direccion") or "").strip(),
    }