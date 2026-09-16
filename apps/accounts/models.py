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
    # ATC necesita poder completar el ciclo que realmente realiza en oficina:
    # registrar y actualizar abonados, mantener sus direcciones, suscripciones
    # y contratos, emitir/consultar OT y gestionar su programación. También
    # necesita consultar la situación económica del abonado para responder en
    # ventanilla o por teléfono: deuda, historial de pagos y comprobantes.
    # Esos permisos son solo de lectura; registrar/anular pagos, crear cargos o
    # conceder compromisos siguen requiriendo permisos explícitos.
    # La asignación de técnicos NO forma parte de este conjunto: los técnicos
    # se autoasignan/toman las órdenes desde su canal propio.
    #
    # NOC, en cambio, consulta la ficha del abonado como contexto para soporte,
    # pero no administra sus datos comerciales. Sus permisos base se limitan
    # al flujo operativo de incidencias.
    ROLE_BASELINE_PERMISSIONS = {
        Role.ATC: frozenset(
            {
                "customers.add_customer",
                "customers.change_customer",
                "customers.add_customeraddress",
                "services.add_subscription",
                "contracts.add_contract",
                "work_orders.add_workorder",
                "work_orders.view_workorder",
                "work_orders.view_incident",
                "work_orders.schedule_workorder",
                "work_orders.cancel_workorder",
                "payments.view_charge",
                "payments.view_payment",
                "payments.view_receipt",
            }
        ),

        Role.NOC: frozenset(
            {
                "work_orders.view_workorder",
                "work_orders.view_incident",
                "work_orders.start_incident",
                "work_orders.close_incident",
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

    # Dato de contacto, no de identidad: a diferencia de username/nombres,
    # el propio usuario sí puede mantenerlo actualizado desde su perfil.
    phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Teléfono"
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
