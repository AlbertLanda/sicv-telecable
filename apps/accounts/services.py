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


def is_active_technician(user):
    """¿Este usuario es un técnico activo?

    Única definición de «técnico activo» del sistema. La consumen tanto el
    login del canal técnico (`authenticate_technician()`) como la permission
    class `IsActiveTechnician` de la API, para que la condición viva en un
    solo lugar: si mañana cambia (por ejemplo, exigir sede asignada), cambia
    aquí y los dos caminos quedan alineados sin tocarlos.

    Acepta cualquier objeto usuario, incluido `AnonymousUser`, y devuelve
    False para él: no asume que quien llama ya validó la autenticación.
    """
    return bool(
        getattr(user, "is_authenticated", False)
        and user.is_active
        and user.role == User.Role.TECHNICIAN
    )


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

    # La condición de «técnico activo» no se reescribe aquí: se delega en el
    # predicado, que es la misma regla que aplica la API en cada petición.
    # El estado de la cuenta se comprobó arriba porque pertenece a la validez
    # de la credencial (401), mientras que el rol es una cuestión de
    # autorización (403); son rechazos distintos y no deben confundirse.
    if not is_active_technician(user):
        raise NotATechnician

    return user
