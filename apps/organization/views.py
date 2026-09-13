from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from apps.organization.context_processors import (
    ACTIVE_BRANCH_SESSION_KEY,
    ACTIVE_OFFICE_SESSION_KEY,
    get_active_branch,
)
from apps.organization.models import Branch, Office


# Adónde se cae al cambiar de sede o de oficina.
#
# Siempre al buscador, nunca de vuelta a la pantalla anterior. Cambiar el
# ámbito desde el que se trabaja deja atrás lo que se estaba mirando: un
# abonado de Jauja no se sigue consultando porque la barra diga ahora Oroya,
# y una pantalla de cobro con las series de una ventanilla deja de valer en
# cuanto se elige otra.
#
# Antes se volvía al `next` que el formulario traía, así que el operador
# seguía viendo la misma ficha con la barra diciendo otra cosa. La pantalla
# no mentía en un rincón: mentía entera, y no había nada que lo delatara.
DESTINO_TRAS_CAMBIAR = "customers:search"


@require_POST
@login_required
def set_active_branch(request):
    """
    Cambia la sede desde la que se consulta, sin tocar la asignación del
    usuario.

    Solo POST: cambiar el ámbito de consulta modifica estado de la sesión,
    y un GET no debería tener ese efecto. La sede llega por id y se resuelve
    contra las sedes activas, así que un id inventado no entra en sesión.
    """
    branch = get_object_or_404(
        Branch,
        pk=request.POST.get("branch"),
        is_active=True,
    )

    request.session[ACTIVE_BRANCH_SESSION_KEY] = branch.pk

    # La oficina elegida pertenecía a la sede anterior, así que deja de
    # aplicar. Se descarta aquí en vez de arrastrar una oficina de otra
    # ciudad hasta que alguien la note.
    request.session.pop(ACTIVE_OFFICE_SESSION_KEY, None)

    # Y el abonado que se estaba consultando también. Es del padrón de la
    # sede anterior: dejarlo elegido haría que las entradas de cuenta del
    # menú siguieran abriendo a alguien de Jauja con la barra en Oroya.
    request.session.pop("selected_customer_id", None)

    return redirect(DESTINO_TRAS_CAMBIAR)


@require_POST
@login_required
def set_active_office(request):
    """
    Cambia la oficina desde la que se atiende.

    La oficina decide de qué talonarios se emite, así que cambiarla cambia
    lo que la pantalla de cobro puede ofrecer: se vuelve al buscador en vez
    de dejar delante un formulario armado con las series de otra ventanilla.

    La oficina se resuelve contra la sede activa, no contra todas: elegir
    por id una oficina de otra sede no entra en sesión.
    """
    office = get_object_or_404(
        Office,
        pk=request.POST.get("office"),
        branch=get_active_branch(request),
        is_active=True,
    )

    request.session[ACTIVE_OFFICE_SESSION_KEY] = office.pk

    # El abonado no se suelta: sigue siendo del padrón de esta sede, que no
    # ha cambiado. Lo que deja de valer es la pantalla que se estaba viendo,
    # y de eso se encarga volver al buscador.
    return redirect(DESTINO_TRAS_CAMBIAR)
