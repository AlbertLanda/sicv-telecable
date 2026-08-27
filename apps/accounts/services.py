"""
Servicios de dominio de cuentas.

La regla «solo un técnico activo puede autenticarse contra la API» es de
dominio, no de transporte: vive aquí y no en la vista, igual que el resto
del sistema (ver `apps/work_orders/services.py`). Así la misma regla puede
reutilizarse desde otro canal sin duplicar la validación.
"""

from django.contrib.auth import authenticate

from apps.accounts.models import User


class AuthenticationError(Exception):
    """Base de los rechazos de autenticación del canal técnico."""


class InvalidCredentials(AuthenticationError):
    """Usuario inexistente, contraseña incorrecta o cuenta desactivada.

    Los tres casos comparten una sola excepción a propósito: la respuesta no
    debe permitir distinguir «no existe» de «existe pero está desactivado» ni
    de «la contraseña está mal».
    """


class NotATechnician(AuthenticationError):
    """Credenciales correctas, pero el usuario no tiene rol técnico."""


def authenticate_technician(username, password, request=None):
    """Autentica a un técnico activo y devuelve el `User`.

    No reutiliza el login genérico de Django tal cual: sobre la autenticación
    estándar añade la exigencia de rol técnico. Un usuario ATC, supervisor o
    almacén con contraseña correcta es rechazado.

    Levanta `InvalidCredentials` o `NotATechnician`. Nunca devuelve, registra
    ni propaga la contraseña recibida.
    """
    user = authenticate(request=request, username=username, password=password)

    # `authenticate()` con el backend estándar ya devuelve None si la cuenta
    # está desactivada. La comprobación explícita deja la regla a la vista y
    # la mantiene si en el futuro se agrega otro backend.
    if user is None or not user.is_active:
        raise InvalidCredentials

    if user.role != User.Role.TECHNICIAN:
        raise NotATechnician

    return user
