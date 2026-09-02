"""Serializadores del canal de API del técnico."""

from rest_framework import serializers


class TechnicianLoginSerializer(serializers.Serializer):
    """Solo transporta las credenciales; no autentica ni decide nada.

    `write_only` en ambos campos garantiza que ni el usuario ni la contraseña
    puedan volver en la respuesta del serializador.
    """

    username = serializers.CharField(
        write_only=True,
        label="Usuario",
    )

    password = serializers.CharField(
        write_only=True,
        label="Contraseña",
        # La contraseña se compara tal cual: recortar espacios cambiaría el
        # valor que el usuario escribió.
        trim_whitespace=False,
        style={"input_type": "password"},
    )


class TechnicianIdentitySerializer(serializers.Serializer):
    """Identidad mínima del técnico autenticado.

    Es solo identificación: el token no otorga permisos funcionales, así que
    aquí no se exponen ni permisos ni datos operativos.
    """

    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    full_name = serializers.SerializerMethodField()
    role = serializers.CharField(read_only=True)
    branch_id = serializers.IntegerField(read_only=True, allow_null=True)
    branch_name = serializers.SerializerMethodField()

    def get_full_name(self, user):
        return user.get_full_name()

    def get_branch_name(self, user):
        return user.branch.name if user.branch_id else None
