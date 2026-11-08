# Validacion F5: ciclo de vida, recuperacion, correo y Markdown

Fecha: 2026-11-07 (UTC: 2026-11-08). Prompt 07, sobre la base existente.
Motor: Podman rootless, conexion `telar-fabulas-dev`, PostgreSQL 16.
No se modifico la maquina anterior ni se borraron volumenes.

## Alcance implementado

| Estado | Salidas permitidas |
| --- | --- |
| REQUESTED / Solicitada | PROCESSING; DELETED mediante cancelacion segura |
| PROCESSING / En proceso | READY; FAILED |
| FAILED / Fallida | REQUESTED si es recuperable y quedan intentos; DELETED |
| READY / Lista para descargar | DELETED |
| DELETED / Borrada | Ninguna |

Los servicios centralizan transiciones y auditoria. PostgreSQL valida el conjunto
de estados y rango de max_attempts. Web/admin no admiten estados enviados por el
cliente; acceso directo ORM/SQL sigue siendo privilegiado, no una API de negocio.

`error_message` se reutiliza, sin un segundo campo equivalente. `cleanup_error`
describe solo problemas de limpieza. Se agregaron intentos/maximo, token,
heartbeat/lease, backoff, expiracion, solicitud/borrado y fecha de correo.

### Claim, archivos y recuperacion

- Orden de locks: proyecto y luego trabajo. Solo REQUESTED sin borrado pendiente
  puede obtener un token nuevo e incrementar attempt_count.
- Un hilo renueva heartbeat cada 30 segundos como maximo, durante el render.
  El token y lease deben seguir vigentes para publicar; started_at no es el reloj
  de abandono. Un heartbeat atrasado no resucita un lease vencido.
- Cada intento queda en ExportAttempt. Sus rutas se derivan del job y UUID, no
  de titulos. Escritura `.part` exclusiva, fsync y os.replace en el mismo volumen.
  El lock de fila protege toda la publicacion. Un worker antiguo solo puede
  terminar calculos: no escribe archivos nuevos ni sustituye el resultado.
- Beat revisa cada minuto REQUESTED sin entrega o sin confirmacion dentro de la
  ventana, PROCESSING con lease vencido, FAILED con backoff vencido y borrados
  pendientes. No reconstruye snapshots. Redis fallando conserva REQUESTED.
- OSError/OperationalError son transitorios, excepto PermissionError. Errores de
  validacion, permisos, snapshot ausente/corrupto y desconocidos son definitivos.
  Maximo por trabajo: 3 por defecto; backoff 60, 120, 240... hasta 3600 segundos.
  Reintento manual no reinicia el contador. Los parciales se limpian antes de
  volver a generar; si el disco falla, se conserva el incidente visible.

### Borrado y caducidad

- POST con CSRF y propietario. PROCESSING se rechaza; cancelar REQUESTED pone
  una marca que impide que una entrega tardia lo reclame.
- La marca de borrado se confirma en una primera transaccion. Bloquea nuevas
  descargas. Otra transaccion elimina archivos, temporales y snapshot, y solo
  entonces confirma DELETED y deleted_at, conservando eventos e intentos.
- Un fallo o caida entre unlink y commit deja la marca durable para recuperacion.
  El reintento es idempotente. Nunca se elimina fuente, version, nota o personaje.
- La descarga mantiene un advisory lock compartido en una conexion dedicada
  durante FileResponse; cleanup solicita un lock exclusivo no bloqueante.
  Una descarga abierta puede terminar antes del borrado. Se rechazan symlinks,
  rutas fuera del propietario/proyecto y archivos referenciados por otro job.
- READY/FAILED caducan a los 7 dias por defecto. Beat limpia cada 24 horas;
  despues de expires_at ya no se puede abrir una nueva descarga. REQUESTED y
  PROCESSING no se borran por caducidad. No se purgan backups ni copias descargadas.

