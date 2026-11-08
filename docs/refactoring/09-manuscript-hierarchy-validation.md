# F2: jerarquia literaria, identidad y movimientos seguros

Fecha: 2026-11-06, America/Mexico_City. Prompt 04 implementado sobre el proyecto
existente. Conexion exclusiva `telar-fabulas-dev`, Podman rootless, Django 5.2.19
LTS, PostgreSQL 16. Sin dependencias nuevas ni cambios en uv.lock/Compose.

## Resultado

- **360 pruebas aprobadas**, 168.209 s, sin fallos ni omisiones en PostgreSQL.
- 297 pruebas anteriores conservadas y 63 nuevas: 54 de jerarquia/integracion,
  ocho de concurrencia real y una de migracion historica.
- Migracion `manuscripts.0002_literary_hierarchy` aplicada correctamente.
- `check` limpio, `makemigrations --check --dry-run` sin cambios, Celery `pong`.
- Escenario de los cuatro movimientos verificado por HTTP real contra Gunicorn,
  sesiones/CSRF y tareas ejecutadas por el worker Celery real.
- HTML, DOCX, PDF y EPUB generados y descargados como adjuntos privados.
- La prueba visual/manual en Chrome **queda pendiente**: el control del navegador
  se detuvo porque no pudo determinar su URL con seguridad. No se eludio ese
  bloqueo. Las comprobaciones HTTP no sustituyen una inspeccion visual del layout.
- No se reinicio PostgreSQL, no se borraron volumenes, no se modifico la maquina
  anterior. Se conservaron los siete `diff_*.txt`, comprobados por SHA-256.

## Modelo y politica

Se conserva una sola tabla `ManuscriptNode`, todas sus columnas anteriores y sus
PK. `short_description` es texto opcional con default vacio. `content`, `status`,
`is_publishable` y `word_count` siguen siendo la fuente actual, sin SceneVersion.

| Tipo | Padre permitido | Hijos permitidos | Titulo |
| --- | --- | --- | --- |
| BOOK | Ninguno, raiz del proyecto | PART, CHAPTER | Obligatorio |
| PART | BOOK | CHAPTER | Obligatorio |
| CHAPTER | BOOK, PART | SCENE | Obligatorio |
| SCENE | CHAPTER | Ninguno | Opcional |
| FRAGMENT | Solo estructura heredada | No se crean nuevos hijos | Legado sin conversion |

Cada proyecto admite varios libros. Una escena vacia de titulo muestra `Escena N`
segun su posicion actual; no se escribe esa etiqueta en `title`. Se usa tambien en
selectores, notas, menciones y exportaciones. Puede cambiar al reordenar: el ID,
no la etiqueta, es la identidad estable.

`hierarchy.py` concentra matriz, validacion de ancestros/subarbol y recorrido.
Se rechazan ausencia de proyecto, padre ajeno, cambio de proyecto de una fila
existente, ciclos directos/indirectos, nuevos FRAGMENT y cambios que dejen hijos
incompatibles. Las operaciones estructurales tambien comprueban los hermanos
que necesitarian renumerarse. El auditor importa la misma matriz.

Modelo, formularios, vistas, servicios y admin aplican esta politica. El admin
no permite borrado masivo ni cambios de padre/tipo/posicion en una edicion normal.
El formulario de texto no acepta cambios estructurales enviados por el cliente.
El movimiento mantiene su formulario propio y revalida dentro de la transaccion.

La UI reutiliza el arbol existente: Crear libro, Crear hijo, Ver, Editar, Mover,
Subir/Bajar y Borrar hoja. Oculta acciones invalidas por tipo, estado y legado.
Descripcion en creacion/edicion/detalle y abreviada a 80 caracteres en el arbol.
Los textos se escapan y se mantienen preparados para gettext.

## Legado

FRAGMENT no se crea, convierte, borra ni modifica desde los escritores normales.
Las ramas incompatibles siguen visibles, auditables y exportables, con indicacion
de solo lectura. Un ciclo se recorre una sola vez, sin recursion infinita ni
exclusion silenciosa de registros. Un padre de otro proyecto no revela su titulo
ni genera un enlace ajeno en el detalle.

