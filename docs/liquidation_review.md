# Revisión de la liquidación técnica

Documentación técnica del ciclo de **validación única y corrección controlada**
de las liquidaciones del módulo `apps/work_orders/` (nuevo SICV — Telecable /
Fiber The Andes).

Complementa a [`work_orders_workflow.md`](work_orders_workflow.md), que cubre
el workflow operativo de la orden y la liquidación técnica en sí. Este
documento cubre lo que ocurre **después** de liquidar: quién revisa esa
liquidación, cómo se corrige y cómo queda bloqueada.

---

## 1. Decisión funcional vigente

El proceso **no** tiene una validación separada por NOC y otra por almacén. La
liquidación se revisa **una sola vez**, por un usuario autorizado.

Si la liquidación contiene un error, el validador puede solicitar una
corrección. El técnico tiene **una sola oportunidad** de editar y reenviar.
Después del reenvío no puede volver a modificarla.

---

## 2. Flujo de estados de revisión

```
LIQUIDATED ──> SUBMITTED ─────────────────────> VALIDATED
                   │                                ▲
                   └─> CORRECTION_REQUESTED ─> RESUBMITTED
```

| Código | Etiqueta | Significado |
|---|---|---|
| `LIQUIDATED` | Liquidada | La liquidación técnica existe, aún sin enviar a revisión. |
| `SUBMITTED` | Enviada | El técnico la envió formalmente. Pendiente de validación. |
| `CORRECTION_REQUESTED` | Corrección solicitada | El validador detectó un error. Se habilita una única edición. |
| `RESUBMITTED` | Reenviada | Corregida y enviada nuevamente. La oportunidad quedó consumida. |
| `VALIDATED` | Validada | Aprobada y bloqueada de forma definitiva. |

`LIQUIDATED` es el estado inicial: la liquidación nace en él desde
`liquidate_order()` y no está enviada todavía. El documento de la actividad lo
dibuja como origen del flujo (§4) aunque no lo lista en la tabla de códigos
(§5); se implementó como un valor propio de `ReviewStatus` para no dejar el
estado inicial sin representar.

### Ventana de edición

| Estado de revisión | ¿Editable? |
|---|---|
| `LIQUIDATED` | Sí — el técnico aún la está construyendo. |
| `SUBMITTED` | **No** — bloqueada. |
| `CORRECTION_REQUESTED` | Sí — única ventana de corrección. |
| `RESUBMITTED` | **No** — bloqueada. |
| `VALIDATED` | **No** — bloqueada definitivamente. |

Expuesto en el modelo como `is_editable`, `is_locked`, `is_validated`,
`can_be_validated`, `has_pending_correction` y `correction_available`.

---

## 3. Estado de la orden vs. estado de revisión

Son **dos dimensiones distintas** y no deben mezclarse.

| | `WorkOrder.status` | `WorkOrderLiquidation.review_status` |
|---|---|---|
| Responde a | Dónde está la **orden** en la operación de campo. | Dónde está el **documento de liquidación** en su revisión administrativa. |
| Lo mueve | El workflow operativo (`change_status()`). | Los servicios de revisión de `services.py`. |
| Ejemplo | `LIQUIDATED` | `SUBMITTED`, `CORRECTION_REQUESTED`, … |

Una orden permanece en `WorkOrder.Status.LIQUIDATED` mientras su liquidación
recorre **todo** el ciclo de revisión. Validar la liquidación **no** cambia el
estado de la orden.

---

## 4. Regla de una sola corrección

`correction_count` **nunca** supera 1. La regla se defiende en tres capas:

1. **Servicio** — `request_liquidation_correction()` y `resubmit_liquidation()`
   exigen `correction_count == 0` antes de actuar. El reenvío lo verifica
   **antes** de consumir la oportunidad.
2. **Modelo** — `MaxValueValidator(1)` en el campo y una comprobación explícita
   en `clean()`.
3. **Base de datos** — `CheckConstraint` `wo_liq_correction_count_max_1`.

El motivo de corrección (`correction_reason`) es **obligatorio**: sin él el
técnico no sabe qué rectificar y la auditoría queda incompleta.

---

## 5. Permiso funcional del validador

```
work_orders.validate_liquidation
```

Declarado en `WorkOrderLiquidation.Meta.permissions`. Quien tenga el permiso
puede validar o solicitar corrección, **sin importar su área**.

La autorización **no** consulta `user.role`. No existe ningún
`if user.role == 'NOC'` en el flujo: eso amarraría la operación a un
organigrama que todavía puede cambiar. La asignación concreta del permiso a
roles o grupos se definirá en una fase posterior.

