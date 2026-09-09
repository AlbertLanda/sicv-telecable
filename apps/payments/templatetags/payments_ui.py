"""
Componentes de presentación de la cuenta del abonado.

El resumen de deuda aparece en la ficha del cliente y en las tres pantallas de
cobranza. Se resuelve aquí, en un solo sitio, para que la ficha y la pantalla
de deuda no acaben diciendo cifras distintas sobre el mismo abonado.
"""

from django import template

from ..services import customer_debt

register = template.Library()


@register.inclusion_tag("payments/_debt_summary.html")
def account_debt_summary(customer, debt=None):
    """
    Cifras de la cuenta: deuda, vencido, cargos abiertos y el más antiguo.

    `debt` se acepta ya calculado porque las pantallas de cobranza lo tienen en
    su contexto; recalcularlo aquí volvería a leer todos los cargos abiertos
    del abonado en cada pintada. La ficha del cliente no lo trae, y ahí sí se
    calcula.
    """

    return {"debt": debt if debt is not None else customer_debt(customer)}
