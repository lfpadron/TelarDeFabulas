# F6.4: referencias, bibliografia y materiales de apoyo

Fecha: 2026-11-08. Prompt 11 sobre la estructura existente.
Django 5.2.19, PostgreSQL 16, uv y Podman rootless; conexion explicita
telar-fabulas-dev. Se preservaron los cambios pendientes de Prompt 09/10.
Sin reconstruccion del proyecto, borrado de bases/volumenes, cambios a la maquina
anterior, TUI/Chrome, subir_repo.bat ni diff_*.txt.

## Modelo y reglas

ReferenceMaterial pertenece a Project y admite BIBLIOGRAPHY, LINK, IMAGE, DOCUMENT
y OTHER. Campos: title, short_description, notes, author, publication_year_text,
publisher, source_url, file, file_size, mime_type, original_filename, created_at,
updated_at. El anio es texto libre para calendarios ficticios; campos
bibliograficos opcionales. Texto plano escapado, con saltos de linea conservados.

LINK requiere URL HTTP/HTTPS; IMAGE requiere JPEG/PNG/WebP; DOCUMENT requiere
PDF/TXT/MD/DOCX. BIBLIOGRAPHY y OTHER admiten texto sin archivo/URL. Titulo y
proyecto obligatorios. No se trasladan materiales entre proyectos ni se editan
metadatos de archivo desde el cliente. Tamano y MIME se derivan de bytes reales.
Checks SQL de tipo, titulo no blanco, obligatorios por tipo y revision positiva;
indice (project,material_type,-updated_at), ademas del indice de FK.

ReferenceAssociation contiene reference, description y created_at, con cinco
FK opcionales: manuscript_node, character, geographic_location, organization y
worldbuilding_entry. CHECK SQL exige exactamente una; cinco UNIQUE parciales
impiden repetir referencia/destino. clean() y servicios exigen el mismo proyecto,
tambien si dos proyectos son del mismo autor. No hay GenericForeignKey.

Cada vinculo conserva una sola referencia, sin copiar el archivo. Borrar entidad
elimina su vinculo por CASCADE, nunca el material. Desvincular conserva material
y archivo; un material sin asociaciones sigue siendo valido. Eliminar material
elimina sus asociaciones, pero no las entidades. No se agrega purga de proyectos.

ReferenceFileCleanup es una tercera tabla tecnica: project_id numerico (no FK
para sobrevivir al borrado del proyecto), nombre UUID unico, tamano, intentos,
proximo intento, clase del ultimo error y fecha. No aparece en el admin del autor
ni es una papelera. Solo registra archivos para limpieza/reintento.

## Servicios, concurrencia y revision

services.py ofrece create_reference, update_reference, delete_reference,
attach_reference, detach_reference, get_references_for_entity y reexporta
validate_reference_upload. El selector por entidad devuelve asociaciones con
referencia/destino cargados, de modo que la UI pueda mostrar la descripcion y
desvincular por ID. Los servicios con actor revalidan propiedad; model.save
tambien usa los mismos servicios para validar integridad y estado.

Orden: atomic -> Project select_for_update -> referencia actual -> escritura.
Revalidacion de estado despues de tomar el bloqueo. La comprobacion de cuota,
reserva del archivo nuevo, guardado y encolado de limpieza ocurren bajo ese lock.
Todos los endpoints POST y el admin conservan el lock durante validacion/guardado.
Character.delete ahora toma ese bloqueo antes de que Django recolecte relaciones;
los otros cuatro modelos de destino ya seguian ese protocolo. Las diez pruebas
concurrentes incluyen vincular mientras se elimina cada tipo de entidad.

Revision inicial 1; cada guardado incrementa la revision, incluso si no cambia
los valores. El formulario envia expected_revision; una revision obsoleta produce
409 con textos conservados, sin sobrescribir ni guardar el upload. Edicion y
confirmacion de borrado requieren revision; el admin tambien la comprueba.
Una copia vieja del modelo no se vuelve vigente modificando su propiedad revision.
No hay historial completo, fusion automatica ni almacenamiento durable del
formulario rechazado. Un upload rechazado debe volver a seleccionarse.

## Archivos privados y validacion

