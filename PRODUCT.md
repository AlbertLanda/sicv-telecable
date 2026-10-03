# SICV Telecable

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Personal de ATC, Contabilidad y administradores de Telecable. El portal de técnicos es una superficie distinta. ATC no asigna técnicos: los técnicos consultan las órdenes y se distribuyen su atención.

## Product Purpose

Reemplazar el sistema comercial actual con un sistema propio para abonados, servicios, cobranza, documentos y operaciones. Permitir cambios oportunos y facilitar el trabajo diario.

## Operating Context

Sedes de Jauja, Huancayo y La Oroya. La empresa valida los avances en Azure QA. El panel debe facilitar lectura de indicadores y acceso a sus detalles por sede y consolidado.

## Capabilities and Constraints

Django modular con plantillas; Python 3.11 en CI/Azure y PostgreSQL en nube. El panel existente tiene permisos separados para indicadores y consolidado. Su cálculo de activos corresponde provisionalmente a fichas habilitadas, incluidas preventas. Recaudación usa pagos confirmados por fecha real de pago. El backend validado debe conservarse durante el rediseño. La emisión fiscal real requiere integrar y validar el proveedor OSE; la preparación actual no equivale a emisión real.

## Brand Commitments

Nombre Telecable, logo existente en `apps/work_orders/static/work_orders/branding/telecable-logo.jpg`. El usuario solicita apariencia empresarial, uso rápido e identidad propia. La paleta, tipografía y composición definitivas quedan pendientes de elegir entre propuestas.

## Evidence on Hand

Panel y detalles existentes en `apps/reports/`, documentación en `docs/administrative_dashboard.md`, logo corporativo. Las propuestas visuales utilizan datos ficticios etiquetados; sus cifras no representan la operación real.

## Product Principles

- Permitir encontrar información y acciones rápidamente.
- Conservar las reglas y los permisos ya validados.
- Explicar estados, cálculos y errores en español claro.
- Validar propuestas visuales antes de extenderlas a otros módulos.
