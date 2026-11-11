# F9: Papelera y recuperacion de manuscritos

Fecha: 2026-11-11. Prompt 14 de refactorizacion v01.

## Alcance y decisiones

Papelera conservadora para BOOK, PART, CHAPTER y SCENE sobre la implementacion
existente. No se reconstruye el proyecto, no se agregan dependencias ni se cambia
SceneVersion. F9 reemplaza la propuesta comercial anterior del roadmap; trial,
pagos, Stripe, papelera general y borrado definitivo quedan fuera de esta entrega.

La eliminacion ordinaria y `ManuscriptNode.delete()` pasan por `soft_delete_node`.
Solo el nodo eliminado directamente recibe `deleted_at` y `deleted_by`. Los
descendientes sin sello propio quedan ocultos por herencia, sin modificar sus
filas. No hace falta `deletion_batch_id`: el sello del ancestro y los sellos
independientes existentes distinguen las operaciones sin duplicar estado.
Las entradas web registran al actor; una llamada interna sin usuario deja
`deleted_by` vacio, no atribuye la operacion a otra persona.

Restaurar un ancestro limpia solo su sello. Sus descendientes activos reaparecen;
un descendiente eliminado antes conserva su sello y sigue en papelera. Se puede
rescatar un descendiente oculto trasladandolo a otro padre valido y visible del
mismo proyecto, sin recuperar los ancestros eliminados. Se conserva el PK.

## Integridad y servicios

- `soft_delete_node`: transaccion, lock Project -> nodo, permiso EDIT, visibilidad
  y jerarquia; sella solo la raiz y normaliza hermanos visibles. Una repeticion
  sobre el mismo sello es idempotente, tras volver a validar permisos.
- `restore_node`: mismos locks, estado/propietario vigentes, destino compatible,
  sin ciclos ni cruces de proyecto. Reutiliza `_move_locked`; no duplica la logica
  de movimientos. Normaliza grupos visibles recuperados; cualquier fallo revierte
  tambien la limpieza del sello. Restaurar un nodo ya visible no lo mueve.
- `get_trash_items`: vuelve a consultar el proyecto para no confiar en estado
  obsoleto; obtiene metadatos, ruta, tipo de ocultamiento y descendientes afectados.
- `get_visible_manuscript_tree`, `.visible()` y `require_visible_node` comparten
  la deteccion de ancestros eliminados. Los servicios de versiones, movimiento,
  guardado y nuevas asociaciones la validan bajo el lock cooperante de Project.

La restauracion puede cambiar posicion/padre y `updated_at` del nodo recuperado;
no cambia contenido literario ni ninguna columna de SceneVersion. Borrador
activo, definitiva vigente, version_number, revision, relaciones entre versiones
y fechas se conservan. No se genera una nueva version ni se decide otra final.
Notas, menciones, referencias y la FK de raiz de exportaciones permanecen intactas.

Los nodos ocultos retienen posiciones que pueden solaparse con las de hermanos
visibles renumerados. El auditor conserva todas las filas en su inventario,
incluye conteos directos/ocultos/visibles y detecta duplicados solo en el conjunto
visible. No se agrego una constraint SQL de posicion a manuscritos.

## Visibilidad y exportaciones

`hidden_node_roots` recorre iterativamente metadatos de todos los nodos de los
proyectos consultados. Asocia cada oculto con su eliminacion directa mas cercana,
sin recorrer la base una consulta por ancestro/nodo. `.visible()` usa una consulta
de metadatos y otra para los resultados; no filtra solo `deleted_at IS NULL`.

Se revisaron arbol, detalle, historial/versiones, busqueda admin, selectores de
padre, notas, menciones, referencias, raices de exportacion, WORK, FINAL y preview.
Las notas/menciones/asociaciones de nodos ocultos se excluyen de las vistas
ordinarias, conservando las filas. Nuevos vinculos hacia nodos ocultos se rechazan.
Un formulario abierto antes de eliminar no puede escribir tras obtener el lock.

El manager base permanece sin filtrar para inventarios, integridad, migraciones y
historial. Futuras consultas ordinarias deben usar la estrategia de visibilidad;
las APIs bulk/SQL no son escritores de negocio protegidos.

