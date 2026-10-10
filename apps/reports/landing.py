from django.shortcuts import redirect


def landing(request):
    if not request.user.is_authenticated:
        return redirect("login")
    if request.user.has_perm("organization.view_operational_dashboard"):
        return redirect("reports:dashboard")
    if request.user.has_perm("accounting.view_workspace"):
        return redirect("accounting:workspace")
    return redirect("customers:search")
