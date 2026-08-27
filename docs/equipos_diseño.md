# Diseño del modelo de Equipos / Equipo Susc.

> Documento de diseño — Día 1, Bloque Equipos (27 ago 2026).
> No implica creación de modelos ni migraciones. La implementación
> (modelo `Equipment` + migración) corresponde al día 2, en la rama
> `feature/equipos-base`.

## Contexto

El sistema anterior (telecable.cableoperador.com) expone en el menú de
cliente los módulos "Equipos" y "Equipo Susc.". Un equipo (decodificador,
router, ONT/módem) se asocia a una **suscripción** del cliente, no
directamente al cliente, para resolver sin ambigüedad qué equipo
corresponde a qué servicio cuando el cliente tiene más de una suscripción.

## Entidad: Equipo

| Campo | Tipo propuesto | Descripción |
|---|---|---|
| tipo | choice | Decodificador, Router, ONT/Módem, ... |
| marca | string | Marca del fabricante |
| modelo | string | Modelo comercial |
| numero_serie_mac | string (único) | Número de serie o dirección MAC |
| estado | choice | En stock, Asignado, Retirado, Dañado/Baja |

## Asociación: Equipo ↔ Suscripción (Equipo Susc.)

| Campo | Tipo propuesto | Descripción |
|---|---|---|
| equipo | FK a Equipo | Equipo asignado |
| suscripcion | FK a Subscription | Suscripción a la que se asocia |
| fecha_asignacion | date | Fecha en que se asignó el equipo |
| fecha_retiro | date (nullable) | Fecha de retiro, si aplica |
| tecnico_instalador | FK a User (nullable) | Técnico que instaló el equipo, si aplica |

## Referencia al sistema anterior

- Columna "Equipos": listado de equipos por tipo/estado.
- Columna "Equipo Susc.": vínculo equipo-suscripción con fechas de
  asignación/retiro y técnico instalador.

## Siguiente paso

Día 2 del bloque: crear el modelo `Equipment` (tipo, marca/modelo,
número de serie, estado) y su migración correspondiente, en la rama
`feature/equipos-base`, a partir de este diseño aprobado.