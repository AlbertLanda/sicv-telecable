"""
Vistas de API del canal del técnico.

Reparto igual que en la capa web del proyecto: el serializador transporta, la
vista orquesta y traduce a HTTP, y el dominio (`apps.accounts.services`)
decide. La vista no compara contraseñas ni consulta roles por su cuenta.
"""

from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.api.permissions import IsActiveTechnician
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

    Los rechazos de credenciales y de rol comparten la misma respuesta pública
    para no confirmar que un usuario existe ni que la contraseña ingresada era
    correcta. La causa concreta sigue diferenciada dentro del dominio mediante
    sus excepciones, pero no se expone al cliente anónimo.
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
        except (InvalidCredentials, NotATechnician):
            return Response(
                {"detail": "Credenciales inválidas."},
                status=status.HTTP_401_UNAUTHORIZED,
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

    Devuelve identidad, no datos operativos: el token identifica, no autoriza.

    Lleva `IsActiveTechnician` por decisión explícita: es un endpoint del canal
    técnico, y el token no caduca, así que sin este permiso un usuario
    desactivado o movido a otro rol después de autenticarse seguiría
    respondiendo con su token viejo. Con el permiso, rol y estado se reevalúan
    en cada petición. Ver docs/api_technician_auth.md.
    """

    permission_classes = [IsAuthenticated, IsActiveTechnician]

    def get(self, request):
        return Response(TechnicianIdentitySerializer(request.user).data)