Corregir es distinto de validar: `resubmit_liquidation()` solo acepta al
técnico responsable de la liquidación (`liquidated_by`) o al técnico asignado a
la orden — la reasignación de una orden no debe dejar la corrección sin nadie
que pueda ejecutarla.

---

## 6. Campos de control

En `WorkOrderLiquidation`:

| Campo | Uso |
|---|---|
| `review_status` | Estado del ciclo de revisión. |
| `submitted_by` / `submitted_at` | Quién envió a revisión y cuándo. |
| `submission_remarks` | Observación del envío. |
| `correction_count` | Correcciones consumidas. Tope duro: 1. |
| `correction_reason` | Motivo indicado por el validador. Obligatorio. |
| `correction_requested_by` / `correction_requested_at` | Quién pidió la corrección y cuándo. |
| `resubmitted_at` | Fecha del reenvío. |
| `validated_by` / `validated_at` | Quién validó y cuándo. |
| `validation_remarks` | Observación de la validación. |

`clean()` impide que el estado y sus fechas se contradigan: una liquidación
`VALIDATED` sin `validated_at`/`validated_by`, una `RESUBMITTED` sin
`resubmitted_at`, una `CORRECTION_REQUESTED` sin motivo o fecha, o una
`validated_at` en un estado que no sea `VALIDATED`.

---

## 7. Servicios implementados

Todos en `apps/work_orders/services.py`, todos con `transaction.atomic`. Son el
**único** camino legítimo para mover `review_status`: ni el Admin ni las vistas
lo tocan directamente.

### `submit_liquidation(liquidation, user, remarks='')`

`LIQUIDATED → SUBMITTED`. Exige liquidación ya registrada, usuario activo y
`resolution_detail` no vacío. Registra `submitted_by` y `submitted_at`. A
partir de aquí la liquidación queda bloqueada.

### `request_liquidation_correction(liquidation, validator, reason)`

`SUBMITTED → CORRECTION_REQUESTED`. Exige estado `SUBMITTED`, validador con el
permiso funcional, motivo no vacío y `correction_count == 0`. Registra
`correction_reason`, `correction_requested_by` y `correction_requested_at`.

### `resubmit_liquidation(liquidation, technician, changes, remarks='')`

`CORRECTION_REQUESTED → RESUBMITTED`. Exige estado `CORRECTION_REQUESTED`,
`correction_count == 0` y técnico autorizado.

`changes` acepta los campos de `LIQUIDATION_CORRECTABLE_FIELDS`
(`resolution_detail`, `technical_notes` y los datos técnicos: elemento de red,
puerto, serie, nivel de señal, metros de cable, referencia Krill) y,
opcionalmente, la clave `items` para redeclarar los materiales/equipos.

En un solo movimiento atómico: aplica los cambios, incrementa
`correction_count` a 1, registra `resubmitted_at`, pasa a `RESUBMITTED` y crea
la traza de la corrección. Vuelve a bloquear la edición.

### `validate_liquidation(liquidation, validator, remarks='')`

`SUBMITTED` o `RESUBMITTED` → `VALIDATED`. Exige validador con el permiso
funcional. Registra `validated_by` y `validated_at`, y bloquea toda edición
funcional. La información queda disponible para consulta y auditoría.

**No cierra la orden.**

---

## 8. Trazabilidad de versiones

No basta con guardar el valor final. `WorkOrderLiquidationCorrection` conserva
el snapshot completo de la única corrección:

| Campo | Contenido |
|---|---|
| `liquidation` | Liquidación corregida. |
| `corrected_by` | Usuario que realizó la corrección. |
| `correction_reason` | Motivo indicado por el validador. |
| `values_before` / `values_after` | Solo los campos que **efectivamente** cambiaron. |
| `items_before` / `items_after` | Materiales declarados antes y después. |
| `remarks` | Observación del técnico. |
| `created_at` | Fecha de modificación. |

Los items se guardan aparte porque `resubmit_liquidation()` los borra y los
recrea: sin ese snapshot la versión previa se perdería.

`summary()` devuelve el formato del documento de la actividad:

```
ANTES: equipment_serial=ABC123 | network_port=5
MOTIVO: Serie de ONU incorrecta
DESPUÉS: equipment_serial=XYZ987 | network_port=5
```

---

## 9. Transacciones y consistencia

Los tres servicios que escriben más de una fila usan `transaction.atomic`, de
modo que no queden estados parciales:

- Si el reenvío falla, no se aplican los cambios, **no** se incrementa
  `correction_count` y no se crea la traza: la liquidación sigue en
  `CORRECTION_REQUESTED` con su oportunidad intacta.