No se renumeran hermanos legados como efecto lateral. Si un grupo contiene una
rama incompatible, una operacion estructural que necesite normalizarlo se bloquea.
Esto puede impedir crear otro libro si las raices contienen legado incompatible;
no es permiso para corregirlo por SQL. Hace falta inventario y decision de una
migracion posterior. Editar texto en una rama valida no reestructura otra rama.

## Transacciones y concurrencia

Crear, guardar, mover, subir/bajar, normalizar y borrar hoja siguen este orden:

1. Abrir `transaction.atomic()`.
2. Bloquear la fila del proyecto con `select_for_update()`.
3. Releer permisos/estado y, si existe, bloquear/releer el nodo.
4. Validar matriz, ciclos, origen/destino y subarbol afectado.
5. Actualizar estructura y posiciones consecutivas de origen/destino.
6. Confirmar todo o revertir todo si una escritura falla.

Bloquear primero el proyecto protege incluso grupos vacios, donde no habria
hermanos que bloquear. Las operaciones cooperantes sobre el mismo proyecto se
serializan; las de proyectos distintos no comparten ese bloqueo. No se bloquea
solo una seleccion de hermanos que pueda quedar obsoleta al insertar otro.

Un movimiento actualiza parent/position/updated_at, no crea una copia ni guarda
otra vez content. Conserva ID, contenido exacto, estado, publicacion, word_count,
created_at, Note.node, CharacterMention.node y ExportJob.root_node. No modifica
el archivo ni metadata de una exportacion historica terminada.

Un guardado de texto desde una instancia anterior conserva la estructura releida
bajo bloqueo; no revierte un movimiento concurrente. Una modificacion estructural
explicita basada en valores obsoletos se rechaza con mensaje de recarga.

### Limites de PostgreSQL