PRIVATE_MEDIA_ROOT/references/<project_id>/<uuid>.<extension>. La extension se
canonicaliza (.jpeg -> .jpg), pero los bytes se conservan. Nunca se usa el nombre
original como ruta fisica, ni se guardan archivos/base64 en PostgreSQL.

Validacion antes de publicar:
- Nombre NFC, limite 240, sin traversal, separadores, controles Unicode,
  nombres reservados de Windows ni terminaciones peligrosas.
- Lectura acotada al limite + 1; se ignoran MIME/tamano declarados por el cliente.
  Se rechazan vacios, formatos prohibidos y extension incompatible.
- JPEG/PNG/WebP: verificacion y decodificacion Pillow, reutilizando el validador
  existente; formato real debe coincidir con la extension.
- PDF: firma %PDF y EOF; pypdf en modo estricto, sin recuperacion de catalogo,
  catalogo/arbol de paginas basico. Cifrados rechazados; no se renderiza ni ejecuta
  contenido. Esto no verifica exhaustivamente todos los objetos del documento.
- DOCX: ZIP sin cifrado, rutas peligrosas ni symlinks; maximo 2048 miembros,
  50 MiB descomprimidos, 20 MiB por miembro y ratio 200. Lectura con CRC, XML UTF-8
  sin DTD/entidades; tipos de contenido, relacion principal y document/body OOXML.
  Se rechazan macros/VBA y componentes .bin/.exe. No hay extraccion al filesystem.
- TXT/MD: UTF-8 (BOM permitido), sin NUL/controles binarios; HTML/SVG/script
  evidentes rechazados. Markdown se descarga, nunca se renderiza como contenido activo.