La captura de nuevas exportaciones selecciona solo nodos visibles bajo el lock
existente de Project. El formato y lectores de snapshots no cambian: un job
anterior se renderiza desde su captura inmutable incluso si su raiz esta oculta.
Las exportaciones del universo omiten asociaciones a manuscritos ocultos, sin
descartar la referencia ni confundir un vinculo oculto legitimo con uno corrupto.
Se mantiene el rechazo de asociaciones de otro proyecto. HTML, Markdown, DOCX,
PDF, EPUB, WORK/FINAL/REFERENCE y preview conservan su infraestructura anterior.

## Interfaz y permisos

Navegacion: Proyecto -> Papelera, tambien desde el arbol narrativo.

```text
/projects/<project_pk>/manuscript/trash/
/projects/<project_pk>/manuscript/trash/<node_pk>/
/projects/<project_pk>/manuscript/trash/<node_pk>/restore/
```

Listado paginado a 50 con tipo, titulo, ubicacion, fecha, estado directo/heredado,
descendientes afectados y acceso a restaurar. No carga prosa de escena. La ruta
se calcula con padres conservados, no con un historial separado: cambiar el
nombre o ubicacion de un ancestro activo puede cambiar esa ruta. El detalle es
informativo; no permite editar texto. Restauracion con confirmacion, POST/CSRF,
destino compatible y posicion; GET no modifica. Sin drag & drop.

| Estado | Consultar papelera | Eliminar/restaurar |
| --- | --- | --- |
| ACTIVE propio | Si | Si |
| FROZEN propio | Si | No, 403 |
| PENDING_DELETION propio | Si | No, 403 |
| DELETED | No, 404 | No, 404 |
| Proyecto ajeno | No, 404 | No, 404 |

Se usa Action.EDIT para recuperar contenido, no Action.RESTORE que regula la
transicion del proyecto. No cambia la politica de restauracion de proyectos.
El servicio comprueba otra vez el estado bajo lock y rechaza destinos ajenos.

Admin distingue Activo, Eliminado y Oculto por ancestro; busqueda normal sin
ocultos, filtros explicitos para inspeccion y sin edicion de nodos ocultos.
Deshabilitados borrado fisico individual y masivo. No se ofrece una segunda
implementacion de restauracion: se usa la pantalla del autor y el mismo servicio.
Los POST admin de manuscrito adquieren Project antes de validar y guardar.

## Migracion y resguardo

Aplicada `manuscripts.0005_manuscript_trash`:

1. `deleted_at`, nullable/no editable.
2. `deleted_by`, FK nullable SET_NULL a usuario/no editable.
3. Indice `(project, deleted_at)`.
4. Forward sin transformacion de datos; guardia de reversa si hay sellos directos.

Se inspeccionaron `migrate --plan` y `sqlmigrate` antes de aplicar. No UPDATE masivo,
recreacion de tablas, cambios de PK ni alteraciones de SceneVersion. Los cuatro
nodos originales quedaron activos y la version original identica. La migracion
se aplico con web/worker/beat detenidos, mediante `compose run --rm --no-deps web`;
despues se inicio la pila completa. No se borro ninguna base ni volumen.

Respaldos locales ignorados por Git, previos a la migracion:

```text
backups/p14_pre_trash.dump
backups/p14_private_media.tar.gz
backups/p14_original_fingerprints.json
```

Se compararon todas las columnas originales y filas de 22 modelos de negocio y
los archivos media por SHA-256 antes/despues de migrar y tras retirar QA. Solo las
nuevas columnas se excluyen de esa comparacion entre esquemas. Datos originales:
1 usuario, 1 proyecto, 4 nodos, 1 SceneVersion, 3 personajes, 3 roles dramaticos,
2 ubicaciones, 2 organizaciones y 1 referencia; otros modelos sin filas, media sin
archivos. La comprobacion dio igualdad. No se ensayo una restauracion nueva del
respaldo en F9; siguen pendientes copia externa/cifrada y ensayos recurrentes.

No revertir el esquema ni desplegar codigo pre-F9 que ignore los sellos: podria
volver a mostrar ocultos. Mantener datos/esquema y corregir hacia delante. Un dump
previo no contiene trabajo posterior y no es un rollback rutinario seguro.

## Pruebas automatizadas

Se agregan 77 pruebas: 67 funcionales, nueve de concurrencia PostgreSQL con
conexiones separadas y una de migracion. Se adaptan expectativas antiguas de
borrado fisico y fixture cleanup sin eliminar cobertura de identidad/versiones.

Cobertura: escena/capitulo/parte/libro; sellos independientes; rescate aislado;
versiones completas; notas/menciones/referencias; posiciones; rollback;
idempotencia; padre invalido/ajeno/oculto; ciclos; GET/POST/CSRF; permisos por
estado; admin; consultas acotadas; WORK/FINAL/preview; snapshots previos y
exportacion del universo. La migracion conserva campos previos y protege reversa.

