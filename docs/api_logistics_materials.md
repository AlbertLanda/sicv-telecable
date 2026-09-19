# API de logística: movimientos de material en campo

**Frente:** Integración SICV → Sistema de logística
**Colaborador:** Kevin Rivera · **Fecha:** 16/09/2026
**Rama:** `feature/reporte-materiales-logistica`

Canal de **solo lectura**, sistema a sistema, para que el sistema de almacén
cruce el material que el técnico declaró en campo contra la **mochila** que le
asigna cada semana.

**No hay migraciones, ni estados nuevos, ni cambios en el dominio.** Todo lo
que este documento describe es exposición de lo que `apps/inventory` y
`apps/reports` ya resuelven. SICV no lleva stock ni kardex y no va a llevarlo:
declara consumo. El stock es de logística.

---

## 1. Para qué existe

Hoy logística descarga el reporte de materiales en Excel y arma una tabla
dinámica por técnico para contrastar lo asignado contra lo consumido. Este
canal entrega esos mismos datos como JSON para que el cruce se haga una vez,
programado, y quede en una pantalla del sistema de almacén.

El objetivo no es exportar mejor la tabla dinámica: es que deje de hacerse a
mano.

### 1.1 Lo que entrega y lo que no

Entrega **el detalle**: una fila por movimiento de material, igual que la hoja
en pantalla. Una orden que instaló tres materiales y retiró uno son cuatro
filas.

No entrega el agregado por técnico. La suma la hace logística del otro lado, y
es a propósito: un total no se puede auditar. Cuando el cuadre no cierre por
unos metros de fibra, alguien tiene que poder abrir ese número y llegar a las
órdenes que lo componen — por eso cada fila trae `order_number` y
`customer_code`.

### 1.2 Dos flujos opuestos, no una resta

`INSTALLED` y `REMOVED` son sentidos contrarios y **pozos de stock distintos**:

| Movimiento | De dónde sale | A dónde va |
|---|---|---|
| `INSTALLED` | de la mochila del técnico | al domicilio del abonado |
| `REMOVED` | del domicilio del abonado | al almacén, como recuperado |

Lo instalado descuenta la mochila. Lo retirado **no la repone**: ingresa como
material recuperado, que es otro pozo. El cuadre son dos cuentas separadas:

```
asignado − instalado = saldo teórico de mochila   →  contra conteo físico
retirado                                          →  ingreso a recuperados
```

Netear las dos columnas da un número sin significado físico.

---

## 2. Contrato

Prefijo `/api/logistics/`. Todos exigen la cabecera `Authorization: Token <key>`.

| Acción | Método y ruta | Éxito | Errores |
|---|---|---|---|
| Detalle del periodo | `GET /api/logistics/material-movements/` | `200` página | `400` · `401` · `403` |
| Ids vigentes | `GET /api/logistics/material-movements/ids/` | `200` lista de ids | `400` · `401` · `403` |
| Marca de agua | `GET /api/logistics/material-movements/watermark/` | `200` sello | `400` · `401` · `403` |

Los tres son de solo lectura: `POST`, `PUT`, `PATCH` y `DELETE` responden `405`.

Los errores de parámetro salen por campo, que es lo que permite registrar
**qué** venía mal en vez de «falló la sincronización»:

```json
{"branch": ["No existe la sede «SED09»."]}
```

### 2.1 Acceso

El consumidor es un usuario de servicio con un token, no una persona. **No
necesita rol de almacén**: necesita el permiso
`inventory.view_workordermaterialmovement`, que es el mismo criterio con el
que se abre la hoja en pantalla.

Se crea una sola vez, del lado de SICV:

```python
# python manage.py shell
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.authtoken.models import Token

usuario = get_user_model().objects.create_user(
    username="svc_logistica", password=None, is_active=True,
)
usuario.user_permissions.add(
    Permission.objects.get(
        content_type__app_label="inventory",
        codename="view_workordermaterialmovement",
    )
)
print(Token.objects.create(user=usuario).key)
```

El token **no caduca**. Va en una variable de entorno del lado de logística,
nunca en el código versionado, y el canal exige HTTPS: viaja en una cabecera y
en HTTP plano lo lee cualquiera en el camino.

Retirar el permiso corta el acceso de inmediato — se comprueba en cada
petición, no solo al emitir el token.

### 2.2 Parámetros

