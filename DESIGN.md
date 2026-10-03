---
name: SICV Telecable
description: Interfaz empresarial de consulta y operación diaria para Telecable.
colors:
  primary: '#0755a6'
  primary-hover: '#064887'
  primary-dark: '#053c78'
  brand-green: '#367d09'
  navigation-marker: '#8acd36'
  critical: '#a97113'
  canvas: '#f3f4f6'
  surface: '#fff'
  ink: '#202c38'
  muted: '#596775'
  border: '#d8dee5'
  input-border: '#aebbc7'
  soft: '#edf3fa'
  control-ink: '#344557'
  table-head: '#eaf0f5'
  table-border: '#e2e7ed'
  table-hover: '#f5f8fb'
  navigation: '#192734'
  navigation-text: '#cad5df'
  navigation-hover: '#26394a'
  navigation-active: '#2a4053'
  navigation-focus: '#a9d2ff'
  success-ink: '#166534'
  success-surface: '#e9f5ee'
  success-border: '#b6dac4'
  selection: '#c9e0f8'
  selection-ink: '#142b41'
  scrollbar: '#8da0b3'
  scrollbar-track: '#edf1f5'
typography:
  headline:
    fontFamily: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif
    fontSize: 1.625rem
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -.025em
  title:
    fontFamily: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif
    fontSize: 1rem
    fontWeight: 600
    lineHeight: 1.2
  customer-name:
    fontFamily: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif
    fontSize: 1.25rem
    fontWeight: 600
    lineHeight: 1.2
  metric:
    fontFamily: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif
    fontSize: clamp(1.5rem,2.2vw,2rem)
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: -.035em
  body:
    fontFamily: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif
    fontSize: .875rem
    fontWeight: 400
    lineHeight: 1.5
  table:
    fontFamily: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif
    fontSize: .8125rem
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif
    fontSize: .75rem
    fontWeight: 400
    lineHeight: 1.5
  small:
    fontFamily: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif
    fontSize: .6875rem
    fontWeight: 600
    lineHeight: 1.5
  button:
    fontFamily: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif
    fontSize: .875rem
    fontWeight: 600
    lineHeight: 1.5
  button-secondary:
    fontFamily: Inter, system-ui, -apple-system, 'Segoe UI', sans-serif
    fontSize: .875rem
    fontWeight: 500
    lineHeight: 1.5
rounded:
  track: 2px
  compact: 3px
  control: 4px
spacing:
  tight: 4px
  control: 8px
  compact: 12px
  cell: 16px
  section: 20px
  roomy: 24px
  canvas: 28px
components:
  button-primary:
    backgroundColor: '{colors.primary}'
    textColor: '{colors.surface}'
    typography: '{typography.button}'
    rounded: '{rounded.control}'
    padding: .375rem .75rem
    height: 40px
  button-primary-hover:
    backgroundColor: '{colors.primary-dark}'
    textColor: '{colors.surface}'
  button-secondary:
    backgroundColor: '{colors.surface}'
    textColor: '{colors.primary}'
    typography: '{typography.button-secondary}'
    rounded: '{rounded.control}'
    padding: 8px 14px
    height: 40px
  button-secondary-hover:
    backgroundColor: '{colors.soft}'
    textColor: '{colors.primary}'
  input-search:
    backgroundColor: '{colors.canvas}'
    textColor: '{colors.ink}'
    typography: '{typography.body}'
    rounded: '{rounded.control}'
    padding: .375rem .75rem
    height: 40px
  navigation-link:
    textColor: '{colors.navigation-text}'
    typography: '{typography.table}'
    rounded: '{rounded.compact}'
    padding: 8px 10px 8px 36px
    height: 40px
  navigation-link-hover:
    backgroundColor: '{colors.navigation-hover}'
    textColor: '{colors.surface}'
  navigation-link-active:
    backgroundColor: '{colors.navigation-active}'
    textColor: '{colors.surface}'
  service-tag:
    backgroundColor: '{colors.scrollbar-track}'
    textColor: '{colors.control-ink}'
    typography: '{typography.small}'
    rounded: '{rounded.compact}'
    padding: 2px 8px
  card:
    backgroundColor: '{colors.surface}'
    rounded: '{rounded.control}'
  table-cell:
    textColor: '{colors.ink}'
    typography: '{typography.table}'
    padding: 13px 16px
  record-tab:
    textColor: '{colors.muted}'
    typography: '{typography.body}'
    padding: 12px 18px
    height: 48px
  record-tab-active:
    backgroundColor: '{colors.surface}'
    textColor: '{colors.primary}'
---

# Design System: SICV Telecable

## Overview

