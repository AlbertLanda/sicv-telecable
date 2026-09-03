from django.contrib import admin

from .models import Plan, ServiceType, Subscription


@admin.register(ServiceType)
class ServiceTypeAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "supports_tv_annexes",
        "annex_installation_price",
        "annex_monthly_price",
        "is_active",
    )
    list_filter = ("supports_tv_annexes", "is_active")
    search_fields = ("code", "name")


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "service_type",
        "speed_mbps",
        "monthly_price",
        "included_tv_points",
        "is_active",
    )
    list_filter = ("service_type", "is_active")
    search_fields = ("code", "name", "service_type__name")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    """Consulta administrativa; el alta operativa sigue ocurriendo por el flujo web."""

    list_display = (
        "customer",
        "service_type",
        "plan",
        "address",
        "service_number",
        "annex_count",
        "status",
        "is_active",
    )
    list_filter = ("service_type", "status", "is_active")
    search_fields = (
        "customer__document_number",
        "customer__first_name",
        "customer__paternal_surname",
        "plan__name",
    )
    list_select_related = (
        "customer",
        "service_type",
        "plan",
        "address",
    )
