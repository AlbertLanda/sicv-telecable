"""
Fachada para la consulta automática de documentos.

Las vistas y formularios del SICV consumen únicamente este módulo.
El proveedor externo puede cambiar sin afectar el flujo comercial.
"""

from .jsonpe import (
    JsonPeError,
    consultar_dni as jsonpe_consultar_dni,
    consultar_ruc as jsonpe_consultar_ruc,
)


class DocumentLookupError(Exception):
    """
    Error de negocio expuesto hacia la capa web.
    """

    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _execute(provider_function, document_number):
    try:
        return provider_function(document_number)

    except JsonPeError as exc:
        raise DocumentLookupError(
            exc.message,
            status_code=exc.status_code,
        ) from exc


def consultar_documento(document_type, document_number):
    """
    Punto de entrada único para consultar documentos.

    Actualmente:
    - DNI -> JSON.pe
    - RUC -> JSON.pe
    - CE / Pasaporte -> ingreso manual
    """

    document_type = (document_type or "").strip().upper()
    document_number = (document_number or "").strip()

    if document_type == "DNI":
        return _execute(
            jsonpe_consultar_dni,
            document_number,
        )

    if document_type == "RUC":
        return _execute(
            jsonpe_consultar_ruc,
            document_number,
        )

    raise DocumentLookupError(
        "La consulta automática solo está disponible para DNI y RUC. "
        "Complete los datos manualmente.",
        status_code=400,
    )