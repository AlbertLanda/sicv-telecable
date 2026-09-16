"""Cómo se reparte el feed en páginas.

El proyecto no declara paginación global (`REST_FRAMEWORK` en
`config/settings.py` solo fija autenticación y permiso), así que sin esto un
mes entero saldría en una sola respuesta. No es un detalle de afinado: con los
miles de movimientos que deja un mes de operación, esa respuesta se cuenta en
megabytes y la arma en memoria un worker que mientras tanto no atiende a
nadie.

Se declara **en la vista** y no en los ajustes globales a propósito: el canal
del técnico ya está en producción sin paginar y sus respuestas son de unas
pocas órdenes. Paginar de golpe a todo el proyecto cambiaría la forma de esas
respuestas -de lista a objeto con `results`- y rompería la app del técnico sin
que nadie lo hubiera pedido.

Es paginación por **cursor** y no por número de página. Un feed que se
sincroniza mientras el sistema sigue operando recibe filas nuevas entre una
página y la siguiente; con `?page=2` esas inserciones corren las filas y hacen
que algunas se salten o se repitan. El cursor apunta a una posición concreta
del orden, así que lo que ya pasó no vuelve a moverse.
"""

from rest_framework.pagination import CursorPagination


class MaterialMovementPagination(CursorPagination):
    """Páginas de 500 movimientos, ordenadas por id.

    El orden es por `pk` y no el del reporte -emisión, orden, sentido,
    material-. No es un descuido: el cursor exige un orden estable y único, y
    los cuatro campos del reporte empatan entre sí con facilidad (dos
    movimientos de la misma orden emitidos el mismo segundo). Además, al otro
    lado nadie lee esto: logística lo guarda y después ordena como quiera. El
    orden legible es cosa de la hoja, no del feed.
    """

    page_size = 500
    max_page_size = 2000
    page_size_query_param = "page_size"
    cursor_query_param = "cursor"
    ordering = "pk"
