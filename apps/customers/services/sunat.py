"""
Consulta de DNI (RENIEC) y RUC (SUNAT) para autocompletar el registro
de clientes (Pantalla 3: "Registrar nuevo cliente").

Proveedor por defecto: Perú API (https://peruapi.com). Fue elegido
porque, a diferencia de otras opciones evaluadas (p. ej. Decolecta /
apis.net.pe), su plan gratuito incluye tanto RUC como DNI:

    GET {SUNAT_API_BASE_URL}/dni/{numero}?api_token=TOKEN
    GET {SUNAT_API_BASE_URL}/ruc/{numero}?api_token=TOKEN

A diferencia de otros proveedores vistos, la autenticación va como
parámetro de consulta (`api_token`) y no como header
"Authorization: Bearer ...". Si en el futuro se cambia de proveedor,
lo normal es que solo haya que ajustar `_get()` y el mapeo de campos
de `consultar_dni()` / `consultar_ruc()` en este archivo.

El token y la URL base se configuran por variables de entorno
(ver .env.example: SUNAT_API_TOKEN, SUNAT_API_BASE_URL,
SUNAT_API_TIMEOUT) y se leen únicamente desde settings, nunca hay
credenciales embebidas en este módulo.

IMPORTANTE (transparencia sobre la fuente de datos): como la mayoría
de proveedores "gratuitos" de este tipo en Perú, Perú API no es una
conexión oficial directa a RENIEC/SUNAT, sino que combina padrones
locales con proveedores externos como respaldo. Ver
docs/consulta_documento_externa.md para más detalle, límites del
plan gratuito y consideraciones sobre protección de datos.

Esta consulta es SIEMPRE opcional: si falla o no está configurada,
el usuario puede seguir completando el formulario manualmente. Por
eso todos los errores se traducen a DocumentLookupError con un
mensaje apto para mostrar directamente en pantalla.
"""

import requests
from django.conf import settings


class DocumentLookupError(Exception):
    """
    Error de negocio al consultar RENIEC/SUNAT.

    `status_code` se usa únicamente para decidir el código HTTP de
    la respuesta JSON del endpoint AJAX (ver views.py), no representa
    necesariamente el código devuelto por el proveedor externo.
    """

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _get_token():
    token = (getattr(settings, "SUNAT_API_TOKEN", "") or "").strip()

    if not token:
        raise DocumentLookupError(
            "La consulta automática de RENIEC/SUNAT no está configurada "
            "en este ambiente. Complete los datos manualmente.",
            status_code=503,
        )

    return token


def _get_base_url():
    return (
        getattr(settings, "SUNAT_API_BASE_URL", "")
        or "https://peruapi.com/api"
    ).rstrip("/")


def _get_timeout():
    try:
        return float(getattr(settings, "SUNAT_API_TIMEOUT", 8) or 8)
    except (TypeError, ValueError):
        return 8.0


def _get(path):
    """
    Ejecuta la petición GET al proveedor y devuelve el JSON ya
    parseado. La autenticación de Perú API va en el parámetro de
    consulta `api_token` (no en un header Authorization).
    """

    token = _get_token()
    url = f"{_get_base_url()}{path}"

    try:
        response = requests.get(
            url,
            params={"api_token": token},
            headers={"Accept": "application/json"},
            timeout=_get_timeout(),
        )
    except requests.RequestException:
        raise DocumentLookupError(
            "No fue posible conectarse al servicio de RENIEC/SUNAT. "
            "Verifique su conexión e inténtelo nuevamente.",
            status_code=502,
        )

    if response.status_code == 404:
        raise DocumentLookupError(
            "No se encontraron datos para el documento ingresado.",
            status_code=404,
        )

    if response.status_code in (401, 403):
        raise DocumentLookupError(
            "El servicio de RENIEC/SUNAT rechazó las credenciales "
            "configuradas. Contacte al administrador del sistema.",
            status_code=502,
        )

    if response.status_code == 429:
        raise DocumentLookupError(
            "Se alcanzó el límite de consultas al servicio de "
            "RENIEC/SUNAT (plan gratuito). Inténtelo nuevamente más "
            "tarde o complete los datos manualmente.",
            status_code=502,
        )

    if not response.ok:
        raise DocumentLookupError(
            "El servicio de RENIEC/SUNAT no respondió correctamente. "
            "Inténtelo nuevamente.",
            status_code=502,
        )

    try:
        payload = response.json()
    except ValueError:
        raise DocumentLookupError(
            "El servicio de RENIEC/SUNAT devolvió una respuesta "
            "inválida.",
            status_code=502,
        )

    if not isinstance(payload, dict):
        raise DocumentLookupError(
            "El servicio de RENIEC/SUNAT devolvió una respuesta "
            "inválida.",
            status_code=502,
        )

    # ---------------------------------------------------------------
    # Perú API devuelve HTTP 200 incluso para errores de negocio
    # (documento no encontrado, formato inválido, etc.) e indica el
    # resultado en el campo "code" (string, p. ej. "200") y describe
    # el error en "mensaje". Se traduce aquí a DocumentLookupError
    # para que toda la vista/JS solo tenga que manejar un tipo de
    # error.
    # ---------------------------------------------------------------

    code = str(payload.get("code") or "").strip()

    if code and code != "200":
        raise DocumentLookupError(
            (payload.get("mensaje") or "").strip()
            or "No se encontraron datos para el documento ingresado.",
            status_code=404,
        )

    return payload