| Parámetro | Valores | Defecto | Significado |
|---|---|---|---|
| `date_from` | `AAAA-MM-DD` | — | **Obligatorio.** Inicio del periodo, inclusivo |
| `date_to` | `AAAA-MM-DD` | — | **Obligatorio.** Fin del periodo, inclusivo |
| `date_basis` | `attended` \| `issued` | `attended` | Sobre qué fecha recorta el periodo |
| `scope` | ver §2.3 | `ALL` | Recorte por tipo de orden |
| `branch` | código de sede | *todas* | Ej. `SED01` |
| `technician` | id de usuario | *todos* | El `technician_id` de las filas |
| `updated_since` | ISO 8601 | — | Solo lo que cambió desde ese sello. No se admite en `ids/` |
| `page_size` | 1 – 2000 | 500 | Tamaño de página |
| `cursor` | opaco | — | Lo entrega `next`; no se construye a mano |

Un periodo invertido, uno de más de 366 días o una sede inexistente responden
`400`. Un periodo sin movimientos responde `200` con `results` vacío: son dos
respuestas distintas y no deben mostrarse igual.

#### `date_basis` — la que importa para el cuadre

Por defecto el periodo recorta por **atención real**, no por emisión de la
orden, y ese defecto es deliberado.

El material sale de la mochila cuando el técnico lo usa, no cuando ATC escribió
la orden. Con corte semanal la diferencia no es un caso de borde: una orden
emitida el viernes y atendida el lunes cae en la semana equivocada **todos los
viernes**, y el cuadre no cierra por material que sí se consumió, solo que en
la otra semana.

Consecuencia a tener presente: **una orden que aún no se ha atendido no
aparece.** Es lo correcto — lo que el técnico todavía puede corregir no debería
descontar stock — y se resuelve solo: en cuanto la orden se cierra, la
siguiente consulta del mismo periodo ya la trae.

`date_basis=issued` reproduce el recorte de la hoja en pantalla, y sirve para
contrastar contra el Excel del sistema anterior.

#### `scope`

Los del desplegable del reporte: `ALL`, `INSTALLATION`, `ANNEX`,
`RECONNECTION`, `CUT`, `SERVICES`, `FAULT`, `INTERNET_FAULT` y `CABLE_FAULT`.
`FAULT` conserva el filtro combinado de averías de Internet y Cable por
compatibilidad; los dos últimos permiten recortarlas por separado.

`ALL` no es la suma de las otras opciones: no recorta por tipo, así que también
trae las órdenes cuyo tipo no tiene opción propia (retiros, cambios de plan,
requerimientos). Para cuadrar almacén se usa `ALL`; cualquier otro valor
esconde material que sí salió.

### 2.3 Forma de la respuesta

Los campos con `choices` viajan **dos veces**: el código estable, que es con lo
que se decide, y la etiqueta legible, que es lo que se pinta. Así logística no
mantiene su propia tabla de traducciones ni se rompe si alguien corrige una
tilde en el admin.

```json
{
  "next": "https://sicv.../material-movements/?cursor=cD0xMjM&date_from=...",
  "previous": null,
  "results": [
    {
      "id": 1,
      "movement_type": "INSTALLED",
      "movement_type_display": "Instalado en domicilio",
      "is_removal": false,
      "quantity": "45.50",
      "material_code": "UTP",
      "material_name": "Cable UTP",
      "unit_of_measure": "METER",
      "unit_of_measure_display": "Metro",
      "remarks": "",
      "technician_id": 1,
      "technician_username": "tecnico1",
      "technician_name": "Luis Quispe",
      "order_number": "OT-00001",
      "order_type_code": "INSTALLATION",
      "order_type_name": "INSTALACIÓN",
      "order_status": "ATTENDED",
      "order_status_display": "Atendida",
      "branch_code": "SED01",
      "branch_name": "Huancayo",
      "customer_code": "CLI001",
      "equipment_code": "AA:BB:CC:DD:EE:FF",
      "issued_at": "2026-09-16T15:22:02.027302-05:00",
      "attended_at": "2026-09-16T15:22:02.032347-05:00",
      "is_liquidated": false,
      "liquidation_status": "",
      "liquidation_status_display": "",
      "updated_at": "2026-09-16T15:22:02.027302-05:00",
      "changed_at": "2026-09-16T15:22:02.027302-05:00"
    }
  ]
}
```