Unica dependencia nueva: pypdf>=6.18,<7, resuelta a 6.21.4 en uv.lock; no se
actualizaron otros paquetes en esta fase. Se usa el parser mantenido, no uno PDF
propio. API consultada: [PdfReader](https://pypdf.readthedocs.io/en/stable/modules/PdfReader.html).
Pillow y python-docx ya existian; no hay servicio nuevo.

Descarga autenticada y acotada por propietario/proyecto/estado. Ruta UUID validada
de nuevo, sin symlinks ni salida del directorio del proyecto. Apertura bajo
bloqueo antes de soltarlo; en Linux el descriptor abierto permite completar una
descarga aunque se reemplace/elimine el nombre despues. Content-Disposition:
attachment para todos los formatos, incluido imagen; Cache-Control privado,
no-store, nosniff y CSP de la infraestructura central. /media/ y /private_media/
no sirven estos archivos. Formularios/admin no revelan rutas ni URL del storage.
source_url admite solo HTTP/HTTPS, con noopener noreferrer; no hay fetch externo.

## Cuotas y ciclo de archivos

Valores .env por defecto (MiB = 1024*1024 bytes):
REFERENCE_IMAGE_MAX_MB=10, REFERENCE_DOCUMENT_MAX_MB=20,
REFERENCE_PROJECT_STORAGE_MAX_MB=500. Configuracion invalida impide arrancar;
rango 1..100 para archivos y 1..1048576 para agregado. Los limites de expansion
DOCX son independientes. Recrear los servicios tras modificar .env.

La cuota agrega ReferenceMaterial.file_size y ReferenceFileCleanup.file_size
del proyecto. Project se bloquea para impedir que dos subidas aprueben el mismo
espacio. Un reemplazo requiere margen para el viejo y el nuevo hasta limpiar.
La cuota solo cubre referencias, no imagenes de personajes, exportaciones,
backups o todos los bytes fisicos del disco; no es una regla comercial por plan.

Reemplazo: validar -> escribir UUID exclusivo/fsync -> guardar DB -> commit ->
limpieza del anterior. Si falla la escritura o DB, el original se conserva y se
retira la copia nueva cuando es posible. El admin devuelve error de formulario
en fallos de escritura, sin perder el texto enviado. Quitar un archivo opcional
tambien encola limpieza; IMAGE/DOCUMENT no pueden quedar sin archivo.

El borrado de referencia usa confirmacion GET y POST/CSRF/revision. post_delete
encola la ruta en la misma transaccion; on_commit intenta borrarla. Si falla,
conserva el registro con clase de error sin rutas en logs. Beat despacha
apps.references.cleanup_files cada 60 segundos; cada registro usa backoff
exponencial hasta un dia. Worker comprueba que ningun material usa esa ruta antes
de borrar; tras exito elimina el registro tecnico. Pending sigue ocupando cuota.

Filesystem y DB no son atomicos. Un rollback externo al servicio o caida antes
del commit puede dejar un UUID no registrado. Comando explicito para reconciliar
solo rutas UUID sin referencia y de al menos 24 horas, revalidando bajo lock:
cleanup_reference_files --orphans. No recorre otras apps ni borra fuentes.
Estos huerfanos no cuentan en la cuota hasta inventariarlos; programar revision
operacional con backups/alertas. El retry normal no activa barridos automaticamente.
Las pruebas cubren rollback, archivo vivo protegido, huerfano antiguo y archivo
reciente conservado. Los directorios vacios de QA pueden permanecer; no son datos.

## Interfaz, permisos y rendimiento

Rutas bajo /projects/<project_pk>/references/:
listado, create/, <reference_pk>/, edit/, delete/, download/, attach/,
associations/create/ y associations/<association_pk>/delete/.
En create/attach se admite exactamente una preseleccion validada:
character, node, location, organization o worldbuilding. Ni GET ni POST
permiten usar una entidad de otro proyecto. No hay redireccion next arbitraria.

Acceso desde el proyecto y seccion en fichas de los cinco destinos. Listado con
busqueda titulo/descripcion/autor/editorial, filtro de tipo, actualizacion, conteo
de asociaciones y acciones. Detalle bibliografico/notas/archivo/tamano/enlace
externo y asociaciones. Paginacion de 50, tambien dentro de las fichas.

Sin N+1: select_related, conteo SQL correlacionado y textos largos diferidos en
listados de materiales/asociaciones. No se abren archivos al listar. La prueba
del listado registra hasta diez consultas; la del selector recorre referencias,
titulos de entidad y URLs en una sola consulta. Formularios aun cargan todas las
opciones del proyecto; medir escala antes de introducir carga progresiva.

Permisos centrales: ACTIVE lectura/escritura; FROZEN/PENDING_DELETION lectura
y descarga, escritura 403; DELETED y autor ajeno 404. Incluye BUSINESS_ADMIN,
TECH_ADMIN y superusuarios; no reciben privilegios sobre contenido ajeno.
CSRF y respuestas privadas conservados; textos con gettext_lazy/trans.

Admin registra ambos modelos, filtra datos y FK por propietario/proyecto,
oculta rutas, difiere texto largo y conserva revision. Referencias no tienen
borrado admin individual/masivo: usar la confirmacion del autor. Asociaciones
permiten borrado individual; no bulk. Campos de identidad no se editan.

## Migracion, respaldo e integridad

references.0001_initial creada, plan inspeccionado y aplicada: solo las tres
tablas nuevas, sus indices y constraints. Sin RunPython ni modificacion de
tablas anteriores. Dependencias explicitas de los cinco destinos y Project.
Las pruebas historicas de migracion excluyen references de sus targets antiguos
para no reconstruir una dependencia futura accidentalmente; las migraciones
historicas de produccion no se editaron. Prueba aditiva con fixtures de las
entidades anteriores y comparacion de campos.

Backups previos locales ignorados por Git:
- backups/p11_pre_references.dump, pg_dump -Fc copiado al workspace.
- backups/p11_private_media.tar.gz.
- backups/p11_original_fingerprints.json.

SHA-256 de todas las columnas originales/media iguales despues de migrate y
tras retirar QA. Inventario conservado: una cuenta, un proyecto, un nodo, tres
personajes, tres papeles dramaticos, dos ubicaciones y dos organizaciones.
Cero versiones, menciones, afiliaciones, worldbuilding, notas, estilos, trabajos,
snapshots y media originales. Nuevas tablas de referencias vacias tras QA.

No se ensayo restauracion nueva en esta fase. Ninguna base ni volumen se elimino,
incluida test_telar_fabulas (--keepdb). La maquina anterior no se opero.
No usar migrate references zero con contenido ni restaurar el dump previo como
rollback rutinario: perderia los materiales posteriores. Preferir correccion
hacia delante y conservar DB/media juntos.

## Pruebas automatizadas

102 nuevas aprobadas: 91 funcionales/validacion, diez carreras PostgreSQL con
conexiones independientes y una migracion. Pase focalizado final: 50.920 s.
Suite integrada: **911 pruebas aprobadas**, 486.994 s, sin fallos.
Regresion de cuentas, manuscritos/versiones, personajes, geografia,
organizaciones, worldbuilding, notas, estilos y exportaciones conservada.
Logs de fallos de disco/exportacion durante tests corresponden a casos simulados.

Cobertura: cinco tipos, obligatorios, bytes/MIME reales, siete formatos,
nombres/URL/archivos peligrosos, corruptos/vacios/tamano, ZIP/XML y cifrado;
cuota y headroom, rollback/fallo fisico/reintento; cinco destinos, pertenencia,
duplicados/CHECK SQL, eliminacion independiente y enlaces heredados corruptos
ocultos; aislamiento web/admin/CSRF/estados; CRUD, filtros, preseleccion,
paginacion, descarga/headers, revision obsoleta y formularios recuperables.

Carreras: dos subidas/cuota; dos reemplazos; duplicar vinculo; borrar vs reemplazar;
vincular vs borrar referencia; descargar vs borrar; admin vs servicio; vincular
vs borrar personaje; vincular vs borrar los otros cuatro tipos (subcasos);
asociar desde admin vs borrar personaje. En la primera ejecucion se encontro la
carrera del collector de Character.delete y se corrigio tomando Project primero.
Tambien se corrigieron el formulario admin de solo lectura y su render de errores
de alta/upload. Los pases finales no relajan las comprobaciones de seguridad.

## QA real de escritorio y movil

Dos cuentas y proyecto temporales. Libro I/Capitulo 3 y Reino de Lumbre/Ciudad de
Cristal creados solo para QA. PNG sinteticos de prueba, no mapas ni activos del autor.

En navegador integrado a 1280x900:
- Navegacion desde proyecto, alta IMAGE Mapa del Reino y upload real mediante picker.
- Tres vinculos desde formulario: Reino de Lumbre, Ciudad de Cristal, Capitulo 3.
- Seccion bidireccional en ficha de Reino de Lumbre.
- Click Descargar archivo conserva la pagina y crea un PNG descargado.
  SHA-256 del archivo descargado igual al de origen.
- Una sola ruta fisica para las tres asociaciones, confirmada desde el contenedor.

Movil 390x844: listado/filtro/busqueda, formulario y reemplazo del archivo junto
con edicion de notas. Referencia conserva PK y tres vinculos; revision 2. Capturas
inspeccionadas, sin controles fuera del viewport ni scroll horizontal; consola
sin errores. No se cambio el navegador Chrome configurado en la TUI.

HTTP real contra Gunicorn (cookies/CSRF): descarga bytes/attachment/cache exactos;
el UUID viejo desaparece tras reemplazar. Admin negocio ajeno 404; estados
congelado/pendiente solo lectura; DELETED 404; media publico 404. GET de confirmacion
no modifica. POST desvincula Ciudad de Cristal y conserva los otros dos enlaces
y archivo; POST elimina referencia/archivo/vinculos sin borrar las cuatro entidades.

Retirados solo proyecto, cuentas, entidades y sesiones QA, resolviendo hijos antes
de padres PROTECT. Verificacion original identica. state.json con credenciales
temporales retirado. Evidencia conservada localmente, ignorada por Git:
backups/p11_qa/results.json, detail-desktop.png, list-mobile.png, form-mobile.png,
detail-mobile.png y PNG de prueba; scripts backups/p11_qa.py y p11_ops.py.

## Operacion validada

Todos los comandos Compose usan podman --connection telar-fabulas-dev.
Se inicio postgres/redis existentes (estaban detenidos), sin reset. Se construyo
web/worker/beat, se respaldo y migro mediante compose run --rm --no-deps web antes
de arrancar escritores. Luego:

```powershell
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec web python manage.py check
podman --connection telar-fabulas-dev compose exec web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose exec web python manage.py migrate --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.references --keepdb --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py test --keepdb --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
podman --connection telar-fabulas-dev compose ps
```

Check sin incidencias; plan final vacio, sin migraciones/cambios de modelos
pendientes. Celery pong; Beat emite la tarea de limpieza y worker la termina
correctamente. Cinco servicios activos, una instancia de Beat, Rootless=true.
Compose usa docker-compose.exe como proveedor contra Podman; no es motor Docker.
uv lock, pg_dump/copia, scripts de QA/huellas y git diff --check completan validacion.
No correr suites simultaneas sobre la misma base de pruebas.

## Inventario de esta fase

35 archivos versionables creados (no confundir con nuevos de fases anteriores):

```text
app/apps/references/__init__.py
app/apps/references/admin.py
app/apps/references/apps.py
app/apps/references/files.py
app/apps/references/forms.py
app/apps/references/management/__init__.py
app/apps/references/management/commands/__init__.py
app/apps/references/management/commands/cleanup_reference_files.py
app/apps/references/migrations/0001_initial.py
app/apps/references/migrations/__init__.py
app/apps/references/models.py
app/apps/references/selectors.py
app/apps/references/services.py
app/apps/references/signals.py
app/apps/references/tasks.py
app/apps/references/templatetags/__init__.py
app/apps/references/templatetags/references.py
app/apps/references/test_concurrency.py
app/apps/references/test_migrations.py
app/apps/references/test_support.py
app/apps/references/test_uploads.py
app/apps/references/tests.py
app/apps/references/urls.py
app/apps/references/validators.py
app/apps/references/views.py
app/templates/admin/references/referencematerial/change_form.html
app/templates/references/_entity_section.html
app/templates/references/_pagination.html
app/templates/references/association_confirm_delete.html
app/templates/references/base.html
app/templates/references/confirm_delete.html
app/templates/references/detail.html
app/templates/references/form.html
app/templates/references/list.html
docs/refactoring/16-references-validation.md
```

20 archivos modificados respecto del inicio de Prompt 11:

```text
.env.example
README.md
app/apps/characters/models.py
app/apps/geography/test_migrations.py
app/apps/manuscripts/test_migrations.py
app/apps/manuscripts/test_version_migrations.py
app/apps/organizations/test_migrations.py
app/apps/worldbuilding/test_migrations.py
app/config/settings/base.py
app/config/urls.py
app/templates/characters/character_detail.html
app/templates/geography/detail.html
app/templates/manuscripts/node_detail.html
app/templates/organizations/detail.html
app/templates/projects/project_detail.html
app/templates/worldbuilding/detail.html
docs/refactoring/04-refactoring-roadmap.md
docs/refactoring/05-risk-register.md
pyproject.toml
uv.lock
```

Backups/scripts/capturas son locales ignorados y no forman parte del codigo
versionable. El inventario compara SHA-256 contra el inicio de esta fase, no
solo git status, porque habia cambios anteriores sin commit.

## Riesgos y siguiente fase

Validacion no equivale a antivirus; parsers de documentos necesitan seguimiento
de seguridad y limites operativos de CPU/memoria. Sin render ni ejecucion en el
servidor, pero abrir un documento en otra aplicacion requiere precauciones.
Los limites ZIP estrictos/UTF-8 pueden rechazar documentos legitimos no soportados.
No hay OCR, IA, importacion bibliografica ni exportacion de referencias.

SQL directo/QuerySet.update/bulk/delete son APIs privilegiadas, no entradas de
negocio; no garantizan pertenencia/revision. El volumen privado debe ser escrito
solo por la aplicacion; rechazar symlinks no protege contra un proceso local
hostil con acceso al mismo volumen. Cuota logica no sustituye medir disco libre.

Pendientes: monitorizar cola de limpieza/espacio, reconciliar huerfanos tras
caidas, respaldos cifrados/externos con restauracion recurrente, carga real con
miles de opciones, recursos de workers/web y hardening/TLS. Las copias descargadas
y backups no se eliminan al borrar el archivo activo. Sin papelera general ni
historial de referencias; recuperacion desde respaldo.

Recomendacion: **F7, relaciones de personajes**, definiendo simetria/direccion,
duplicados y pertenencia, reutilizando las referencias para imagenes y sin
duplicar afiliaciones de F6.2. Exportacion de entidades/materiales queda para F8;
suscripciones/cobros y politica de retencion requieren entregas independientes.