**Creative North Star: "SICV Telecable"**

Una interfaz empresarial sobria para el trabajo diario de ATC, Contabilidad y Administración. La barra blanca identifica Telecable y la sede; la navegación de tinta separa las opciones globales del contenido neutro. El azul señala acciones y selección; el verde conserva la identidad de marca y la confirmación.

La densidad favorece consulta rápida, con jerarquía corta, separadores finos y cifras alineadas. La referencia es la documentación pública de Carbon adaptada a Django y Bootstrap, sin extracción de nodos de Figma ni reproducción de una pantalla de su kit. La evidencia visual revisada cubre panel, búsqueda de abonados, Información de la ficha y marco compartido; las composiciones de otros módulos y la preparación fiscal requieren revisión propia antes de extenderlas.

**Key Characteristics:**

- Jerarquía corta y texto en español claro.
- Superficies neutras, bordes finos y esquinas discretas.
- Acciones azules, marca verde y navegación de tinta.
- Tablas con enlaces explícitos y navegación por teclado.

## Colors

Paleta operativa contenida: azul de acción, verde de marca, tinta de navegación y neutros fríos. El frontmatter es la fuente normativa de valores; las variantes son estados reales, no una escala decorativa.

### Primary

- **Azul de acción** (`primary`): enlaces, botones y pestaña seleccionada. `primary-dark` es hover/foco del botón Bootstrap; `primary-hover` es hover del botón compartido de ficha.
- **Azul suave** (`soft`): respuesta de las acciones secundarias.

### Secondary

- **Verde Telecable** (`brand-green`): acento del nombre de marca. `navigation-marker` señala la opción global activa.
- **Confirmación** (`success-ink`, `success-surface`, `success-border`): estado activo con texto explícito.

### Tertiary

- **Ámbar de atención** (`critical`): punto del indicador de órdenes críticas.

### Neutral

- **Lienzo / superficie** (`canvas`, `surface`): fondo de trabajo y paneles. Algunos controles y tarjetas Bootstrap heredan el lienzo; no forzar blanco a todas las regiones.
- **Tinta / secundario** (`ink`, `muted`, `control-ink`): lectura principal, ayudas y controles.
- **Líneas** (`border`, `input-border`, `table-border`): contenedores, campos y filas.
- **Tabla** (`table-head`, `table-hover`): encabezados y respuesta de filas de la ficha.
- **Navegación de tinta** (`navigation`, `navigation-text`, `navigation-hover`, `navigation-active`, `navigation-focus`): marco oscuro, estados y foco contrastado.
- **Superficie del navegador** (`selection`, `selection-ink`, `scrollbar`, `scrollbar-track`): selección legible y barras de desplazamiento de tabla. El caret de los campos es azul; el del buscador de menú es blanco.

**The Acción reconocible Rule.** Reservar el azul para enlaces, acciones y selección; el ámbar marca la atención crítica y no decora las superficies.

## Typography

**Body Font:** Inter, con system-ui, -apple-system, Segoe UI y sans-serif de respaldo. La misma familia sirve a títulos y controles; no hay pareja ornamental ni fuente monoespaciada independiente.

El cuerpo usa el rol `body`; tablas, metadatos y menú usan `table`. `headline` corresponde al título de página, `title` a la sección y `customer-name` a la identidad de la ficha. `metric` aporta énfasis a los indicadores sin competir con las acciones. `label` y `small` sirven a etiquetas y detalles cortos. Los valores y pesos efectivos están en el frontmatter.

En móvil, el título de página y las cifras del panel bajan a (1.5rem); el nombre del abonado conserva su rol. Los encabezados específicos corporativos usan peso (600), mientras los encabezados genéricos heredados conservan (700). No extender el titular de acceso a pantallas operativas.

**The Cifras en columna Rule.** Usar numerales tabulares en importes, métricas y columnas numéricas; conservar cifras proporcionales en códigos y texto corriente.

## Layout

Barra superior adhesiva (64px). Menú de escritorio (240px), con contenido desplazado a su derecha y margen interior (28px 28px 48px). El área de página alcanza (1600px) y se centra. Ritmo de sección (20px–24px), con celdas y controles más compactos.

El panel usa cuatro métricas separadas y dos zonas de consulta en proporción (1.4:1); esto describe el panel, no una plantilla obligatoria para todos los módulos. Información usa dos columnas equivalentes. La ficha conserva identidad y pestañas al cambiar de consulta.