`select_for_update()` se evalua dentro de una transaccion y sus bloqueos duran
hasta commit/rollback; no es un mutex global ni bloquea las lecturas ordinarias
MVCC. Las pruebas deben usar conexiones independientes y `TransactionTestCase`,
no confiar en la transaccion implicita de `TestCase`.
[Django: select_for_update](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update),
[Django: transacciones](https://docs.djangoproject.com/en/5.2/topics/db/transactions/).

La garantia de orden corresponde a escritores que respetan este protocolo. No se
agrego UNIQUE(project,parent,position) sobre datos heredados: una constraint con
raices NULL y reordenamientos transitorios requiere una estrategia de esquema
propia. SQL directo, bulk_create, update, bulk_update y QuerySet.delete externos
pueden omitir save/clean/locks. No son APIs de escritura de la aplicacion. El
bulk_update interno de posiciones solo ocurre bajo el bloqueo del proyecto.

El bloqueo es deliberadamente amplio y puede producir espera entre dos autores
o solicitudes del mismo proyecto. No garantiza imparcialidad ni timeout de
produccion; las pruebas fijan lock_timeout para detectar esperas indebidas. Los
procesos administrativos futuros deben respetar el mismo orden de bloqueo.
Dos ediciones de texto siguen siendo ultimo guardado; F3 debe incorporar revision
esperada. Los snapshots coherentes de exportacion quedan para F4.

## Migracion y preservacion

El preflight encontro cero usuarios/proyectos/nodos/personajes/notas/menciones/
exportaciones; no habia incompatibilidades que transformar. El auditor solo
indicaba ausencia del nuevo campo y su aviso informativo de lectura.

`0002_literary_hierarchy` contiene AddField(short_description) y
AlterField(title, blank=True). SQL revisado: ADD COLUMN text con valor inicial
vacio, retiro de default SQL; title es no-op en PostgreSQL. No hay RunPython,
DELETE, cambios de PK, ni conversion de FRAGMENT. `showmigrations` marca 0001 y
0002 como aplicadas. Las migraciones iniciales permanecen intactas.

La prueba historica migra 0001 -> 0002 exclusivamente en la DB de pruebas. Crea
un FRAGMENT con contenido Unicode/saltos/espacios, estado y word_count heredados,
nota, mencion y referencia a export historico. Compara todos los campos previos
y FK, sin transformaciones; short_description queda vacia. La prueba de rollback
inyecta un error en la segunda normalizacion y exige snapshot identico al inicial.

No usar `migrate manuscripts 0001` como retorno en una base de trabajo: borraria
las descripciones nuevas. Conservar la expansion aditiva con lector compatible.
Repetir inventario antes de importar/restaurar datos; detener y reportar
incompatibilidades, sin reparaciones o borrados automaticos.

## Validacion ejecutada

Comandos principales desde la raiz (se uso `-T` en ejecucion automatizada):

```powershell
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec -T web python manage.py audit_refactoring
podman --connection telar-fabulas-dev compose exec -T web python manage.py check
podman --connection telar-fabulas-dev compose exec -T web python manage.py makemigrations manuscripts
podman --connection telar-fabulas-dev compose exec -T web python manage.py sqlmigrate manuscripts 0002
podman --connection telar-fabulas-dev compose exec -T web python manage.py migrate
podman --connection telar-fabulas-dev compose exec -T web python manage.py showmigrations manuscripts
podman --connection telar-fabulas-dev compose exec -T web python manage.py test
podman --connection telar-fabulas-dev compose exec -T web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec -T worker celery -A config inspect ping
podman --connection telar-fabulas-dev info --format '{{.Host.Security.Rootless}}'
podman --connection telar-fabulas-dev compose exec -T web id -u
```

Resultados finales: 360/360 OK; check sin problemas; ninguna migracion pendiente;
pong, un worker online; rootless true y UID 1000. La suite crea/destruye una DB
aislada de pruebas, nunca la base de trabajo. Tambien se ejecutaron subconjuntos
de manuscritos/core, jerarquia y concurrencia durante el desarrollo.

La primera corrida completa detecto un fixture antiguo que creaba SCENE bajo
BOOK; se adapto a un segundo CHAPTER conservando las aserciones de alcance de
exports. No se deshabilitaron pruebas ni se relajo la matriz para aprobarlas.
Los avisos Not Found de media en la suite son rechazos esperados de seguridad.

Concurrencia real cubierta: dos altas en la misma posicion, dos movimientos al
mismo grupo, alta contra movimiento, dos movimientos del mismo nodo, subir contra
bajar, editar texto desde instancia antigua contra mover, normalizar contra mover
y cambio de estado a FROZEN mientras otra conexion espera el bloqueo.

## Escenario HTTP de aceptacion

Se crearon cuentas y un proyecto exclusivamente temporales con marcador unico;
login real, cookies y CSRF mediante HTTP local, sin Django TestClient ni mocks.
Los diez nodos del anexo se crearon por POST a los formularios. La ultima corrida
uso proyecto 3, cuentas 5/6 y nodos 22-31; ya no existen tras la limpieza.

| Movimiento | ID conservado | Padre antes | Padre despues |
| --- | --- | --- | --- |
| Escena 2 -> Capitulo 4 | 26 | 24 | 31 |
| Capitulo 2 -> Parte B | 27 | 23 | 30 |
| Capitulo 3 -> Parte A | 28 | 22 | 23 |
| Parte A -> Libro B | 23 | 22 | 29 |

Se compararon todos los campos salvo parent/position/updated_at para los diez
nodos. Notas, menciones y raiz historica permanecieron iguales. Cada paso verifico
posiciones 1..N sin duplicados. Orden final verificado en el HTML del arbol:

```text
Libro A
Libro B
  Parte B
    Capitulo 4
      Escena 2
    Capitulo 2
  Parte A
    Capitulo 1
      Escena 1
    Capitulo 3
```

El archivo historico anterior al movimiento conservo bytes y SHA-256:
`c14b739ee24ec3be99570185c104f1af6a5cf82f65c64e625860b48caaabd295`.
Se comparo tambien el registro ExportJob completo, sin cambios.

| Export nueva, Celery real | Bytes descargados | Comprobacion |
| --- | --- | --- |
| HTML, job 8 | 2810 | CSS incrustado, IDs en orden, attachment |
| DOCX, job 9 | 37007 | Encabezados en orden al abrir con python-docx, attachment |
| PDF, job 10 | 8420 | Firma %PDF, attachment |
| EPUB, job 11 | 6778 | ZIP/OPF y spine en orden, attachment |

Todas terminaron DONE; el usuario ajeno recibio 404 al descargarlas. Las pruebas
automatizadas cubren ambos caminos con/sin PART, ademas del escenario HTTP.
PDF se verifico estructuralmente y con las regresiones existentes, no se afirma
inspeccion visual de paginas. EPUBCheck externo sigue pendiente.

POST de movimiento ajeno: 404. FROZEN/PENDING_DELETION: 403 y snapshot intacto.
DELETED: 404 y snapshot intacto. Se creo una escena adicional sin titulo por HTTP,
se comprobo title vacio en DB/etiqueta en detalle y se borro por POST.

La limpieza verifico ID, marcador, propietario, jobs terminales y rutas dentro
del storage privado. Borro solo archivos temporales y sus filas, hojas antes que
padres, ademas de cuentas/sesiones temporales. El primer intento del guion tenia
dos aserciones/configuracion de QA incorrectas, ya corregidas antes de las dos
corridas exitosas; sus datos tambien se retiraron con verificaciones explicitas.
El script auxiliar se elimino del workspace al terminar.

Inventario posterior: cero registros de negocio, cero invalidos, cero decisiones
pendientes de datos, cero CRITICAL/HIGH/MEDIUM; un LOW informativo
READ_ONLY_INVENTORY. No quedaron cuentas ni contenido de prueba.

## Archivos de esta entrega

Inventario comparado por hashes contra el inicio de Prompt 04, no contra HEAD,
porque el workspace ya contenia cambios de fases anteriores. Seis archivos
creados y 23 modificados; ningun archivo anterior eliminado.

Creado:

```text
app/apps/manuscripts/hierarchy.py
app/apps/manuscripts/migrations/0002_literary_hierarchy.py
app/apps/manuscripts/test_hierarchy.py
app/apps/manuscripts/test_concurrency.py
app/apps/manuscripts/test_migrations.py
docs/refactoring/09-manuscript-hierarchy-validation.md
```

Modificado:

```text
README.md
docs/refactoring/03-data-migration-plan.md
docs/refactoring/04-refactoring-roadmap.md
app/apps/manuscripts/models.py
app/apps/manuscripts/forms.py
app/apps/manuscripts/services.py
app/apps/manuscripts/views.py
app/apps/manuscripts/admin.py
app/apps/manuscripts/audit.py
app/apps/manuscripts/tests.py
app/apps/manuscripts/test_audit_refactoring.py
app/apps/exports/services.py
app/apps/exports/docx.py
app/apps/exports/epub.py
app/apps/exports/tests.py
app/templates/manuscripts/manuscript_tree.html
app/templates/manuscripts/node_detail.html
app/templates/manuscripts/node_move.html
app/templates/manuscripts/node_confirm_delete.html
app/templates/notes/note_detail.html
app/templates/notes/note_list.html
app/templates/characters/character_detail.html
app/templates/characters/mention_confirm_delete.html
```

`node_form.html` ya renderiza los campos del formulario y no necesito cambios.
No se modificaron modelos Note/CharacterMention/ExportJob, seguridad F1, .env,
dependencias, TUI, Compose, Dockerfile ni migraciones anteriores.

## Pendientes y siguiente fase

- Revision visual en Chrome, escritorio/movil; la automatizacion de UI quedo
  bloqueada, aunque rutas/formularios/respuestas HTTP pasaron.
- Medir proyectos grandes: la carga evita content para validar estructura, pero
  comprobar cada rama puede ser cuadratico. No se hizo una prueba de carga.
- Constraints de orden y estrategia de saneamiento legado requieren fase propia;
  no escribir estructura mediante SQL/bulk externos al protocolo.
- Conflictos de texto, versiones, snapshots e idempotencia/retencion de exports
  siguen pendientes; no se atribuyen esas garantias a este bloqueo estructural.
- Restauracion ensayada de datos originales y pendientes de produccion siguen
  vigentes en el registro de riesgos. Una base vacia no los da por resueltos.

Siguiente entrega recomendada: F3 SceneVersion, despues de decidir D04-D05,
inventariar/respaldar y ensayar copia exacta con hashes y control de revision.
Mantener FRAGMENT y texto de contenedores hasta aprobar una transformacion
especifica. Sin IA, suscripciones, worldbuilding ni nuevos exportadores en F2.