Concurrencia: edicion de version, movimiento, nota, mencion y referencia que
esperan una eliminacion; restauracion frente a cambio de estado; doble
restauracion; captura antes y despues de eliminar. Todos usan Project primero.

| Ejecucion | Resultado |
| --- | --- |
| Primer bloque funcional | 64 aprobadas, 17.520 s |
| Regresion de apps afectadas | 863 ejecutadas; una consulta extra detectada en referencias, corregida |
| Revalidacion tras correccion y casos adicionales | 122 aprobadas, 23.954 s |
| Suite integrada completa | **1170 aprobadas**, 564.355 s, sin fallos ni pruebas omitidas |

La correccion evita calcular visibilidad literaria al pedir referencias de una
entidad no manuscrito: la constraint de destino unico impide que esa misma
asociacion tenga ademas un manuscrito. Se conserva la asercion previa de una
consulta; no se relaja el presupuesto para ocultar la regresion.

Logs locales ignorados: `backups/p14_focused_tests.log`,
`backups/p14_recheck_tests.log` y `backups/p14_full_tests.log`. Se utiliza
`--keepdb --noinput` para conservar la base de pruebas entre ejecuciones, sin
correr suites simultaneas ni tocar la base de negocio.

Validaciones operativas: `check` limpio, `migrate --plan` sin operaciones,
`migrate` sin pendientes, `makemigrations --check --dry-run` sin cambios y Celery
`pong` con un worker. Cinco servicios activos en Podman rootless. Los mensajes
de error simulados en los logs corresponden a pruebas de fallos de disco,
broker, permisos y correo; el resultado integrado final es OK.

## Prueba manual con HTTP, navegador y Celery

Proyecto temporal registrado: 16. Libro 64 -> Parte 65 -> Capitulo 66 -> escenas
67 (A) y 68 (B). Tres versiones por escena: V1 original, V2 definitiva vigente y
V3 borrador activo. Nota y mencion vinculadas a A. Dos usuarios QA para comprobar
aislamiento. Sesiones HTTP reales con CSRF, no Django TestClient.

1. Se solicitaron WORK/FINAL antes de eliminar (jobs 49/50).
2. Se envio A a papelera y se solicitaron WORK/FINAL sin A (51/52).
3. Se envio el capitulo a papelera. A conservo su sello; B quedo oculta por
   ancestro con `deleted_at` nulo.
4. En navegador se restauro el capitulo: B regreso (200), A continuo oculta (404).
5. En vista movil se restauro A. Historial V1/V2/V3, V2 definitiva y V3 trabajo.
6. Se compararon todas las columnas de las seis versiones, fechas/revisiones
   incluidas, y los punteros de borrador: iguales. Nota y mencion conservaron FK.
7. Se solicitaron WORK/FINAL recuperados (53/54). Los seis jobs llegaron a READY
   por Celery; descargados como attachment/no-store. Usuario ajeno recibio 404.
8. WORK antes/despues coincidio byte a byte (189 bytes); FINAL tambien (191 bytes).
   Sin A, WORK tuvo 120 bytes y FINAL 121. Capturas/checksums previos intactos.
9. Se retiraron exclusivamente IDs QA registrados y sus archivos mediante el
   lifecycle de exportaciones y limpieza acotada de fixtures. Credenciales QA
   retiradas del registro local. No se tocaron originales; SHA-256 iguales.

Navegador integrado a 1280x900 y 390x844: listado, confirmacion y recuperacion.
Ancho del documento igual al viewport; tabla con desplazamiento interno cuando
hace falta. Sin cambios a la preferencia Chrome de la TUI. No se afirma prueba
de esta fase en Chrome nativo.

Evidencias locales ignoradas en `backups/p14_qa/`: `state.json` (limpieza marcada),
seis archivos Markdown descargados, `trash-desktop.png`, `trash-mobile.png`,
`restore-mobile.png`, `history-mobile.png` y `restored-history.png`.

## Comandos ejecutados

Todas las operaciones de contenedores se dirigieron a `telar-fabulas-dev`.
Se inicio solo esa maquina; no se modifico la maquina anterior. El proveedor
Compose instalado puede ser docker-compose.exe, conectado al motor Podman
rootless mediante la conexion explicita; no se migro a Docker Desktop.

