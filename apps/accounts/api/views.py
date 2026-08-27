"""
Vistas de API del canal del técnico.

Reparto igual que en la capa web del proyecto: el serializador transporta, la
vista orquesta y traduce a HTTP, y el dominio (`apps.accounts.services`)
decide. La vista no compara contraseñas ni consulta roles por su cuenta.
"""

from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.serializers import (
    TechnicianIdentitySerializer,
    TechnicianLoginSerializer,
)
from apps.accounts.services import (
    InvalidCredentials,
    NotATechnician,
    authenticate_technician,
)


class TechnicianLoginView(APIView):
    """POST /api/technicians/login/ — entrega un token al técnico activo.

    Único endpoint abierto de la API: no puede exigir un token para emitirlo.
    La apertura es explícita aquí, no en los ajustes globales, que siguen
    cerrados con `IsAuthenticated`.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TechnicianLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user = authenticate_technician(
                username=serializer.validated_data["username"],
                password=serializer.validated_data["password"],
                request=request,
            )
        except InvalidCredentials:
            # Mensaje único para credenciales malas, usuario inexistente y
            # cuenta desactivada: la respuesta no debe servir para descubrir
            # qué usuarios existen.
            return Response(
                {"detail": "Credenciales inválidas."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except NotATechnician:
            return Response(
                {"detail": "El usuario no tiene rol técnico."},
                status=status.HTTP_403_FORBIDDEN,
            )

        token, _ = Token.objects.get_or_create(user=user)

        return Response(
            {
                "token": token.key,
                "technician": TechnicianIdentitySerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class TechnicianMeView(APIView):
    """GET /api/technicians/me/ — identidad del técnico autenticado.

    Endpoint protegido de referencia: hereda `TokenAuthentication` +
    `IsAuthenticated` de los ajustes globales, sin declarar nada. Devuelve
    identidad, no datos operativos: el token identifica, no autoriza.
    """

    def get(self, request):
        return Response(TechnicianIdentitySerializer(request.user).data)
