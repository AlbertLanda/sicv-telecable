\# Flujo de registro de clientes, direcciones y suscripciones



\## 1. Contexto



El nuevo SICV cuenta actualmente con una base de dominio para clientes,

direcciones, suscripciones, contratos y órdenes de trabajo.



La consulta y ficha funcional de clientes ya fue desarrollada y permite

buscar clientes, consultar su información consolidada, visualizar sus

direcciones, suscripciones, contratos y órdenes de trabajo.



Esta actividad tiene como finalidad documentar y preparar el flujo de alta

de clientes y suscripciones sin modificar el motor existente de órdenes de

trabajo ni generar cambios innecesarios en la arquitectura.



El flujo funcional considerado es:



BUSCAR CLIENTE

→ NO EXISTE

→ REGISTRAR CLIENTE

→ REGISTRAR DIRECCIÓN

→ CREAR SUSCRIPCIÓN

→ CONTRATO

→ ORDEN DE INSTALACIÓN



La generación de la orden de instalación queda fuera del alcance de esta

actividad.



\---



\# 2. Objetivo



Definir de manera ordenada el flujo funcional y técnico para:



\- registrar clientes;

\- validar duplicados;

\- distinguir persona natural y jurídica;

\- registrar una o más direcciones;

\- crear una suscripción;

\- preparar la relación con el contrato;

\- establecer validaciones;

\- definir mensajes funcionales;

\- establecer casos de prueba;

\- proponer las pantallas necesarias.



La implementación futura deberá utilizar los modelos existentes y evitar

duplicar lógica de dominio.



\---



\# 3. Estado actual de implementación



A la fecha de esta documentación se encuentra implementado y validado:



\- búsqueda de clientes;

\- ficha de cliente;

\- registro de cliente;

\- registro de dirección;

\- selección de dirección para una suscripción;

\- selección de tipo de servicio;

\- selección de plan;

\- validación de plan contra tipo de servicio;

\- número de servicio;

\- validación de duplicidad del número de servicio;

\- creación de suscripción;

\- estado inicial de suscripción en `PRESALE`;

\- relación de suscripción con cliente;

\- relación de suscripción con dirección;

\- relación de suscripción con tipo de servicio;

\- relación de suscripción con plan;

\- restricción única para cliente + tipo de servicio + número de servicio;

\- creación de contrato como entidad relacionada con cliente y suscripción.



Las pruebas automatizadas actuales se encuentran operativas.



Resultado de la última ejecución:



&#x20;   Found 77 test(s).

&#x20;   Ran 77 tests

&#x20;   OK



También se ejecutó:



&#x20;   python manage.py check



Resultado:



&#x20;   System check identified no issues.



\---



\# 4. Flujo funcional general



\## 4.1 Buscar cliente



El operador debe iniciar el proceso buscando al cliente antes de crear

un nuevo registro.



La búsqueda debe utilizar principalmente el tipo y número de documento.



\### Resultado A: cliente encontrado



No se debe crear un nuevo cliente automáticamente.



Se debe mostrar la información suficiente para que el operador pueda:



\- ver la ficha;

\- utilizar el cliente existente;

\- cancelar la operación.



\### Resultado B: cliente no encontrado



El operador puede continuar con el registro de un nuevo cliente.



\---



\# 5. Registro de cliente



El formulario debe adaptarse al tipo de persona seleccionado.



\## 5.1 Persona natural



Campos principales:



\- tipo de documento;

\- número de documento;

\- nombres;

\- apellido paterno;

\- apellido materno;

\- teléfono;

\- teléfono secundario;

\- correo;

\- sede.



\## 5.2 Persona jurídica



Campos principales:



\- tipo de documento;

\- número de documento;

\- razón social;

\- teléfono;

\- teléfono secundario;

\- correo;

\- sede.



Los campos exclusivos de persona natural no deben ser presentados como

obligatorios para una persona jurídica.



La razón social debe ser obligatoria para una persona jurídica.



\---



\# 6. Matriz de campos de Customer



| Campo | Obligatorio | Aplica a | Validación | Observación |

|---|---|---|---|---|

| document\_type | Sí | Todos | Valor permitido | Debe ser coherente con el tipo de persona |

| document\_number | Sí | Todos | Formato y duplicidad | Identificador principal de búsqueda |

| person\_type | Sí | Todos | Natural/Jurídica | Determina los campos visibles |

| first\_name | Condicional | Natural | No vacío cuando corresponda | No aplica a empresa |

| paternal\_surname | Condicional | Natural | Según modelo/regla funcional | No aplica a empresa |

| maternal\_surname | Según modelo | Natural | Según modelo/regla funcional | No aplica a empresa |

| business\_name | Condicional | Jurídica | Obligatorio para empresa | Razón social |

| phone | Según modelo | Todos | Longitud/formato | Debe definirse criterio operativo |

| secondary\_phone | No | Todos | Longitud/formato | Opcional |

| email | No | Todos | Formato email | Opcional |

| branch | Sí | Todos | Sede válida | Sede responsable |



No se deben agregar campos que no existan actualmente en el modelo sin

