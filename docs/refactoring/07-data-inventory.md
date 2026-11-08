# Inventario de datos e integridad v01

Fecha: 2026-11-06. Alcance: Prompt 02, comando `audit_refactoring`.

Referencias: [arquitectura actual](01-current-architecture.md),
[arquitectura objetivo](02-target-architecture.md),
[plan de migracion](03-data-migration-plan.md),
[roadmap](04-refactoring-roadmap.md), [riesgos](05-risk-register.md) y
[decisiones pendientes](06-decisions-required.md).

## Procedencia del entorno

La conexion original de Podman estaba desactualizada: apuntaba al puerto 61427,
mientras la maquina iniciada durante el diagnostico exponia SSH en 56851. Al
consultar ese motor directamente no habia contenedores ni volumenes de Telar.
Esto no demuestra que los manuscritos anteriores estuvieran vacios ni que hayan
sido borrados: su ubicacion sigue sin conocerse.

Despues del diagnostico, el usuario autorizo crear otra maquina y empezar con
datos nuevos de prueba. Se creo `telar-fabulas-dev` en modo rootless con recursos
solicitados de 2 CPU, 2048 MiB de memoria y 40 GiB de disco. Los limites efectivos
de WSL dependen tambien de su configuracion global.

El primer inicio coincidio con un error `user@1000.service: Device or resource
busy`. Se detuvo la maquina anterior, iniciada para el diagnostico, y se reinicio
solo la nueva. El motor nuevo respondio correctamente como rootless. El sintoma
es compatible con el [conflicto documentado de WSL/systemd](https://github.com/microsoft/WSL/issues/40593),
sin necesidad de reinstalar herramientas ni cambiar a rootful.

No se elimino ninguna maquina ni volumen, no se uso `down -v` y no se restauro
ningun respaldo. La autorizacion posterior se limita a inicializar el entorno
nuevo con las migraciones ya existentes; no autoriza transformar datos legacy.
La conexion predeterminada global se conserva. Todos los comandos operativos de
esta fase seleccionan explicitamente `--connection telar-fabulas-dev`.

## Implementacion y garantias

- Se consultan siete conjuntos mediante el ORM: usuarios, proyectos, nodos,
  personajes, notas, menciones y exportaciones. El total no incluye sesiones,
  permisos, estilos ni papeles dramaticos.
- Las siete consultas son masivas, sin consultas adicionales por nodo. PostgreSQL
  usa una transaccion `REPEATABLE READ, READ ONLY` cuando no existe una exterior.
  Un guard de ejecucion rechaza sentencias distintas de `SELECT` durante la
  carga ORM, tambien dentro de las transacciones de las pruebas.
- El comando no invoca `save`, `delete`, `update`, migraciones ni normalizaciones.
  No recalcula contadores persistidos, no cambia IDs ni relaciones y no convierte
  estados editoriales.
- El texto permanece en PostgreSQL: SQL obtiene longitudes y banderas de texto
  no vacio. El reporte no incluye contenido, titulos, emails, nombres reales,
  nombres de archivo ni rutas sensibles. Usuarios se informan agregadamente.
- Ciclos y alcanzabilidad se analizan iterativamente, incluso en componentes sin
  raiz. Se revisan padres, proyecto, tipos, posiciones y referencias asociadas.
- Los archivos se inspeccionan solo mediante metadatos de existencia, extension
  y tamano. No se leen ni copian contenidos, no se generan URLs ni se enumeran
  archivos huerfanos. Se rechazan rutas inseguras o fuera del storage.
- `--output` crea exclusivamente un informe nuevo; no sobrescribe destinos,
  rechaza enlaces simbolicos como destino y no permite escribir en media ni
  staticfiles. Sin acceso a DB falla explicitamente, sin inventar conteos cero.

## Interpretacion de los indicadores

Las severidades son `CRITICAL`, `HIGH`, `MEDIUM` y `LOW`. Cada hallazgo se clasifica
como `READY`, `REQUIRES_MIGRATION`, `REQUIRES_DECISION` o `INVALID_DATA`.
Los contadores de registros usan pares unicos `(modelo, id)` dentro de cada
indicador; migracion, decision y datos invalidos pueden solaparse. Hallazgos de
configuracion o esquema pueden afectar cero registros y seguir siendo relevantes.

Contenido vacio incluye cadenas de espacios; la distribucion de longitud cuenta
caracteres y distingue esos espacios. Las palabras son la suma aproximada del
`word_count` persistido, sin releer ni corregir texto. No existe actualmente
`short_description`: `empty_descriptions` es `null`, no un cero inventado.

Las escenas se separan por estado y presencia de texto. `FRAGMENT`, texto fuera
de `SCENE`, escenas vacias y etapas avanzadas requieren decisiones explicitas.
`FINISHED`, `PUBLISHABLE` y `PUBLISHED` nunca se convierten automaticamente a
`FINAL`. No se crea `SceneVersion`.

El tamano de media suma referencias unicas con metadata disponible; no pretende
medir todo el disco. Una falla del backend no se presenta como archivo faltante.
DB y filesystem no comparten snapshot. Las referencias bajo jerarquias a revisar
incluyen sus descendientes. Un `root_node` nulo no permite distinguir una
exportacion de proyecto completo de una raiz previamente eliminada.

Los tipos FREE/PREMIUM no prueban pago ni vigencia. Trial y retencion anual
requieren decision; periodos mensual/anual, pago manual, Stripe y modo de solo
lectura al vencer requieren trabajo posterior, sin modificar usuarios ahora.

## Uso

Desde la raiz del proyecto, con la maquina nueva en ejecucion:

```powershell
podman machine start telar-fabulas-dev
podman --connection telar-fabulas-dev compose up -d
podman --connection telar-fabulas-dev compose exec web python manage.py audit_refactoring
podman --connection telar-fabulas-dev compose exec web python manage.py audit_refactoring --format json
podman --connection telar-fabulas-dev compose exec web python manage.py audit_refactoring --format markdown
podman --connection telar-fabulas-dev compose exec web python manage.py audit_refactoring --output /code/inventario_nuevo.json
```

Omitir `machine start` si ya esta encendida. Usar un nombre de informe que todavia
no exista. La extension `.json`, `.md` o `.txt` determina el formato si se omite
`--format`; si se especifican ambos, deben coincidir. El informe queda fuera de
media y no se sirve por HTTP. Revisar su alcance antes de compartirlo.

La TUI existente usa comandos sin nombre de maquina ni conexion explicita. Esta
fase no modifica su comportamiento ni cambia globalmente el contexto de otros
proyectos: para este entorno aislado usar los comandos anteriores.

## Validacion e inventario

### Resultado del entorno nuevo

El inventario se ejecuto el 2026-11-06 a las 20:11, hora de Mexico. Los timestamps
de los informes usan UTC (2026-11-07). **Son datos reales de una base nueva vacia,
no de la base anterior.** No se cargaron fixtures en la base de la aplicacion.

| Categoria | Registros en el entorno nuevo |
| --- | ---: |
| Usuarios | 0 |
| Proyectos | 0 |
| Nodos narrativos | 0 |
| Personajes | 0 |
| Notas | 0 |
| Menciones | 0 |
| Exportaciones | 0 |
| Total analizado en las siete categorias | 0 |

No hay jerarquias invalidas, ciclos, posiciones duplicadas, FRAGMENT, texto en
contenedores, estados ambiguos ni referencias rotas en **esta base vacia**. Hay
cero registros que necesiten migracion/decision y cero registros invalidos. No
se deduce nada sobre esas cantidades en los datos anteriores.

Hay cero referencias de archivos, cero referencias faltantes o fuera de su
ubicacion esperada, ninguna extension observada y cero bytes conocidos. No se
enumeraron ni abrieron archivos media. Este resultado no constituye una revision
de archivos antiguos ni una prueba de restauracion.

| Hallazgo | Severidad | Compatibilidad | Conclusion |
| --- | --- | --- | --- |
| DEBUG_MEDIA_ROUTE | HIGH | REQUIRES_MIGRATION | La configuracion DEBUG tiene una ruta directa de media; protegerla en F1. No se expuso ni descargo media durante la auditoria |
| DESCRIPTION_FIELD_ABSENT | LOW | REQUIRES_MIGRATION | Falta short_description en el esquema actual; no se inventa un conteo de descripciones vacias |
| READ_ONLY_INVENTORY | LOW | READY | El comando informa sin corregir registros |

Se detectan tres hallazgos: uno HIGH, dos LOW, cero CRITICAL y cero MEDIUM. Los
dos pendientes de esquema/configuracion no implican registros corruptos. Sin
poblacion legacy no es posible aprobar conversiones de narrativa ni declarar
resueltos los riesgos R01/R05/R07/R08/R17/R23 de la auditoria arquitectonica.

Informes generados por el comando y comprobados como JSON valido y Markdown con
todas las secciones requeridas:

- [JSON del entorno nuevo](07-inventory-new-environment.json).
- [Markdown del entorno nuevo](07-inventory-new-environment.md).

### Pruebas y comandos ejecutados

El motor se verifico rootless. Los cinco servicios estan arriba; PostgreSQL y
Redis iniciaron correctamente, Celery respondio `pong` y Beat registro su
arranque. `http://localhost:8000/` respondio HTTP 200 con el texto de bienvenida.

Antes de inicializar, la introspeccion PostgreSQL devolvio cero tablas. Se
confirmaron `telar_fabulas` como base de la aplicacion y `test_telar_fabulas` como
base separada de pruebas. No habia una base de pruebas anterior que reemplazar.
El runner creo y retiro exclusivamente su propia base temporal.

| Verificacion | Resultado |
| --- | --- |
| check local con uv --frozen --offline --no-sync | OK |
| 33 pruebas sin DB (analisis e interfaz CLI) | OK; no se preparo ninguna DB |
| Comparacion offline de modelos/migraciones | Sin cambios |
| compose up -d --build, con conexion explicita | OK; cinco servicios y cuatro volumenes nuevos |
| migrate --plan; migrate --noinput | Solo inicializacion autorizada de la base nueva con migraciones existentes |
| showmigrations | 25 aplicadas: 7 propias iniciales y 18 de Django; ninguna nueva creada |
| manage.py check en Podman | OK, sin incidencias |
| makemigrations --check --dry-run en Podman | No changes detected |
| test apps.manuscripts.test_audit_refactoring --verbosity 2 | 40/40 OK en 2.129 s |
| manage.py test, suite completa en PostgreSQL | 217/217 OK en 117.490 s; 177 previas y 40 nuevas |
| audit_refactoring, resumen y JSON directo | OK sobre las siete tablas de la aplicacion |
| --output JSON y Markdown | Archivos creados; formatos y secciones comprobados |
| celery -A config inspect ping | Un worker online, pong |
| logs de Beat y HTTP local | Scheduler iniciado; bienvenida HTTP 200 |
| Hashes SHA-256 de 155 archivos preexistentes | Sin cambios, incluidos docs 01-06 y diff_*.txt |

No hubo errores de la suite, preexistentes ni nuevos. Los fallos iniciales fueron
de entorno: conexion Podman obsoleta, base original ausente y conflicto de inicio
WSL. Una llamada local sin DB fallo de forma explicita sin generar un informe
vacio falso. Ninguno de esos fallos se contabiliza como prueba aprobada.

Las 40 pruebas del auditor cubren base vacia, proyecto sin manuscrito, jerarquia
objetivo valida/invalida, FRAGMENT, contenido no-SCENE, estados ambiguos, posiciones,
padres faltantes/cruzados, ciclos desconectados y profundidad de 3000 nodos;
notas/menciones/exports, referencias multiples y cruzadas, archivos faltantes,
rutas inseguras, metadata no disponible y privacidad; formatos de salida,
proteccion de destinos y ausencia de modificaciones. Las siete pruebas ORM
comparan valores completos antes/despues, revisan ausencia de DML y comprueban
que las consultas SELECT permanecen en siete al aumentar los nodos.

Comandos reproducibles de validacion (la seleccion explicita evita usar la
conexion anterior). `-T` desactiva solo la asignacion de terminal interactiva:

```powershell
podman --connection telar-fabulas-dev compose ps
podman --connection telar-fabulas-dev compose exec -T web python manage.py check
podman --connection telar-fabulas-dev compose exec -T web python manage.py showmigrations
podman --connection telar-fabulas-dev compose exec -T web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec -T web python manage.py test
podman --connection telar-fabulas-dev compose exec -T web python manage.py audit_refactoring
podman --connection telar-fabulas-dev compose exec -T web python manage.py audit_refactoring --format json
podman --connection telar-fabulas-dev compose exec -T worker celery -A config inspect ping
```

Para la inicializacion autorizada se ejecutaron ademas `podman machine init
--cpus 2 --memory 2048 --disk-size 40 telar-fabulas-dev`, `podman machine start
telar-fabulas-dev`, `podman --connection telar-fabulas-dev compose up -d --build`
y `podman --connection telar-fabulas-dev compose exec -T web python manage.py
migrate --noinput`. **No son instrucciones para reiniciar ni sustituir otra base
con datos.** La maquina anterior queda detenida y conservada.

No se genero superusuario ni se sembraron estilos; el usuario puede registrarse
en `/register/`. Para crear un administrador del nuevo entorno, ejecutar
interactivamente `podman --connection telar-fabulas-dev compose exec web python
manage.py createsuperuser`. No se establecio ninguna contrasena predeterminada.

## Archivos de esta fase

- `app/apps/manuscripts/audit.py`: consultas, analisis, metadata y serializacion.
- `app/apps/manuscripts/management/__init__.py`.
- `app/apps/manuscripts/management/commands/__init__.py`.
- `app/apps/manuscripts/management/commands/audit_refactoring.py`: interfaz CLI.
- `app/apps/manuscripts/test_audit_refactoring.py`: pruebas unitarias e integracion.
- `docs/refactoring/07-data-inventory.md`: este informe tecnico.
- `docs/refactoring/07-inventory-new-environment.json`: salida JSON real.
- `docs/refactoring/07-inventory-new-environment.md`: salida Markdown real.

Los ocho archivos son nuevos. No se modifican archivos preexistentes, modelos,
permisos, dependencias, configuracion de media ni
migraciones. Se conservan los cambios locales previos y los archivos `diff_*.txt`.

## Siguiente fase

Se mantiene el orden del roadmap: F1, proteccion uniforme de operaciones y media
privada, antes de F2/F3 (arbol y versiones). Una base nueva vacia no prueba la
seguridad de una migracion del legado. Si aparecen los datos anteriores, ejecutar
este auditor en una copia controlada y resolver D01-D06/D16 antes de transformar
contenido; verificar respaldo y restauracion DB/media antes de esa migracion.

El ensayo de restauracion de F0 y la politica D17 siguen pendientes: construir un
entorno vacio no equivale a recuperar una copia de los manuscritos.