La coordinacion usa las garantias de locks de sesion/transaccion documentadas por
[PostgreSQL 16](https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS).
Celery usa ack tardio como ayuda, no como sustituto del reconciliador durable;
la [documentacion de tareas](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
explica por que un proceso perdido no equivale a entrega exactamente una vez.

### Correo

Checkbox activado por defecto. ExportNotification tiene unicidad por
job/evento/intento, claim temporal, fecha de envio y hasta ocho intentos de
entrega con backoff. Solo READY y FAILED definitivo crean aviso, no un fallo que
se reintentara. El idioma proviene del usuario (es-mx/en-us); el renderer de correo
tiene mensajes explicitos para ambos mientras no existe un catalogo general.
Textos preparados con gettext_lazy y override de locale.

Sin titulos, texto literario, snapshots ni adjuntos. Solo resultado, fecha UTC
de caducidad y enlace de detalle que requiere login. Errores SMTP no cambian el
estado del export. El backend por defecto escribe archivos privados locales;
no se enviaron correos reales en QA.

Garantia: **deduplicacion best-effort**, no exactamente una vez. Una caida despues
de la aceptacion SMTP y antes de sent_at puede duplicar el mensaje; el Message-ID
estable ayuda, pero no obliga al proveedor a deduplicar. Tras ocho fallos queda
un registro para revision; la entrega no esta garantizada.

### Formatos e interfaz

La interfaz ofrece Markdown, DOCX y PDF. HTML/EPUB siguen funcionando por los
servicios internos y en descargas historicas, sin cambiar sus nombres previos.
Preview HTML mantiene limites y aislamiento.

Markdown es UTF-8, `.md`, `text/markdown; charset=utf-8`, siempre desde el documento
del snapshot. WORK/FINAL, orden y encabezados siguen el selector existente. El
nivel viene de la profundidad real, incluyendo PART cuando existe. Escapa
sintaxis y conserva parrafos/saltos, sin incluir notas/personajes/metadatos.
Tambien conserva texto legado de contenedores en WORK; FINAL solo lleva texto de
las definitivas seleccionadas. La indentacion se escapa para no crear bloques de
codigo accidentalmente. No tiene maquetacion ni estilos tipograficos del PDF.

Formulario/lista/detalle muestran modalidad, formato, estado, fechas, intentos,
correo, descarga y borrado segun disponibilidad. REQUESTED/PROCESSING tienen
actualizacion manual de estado; no se agrego polling. Borrado pendiente bloquea
descargas sin inventar un sexto estado.

## Migracion y respaldo

Aplicada `exports.0003_export_lifecycle` despues de detener ordenadamente
web/worker/Beat. PENDING->REQUESTED, DONE->READY; PROCESSING/FAILED conservados.
Archivos y snapshots no se borran ni reescriben. Los historicos tienen correo
desactivado y una ventana completa de retencion desde la migracion. Se rechazan
estados desconocidos. Las pruebas incluyen datos historicos y snapshots reales.

Reversa protegida: no permite perder intentos/eventos/notificaciones, Markdown o
registros borrados. Conservar expansion y usar lector compatible, o restaurar una
copia aparte y conciliar escrituras posteriores; no ejecutar un reset de volumen.

Respaldo local, excluido de Git:

- `backups/p07_pre_lifecycle.dump`: pg_dump -Fc, pg_restore --list y restauracion
  completa a `p07_restore_check`. Huellas originales verificadas en la copia.
- `backups/p07_private_media.tar.gz`: almacenamiento privado previo a esta fase
  (sin archivos originales en esta base, comprobado al finalizar).
- `backups/p07_original_fingerprints.json`: solo hashes/conteos, no texto fuente.

La base temporal de restauracion se retiro. Las huellas finales coinciden:
1 cuenta, 1 proyecto, 1 nodo, 0 versiones, 1 personaje, 0 notas y 0 estilos.
Estos conteos solo describen la base actual, no la maquina anterior.

## Validacion

Suite final: **540 pruebas aprobadas en 265.306 segundos**, sin omisiones.
Son **58 pruebas nuevas** respecto a las 482 de Prompt 06: 48 funcionales,
9 de concurrencia/caida y 1 de migracion. La suite previa conserva su cobertura;
se adaptaron fixtures a READY/REQUESTED y los objetivos de migracion historica
a sus dependencias de esquema. No se modificaron las migraciones de manuscritos.

Pruebas nuevas: estados/transiciones, claim/lease/heartbeat/fencing, recuperacion,
backoff, maximo de intentos, snapshot inalterado, broker, publicacion atomica,
parciales, notificacion opt-in/locales/SMTP/duplicados, enlaces autenticados,
borrado POST/CSRF/propietario, streaming, symlinks/referencias cruzadas, caducidad,
fuentes intactas, Markdown/legacy/orden/jerarquia y migracion conservadora.

Nueve escenarios nuevos con transacciones y conexiones PostgreSQL separadas:
claim doble; worker duplicado; dos recuperadores; cancelar frente a claim;
heartbeat real en hilo; envio de correo concurrente; limpieza frente a descarga;
worker antiguo frente a publicacion nueva; caida despues de unlink conserva la
marca de borrado confirmada. No se mato ningun worker de produccion.

QA HTTP contra Gunicorn y worker/Redis reales, proyecto temporal:

| Comprobacion | Resultado |
| --- | --- |
| Markdown/DOCX/PDF WORK y FINAL | 6 archivos READY, un intento cada uno; descarga attachment privada |
| PDF descargado | Dos documentos abiertos con pypdf, seleccion correcta y rasterizacion para inspeccion |
| Interrupcion controlada | Claim+parcial+lease vencido -> FAILED -> POST retry -> READY, dos intentos |
| Snapshot y worker antiguo | Checksum inalterado, parcial retirado, publicacion antigua rechazada |
| Correo activado/desactivado | Entrega a backend local; sin avisos opt-out ni contenido literario |
| FAILED definitivo | Aviso local generado al agotar un intento configurado para QA |
| Borrado manual | Archivo y snapshot retirados; descarga devuelve 404 |
| Caducidad | Tarea Celery real elimina solo la exportacion temporal vencida |
| Fuentes | Hash de manuscrito/versiones/notas/personajes temporal intacto antes de retirar QA |
| Navegador | Formulario, estados, detalle y viewport movil revisados; descarga .md no navega fuera del detalle |
| Limpieza de QA | Cuenta/proyecto/filas/archivos/correos locales temporales retirados; datos originales intactos |

La comprobacion visual uso el navegador integrado disponible, sin cambiar la
preferencia Chrome de la TUI. Las copias sinteticas de QA quedan en backups/p07_qa;
la descarga de navegador quedo en Downloads. No contienen manuscritos originales.

Comandos principales ejecutados sobre `telar-fabulas-dev`:

```powershell
podman --connection telar-fabulas-dev compose stop web worker beat
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py makemigrations exports --name export_lifecycle
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py migrate --noinput
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec web python manage.py check
podman --connection telar-fabulas-dev compose exec web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose exec web python manage.py migrate
podman --connection telar-fabulas-dev compose exec web python manage.py test --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
podman --connection telar-fabulas-dev compose ps
```

Check sin problemas, esquema al dia, worker pong, cinco servicios y un solo Beat.
No se instalaron dependencias nuevas; pyproject.toml y uv.lock permanecen intactos.

## Inventario de esta fase

Comparado por SHA-256 contra el estado inicial del turno, no contra HEAD, porque
el repositorio ya contenia cambios de fases previas sin commit.

Archivos nuevos:

```text
app/apps/exports/files.py
app/apps/exports/lifecycle.py
app/apps/exports/markdown.py
app/apps/exports/notifications.py
app/apps/exports/migrations/0003_export_lifecycle.py
app/apps/exports/test_lifecycle.py
app/apps/exports/test_lifecycle_concurrency.py
app/apps/exports/test_lifecycle_migration.py
docs/refactoring/12-export-lifecycle-validation.md
```

Archivos modificados:

```text
.env.example
README.md
app/config/settings/base.py
app/apps/core/permissions.py
app/apps/core/tests/test_admin_security.py
app/apps/core/tests/test_permissions.py
app/apps/core/tests/test_private_files.py
app/apps/exports/admin.py
app/apps/exports/forms.py
app/apps/exports/job_services.py
app/apps/exports/models.py
app/apps/exports/tasks.py
app/apps/exports/urls.py
app/apps/exports/views.py
app/apps/exports/tests.py
app/apps/exports/test_snapshots.py
app/apps/exports/test_snapshot_concurrency.py
app/apps/exports/test_snapshot_migration.py
app/apps/manuscripts/test_hierarchy.py
app/apps/manuscripts/test_migrations.py
app/apps/manuscripts/test_version_migrations.py
app/templates/base.html
app/templates/exports/export_form.html
app/templates/exports/export_list.html
app/templates/exports/export_detail.html
docs/refactoring/03-data-migration-plan.md
docs/refactoring/04-refactoring-roadmap.md
docs/refactoring/05-risk-register.md
```

Backups y scripts/evidencia temporal estan excluidos de Git. No se borro ningun
archivo previo. `subir_repo.bat`, `diff_*.txt`, TUI y sus preferencias se conservan.

## Limites y siguiente fase

- PostgreSQL directo y volumen local privado compartido son requisitos de esta
  implementacion. Adaptar locks/publicacion antes de S3 o transaction pooling.
- Una conexion adicional por descarga activa; dimensionar pools y servidores.
- SMTP real no probado ni activado. Revisar agotamiento de envios, credenciales,
  reputacion del remitente y monitorizacion antes de produccion.
- Beat debe tener una instancia; sin scheduler/broker no hay recuperacion ni
  notificacion o limpieza hasta que vuelvan. Las solicitudes permanecen en DB.
- Un renderer colgado que continua renovando heartbeat requiere supervision;
  faltan cuotas, presupuestos de memoria/tiempo y ensayos con novelas grandes.
- PostgreSQL y disco no comparten transaccion; las marcas y rutas durables hacen
  las operaciones recuperables, no reemplazan backups ante perdida del volumen.
  Los puntos de entrada actuales llaman delete_export sin una transaccion externa;
  conservar ese limite para que su primera fase pueda confirmar la marca durable.
- La purga de exportaciones no es purga de usuarios/proyectos ni de sus backups.
- Siguiente fase: F6 (mundo y referencias), con alcance acotado y aislamiento por
  proyecto. No se implementaron geografia, organizaciones, suscripciones, Stripe,
  IA, imagenes ni comparacion visual de versiones en esta entrega.
