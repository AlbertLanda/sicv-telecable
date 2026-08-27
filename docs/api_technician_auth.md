# API REST y autenticación del técnico

Documentación técnica de la capa de API REST de SICV (SICV — Telecable / Fiber
The Andes) y del endpoint de autenticación por token del técnico.

Es el cimiento del canal que consumirá la app/PWA del técnico. Los endpoints
operativos («mis órdenes», iniciar atención, atender, liquidar) **no** están
aquí: llegan en los días siguientes del bloque y reutilizarán los servicios de
dominio ya documentados en
[`work_orders_start_attention.md`](work_orders_start_attention.md) y
[`work_orders_workflow.md`](work_orders_workflow.md).

---

## 1. Principio: dos canales separados, un solo dominio

```
App/PWA del técnico                      Navegador de ATC / despacho
      ↓                                          ↓
POST /api/technicians/login/            POST /accounts/login/
      ↓                                          ↓
TokenAuthentication                     SessionAuthentication (cookies)
      ↓                                          ↓
      └──────────────► apps.accounts.models.User ◄───────────┘
                                ↓
                    mismos servicios de dominio
                    (start_order_attention, ...)
```

- **Canales de identificación distintos.** La API no usa cookies de sesión ni
  CSRF; la web no usa tokens. Un canal no puede autenticar al otro (hay una
  prueba que lo fija).
- **Un solo modelo de usuario.** Se reutiliza `apps.accounts.models.User` y
  `User.Role.TECHNICIAN`. No existe un modelo de usuario paralelo para la API.
- **Un solo dominio.** El token identifica al usuario; no otorga ningún permiso
  funcional. Los permisos (`work_orders.start_workorder`, etc.) se evaluarán en
  los endpoints operativos exactamente igual que en la web.

---

## 2. Archivos

| Archivo | Rol |
|---|---|
| `requirements.txt` | `djangorestframework==3.18.0` |
| `config/settings.py` | `rest_framework` + `rest_framework.authtoken` en `INSTALLED_APPS`, bloque `REST_FRAMEWORK` |
| `config/urls.py` | Prefijo `api/technicians/` |
| `apps/accounts/services.py` | `authenticate_technician()` y sus excepciones |
| `apps/accounts/api/serializers.py` | `TechnicianLoginSerializer`, `TechnicianIdentitySerializer` |
| `apps/accounts/api/views.py` | `TechnicianLoginView`, `TechnicianMeView` |
| `apps/accounts/api/urls.py` | Rutas `technicians_api:login` y `technicians_api:me` |
| `apps/accounts/tests/test_api_auth.py` | Pruebas del canal de autenticación |

---

## 3. Configuración de DRF

```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}
```

**Cerrado por defecto.** `IsAuthenticated` global significa que un endpoint
nuevo nace protegido. Abrir uno es una decisión explícita en la vista, visible
en la revisión de código: hoy solo `TechnicianLoginView` lo hace, y no puede
hacer otra cosa, porque es el endpoint que emite el token.

**`SessionAuthentication` no está incluida a propósito.** Si estuviera, una
sesión web abierta en el navegador autenticaría llamadas a la API sin token y
los dos canales quedarían mezclados; además arrastraría la validación de CSRF a
peticiones que no la necesitan. La prueba
`test_web_session_does_not_authenticate_the_api` fija este comportamiento.

`rest_framework.authtoken` aporta sus propias migraciones (tabla del token). No
se generó ninguna migración del proyecto: `makemigrations --check` sale limpio.

---

## 4. Endpoints

### `POST /api/technicians/login/`

Único endpoint abierto de la API.

**Petición**

```json
{"username": "tecnico1", "password": "********"}
```

**Respuesta 200**

```json
{
  "token": "9c4f1a...",
  "technician": {
    "id": 4,
    "username": "tecnico1",
    "full_name": "Luis Quispe",
    "role": "TECHNICIAN",
    "branch_id": 1,
    "branch_name": "Sede Central"
  }
}
```

**Respuestas de rechazo**

| Situación | Código | Cuerpo |
|---|---|---|
| Falta `username` o `password` | 400 | Errores por campo |
| Contraseña incorrecta | 401 | `Credenciales inválidas.` |
| Usuario inexistente | 401 | `Credenciales inválidas.` |
| Técnico desactivado (`is_active=False`) | 401 | `Credenciales inválidas.` |
| Credenciales correctas, rol distinto de `TECHNICIAN` | 403 | `El usuario no tiene rol técnico.` |

Los tres casos de 401 comparten un mensaje idéntico **a propósito**: la
respuesta no debe permitir distinguir «este usuario no existe» de «existe pero
está desactivado» ni de «existe y la contraseña está mal». El 403 del cuarto
caso sí es distinguible, y es una concesión consciente: es un sistema interno,
el criterio de aceptación exige que el rechazo por rol sea explícito, y el
mensaje solo revela un rol, no una credencial.

### `GET /api/technicians/me/`

Endpoint protegido de referencia: hereda `TokenAuthentication` de los ajustes
globales, y por eso sirve para verificar que la configuración por defecto
realmente cierra la API.

> **Actualización del día 2.** Además de `IsAuthenticated`, este endpoint pasa
> a exigir la permission class `IsActiveTechnician`, para que el rol y el
> estado de la cuenta se reevalúen en cada petición y no solo al emitir el
> token. La decisión, con su tabla de casos, está en
> [`api_technician_work_orders.md`](api_technician_work_orders.md) §3.1.