identificarlos expresamente como propuesta.



\---



\# 7. Reglas de duplicidad



\## 7.1 Documento



Si ya existe un cliente con el mismo documento:



\- no se debe crear automáticamente otro cliente;

\- se debe informar al operador;

\- se debe ofrecer consultar o utilizar el cliente existente.



Para DNI:



> El DNI ingresado ya se encuentra registrado.



Para RUC:



> El RUC ingresado ya pertenece a un cliente.



\## 7.2 Código de cliente



El código existente debe considerarse una coincidencia exacta.



\## 7.3 Teléfono



La repetición del teléfono no debe bloquear automáticamente el registro

sin una definición funcional adicional.



Propuesta:



\- advertencia cuando el teléfono ya existe;

\- permitir continuar si el operador confirma.



Esta regla queda pendiente de validación con TI/negocio.



\## 7.4 Correo



La repetición del correo tampoco debe bloquear automáticamente el

registro sin una definición funcional.



Propuesta:



\- mostrar advertencia;

\- permitir continuar si corresponde.



\---



\# 8. Persona natural y persona jurídica



\## Persona natural



Debe permitir:



\- DNI;

\- nombres;

\- apellido paterno;

\- apellido materno.



\## Persona jurídica



Debe permitir:



\- RUC;

\- razón social.



Debe evitarse mostrar campos personales innecesarios para una empresa.



También debe validarse la coherencia entre:



\- tipo de persona;

\- tipo de documento;

\- información ingresada.



Ejemplo:



> El tipo de documento seleccionado no corresponde al tipo de persona.



\---



\# 9. Registro de dirección



El cliente puede tener una o más direcciones.



La dirección debe estar asociada directamente al cliente.



Campos contemplados por el dominio:



\- dirección;

\- referencia;

\- distrito;

\- zona;

\- número de medidor;

\- latitud;

\- longitud;

\- enlace GPS;

\- indicador de dirección principal.



La existencia de otros campos debe verificarse directamente contra el

modelo vigente antes de implementarlos.



\---



\# 10. Dirección principal



El sistema debe permitir identificar una dirección como principal.



Debe existir una regla para evitar que un cliente termine con múltiples

direcciones principales simultáneamente.



Comportamiento propuesto:



Si se registra una nueva dirección como principal:



1\. identificar la dirección principal actual;

2\. retirar el indicador de principal de la anterior;

3\. marcar la nueva dirección como principal.



Esta regla debe validarse antes de implementarse definitivamente.



\---



\# 11. Múltiples direcciones



Un cliente puede tener más de una dirección.



Ejemplos:



\- domicilio;

\- local comercial;

\- oficina;

\- segunda vivienda;

\- nueva ubicación de servicio.



Una suscripción debe seleccionar explícitamente la dirección donde se

prestará el servicio.



Por lo tanto:



CLIENTE

→ puede tener múltiples DIRECCIONES

→ cada SUSCRIPCIÓN utiliza una DIRECCIÓN.



\---



\# 12. Creación de suscripción



La creación de una suscripción requiere:



1\. cliente;

2\. dirección;

3\. tipo de servicio;

4\. plan;

5\. número de servicio;

6\. ciclo de facturación, cuando corresponda.



La implementación actual ya recibe el cliente desde la URL y restringe

las direcciones disponibles a las pertenecientes a dicho cliente.



También se valida que:



\- la dirección pertenezca al cliente;

\- el plan corresponda al tipo de servicio;

\- no exista el mismo número de servicio para el cliente y tipo de servicio.



\---



\# 13. Estado inicial de la suscripción



Una nueva venta debe comenzar en:



&#x20;   PRESALE



Interpretación:



> Preventa.



La creación de la suscripción no representa todavía una instalación.



El cambio posterior de estado deberá ocurrir mediante el flujo operativo

correspondiente.



No se debe modificar el motor de órdenes de trabajo como parte de esta

actividad.



\---



\# 14. Regla de número de servicio



Actualmente `Subscription.service\_number` es un campo numérico positivo.



Además existe una restricción única sobre:



&#x20;   customer

&#x20;   service\_type

&#x20;   service\_number



Por lo tanto, un cliente puede tener múltiples servicios, siempre que no

repita el mismo número de servicio dentro del mismo tipo de servicio.



Ejemplo:



Cliente 1001:



\- Internet #1

\- TV #1

\- Internet #2



La combinación prohibida sería:



\- Internet #1

\- Internet #1 nuevamente.



\---



\# 15. Validación de plan



El plan pertenece a un tipo de servicio.



Por lo tanto:



&#x20;   Tipo de servicio → Plan



debe mantener correspondencia.



Ejemplo:



Si se selecciona:



&#x20;   Internet



el plan debe pertenecer a Internet.



Si el usuario intenta seleccionar un plan de otro servicio, debe mostrarse:



> El plan seleccionado no pertenece al tipo de servicio elegido.



\---



\# 16. Contrato



El modelo `Contract` actualmente contiene:



\- contract\_number;

\- customer;

\- subscription;

\- start\_date;

\- end\_date;

\- status;

