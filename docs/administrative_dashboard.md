# Panel administrativo

URL: `/reportes/panel/`. Se abre al iniciar sesión para usuarios autorizados
al panel; está enlazado en la barra y menú lateral. Los otros roles conservan
el buscador como entrada. No modifica registros ni ejecuta órdenes.

## Reglas de esta primera entrega

- **Activos:** fichas `Customer.is_active=True`, incluidas preventas, por sede
  de la ficha. No equivale a servicios instalados. La política exacta del
  proveedor sigue pendiente; esta regla se muestra al operador.
- **Recaudación:** pagos `REGISTERED` por `paid_at` en el mes elegido y sede
  receptora del cobro; excluye pendientes, anulados, fechas futuras y registros
  antiguos sin fecha real de pago, cuyo contador se muestra para subsanar el
  dato. Una aplicación a varios cargos no duplica
  el ingreso. Puede mostrar un pago sin recibo; los recibos son internos.
- **Cartera:** cargos abiertos vencidos antes de hoy, de fichas habilitadas,
  por sede de la ficha. Saldo igual a `Charge.balance_on`: resta aplicaciones
  confirmadas y descuentos concedidos; excluye futuros, anulados y saldo cero.
  Cuenta abonados distintos. Los tramos clasifican todo su saldo vencido por
  el vencimiento más antiguo; esta política se explicita en pantalla.
- **Órdenes:** `WorkOrder.ACTIVE_STATUSES`, por sede de la orden y creación.
  Críticas estrictamente mayores de 48 horas; el redondeo solo es visual.
  Incluye órdenes sin suscripción (p. ej. planta externa) sin inventar abonado.

La hora y fechas usan `America/Lima`. Panel y detalle comparten selectores,
criterios y filtros; cada consulta tiene su propia hora visible. La consulta
no es una instantánea histórica inmutable: un movimiento puede cambiar el
resultado entre abrir la tarjeta y el detalle. No se comparan porcentajes
mensuales hasta validar el periodo anterior; el gráfico señala el mes en curso.

## Permisos

`organization.view_operational_dashboard` permite el panel y sus listados.
`organization.view_consolidated_dashboard` habilita consultar todas las sedes
activas o seleccionar una. Administrador recibe ambos en su matriz base;
otros roles requieren concesión explícita. Las vistas comprueban permisos y
filtros en servidor; sin sede actual la consulta devuelve error, no datos
globales. Acceder a la ficha, recibo u orden utiliza las capacidades existentes.

Los detalles tienen búsqueda, paginación de 20/50/100 filas y total de todo el
filtro. Las URLs conservan alcance, sede, mes, antigüedad y búsqueda. Se ofrece
el total de pendientes además del detalle crítico, seis meses de recaudación
y tres tramos de deuda. El consolidado incluye un comparativo por sede y permite
abrir cada sede con el mismo mes. Las respuestas son privadas y no almacenables
en caché.

## Validación

`apps.reports.tests.test_dashboard` cubre conciliación de totales, pagos
pendientes/anulados, descuentos ganados, varias aplicaciones por cargo,
agrupación y antigüedad, corte de 48 horas, permisos por URL, consolidación,
paginación, filtros inválidos, medianoche de Lima y ausencia de consultas por
cada cargo. El saldo SQL se contrasta con el cálculo existente de la ficha.

No incluye emisión electrónica real, cierre persistido de caja, alertas
fiscales ni equivalencia certificada con las consultas internas del proveedor.