```
GET /api/technicians/me/
Authorization: Token 9c4f1a...
```

Devuelve el mismo bloque `technician` del login. Es **identidad, no
operación**: no expone órdenes ni permite transiciones. Los endpoints
operativos son alcance de los días 2 a 6 del bloque.

---

## 5. Dónde vive la regla

`authenticate_technician()` está en `apps/accounts/services.py`, no en la
vista. Mismo reparto que el resto del sistema:

- **El serializador transporta.** `TechnicianLoginSerializer` solo lleva
  usuario y contraseña, ambos `write_only`. No autentica.
- **La vista orquesta y traduce a HTTP.** Llama al servicio y convierte cada
  excepción en su código de estado. No compara contraseñas ni consulta roles.
- **El dominio decide.** El servicio autentica con el backend estándar de
  Django y **sobre eso** exige rol técnico y cuenta activa.

No se reutiliza el login genérico de Django tal cual: un usuario ATC con
contraseña correcta se autenticaría sin problema con `authenticate()` a secas.
La exigencia de rol es lo que convierte ese login genérico en el login del
canal técnico.

---

## 6. Decisiones registradas

### 6.1 Token opaco de DRF, no JWT

Se evaluó JWT y **se descarta por ahora**. Razones:

- El token de DRF se revoca borrando una fila. Un JWT sigue siendo válido hasta
  que expira, y revocarlo antes exige mantener una lista de revocación —
  volviendo a consultar la base de datos en cada petición, que es justo el
  costo que el JWT pretendía evitar.
- El esquema de refresh tokens añade estado y superficie de error sin beneficio
  a esta escala (una app de técnicos de campo, un solo backend).
- No hay múltiples servicios que necesiten validar la identidad sin consultar
  la base de datos, que es el escenario donde el JWT gana.

Si el requisito cambia (varios servicios, expiración corta obligatoria), la
migración es acotada: cambia `DEFAULT_AUTHENTICATION_CLASSES` y el endpoint de
login; el resto de la API no se entera.

### 6.2 El token **no expira**

Constancia explícita, como exige la actividad: el token emitido **no tiene
fecha de caducidad**. `rest_framework.authtoken.models.Token` no incluye
expiración y no se añadió ninguna.

Es una decisión, no un olvido:

- El técnico trabaja en campo, con conectividad intermitente. Un token que
  caduca a media jornada obliga a reautenticar en el peor momento posible.
- La revocación existe y es del lado del servidor: borrar el token (admin o
  shell) corta el acceso de inmediato. Desactivar al usuario
  (`is_active=False`) impide emitir uno nuevo.
- Volver a autenticarse **no** rota el token (`get_or_create`): la app puede
  reintentar el login sin invalidar la sesión que ya tenía abierta.

> **Actualización del día 2.** Que el token no caduque es precisamente la
> razón por la que los endpoints del canal técnico verifican rol y estado en
> cada petición mediante `IsActiveTechnician`: desactivar al usuario o
> cambiarle el rol revoca el acceso de inmediato, sin esperar a que el token
> venza. Ver [`api_technician_work_orders.md`](api_technician_work_orders.md).

Riesgo asumido: un token filtrado es válido hasta que alguien lo borra.
Mitigaciones pendientes, fuera del alcance de hoy y a evaluar en el bloque de
despliegue:

- HTTPS obligatorio en producción (el token viaja en el header).
- Endpoint de logout que borre el token del dispositivo.
- Rotación de token o caducidad por inactividad, si el área de TI lo exige.

### 6.3 La contraseña nunca se registra

No se devuelve ni se escribe en logs en ningún punto: ambos campos del
serializador son `write_only`, el servicio recibe la contraseña como argumento
y no la guarda en ninguna parte, y ningún mensaje de error la incluye. La
prueba `test_response_never_echoes_the_password` verifica además que la cadena
no aparezca en el cuerpo de la respuesta.

---

## 7. Pruebas

`apps/accounts/tests/test_api_auth.py`

| # | Escenario | Resultado esperado |
|---|---|---|
| 1 | Credenciales válidas de técnico | 200 y token devuelto |
| 2 | Contraseña incorrecta | 401, sin token |
| 2b | Usuario inexistente | 401, mismo mensaje genérico |
| 3 | Usuario válido, rol no técnico | 403, sin token |
| 4 | Técnico inactivo | 401, sin token |
| 5 | `GET /me/` sin token | 401 |
| 5b | `GET /me/` con token inexistente | 401 |
| 6 | `GET /me/` con token válido | 200 |
| — | La contraseña no vuelve en la respuesta | No aparece en el cuerpo |
| — | Login repetido | Mismo token, una sola fila |
| — | Petición sin campos | 400 |
| — | Sesión web contra la API | 401 (canales separados) |
| — | Ajustes por defecto de DRF | Token-only e `IsAuthenticated` |

```
python manage.py test apps.accounts
Ran 14 tests — OK
```

---

## 8. Qué NO se tocó

- El login web de ATC/despacho (`config/urls.py` → `accounts/login/`) y sus
  plantillas: intactos.
- `apps/customers` y `apps/work_orders/views.py`: intactos.
- No se agregó ninguna librería de autenticación de terceros más allá de DRF.

El único cambio en `apps/accounts` fuera del paquete `api/` es `services.py`
(nuevo) y la sustitución del stub vacío `tests.py` por el paquete `tests/`,
siguiendo la convención ya usada en `apps/work_orders/tests/`.
