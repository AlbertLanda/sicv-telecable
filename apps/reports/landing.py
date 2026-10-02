from django.shortcuts import redirect


def landing(request):
    if not request.user.is_authenticated:
        return redirect("login")
    if request.user.has_perm("organization.view_operational_dashboard"):
        return redirect("reports:dashboard")
    return redirect("customers:search")
