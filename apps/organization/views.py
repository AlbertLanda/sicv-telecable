from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.organization.context_processors import (
    ACTIVE_BRANCH_SESSION_KEY,
    ACTIVE_OFFICE_SESSION_KEY,
    get_active_branch,
)
from apps.organization.models import Branch, Office


def _back_to(request):
    """
    Vuelve a la pantalla desde la que se cambió, para no interrumpir lo que
    el operador estaba haciendo.

    El destino se valida contra el propio host: un `next` apuntando a otro
    dominio se descarta y se cae a la búsqueda, de modo que estos
    formularios no sirvan de trampolín a un sitio externo.
    """
    destination = request.POST.get("next", "")

    if destination and url_has_allowed_host_and_scheme(
        url=destination,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(destination)

    return redirect("customers:search")


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

    return _back_to(request)


@require_POST
@login_required
def set_active_office(request):
    """
    Cambia la oficina desde la que se atiende.

    Hoy la oficina es solo contexto visible: no acota ninguna consulta.
    Se registra desde ahora porque el flujo de caja la va a necesitar.

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

    return _back_to(request)
