# F4: exportaciones WORK/FINAL y snapshots
Fecha de validacion: 2026-11-07 (America/Mexico_City).
Prompt 06, sobre el proyecto existente en Podman rootless `telar-fabulas-dev`.

## Resultado
- WORK y FINAL disponibles en solicitud y preview.
- Captura persistente antes de encolar; HTML, DOCX, PDF y EPUB usan el mismo
  documento neutral derivado exclusivamente del snapshot.
- 482 pruebas integradas aprobadas: 445 anteriores + 37 nuevas.
- Ocho exportaciones Celery reales (dos modalidades por cuatro formatos),
  descargadas por HTTP con autenticacion y CSRF en las solicitudes.
- Migracion exports.0002 aplicada sin reset, sin reiniciar PostgreSQL y sin
  borrar volumenes. Una cuenta y un proyecto originales conservados por huella.
- Sin paquetes nuevos: pyproject.toml y uv.lock no cambiaron.

## Seleccion editorial
WORK elige el DRAFT/REVIEW activo; si no existe usa FINAL vigente. Sin ninguna
version, mantiene un encabezado de escena vacio. Conserva contenedores y texto
legado no SCENE, incluido FRAGMENT, sin convertirlo ni modificarlo.

FINAL incluye solo escenas con definitiva vigente, mantiene sus ancestros
BOOK/PART/CHAPTER dentro del alcance y elimina contenedores sin escenas finales.
No publica texto legado de contenedores/FRAGMENT. Una rama definitiva con
ancestro incompatible o ciclo se rechaza claramente; no se repara el manuscrito.
Una seleccion sin definitivas falla sin crear trabajo ni snapshot.

El formulario muestra conteos y advertencia de exclusion antes de crear FINAL.
La confirmacion firmada contiene seleccion, clave y conteos, dura una hora y se
revisa nuevamente si cambia el alcance o el conteo. El servicio compara el
conteo con la captura efectiva bajo lock; no congela la preview anterior.
Las notas, personajes y datos internos nunca se insertan en los documentos.

## Captura e inmutabilidad
ExportSnapshot tiene relacion uno a uno con ExportJob: manifiesto JSON version 1,
fecha, SHA-256, bytes canonicos y resumen de conteos/titulo/estilo.
El manifiesto conserva proyecto, propietario, formato, modo, root original,
nombre/idioma/autor, nodos en orden, profundidad, tipo, padre, posicion, titulo,
descripcion, ID/revision/etapa de la version elegida y su texto exacto.
selected_versions contiene referencias sin duplicar el texto literario.
style_configuration copia todos los ajustes, incluido config_json.

El JSON canonico usa UTF-8, claves ordenadas y separadores estables. El checksum
no depende del orden de claves en JSONB. Se verifica al cargar el documento,
junto con propietario, proyecto, formato, modo e ID de estilo. La FK root puede
quedar NULL tras borrar una escena: el alcance conservado no se amplia.

No hay endpoint ni registro admin del manifiesto. El modelo impide save/delete
independientes; un trigger PostgreSQL impide todo UPDATE, incluso QuerySet.update.
La eliminacion por cascada de un job sigue siendo posible para una futura
limpieza autorizada; esta fase no ofrece borrado de trabajos ni snapshots.
No se promete proteccion frente a un DBA que desactive triggers o reescriba el
esquema. Es informacion privada en PostgreSQL y debe incluirse en respaldos
con acceso restringido. No se imprime texto, manifiestos ni secretos en logs.

## Transacciones y concurrencia
Orden de locks: proyecto del propietario -> fila del estilo. Luego seleccion
por lotes y creacion de job + snapshot en la misma transaccion. Se revalidan
estado, root y estilo dentro de ella. Los escritores F2/F3 de estructura,
borradores y definitivas usan el mismo lock del proyecto; el UPDATE normal de
estilos queda bloqueado por select_for_update de su fila. No se cambio su editor.