- Hasta (1199.98px): métricas en dos columnas; resumen del abonado en una columna y cifras bajo un separador horizontal.
- Hasta (991.98px): consultas e Información en una columna, margen principal (22px 20px 40px), menú móvil (280px) con fondo de cierre.
- Hasta (575.98px): margen principal (20px 12px 32px); acciones y búsqueda envuelven, pestañas en dos columnas y datos en una. Controles estándar tienen mínimo (44px), frente a (40px) en escritorio; botones pequeños conservan (32px).

Las tablas desplazan dentro de una región nombrada y enfocable, sin ensanchar el documento. Búsqueda mantiene ancho mínimo de tabla (1100px); detalles del panel (850px). El aviso «Desliza o usa las flechas para ver más columnas» aparece en móvil solo si hay columnas fuera de vista. Los campos y nombres pueden envolver texto largo.

## Elevation & Depth

Tarjetas, resumen de abonado y barra superior son planos, sin sombra. Líneas finas, fondos tonales y espacio establecen la profundidad. La opción de menú activa lleva una línea interior verde y la pestaña activa una línea interior azul. Estos marcadores son selección, no elevación.

El foco general usa contorno azul (2px), separado del control (3px); sobre el menú cambia a `navigation-focus`. Los campos Bootstrap conservan su halo de foco heredado y borde de foco; la implementación también conserva pequeñas sombras funcionales de pulsación y menús desplegables. Sus valores figuran en el sidecar, no en los tokens de superficie.

**The Plano por defecto Rule.** Separar contenido mediante tono, borde y espacio; no añadir sombras decorativas ni animaciones de entrada.

## Shapes

Esquinas pequeñas y rectangulares: `control` para tarjetas, campos y botones; `compact` para etiquetas y enlaces del menú; `track` para barras de consulta. Los contenedores se delimitan con borde (1px). La ficha usa avatar cuadrado suavizado, no medallón circular; se oculta en móvil. Las pestañas son una franja abierta con subrayado activo, sin cápsulas.

## Components

- **Botón principal:** azul con texto blanco y peso de interfaz fuerte. Bootstrap oscurece en hover/foco; el botón compartido de ficha usa `primary-hover` y `primary-dark` al pulsar. No unificar sus estados por suposición. Las transiciones heredadas solo afectan color, borde y respuesta funcional.
- **Botón secundario:** blanco con contorno, texto azul y padding (8px 14px). Hover en azul suave; foco general visible. Las acciones de ficha mantienen permisos y su ubicación contextual.
- **Campo de búsqueda:** fondo de lienzo heredado, borde de campo, esquinas `control`, texto `body` y etiqueta visible o accesible. Foco con halo Bootstrap más contorno corporativo; sin adornos nuevos.
- **Navegación:** enlaces compactos de tinta clara, hover tonal y activo con línea verde interior (3px). Menú móvil cierra con fondo o Escape, contiene el foco y vuelve al botón de apertura; contenido principal inerte mientras abre. La preferencia de escritorio se conserva por separado.
- **Etiquetas:** servicio neutro de tamaño `small`, compacto y rectangular; estado activo verde con texto. Son información estática, no botones de filtro. No fabricar comportamiento al hover.
- **Tarjetas y consultas:** superficie blanca o lienzo heredado según componente, borde fino y sin sombra. Cabeceras alineadas con el cuerpo; las secciones de Información usan padding lateral (20px), reducido a (16px) en móvil. Los enlaces de consulta responden con subrayado o cambio de color y foco visible.
- **Tablas y ficha:** cabecera tonal, texto `table`, celdas (13px 16px), importes alineados a la derecha. Nombre y código abren enlaces reales. Pestañas de ficha con altura mínima (48px), selección azul y hover tonal; la cabecera compartida puede reutilizarse sin dar por aprobada la composición de cada pestaña.

Movimiento reducido elimina duraciones de transición/animación y desplazamiento suave. El marco no anima al alternar el menú. Impresión elimina navegación, fondo de cierre y aviso de desbordamiento.

## Do's and Don'ts

### Do:

- Do conservar Inter, la identidad Telecable y las funciones reales de cada enlace.
- Do mantener un encabezado principal, etiquetas accesibles y foco visible.
- Do nombrar y hacer enfocables los contenedores de tablas anchas, con aviso móvil solo cuando hay desbordamiento.
- Do revisar cada nueva composición de módulo en escritorio y móvil antes de declararla aprobada.

### Don't:

- Don't convertir filas completas en controles ambiguos: enlazar el nombre o código y la acción pertinente.
- Don't usar color como único indicador de estado ni eliminar el foco del teclado.
- Don't añadir mayúsculas decorativas, sombras de tarjeta o animaciones de entrada al marco corporativo.
- Don't presentar las muestras QA como datos reales ni la preparación fiscal como emisión tributaria validada.