def _parse_fecha_nacimiento(payload):
    """
    Intenta extraer la fecha de nacimiento del payload de RENIEC y
    normalizarla a ISO (YYYY-MM-DD).

    Perú API (y proveedores similares) no siempre incluyen este dato
    en el plan gratuito, y el nombre exacto de la clave puede variar
    según el proveedor configurado. Por eso se prueban varias claves
    conocidas y varios formatos de fecha; si ninguna coincide, se
    devuelve cadena vacía y el usuario completa la fecha manualmente
    en la Pantalla 4, tal como ya ocurre con el resto de datos
    obtenidos de este servicio opcional.
    """

    import datetime

    posibles_claves = (
        "fecha_nacimiento",
        "fechaNacimiento",
        "fecha_de_nacimiento",
        "birth_date",
    )

    valor = ""

    for clave in posibles_claves:
        valor = (payload.get(clave) or "").strip()

        if valor:
            break

    if not valor:
        return ""

    formatos_conocidos = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")

    for formato in formatos_conocidos:
        try:
            return datetime.datetime.strptime(
                valor, formato
            ).date().isoformat()
        except ValueError:
            continue

    return ""


def consultar_dni(numero):
    """
    Consulta datos personales por DNI.

    Devuelve un dict con las claves usadas por CustomerInitialForm:
    first_name, paternal_surname, maternal_surname y, cuando el
    proveedor la entrega, birth_date (ISO YYYY-MM-DD). birth_date es
    siempre opcional: si el proveedor no la incluye en el plan
    contratado, se devuelve vacía y el usuario la completa
    manualmente en la Pantalla 4 (Datos generales).
    """

    numero = (numero or "").strip()

    if not numero.isdigit() or len(numero) != 8:
        raise DocumentLookupError(
            "El DNI debe tener exactamente 8 dígitos numéricos.",
        )

    payload = _get(f"/dni/{numero}")

    nombres = (payload.get("nombres") or "").strip()
    apellido_paterno = (payload.get("apellido_paterno") or "").strip()
    apellido_materno = (payload.get("apellido_materno") or "").strip()

    if not (nombres or apellido_paterno or apellido_materno):
        raise DocumentLookupError(
            "No se encontraron datos para el DNI ingresado.",
            status_code=404,
        )

    return {
        "first_name": nombres,
        "paternal_surname": apellido_paterno,
        "maternal_surname": apellido_materno,
        "birth_date": _parse_fecha_nacimiento(payload),
    }


def consultar_ruc(numero):
    """
    Consulta información de empresa por RUC.

    Devuelve un dict con, al menos, la clave business_name (usada por
    CustomerInitialForm/CustomerRegistrationForm). Se incluyen además
    algunos datos informativos (estado, condición, dirección) por si
    se quieren mostrar en pantalla, aunque no se guardan en el modelo
    Customer.
    """

    numero = (numero or "").strip()

    if not numero.isdigit() or len(numero) != 11:
        raise DocumentLookupError(
            "El RUC debe tener exactamente 11 dígitos numéricos.",
        )

    payload = _get(f"/ruc/{numero}")

    razon_social = (payload.get("razon_social") or "").strip()

    if not razon_social:
        raise DocumentLookupError(
            "No se encontraron datos para el RUC ingresado.",
            status_code=404,
        )

    return {
        "business_name": razon_social,
        "status": (payload.get("estado") or "").strip(),
        "condition": (payload.get("condicion") or "").strip(),
        "address": (payload.get("direccion") or "").strip(),
    }


def consultar_documento(document_type, document_number):
    """
    Punto de entrada único usado por la vista AJAX.

    Solo DNI y RUC tienen consulta automática disponible (son los
    únicos documentos con un servicio público oficial en Perú). Para
    CE y Pasaporte se informa que el llenado debe ser manual.
    """

    document_type = (document_type or "").strip().upper()
    document_number = (document_number or "").strip()

    if document_type == "DNI":
        return consultar_dni(document_number)

    if document_type == "RUC":
        return consultar_ruc(document_number)

    raise DocumentLookupError(
        "La consulta automática solo está disponible para DNI y RUC. "
        "Complete los datos manualmente.",
        status_code=400,
    )
