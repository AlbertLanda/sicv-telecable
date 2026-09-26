from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.organization.models import Branch, Office


class User(AbstractUser):

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrador"
        ATC = "ATC", "Atención al Cliente"
        SALES = "SALES", "Ventas"
        NOC = "NOC", "NOC"
        TECHNICIAN = "TECHNICIAN", "Técnico"
        WAREHOUSE = "WAREHOUSE", "Almacén"
        SUPERVISOR = "SUPERVISOR", "Supervisor"
        RETENTION = "RETENTION", "Retenciones"
        ACCOUNTING = "ACCOUNTING", "Contabilidad"

    # Capacidades mínimas que nacen del rol operativo y no dependen de que
    # un administrador haya marcado permisos uno por uno en Django Admin.
    #
    # Administrador gestiona el personal operativo desde el SICV. Usa los
    # permisos estándar de Django sobre User (ver/agregar/cambiar), pero no el
    # permiso de borrado: las cuentas se desactivan para conservar trazabilidad.
    # Una cuenta con is_superuser=True queda por encima de este rol y conserva
    # todos los permisos del sistema.
    #
    # ATC necesita poder completar el ciclo que realmente realiza en oficina:
    # registrar y actualizar abonados, mantener sus direcciones, suscripciones
    # y contratos, emitir/consultar OT y gestionar su programación. También
    # necesita consultar la situación económica del abonado y registrar cobros
    # desde una oficina autorizada. Crear cargos, anular pagos y conceder
    # compromisos siguen requiriendo permisos explícitos.
    # La asignación de técnicos NO forma parte de este conjunto: los técnicos
    # se autoasignan/toman las órdenes desde su canal propio.
    #
    # NOC consulta la ficha del abonado como contexto para soporte, pero no
    # administra sus datos comerciales. Sus permisos base se limitan al flujo
    # operativo de incidencias.
    ROLE_BASELINE_PERMISSIONS = {
        Role.ADMIN: frozenset(
            {
                "accounts.view_user",
                "accounts.add_user",
                "accounts.change_user",
                "customers.discard_incomplete_registration",
                "services.view_subscription",
            }
        ),
        Role.ATC: frozenset(
            {
                "customers.add_customer",
                "customers.change_customer",
                "customers.add_customeraddress",
                "customers.discard_incomplete_registration",
                "services.add_subscription",
                "contracts.add_contract",
                "work_orders.add_workorder",
                "work_orders.view_workorder",
                "work_orders.view_incident",
                "work_orders.schedule_workorder",
                "work_orders.cancel_workorder",
                "work_orders.withdraw_installation",
                "work_orders.create_outsideplant",
                "work_orders.view_outsideplant",
                "payments.view_charge",
                "payments.view_payment",
                "payments.view_receipt",
                "payments.add_payment",
            }
        ),
        Role.NOC: frozenset(
            {
                "work_orders.view_workorder",
                "work_orders.view_incident",
                "work_orders.start_incident",
                "work_orders.close_incident",
                "work_orders.create_outsideplant",
                "work_orders.view_outsideplant",
            }
        ),
    }

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.ATC,
        verbose_name="Rol"
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
        verbose_name="Sede"
    )

    office = models.ForeignKey(
        Office,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
        verbose_name="Oficina"
    )

    # Oficinas físicas en las que el administrador autoriza al usuario a
    # registrar cobros. Para ATC esta lista controla qué ventanillas aparecen
    # en la barra superior. Los depósitos no se asignan aquí: son medios
    # compartidos de la sede y se habilitan automáticamente.
    allowed_offices = models.ManyToManyField(
        Office,
        related_name="authorized_users",
        blank=True,
        verbose_name="Oficinas habilitadas para cobro",
    )

    # Dato de contacto, no de identidad: a diferencia de username/nombres,
    # el propio usuario sí puede mantenerlo actualizado desde su perfil.
    phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Teléfono"
    )

    is_salesperson = models.BooleanField(
        default=False,
        verbose_name="Participa como vendedor",
        help_text=(
            "Permite atribuirle ventas sin cambiar su rol operativo. "
            "Un administrador o ATC puede vender y seguir conservando su rol."
        ),
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def has_perm(self, perm, obj=None):
        """Aplica permisos explícitos de Django más la matriz base del rol.

        La matriz no reemplaza ``user_permissions`` ni grupos: únicamente
        garantiza el mínimo operativo de cada rol. Los permisos adicionales
        siguen pudiendo concederse por los mecanismos estándar de Django.
        """
        if not self.is_active:
            return False

        if self.is_superuser:
            return True

        if perm in self.ROLE_BASELINE_PERMISSIONS.get(self.role, frozenset()):
            return True

        return super().has_perm(perm, obj=obj)

    def __str__(self):
        return self.get_full_name() or self.username