| Campo | Notas |
|---|---|
| `id` | Llave del movimiento en SICV. **Estable**: corregir la cantidad actualiza la fila, no crea otra. Es la llave de idempotencia |
| `movement_type` | `INSTALLED` \| `REMOVED` |
| `is_removal` | El sentido ya resuelto, para no comparar contra el código |
| `quantity` | Cadena decimal con dos decimales. No redondear al leer |
| `material_code` | **Cruzar por aquí**, nunca por `material_name` |
| `technician_id` | **Cruzar por aquí**, nunca por `technician_name` |
| `equipment_code` | MAC/equipo general registrado en la ficha técnica de la **OT**. Puede repetirse en varias filas de la misma orden y **no identifica ni serializa el material de esa fila**. El modelo de movimiento todavía no tiene serial propio |
| `order_number`, `customer_code` | Para abrir una celda del cuadre y llegar a la orden |
| `is_liquidated`, `liquidation_status` | Ver §2.4 |
| `changed_at` | La marca de agua de la sincronización. Ver §3.2 |

Todo lo opcional se lee como cadena vacía, nunca como error: un movimiento de
una orden sin tipo, sin ficha de campo o sin técnico asignado sigue siendo
material que salió del almacén y tiene que llegar al cuadre.

### 2.4 Declarado y liquidado

Viaja **el estado**, no una decisión ya tomada.

Descontar stock contra una declaración que el técnico todavía puede corregir
obliga a reversar asientos; esperar a la validación deja al almacén sin ver el
material en tránsito. Con el estado en cada fila, logística puede mostrar todo
y consolidar solo lo validado — pero esa es una política de logística, no de
SICV.

`liquidation_status` recorre `LIQUIDATED` → `SUBMITTED` → `VALIDATED`, con
`CORRECTION_REQUESTED` y `RESUBMITTED` como desvío. La liquidación de una orden
es independiente del estado de la orden misma.

---

## 3. Guía para el consumidor

### 3.1 Descarga por lote (el flujo principal)

Cuando el almacenero elige un periodo, logística baja ese periodo completo, lo
**guarda** y desde ahí filtra en local. Los filtros de pantalla —técnico,
material, acción— consultan la tabla de logística, nunca a SICV: así son
instantáneos y la pantalla funciona aunque SICV esté en mantenimiento.

```python
def sincronizar(desde, hasta):
    url = f"{settings.SICV_URL}/api/logistics/material-movements/"
    params = {"date_from": desde, "date_to": hasta, "scope": "ALL"}

    while url:
        r = requests.get(
            url,
            headers={"Authorization": f"Token {settings.SICV_TOKEN}"},
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        pagina = r.json()

        for fila in pagina["results"]:
            MovimientoMaterialSICV.objects.update_or_create(
                sicv_id=fila["id"],
                defaults={...},
            )

        url, params = pagina["next"], None   # el cursor ya viaja en `next`
```

Un mes no llega en una sola respuesta: se camina con `next` hasta que venga
`null`. Es paginación por **cursor** y no por número de página, para que las
filas nuevas que entren durante la descarga no corran las páginas y hagan que
se salte o se repita alguna.

`update_or_create` sobre `sicv_id` es lo que permite reprocesar el mismo
periodo cuantas veces haga falta sin duplicar una sola fila. Conviene un botón
«Actualizar» en la pantalla que simplemente vuelva a llamar a esto.

### 3.2 Incremental (opcional)

Para refrescos frecuentes sin bajar el periodo entero:

1. Pedir `watermark/` del periodo y guardar el valor.
2. En la corrida siguiente, pasar ese valor como `updated_since`.
3. Al terminar, volver a pedir `watermark/` y guardar el nuevo.

**La marca se pide a SICV; no se calcula con el reloj de logística.** Si los dos
servidores difieren en unos segundos, una marca calculada localmente se salta
movimientos en cada corrida y el hueco no se nota hasta que el cuadre no
cierra.

`changed_at` representa el cambio más reciente entre el movimiento, su orden y
la liquidación/revisión asociada. Así un cambio administrativo que modifica
`liquidation_status` vuelve a publicar la fila aunque no se haya tocado ni el
movimiento ni `WorkOrder.updated_at`.

Un periodo vacío devuelve `watermark: null`, que se lee como «no muevas tu
marca», no como «no hay nada más».

