"""Códigos estables de órdenes físicas publicables al canal técnico.

El canal de técnicos empezó con instalaciones como alcance MVP. Las averías
nacidas de una derivación NOC también deben entrar al mismo pool compartido:
son trabajo físico, nacen PENDING y sin técnico, y el técnico que las toma se
convierte en su responsable.

Los códigos de avería coinciden con el catálogo operativo sembrado por
``cargar_catalogo_ordenes``.
"""

from apps.work_orders.services import INSTALLATION_ORDER_TYPE_CODE


INTERNET_FAULT_ORDER_TYPE_CODE = "INTERNET_FAULT"
CABLE_FAULT_ORDER_TYPE_CODE = "CABLE_FAULT"
OUTSIDE_PLANT_ORDER_TYPE_CODE = "OUTSIDE_PLANT"

FAULT_ORDER_TYPE_CODES = (
    INTERNET_FAULT_ORDER_TYPE_CODE,
    CABLE_FAULT_ORDER_TYPE_CODE,
)

TECHNICIAN_AVAILABLE_ORDER_TYPE_CODES = (
    INSTALLATION_ORDER_TYPE_CODE,
    *FAULT_ORDER_TYPE_CODES,
    OUTSIDE_PLANT_ORDER_TYPE_CODE,
)
