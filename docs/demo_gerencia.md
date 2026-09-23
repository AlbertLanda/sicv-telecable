# Demo de gerencia — contratos y firma

Este procedimiento crea una **SQLite nueva** para demostración sin eliminar la
base local anterior.

## 1. Conservar la base actual

Desde PowerShell, en la raíz del proyecto:

```powershell
if (Test-Path .\db.sqlite3) {
    Rename-Item .\db.sqlite3 .\db_legacy_antes_demo.sqlite3
}
```

La base anterior queda guardada como `db_legacy_antes_demo.sqlite3`.

## 2. Crear la base limpia

```powershell
python manage.py migrate
python manage.py preparar_demo_gerencia
```

El comando carga los catálogos reales del proyecto y luego crea exclusivamente
datos ficticios de demostración.

## 3. Credenciales locales

Contraseña común:

```text
Demo2026!
```

Usuarios:

- `gerencia_demo` — administrador.
- `atc_demo` — Atención al Cliente.
- `tecnico_demo` — técnico.

Estas credenciales son exclusivamente para una base local de demostración.
El comando se niega a ejecutarse con `DEBUG=False`.

## 4. Escenarios creados

### Contrato ya firmado

Un primer domicilio queda con:

- suscripción DUO 600;
- código de servicio propio;
- contrato activo;
- OT de instalación;
- firma ficticia;
- PDF firmado archivado;
- SHA-256 del PDF;
- instalación atendida y liquidada.

Sirve para mostrar el documento final y la trazabilidad.

### Firma en vivo

El mismo abonado tiene una segunda vivienda con:

- otra dirección;
- otro código de servicio;
- otra suscripción;
- otro contrato;
- otra OT de instalación;
- técnico `tecnico_demo`;
- estado **En atención**;
- contrato todavía sin firmar.

Este segundo escenario permite entrar al portal técnico y dibujar la firma
durante la presentación. Hasta que se firme, la instalación no puede cerrarse
como exitosa.

## 5. Volver a la base anterior

Detener Django y ejecutar:

```powershell
Remove-Item .\db.sqlite3
Rename-Item .\db_legacy_antes_demo.sqlite3 .\db.sqlite3
```

Los archivos de media generados por la demo están identificados bajo contratos
`CONT-DEMO-...` y no forman parte de la base histórica.