### 3.3 Borrados

Un técnico puede quitar un material que declaró por error, y ese borrado es
real: la fila desaparece. Una sincronización que solo trae altas y cambios no
se entera nunca, y la fila sobrevive en logística descontando stock que volvió
al almacén.

Por eso existe `ids/`. Devuelve los ids **vigentes y completos** del periodo con
los mismos filtros de dominio. `updated_since` está prohibido en este endpoint:
una lista incremental no sirve para reconciliar borrados y podría hacer que
logística elimine filas que siguen vigentes.

```python
vigentes = set(requests.get(f"{url}/ids/", ...).json()["ids"])
MovimientoMaterialSICV.objects.filter(
    atendido_en__date__range=(desde, hasta),
).exclude(sicv_id__in=vigentes).delete()
```

Conviene correrlo una vez al día sobre el periodo abierto, no en cada
descarga. Un periodo con más de 100 000 movimientos responde `400` pidiendo que
se parta en tramos: media lista borraría filas vigentes que no alcanzaron a
entrar.

### 3.4 Nunca descartar una fila que no mapea

Lo más probable que falle el día del go-live no es el código: es que un
`material_code` o un `technician_id` de SICV no exista todavía en logística.

La regla es **guardar la fila igual, con el FK en nulo**, y listar aparte lo
que quedó sin mapear:

```python
class MovimientoMaterialSICV(models.Model):
    sicv_id = models.PositiveIntegerField(unique=True)

    # Siempre se guarda lo que SICV mandó, mapee o no.
    sicv_material_code = models.CharField(max_length=40)
    sicv_technician_id = models.PositiveIntegerField()

    # El mapeo puede faltar. La fila NO se descarta por eso.
    material = models.ForeignKey(Material, null=True, on_delete=models.PROTECT)
    tecnico = models.ForeignKey(Tecnico, null=True, on_delete=models.PROTECT)
```

Si la sincronización descarta lo que no mapea, el cuadre da un número menor al
real, cierra «bien», y nadie se entera de que faltan 200 metros de fibra hasta
el inventario físico.

---

## 4. Puesta en marcha

SICV todavía no tiene datos migrados; logística está en producción. El orden es:

1. **Contrato acordado** — este documento. Permite que los dos equipos avancen
   en paralelo sin esperarse.
2. **Logística despliega apagado.** El modelo, el cliente, la vista y el menú
   van a producción detrás de un flag (`SICV_SYNC_ENABLED`, por defecto
   `False`). Dejarlo en una rama es peor: acumularía meses de divergencia
   contra un sistema vivo.
3. **Desarrollo contra datos sembrados.** En un SICV de desarrollo:
   ```
   python manage.py generar_datos_materiales_prueba
   ```
   Genera órdenes con material declarado pasando por el mismo camino que el
   técnico real, así que el JSON es indistinguible del de producción.
4. **El día que haya datos reales:** conciliar catálogos (§3.4), sincronizar
   una semana de un técnico, y **cuadrarla a mano contra el Excel del sistema
   anterior**. Si los dos números coinciden, la integración es correcta. Recién
   ahí se prende el flag.

### 4.1 Los tres estados vacíos

La pantalla de logística está en producción y va a toparse con los tres. Deben
verse distintos:

| Situación | Mensaje |
|---|---|
| Flag apagado | «La conexión con SICV aún no está habilitada.» |
| Conectada, sin movimientos | «No hay movimientos registrados entre el 8 y el 14.» |
| SICV no respondió | «No se pudo consultar SICV. Se muestra lo último sincronizado el 12/09 a las 14:30.» |

Si las tres dicen «no hay datos», el almacenero va a cuadrar contra una tabla
vacía creyendo que el técnico no consumió nada.

---

## 5. Comprobar que funciona

```bash
curl -H "Authorization: Token <key>" \
  "https://sicv.tudominio.pe/api/logistics/material-movements/?date_from=2026-09-08&date_to=2026-09-14"
```

Las pruebas del canal están en
`apps/reports/tests/test_api_logistics_materials.py` y cubren el contrato, el
acceso, el recorte por atención, la paginación, el incremental y la
reconciliación. Mientras no haya datos migrados, **son la garantía de que esto
funciona**: cualquier cambio de nombre de campo las rompe antes de romper
producción.

```
python manage.py test apps.reports
```