- Si la validación falla, **no** queda `validated_at` grabado.
- `review_status` y sus fechas asociadas no pueden quedar en contradicción.

---

## 10. Django Admin

`WorkOrderLiquidationAdmin` es una **interfaz de revisión**, no de edición.

- Muestra en el listado: `review_status`, `correction_count`,
  `correction_requested_by` / `correction_requested_at`, `validated_by` /
  `validated_at`. Filtrable por estado de revisión y por correcciones.
- Todo el ciclo de revisión es `readonly`: `review_status` **no** puede
  editarse a mano y `VALIDATED` **no** puede marcarse desde un select.
- `has_add_permission`, `has_change_permission` y `has_delete_permission`
  devuelven `False`: la liquidación y sus evidencias quedan protegidas contra
  borrado.
- `WorkOrderLiquidationCorrectionInline` muestra la traza de la corrección
  dentro de la liquidación; `WorkOrderLiquidationCorrectionAdmin` permite
  consultarla y buscarla de forma independiente. Ambos de solo lectura.

Saltarse los servicios desde el Admin no es posible: no hay ningún formulario
que escriba `review_status`.

---

## 11. Pruebas agregadas

`apps/work_orders/tests/test_liquidation_review.py` — 25 pruebas (las 24
obligatorias del checklist más una que verifica que validar no cierra la
orden). La numeración de cada docstring corresponde al checklist de la
actividad.

**`LiquidationSubmissionTests`** — envío formal

| # | Prueba |
|---|---|
| 1 | La liquidación puede enviarse a `SUBMITTED` |
| 2 | Una liquidación `SUBMITTED` queda bloqueada para edición libre |

**`LiquidationValidationTests`** — validación única

| # | Prueba |
|---|---|
| 3 | Un validador autorizado puede validar desde `SUBMITTED` |
| 4 | Un usuario sin el permiso funcional no puede validar |
| 5 | La validación registra `validated_by` |
| 6 | La validación registra `validated_at` |
| 7 | Una liquidación `VALIDATED` no puede volver a `SUBMITTED` |
| + | La validación **no** cierra la orden |

**`LiquidationCorrectionRequestTests`** — solicitud de corrección

| # | Prueba |
|---|---|
| 8 | El validador puede solicitar corrección desde `SUBMITTED` |
| 9 | El motivo de corrección es obligatorio |
| 10 | Se registra `correction_requested_by` |
| 11 | Se registra `correction_requested_at` |
| 12 | Se guarda `correction_reason` |
| 13 | No se puede solicitar corrección si `correction_count` ya es 1 |

**`LiquidationResubmissionTests`** — única corrección y reenvío

| # | Prueba |
|---|---|
| 14 | El técnico puede corregir cuando el estado es `CORRECTION_REQUESTED` |
| 15 | Otro usuario no autorizado no puede corregir |
| 16 | El reenvío cambia el estado a `RESUBMITTED` |
| 17 | El reenvío incrementa `correction_count` a 1 |
| 18 | El reenvío registra `resubmitted_at` |
| 19 | No se permite un segundo reenvío ni una segunda corrección |
| 20 | Puede validarse una liquidación `RESUBMITTED` |
| 21 | Después de `VALIDATED` no se permite edición |

**`LiquidationReviewAtomicityTests`** — transacciones

| # | Prueba |
|---|---|
| 22 | Una falla durante el reenvío revierte los cambios |
| 23 | Una falla durante la validación no deja `validated_at` parcial |

**`LiquidationCorrectionTraceabilityTests`** — auditoría

| # | Prueba |
|---|---|
| 24 | La trazabilidad conserva los valores antes y después |

La prueba 4 aísla el permiso como única causa de la autorización: el usuario
sin permiso tiene **el mismo rol** que el validador autorizado.

---

## 12. Trabajo pendiente para el cierre definitivo

Esta fase deja la liquidación en `VALIDATED` y la orden en su estado operativo
actual. Queda pendiente de definir:

- El estado `WorkOrder.Status.CLOSED` y sus transiciones de cierre.
- Si el cierre es automático al validar o requiere una acción explícita.
- Qué condiciones adicionales debe cumplir una orden para cerrarse.
- La asignación concreta del permiso `work_orders.validate_liquidation` a roles
  o grupos.

**No implementado en esta fase, por definición de la actividad:** doble
validación NOC + almacén, cierre definitivo de la orden, inventario real,
kardex, stock por técnico, descuento automático de materiales, integración
Krill, integración RENIEC, Azure Blob Storage, PWA del técnico y notificaciones
WhatsApp.