\- notes;

\- is\_active;

\- created\_at;

\- updated\_at.



Estados disponibles:



\- DRAFT;

\- ACTIVE;

\- SUSPENDED;

\- CANCELLED;

\- FINISHED.



El contrato mantiene relación directa con:



\- Customer;

\- Subscription.



El número de contrato es obligatorio y único.



La fecha de inicio es obligatoria.



La fecha de finalización es opcional.



Las observaciones son opcionales.



\---



\# 17. Relación suscripción → contrato



La relación funcional propuesta es:



&#x20;   Cliente

&#x20;      ↓

&#x20;   Suscripción

&#x20;      ↓

&#x20;   Contrato



Sin embargo, el modelo actual no establece por sí mismo una regla de

generación automática del contrato.



Por ello, queda pendiente definir:



\- cuándo se crea el contrato;

\- quién lo crea;

\- si se genera automáticamente;

\- cuándo se asigna contract\_number;

\- qué estado inicial debe utilizar;

\- cuál debe ser start\_date;

\- si una suscripción puede tener más de un contrato.



No se debe asumir que el contrato se genera automáticamente hasta que

esta regla sea aprobada funcionalmente.



\---



\# 18. Orden de instalación



La orden de instalación forma parte del flujo posterior:



&#x20;   SUSCRIPCIÓN

&#x20;       ↓

&#x20;   CONTRATO

&#x20;       ↓

&#x20;   ORDEN DE INSTALACIÓN



Sin embargo, la creación o modificación del motor de órdenes de trabajo

queda fuera de esta actividad.



No se deben modificar:



\- apps/work\_orders/models.py

\- apps/work\_orders/services.py

\- WorkOrder.Status

\- WorkOrderLiquidation



\---



\# 19. Flujo completo propuesto



```text

BUSCAR CLIENTE

&#x20;      │

&#x20;      ├── CLIENTE EXISTE

&#x20;      │       │

&#x20;      │       ├── Ver ficha

&#x20;      │       ├── Usar cliente

&#x20;      │       └── Cancelar

&#x20;      │

&#x20;      └── CLIENTE NO EXISTE

&#x20;              │

&#x20;              ↓

&#x20;       REGISTRAR CLIENTE

&#x20;              │

&#x20;              ↓

&#x20;       VALIDAR DUPLICADOS

&#x20;              │

&#x20;              ↓

&#x20;       REGISTRAR DIRECCIÓN

&#x20;              │

&#x20;              ↓

&#x20;       SELECCIONAR SERVICIO

&#x20;              │

&#x20;              ↓

&#x20;       SELECCIONAR PLAN

&#x20;              │

&#x20;              ↓

&#x20;       ASIGNAR NÚMERO

&#x20;              │

&#x20;              ↓

&#x20;       RESUMEN

&#x20;              │

&#x20;              ↓

&#x20;       CREAR SUSCRIPCIÓN

&#x20;              │

&#x20;              ↓

&#x20;           PRESALE

&#x20;              │

&#x20;              ↓

&#x20;       DEFINIR CONTRATO

&#x20;              │

&#x20;              ↓

&#x20;      FLUJO TÉCNICO POSTERIOR

&#x20;              │

&#x20;              ↓

&#x20;     ORDEN DE INSTALACIÓN

---

---

# 20. Propuesta de pantallas

La implementación futura deberá mantener un flujo claro y progresivo,
evitando solicitar información que todavía no sea necesaria.

El flujo propuesto se divide en las siguientes pantallas.

## 20.1 Pantalla 1 - Buscar cliente

Objetivo:

Determinar si el cliente ya existe antes de iniciar un nuevo registro.

Campos principales:

- Tipo de documento.
- Número de documento.

Acciones:

- Buscar.
- Limpiar.
- Registrar nuevo cliente, únicamente cuando no exista coincidencia.

Resultado esperado:

### Cliente encontrado

Mostrar información resumida:

- Código de cliente.
- Documento.
- Nombre o razón social.
- Teléfono.
- Sede.
- Estado.

Acciones:

- Ver ficha.
- Usar cliente.
- Cancelar.

### Cliente no encontrado

Mostrar mensaje:

> No se encontró un cliente con los datos ingresados. Puede continuar con el registro.

Acción:

- Registrar cliente.

---

## 20.2 Pantalla 2 - Datos generales del cliente

La pantalla debe adaptar los campos según el tipo de persona.

### Persona natural

```text
Tipo de persona: Natural

Tipo de documento: [ DNI ▼ ]
Número de documento: [             ]

Nombres:             [             ]
Apellido paterno:    [             ]
Apellido materno:    [             ]

Teléfono:            [             ]
Teléfono secundario: [             ]
Correo electrónico:  [             ]

Sede:                [             ]

[Cancelar] [Continuar]

Tipo de persona: Jurídica

Tipo de documento: [ RUC ▼ ]
Número de documento: [             ]

Razón social:       [             ]

Teléfono:           [             ]
Teléfono secundario:[             ]
Correo electrónico: [             ]

Sede:               [             ]

[Cancelar] [Continuar]

