from django.contrib import admin

from .models import (
    BillingPolicy,
    CommercialCoverageRule,
    InstallationMaterialRule,
    InstallationMaterialUsage,
    Plan,
    PlanTariff,
    ServiceType,
    Subscription,
    SubscriptionAnnexAdjustment,
)


@admin.register(BillingPolicy)
class BillingPolicyAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "billing_mode",
        "discount_amount",
        "discount_deadline_day",
        "discount_days_before_due",
        "cut_day_next_month",
        "cut_days_after_due",
        "is_active",
    )
    list_filter = ("billing_mode", "is_active")
    search_fields = ("code", "name")


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
        "generation",
        "commercial_category",
        "service_type",
        "speed_mbps",
        "monthly_price",
        "initial_tv_courtesy_limit_display",
        "requires_geographic_tariff",
        "billing_policy",
        "is_active",
    )
    list_filter = (
        "generation",
        "commercial_category",
        "service_type",
        "requires_geographic_tariff",
        "billing_policy",
        "is_active",
    )
    search_fields = ("code", "name", "service_type__name")
    autocomplete_fields = ("billing_policy",)

    @admin.display(description="Máx. TV cortesía inicial")
    def initial_tv_courtesy_limit_display(self, obj):
        return obj.initial_tv_courtesy_limit


@admin.register(PlanTariff)
class PlanTariffAdmin(admin.ModelAdmin):
    list_display = (
        "plan",
        "branch",
        "zone",
        "installation_fee",
        "monthly_fee",
        "valid_from",
        "valid_until",
        "is_active",
    )
    list_filter = ("branch", "plan__service_type", "plan__generation", "is_active")
    search_fields = ("plan__code", "plan__name", "branch__name", "zone__name")
    autocomplete_fields = ("plan", "branch", "zone")


@admin.register(CommercialCoverageRule)
class CommercialCoverageRuleAdmin(admin.ModelAdmin):
    list_display = (
        "generation",
        "branch",
        "zone",
        "commercial_category",
        "availability",
        "valid_from",
        "valid_until",
        "is_active",
    )
    list_filter = (
        "generation",
        "commercial_category",
        "availability",
        "branch",
        "is_active",
    )
    search_fields = ("branch__name", "zone__name")
    autocomplete_fields = ("branch", "zone")


@admin.register(InstallationMaterialRule)
class InstallationMaterialRuleAdmin(admin.ModelAdmin):
    list_display = (
        "material",
        "service_type",
        "branch",
        "free_meters",
        "excess_price_per_meter",
        "valid_from",
        "valid_until",
        "is_active",
    )
    list_filter = ("material", "service_type", "branch", "is_active")
    search_fields = ("service_type__name", "branch__name")
    autocomplete_fields = ("service_type", "branch")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    """Consulta administrativa; el alta operativa sigue ocurriendo por el flujo web."""

    list_display = (
        "customer",
        "service_type",
        "plan",
        "address",
        "service_number",
        "base_monthly_fee",
        "initial_tv_courtesy_granted",
        "annex_count",
        "status",
        "is_active",
    )
    list_filter = ("service_type", "plan__generation", "plan__commercial_category", "status", "is_active")
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
        "tariff",
        "billing_policy",
    )
    readonly_fields = (
        "tariff",
        "billing_policy",
        "base_installation_fee",
        "base_monthly_fee",
        "initial_tv_courtesy_granted",
    )


@admin.register(SubscriptionAnnexAdjustment)
class SubscriptionAnnexAdjustmentAdmin(admin.ModelAdmin):
    list_display = (
        "work_order",
        "subscription",
        "operation",
        "previous_annex_count",
        "quantity",
        "target_annex_count",
        "installation_charge",
        "monthly_delta",
        "applied_at",
    )
    list_filter = ("operation", "applied_at")
    search_fields = (
        "work_order__order_number",
        "subscription__customer__document_number",
    )
    list_select_related = ("work_order", "subscription__customer")
    readonly_fields = (
        "subscription",
        "work_order",
        "operation",
        "previous_annex_count",
        "quantity",
        "target_annex_count",
        "installation_charge",
        "monthly_delta",
        "monthly_charge_after",
        "applied_at",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InstallationMaterialUsage)
class InstallationMaterialUsageAdmin(admin.ModelAdmin):
    list_display = (
        "work_order",
        "rule",
        "meters_used",
        "free_meters_snapshot",
        "excess_meters",
        "excess_charge",
    )
    list_filter = ("rule__material", "rule__service_type", "work_order__branch")
    search_fields = ("work_order__order_number", "work_order__subscription__customer__document_number")
    readonly_fields = (
        "work_order",
        "rule",
        "meters_used",
        "free_meters_snapshot",
        "excess_price_per_meter_snapshot",
        "excess_meters",
        "excess_charge",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
