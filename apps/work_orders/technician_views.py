"""Shell web responsive del canal técnico.

La interfaz no autentica con la sesión web de Django ni replica reglas del
dominio. Solo entrega HTML/CSS/JS; toda identidad y operación se resuelve
contra la API de técnicos mediante TokenAuthentication.
"""

from django.views.generic import TemplateView


class TechnicianPortalView(TemplateView):
    """Entrada única del portal móvil del técnico."""

    template_name = "work_orders/technician/portal.html"