```powershell
podman machine start telar-fabulas-dev
podman --connection telar-fabulas-dev compose up -d postgres redis
podman --connection telar-fabulas-dev compose exec -T postgres pg_dump -U telar -d telar_fabulas -Fc -f /tmp/p14_pre_trash.dump
podman --connection telar-fabulas-dev cp telar-fabulas-postgres-1:/tmp/p14_pre_trash.dump backups/p14_pre_trash.dump
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py makemigrations manuscripts --name manuscript_trash
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py sqlmigrate manuscripts 0005
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py migrate
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec web python manage.py check
podman --connection telar-fabulas-dev compose exec web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose exec web python manage.py migrate
podman --connection telar-fabulas-dev compose exec web python manage.py test --keepdb --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
```

Tambien se ejecutaron comprobacion de huellas (`backups/p14_ops.py`), QA controlado
(`backups/p14_manual.py`), pruebas enfocadas y revision `git diff --check`. Los
helpers/evidencias son locales, no componentes de produccion ni tareas de purga.
No se modifican `subir_repo.bat`, `diff_*.txt`, `.env`, TUI, Compose, lock uv ni
otras maquinas Podman. No se ejecuta `down -v`, reset de base ni publicacion Git.

## Archivos creados

```text
app/apps/manuscripts/visibility.py
app/apps/manuscripts/trash.py
app/apps/manuscripts/trash_views.py
app/apps/manuscripts/migrations/0005_manuscript_trash.py
app/apps/manuscripts/test_trash.py
app/apps/manuscripts/test_trash_concurrency.py
app/apps/manuscripts/test_trash_migration.py
app/templates/manuscripts/trash_list.html
app/templates/manuscripts/trash_detail.html
app/templates/manuscripts/trash_restore.html
docs/refactoring/19-manuscript-trash-validation.md
```

## Archivos modificados

```text
README.md
app/apps/characters/forms.py
app/apps/characters/models.py
app/apps/characters/views.py
app/apps/core/admin.py
app/apps/core/permissions.py
app/apps/exports/forms.py
app/apps/exports/job_services.py
app/apps/exports/services.py
app/apps/exports/snapshots.py
app/apps/exports/test_snapshots.py
app/apps/exports/views.py
app/apps/exports/world_exports.py
app/apps/manuscripts/admin.py
app/apps/manuscripts/audit.py
app/apps/manuscripts/models.py
app/apps/manuscripts/services.py
app/apps/manuscripts/test_audit_refactoring.py
app/apps/manuscripts/test_hierarchy.py
app/apps/manuscripts/test_migrations.py
app/apps/manuscripts/test_version_migrations.py
app/apps/manuscripts/test_versions.py
app/apps/manuscripts/tests.py
app/apps/manuscripts/urls.py
app/apps/manuscripts/version_services.py
app/apps/manuscripts/version_views.py
app/apps/manuscripts/views.py
app/apps/notes/forms.py
app/apps/notes/models.py
app/apps/notes/views.py
app/apps/references/forms.py
app/apps/references/models.py
app/apps/references/selectors.py
app/apps/references/services.py
app/apps/references/views.py
app/templates/base.html
app/templates/manuscripts/manuscript_tree.html
app/templates/manuscripts/node_confirm_delete.html
app/templates/manuscripts/node_detail.html
app/templates/projects/project_detail.html
docs/refactoring/04-refactoring-roadmap.md
docs/refactoring/05-risk-register.md
```

## Riesgos pendientes y siguiente fase

- Retencion indefinida de literatura eliminada: medir crecimiento de DB; no
  convertir la limpieza de exports en una purga de fuentes.
- Backups externos/cifrados y ensayo recurrente de restauracion siguen pendientes.
  La papelera no cubre borrado privilegiado, dano de almacenamiento ni otras apps.
- Visibilidad, papelera y selectores materializan metadatos del proyecto. Medir
  memoria/latencia/contencion con volumen representativo antes de ampliar escala.
- SQL/bulk son privilegiados y pueden saltar permisos/locks/jerarquia; futuros
  escritores y lectores deben usar los servicios y visibilidad compartidos.
- No hay historial independiente de eliminaciones/rutas, reparacion automatica
  de estructuras legacy invalidas ni politica de eliminacion definitiva.

Recomendacion: consolidar operacion y capacidad (backups y restauracion,
monitorizacion, TLS/estaticos, pruebas de carga). Trial/pago manual queda pospuesto
y requiere requisitos separados; sin cobros ni papelera general en esta fase.
