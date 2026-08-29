from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.organization.context_processors import ACTIVE_BRANCH_SESSION_KEY
from apps.organization.models import Branch


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

    # Se vuelve a la pantalla desde la que se cambió, para no interrumpir lo
    # que el operador estaba haciendo. El destino se valida contra el propio
    # host: un `next` apuntando a otro dominio se descarta y se cae a la
    # búsqueda, de modo que este formulario no sirva de trampolín a un sitio
    # externo.
    destination = request.POST.get("next", "")

    if destination and url_has_allowed_host_and_scheme(
        url=destination,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(destination)

    return redirect("customers:search")
