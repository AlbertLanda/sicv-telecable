# Catálogos operativos

Las zonas y cajas NAP oficiales de Telecable están versionadas dentro del
repositorio para que una base nueva pueda reconstruir el mismo catálogo sin
depender de una SQLite local ni de archivos externos.

## Carga

Después de aplicar las migraciones:

```powershell
python manage.py cargar_catalogos_operativos
```

Para validar sin persistir:

```powershell
python manage.py cargar_catalogos_operativos --dry-run
```

El comando es idempotente: puede ejecutarse otra vez sin duplicar registros.

## Catálogo versionado

- Zonas: Jauja 25, Huancayo 9, La Oroya 41.
- NAP: Jauja 1113, Huancayo 830, La Oroya 590.

Los comandos `importar_zonas` e `importar_naps` se conservan para cargas
administrativas controladas. El comando `cargar_catalogos_operativos` es la
fuente reproducible para instalaciones nuevas y despliegues.
