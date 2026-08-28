from django.contrib import admin

from .models import Equipment


@admin.register(Equipment)
class EquipmentAdmin(admin.ModelAdmin):
    list_display = ("equipment_type", "brand", "model", "serial_or_mac", "status")
    list_filter = ("equipment_type", "status")
    search_fields = ("brand", "model", "serial_or_mac")