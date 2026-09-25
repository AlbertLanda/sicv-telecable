"""Qué archivo se acepta como evidencia de una orden.

La misma regla sirve al portal del técnico y a los formularios web del
operador: una foto que el portal rechaza no puede entrar por la ventanilla.
"""

from pathlib import Path

from django.core.exceptions import ValidationError


MAX_EVIDENCE_SIZE = 10 * 1024 * 1024
ALLOWED_EVIDENCE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
}
ALLOWED_EVIDENCE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


def validate_evidence_file(file):
    if file.size > MAX_EVIDENCE_SIZE:
        raise ValidationError("La evidencia no puede superar 10 MB.")

    extension = Path(file.name or "").suffix.lower()
    content_type = getattr(file, "content_type", "")

    if extension not in ALLOWED_EVIDENCE_EXTENSIONS:
        raise ValidationError(
            "Formato no permitido. Use JPG, PNG, WEBP o PDF."
        )
    if content_type and content_type not in ALLOWED_EVIDENCE_CONTENT_TYPES:
        raise ValidationError("El tipo de archivo no está permitido.")

    return file
