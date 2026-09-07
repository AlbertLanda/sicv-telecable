"""Compatibilidad controlada para endpoints web retirados.

La operación de asignación dejó de pertenecer al canal web: una OT queda
PENDING y sin técnico hasta que un técnico la toma desde la API técnica.

Se conserva temporalmente el nombre de URL `work_orders:assign` únicamente
para que enlaces históricos no provoquen un error de resolución. El endpoint
no consulta la OT, no acepta datos de técnico y no muta el dominio.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class RetiredWebAssignmentView(LoginRequiredMixin, TemplateView):
    """Informa que la asignación manual web fue retirada.

    Responde 410 Gone para dejar claro que el recurso operativo ya no existe.
    No se busca la orden por `pk`: así un enlace antiguo tampoco sirve para
    enumerar órdenes existentes.
    """

    template_name = "work_orders/work_order_assign.html"

    def render_to_response(self, context, **response_kwargs):
        response_kwargs.setdefault("status", 410)
        return super().render_to_response(context, **response_kwargs)