Esto serializa las lecturas con los escritores cooperantes bajo READ COMMITTED;
atomic sin locks no bastaria. Referencias: [bloqueos de filas PostgreSQL 16](https://www.postgresql.org/docs/16/explicit-locking.html#LOCKING-ROWS)
y [on_commit de Django 5.2](https://docs.djangoproject.com/en/5.2/topics/db/transactions/#performing-actions-after-commit).

on_commit publica solo solicitudes confirmadas. Un error de broker conserva
PENDING, sin enqueued_at, con mensaje generico y reenvio explicito por POST/CSRF.
El UUID del formulario evita duplicar jobs al repetir la misma solicitud.
Una clave ya usada con otros parametros no se reutiliza.
Reintentar nunca recaptura texto ni estilo.

El worker reclama bajo lock, omite PROCESSING/DONE, verifica el snapshot una
vez y pasa el documento en memoria al renderizador. Revalida permisos antes de
publicar el archivo privado. Un fallo marca FAILED y no expone excepciones.
La entrega duplicada no produce otro archivo para un trabajo ya terminado.

## Limites y rendimiento
- EXPORT_SNAPSHOT_MAX_BYTES: 20971520 por defecto (20 MiB de JSON canonico).
- EXPORT_SNAPSHOT_MAX_NODES: 10000 por proyecto, incluso al elegir un subarbol.
- Preflight con Length/Sum antes de cargar contenido; limite final en bytes UTF-8.
- Metadatos y texto seleccionado por lotes; no se serializan objetos Django.
- Captura WORK medida: ocho consultas del selector, sin contar lectura del
  proyecto/estilo ni validaciones/INSERT. El test compara 3 frente a 18 escenas
  y exige el mismo numero de consultas.
- Cada renderizador independiente lee solo una fila de snapshot, no las tablas
  ManuscriptNode/SceneVersion/StyleTemplate. El worker comparte la carga en memoria.
- Listado/detalle usan anotaciones del resumen, sin cargar manifest_json.
- Preview mantiene limites de 12 nodos/2500 palabras por defecto, recorta antes
  de cargar los textos de nodos fuera del limite y nunca persiste ni encola.
- Los limites rechazan la solicitud completa; no representan cuotas comerciales.

## Migracion y preservacion
Migracion:
`exports.0002_exportjob_enqueued_at_exportjob_export_mode_and_more`.

Agrega export_mode=WORK, request_key nullable unica, enqueued_at y ExportSnapshot.
No rellena snapshots historicos ni modifica archivo, timestamps, PK o estado.
Los jobs historicos DONE se siguen leyendo/descargando. No se regeneran:
un job pendiente sin snapshot falla de forma controlada; solicitar uno nuevo.
La reversa se rechaza si existen snapshots. Conservar el esquema aditivo al
revertir codigo y conciliar trabajo nuevo antes de cualquier restauracion.

Inventario previo y posterior: 1 usuario, 1 proyecto, 0 nodos, 0 exports.
El proyecto vacio original no fue completado ni modificado automaticamente.
Respaldo previo: `backups/p06_pre_snapshots_20261107.dump`.
SHA-256:
`3e237973f94b66ab25f430cb982d4759f268fcc66809cb4f5f92442140763e7b`.
Se restauro con pg_restore --exit-on-error en `telar_p06_restore_check`,
se comprobaron los conteos y se retiro exclusivamente esa base QA.
La compatibilidad con archivos historicos se verifica con fixtures; no habia
exportaciones originales locales para comprobarla con datos del propietario.

## Pruebas automatizadas
Las 37 nuevas se distribuyen asi:
- test_snapshots.py: 28 pruebas de seleccion, texto/revision exactos, estilo,
  orden, edicion/movimiento/borrado posterior, checksum, trigger, limites,
  rollback, broker, on_commit, clave idempotente, reintento, cuatro formatos,
  consultas por lotes, confirmacion, permisos, preview e historicos.
- test_snapshot_concurrency.py: ocho TransactionTestCase con conexiones distintas:
  edicion durante captura; movimiento; UPDATE de estilo; captura esperando
  estilo no confirmado; dos snapshots simultaneos; doble envio con misma clave;
  tareas duplicadas; cambio a DELETED mientras se espera el lock.
- test_snapshot_migration.py: migracion aditiva de un trabajo historico DONE,
  conservando todos sus campos anteriores y sin backfill de snapshot.

Las regresiones existentes ahora solicitan snapshots antes de renderizar; se
conservaron los casos de archivos historicos y referencias corruptas. Los mocks
de envio cubren tambien la ejecucion de callbacks on_commit. En una primera
pasada se detecto un orden incorrecto de esos context managers y se corrigio;
se retiraron 12 mensajes de prueba huerfanos, solo de esta tarea y sin trabajo
en la base real, mientras el worker estaba detenido. No se purgo la cola general.

Comandos ejecutados (prefijo explicito en todos):
```powershell
podman --connection telar-fabulas-dev compose stop web worker beat
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py makemigrations exports
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py sqlmigrate exports 0002
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py test --noinput
podman --connection telar-fabulas-dev compose up -d --build web
podman --connection telar-fabulas-dev compose exec web python manage.py check
podman --connection telar-fabulas-dev compose exec web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose exec web python manage.py migrate
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec web python manage.py test --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
```
Tambien se ejecutaron los tres modulos nuevos juntos: 37 aprobadas.
check sin incidencias; migraciones al dia; makemigrations sin cambios; worker pong.

## Prueba HTTP y Celery real
Se crearon dos cuentas QA y un proyecto temporal BOOK -> PART -> CHAPTER con
escena 1 FINAL V2, escena 2 DRAFT V3 y escena 3 FINAL V1.
Con worker detenido:
1. Se verificaron previews WORK/FINAL sin crear jobs.
2. Se solicitaron ocho exports via HTTP, con CSRF, confirmacion FINAL y
   reenvio del mismo formulario para comprobar idempotencia.
3. WORK capturo tres escenas; FINAL dos incluidas y una excluida.
4. Se cambio por HTTP el texto del borrador, se movio escena 3 al principio
   y se cambio el estilo de 12.5 a 19 puntos y su separador.
5. Se confirmaron ocho jobs aun PENDING antes de arrancar Celery.

Tras arrancar el stack: ocho DONE, snapshots/checksums iguales, descargas attachment
para HTML/DOCX/PDF/EPUB en ambas modalidades. Los archivos mantuvieron texto,
orden 1-2-3 (1-3 en FINAL), separador y fuente/tamano previos. El HTML contiene CSS
incrustado en un solo archivo. PDF: extraccion del texto/orden y del tamano real
12.5pt, mas inspeccion visual de ambas paginas renderizadas; sin recortes.
DOCX verifico el estilo Normal y EPUB el CSS empaquetado. Ninguno incluyo notas.

La otra cuenta recibio 404 en detalle y descarga. /private_media/... recibio 404.
Las dos cuentas, sesiones QA, proyecto, estilos, jobs, snapshots y archivos de
storage QA se retiraron. Se compararon huellas SHA-256 de todas las filas de
accounts.User y projects.Project originales: identicas. Los artefactos ficticios
de comprobacion y respaldo quedan locales bajo backups/, excluidos de Git/imagen.

Se revisaron formulario y confirmacion a 1280x900 y 390x844, detalle y lista,
y preview FINAL por DOM/HTTP en el navegador integrado. Se corrigio la alineacion
de radios sin alterar otras pantallas. No se observo desbordamiento horizontal
de pagina. La tabla mantiene su scroll interno. Capturas:
`backups/p06_qa/export-form-desktop.png` y `export-form-mobile.png`.
Chrome no estaba disponible para automatizacion; no se cambio la TUI ni su
preferencia de abrir Chrome.

## Archivos de esta entrega
Este inventario compara huellas con el inicio del Prompt 06, no con HEAD:
el workspace ya contenia cambios de F3 y archivos del usuario.

Creados (7):
- `app/apps/exports/job_services.py`
- `app/apps/exports/migrations/0002_exportjob_enqueued_at_exportjob_export_mode_and_more.py`
- `app/apps/exports/snapshots.py`
- `app/apps/exports/test_snapshot_concurrency.py`
- `app/apps/exports/test_snapshot_migration.py`
- `app/apps/exports/test_snapshots.py`
- `docs/refactoring/11-export-snapshot-validation.md`

Modificados (26):
- `.env.example`
- `app/apps/core/tests/helpers.py`
- `app/apps/core/tests/test_permissions.py`
- `app/apps/core/tests/test_rendering_security.py`
- `app/apps/exports/admin.py`
- `app/apps/exports/docx.py`
- `app/apps/exports/epub.py`
- `app/apps/exports/forms.py`
- `app/apps/exports/models.py`
- `app/apps/exports/pdf.py`
- `app/apps/exports/services.py`
- `app/apps/exports/tasks.py`
- `app/apps/exports/tests.py`
- `app/apps/exports/urls.py`
- `app/apps/exports/views.py`
- `app/apps/manuscripts/test_hierarchy.py`
- `app/apps/manuscripts/test_versions.py`
- `app/config/settings/base.py`
- `app/templates/base.html`
- `app/templates/exports/export_detail.html`
- `app/templates/exports/export_form.html`
- `app/templates/exports/export_list.html`
- `app/templates/exports/export_preview.html`
- `docs/refactoring/03-data-migration-plan.md`
- `docs/refactoring/04-refactoring-roadmap.md`
- `README.md`

Backups y scripts QA locales ignorados no forman parte del codigo a publicar.
`subir_repo.bat` y los ocho `diff_*.txt` existentes conservan exactamente
sus huellas iniciales. No se hizo commit ni push.

## Riesgos pendientes y siguiente fase
- F5: lease, recuperacion de PROCESSING tras caida, notificaciones y retencion
  con reglas explicitas. PENDING enviado que se pierda en el broker necesita
  diagnostico operativo; no hay watchdog ni reenvio masivo automatico.
- Hay una ventana entre escritura de storage y commit final: un corte de proceso
  puede dejar un archivo huerfano. Una futura limpieza debe ser privada,
  idempotente y no tocar manuscritos ni versiones.
- Los locks son cooperantes para escritores de manuscritos. SQL o QuerySet.update
  sobre texto/estructura fuera de servicios puede violar el protocolo; no usarlo
  en escritores futuros. El trigger si protege UPDATE del snapshot en PostgreSQL.
- Copiar texto por solicitud consume almacenamiento y bloquea brevemente al editor;
  medir novelas grandes con carga real y definir cuotas/retencion mas adelante.
- El snapshot congela datos/configuracion, no binarios de librerias ni fuentes:
  una futura regeneracion puede diferir en paginacion o bytes. DONE no se regenera.
- Los limites de preview no son cuotas globales; faltan limites de CPU/tiempo y
  concurrencia por cuenta para produccion.
- EPUBCheck externo, indice dinamico/paginacion DOCX y fuentes personalizadas
  siguen siendo pendientes previos. No se incorporaron paquetes nuevos.
- No implementados: Markdown, nuevo ciclo de estados, correos, caducidad, pagos,
  suscripciones, IA, worldbuilding ni comparacion visual de versiones.
