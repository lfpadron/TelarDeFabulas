# F8: exportacion del universo narrativo

Fecha: 2026-11-09. Prompt 13. Implementacion sobre la base existente, sin nuevos
servicios, dependencias, tablas de trabajos ni almacenamiento paralelo.
Fuente de verdad: codigo actual de exports, characters, geography, organizations,
worldbuilding y references; contratos de 02, 04, 05, 11, 12, 16 y 17 conservados.

## Resultado

- **1093 pruebas aprobadas**, frente a 1005 de F7: 88 nuevas.
- `exports.0004_world_exports` inspeccionada y aplicada, sin cambios pendientes.
- `check` sin incidencias; Celery `pong`; cinco servicios en `telar-fabulas-dev`,
  Podman rootless confirmado. PostgreSQL y Redis conservan sus volumenes.
- Nueve exportaciones reales; Markdown, DOCX y PDF privados descargados.
- Capturas conservadas tras editar texto/relaciones/estilo, mover y borrar fuente.
- QA temporal eliminado; huellas de los 22 modelos originales y media identicas.
- No se modificaron `subir_repo.bat`, `diff_*.txt`, TUI, configuracion de Chrome,
  uv.lock, pyproject.toml, compose.yaml ni la maquina Podman anterior.

## Alcances y contenido

| Alcance | Seleccion y contenido |
| --- | --- |
| CHARACTER | Una ficha con campos reales no vacios, papeles dramaticos, residencia, afiliaciones/periodos, relaciones salientes/entrantes/mutuas y bibliografia |
| CHARACTERS_ALL | Personajes por nombre/PK; una ficha por ID y un apartado comun de relaciones. Una relacion mutua se representa una vez; las unilaterales no se convierten |
| GEOGRAPHIC_LOCATION | Una ubicacion; descendientes opcionales. Ruta completa, tipo/descripciones, residentes, sedes y referencias |
| GEOGRAPHY_ALL | Arbol completo en preorden, posicion del autor y PK estable; cada ubicacion una vez |
| ORGANIZATION | Una organizacion; subordinadas opcionales. Tipo/descripciones, superior, ruta, sede, integrantes y referencias |
| ORGANIZATIONS_ALL | Arbol completo. Varias afiliaciones de un personaje se agrupan bajo su nombre dentro de cada organizacion, conservando cargos/estados/periodos |
| WORLDBUILDING_ENTRY | Una entrada y sus referencias, con categoria, titulo, descripcion y contenido |
| WORLDBUILDING_CATEGORY | Categoria obligatoria POLITICS, RELIGION o HISTORY; posicion/PK del autor |
| WORLDBUILDING_ALL | Politica, religion e historia, en ese orden, omitiendo categorias vacias |
| REFERENCE_MATERIAL | Una ficha bibliografica, metadatos seguros del adjunto y destinos vinculados |
| REFERENCES_ALL | Catalogo por titulo/PK, sin copiar documentos ni imagenes |
| WORLD_COMPENDIUM | Personajes, geografia, organizaciones, politica, religion, historia y referencias; sin secciones vacias ni contenido de manuscritos |

Las referencias asociadas se agregan como fichas al catalogo bibliografico una
sola vez, aunque se mencionen desde varias entidades. Los nombres de personajes,
sedes o entidades vinculadas pueden repetirse como contexto, no como fichas
duplicadas. Un vinculo bibliografico con un manuscrito conserva solo el titulo
o identificador, no content ni SceneVersion. Una seleccion vacia se rechaza.

Para arboles individuales, la profundidad se normaliza desde la raiz elegida;
la ruta textual conserva los antecesores del proyecto. No se impone jerarquia
de tipos ni se reparan ciclos o datos cruzados durante una exportacion.

## Snapshot y concurrencia

`request_export` es el unico servicio de solicitud. Mantiene UUID de idempotencia,
bloqueo de Project seguido de StyleTemplate, revalidacion de propietario/estado,
captura, guardado atomico de job/snapshot y encolado despues del commit.
Una clave repetida con el mismo alcance reutiliza la captura; cambiar seleccion,
formato, estilo, modalidad o preferencia de correo con esa clave se rechaza.
No se guardan nuevas FK hacia entidades seleccionadas: borrarlas no cambia el
alcance ni convierte una exportacion individual en una exportacion completa.

Los manifiestos literarios siguen en `schema_version=1`. REFERENCE usa esquema 2:
- Proyecto, propietario, creador, locale, formato y modalidad.
- Seleccion normalizada: scope_kind, entity_id, category, include_descendants.
- Secciones ordenadas con titulo, profundidad, texto, clase/ID fuente, padre y
  posicion cuando corresponda. Campos y etiquetas se materializan al solicitar.
- Configuracion editorial completa, con decimales serializados como texto.
- Conteo de fichas principales y referencias agregadas; conteos de escenas cero.

Se conserva SHA-256 sobre JSON canonico UTF-8 y el trigger PostgreSQL que impide
UPDATE. No hay recalculo desde fuentes en un retry. `get_export_document` valida
checksum, bytes, propietario/proyecto, formato/modalidad, estilo y alcance;
materializa `ReferenceSection` dentro del documento neutral existente.
El worker consulta el job/proyecto para autorizar y gestionar su estado, pero
no consulta contenido vivo de personajes, relaciones, ubicaciones, organizaciones,
worldbuilding ni referencias para renderizarlo. Una prueba verifica una sola
consulta al snapshot al cargar el documento y renderizar MD/HTML/DOCX.

Once pruebas PostgreSQL con conexiones separadas: captura frente a edicion de
personaje, relacion, afiliacion, referencia, entrada y estilo; movimiento de
ubicacion/organizacion; borrado de personaje; doble solicitud con la misma clave;
proyecto eliminado mientras se espera el lock. Escritores normales cooperan con
Project. SQL y bulk privilegiados no son una API de negocio ni quedan serializados
automaticamente por esta captura.

## Renderizado y privacidad

Se reutilizan los exportadores actuales, sin tres selectores independientes.
Markdown escapa puntuacion/HTML y conserva parrafos; agrega indice textual para
REFERENCE si el estilo lo pide. DOCX usa las mismas fuentes, margenes, headings
y el indice estatico existente. PDF usa el mismo HTML escapado, CSS incrustado
y fetcher que impide recursos externos. Encabezados hasta nivel seis; se mantiene
la profundidad completa en el manifiesto y las rutas textuales.

La whitelist no consulta `Character.image` ni `ReferenceMaterial.file`. Los
archivos fuente no se abren; una prueba hace fallar Storage.open y los tres
formatos siguen funcionando. Nombre original se valida sin rutas; MIME y
descripcion se capturan como texto. No ZIP, binarios, OCR ni recursos externos.
URLs bibliograficas HTTP(S) validas pueden aparecer como texto. Se omiten userinfo,
localhost/IP privadas, rutas de media/descarga de proyecto y parametros/fragmentos
con tokens, firmas o credenciales reconocibles. Esto no sustituye DLP: un secreto
pegado por el autor en biografia/notas o una URL opaca sigue siendo texto autoral.

Propietario exclusivo y politica central: ACTIVE/FROZEN/PENDING_DELETION permiten
exportar; DELETED y proyectos ajenos reciben 404. El servicio rechaza IDs ajenos;
el formulario usa ModelChoiceField acotado, por lo que un ID manipulado recibe
error de seleccion sin revelar su contenido. Asociaciones cruzadas detectadas
provocan rechazo, no se mezclan datos de otros proyectos. POST con CSRF, estilo
propio/sistema y combinacion modo/alcance/formato validada tambien en SQL.

Descarga autenticada como attachment, no-store y sin rutas publicas de media.
El historial unico muestra modalidad, alcance, estilo capturado, estado, fechas,
caducidad, intentos, correo y acciones. El formulario de consulta no presenta
WORK/FINAL. El control condicional de campos va en el template, como los estilos
actuales: no depende de servir un archivo JS con Gunicorn ni agrega dependencias.

## Ciclo de vida

No cambia tasks.py ni se duplican tareas periodicas. REQUESTED, PROCESSING,
FAILED, READY y DELETED, leases, heartbeat, token de intento, outbox, retry,
retencion y borrado usan la infraestructura F5. La limpieza retira snapshot y
artefactos del trabajo, no entidades fuente. La descarga expirada se bloquea
antes de ejecutar la limpieza diaria. Notificacion opcional verificada con backend
de correo en memoria; no se afirma entrega SMTP externa en esta fase.

## Rendimiento y limites

`CaptureBudget` usa agregados previos de filas/longitud y lecturas por lotes de
200 filas, con whitelist de campos. Acumula bytes UTF-8 y fuentes distintas;
el documento vuelve a validarse por bytes durante la construccion y al calcular
su checksum. Reutiliza `EXPORT_SNAPSHOT_MAX_NODES` (10000 por defecto) y
`EXPORT_SNAPSHOT_MAX_BYTES` (20 MiB). No son nuevos limites de plan comercial.
El presupuesto cuenta tambien contexto/antecesores/roles/vinculos; las lecturas
repetidas se cuentan conservadoramente por bytes. Un alcance menor puede ser
necesario aunque las fichas principales sean pocas. No hay truncamiento silencioso.

Arboles y recorridos iterativos: prueba de 1052 ubicaciones, rama de 1050, sin
RecursionError. Numero de consultas constante al agregar 60 personajes; sin
consultas por cada relacion, miembro, residente o referencia. Los renderizadores
siguen materializando su salida y el presupuesto no es una cota exacta de RSS;
falta medir memoria/latencia y contencion del bloqueo con proyectos representativos.
Se conservan limites y concurrencia Celery existentes. Selectores HTML e historial
no se paginan en esta entrega; crecimiento grande requiere trabajo de capacidad.

## Migracion y datos originales

`exports.0004_world_exports` agrega:
1. ExportJob.scope_kind, default MANUSCRIPT para historicos.
2. ExportSnapshot.included_entity_count, default cero.
3. Opcion REFERENCE y CHECK de combinaciones validas.
4. Guardia de reversa mientras exista cualquier job REFERENCE, incluso borrado.

No crea tablas, no modifica JSON/checksum/archivos historicos ni elimina registros.
La prueba 0003 -> 0004 compara todos los campos previos de jobs y snapshots de
HTML/EPUB/Markdown/DOCX/PDF, verifica los defaults, trigger inmutable y reversa
rechazada. La prueba de lifecycle anterior queda fijada en 0002 -> 0003 para
comparar su contrato; el nuevo test cubre la extension siguiente.

Se arrancaron PostgreSQL/Redis existentes, se respaldaron DB y media y se registro
el inventario antes de migrar. Se inspecciono el archivo y `migrate --plan`;
0004 se aplico con web/worker/beat detenidos. Luego se reconstruyeron y arrancaron
los cinco servicios. No se toco la maquina anterior ni se borro ninguna base o
volumen; `--keepdb --noinput` conserva la base de pruebas separada.

Respaldo local ignorado en Git/imagen: `backups/p13_pre_world_exports.dump`,
`p13_private_media.tar.gz`, `p13_original_fingerprints.json`. No hubo ensayo nuevo
de restauracion; sigue pendiente una politica externa/cifrada/recurrente.
No restaurar este dump ni revertir columnas como rollback rutinario despues de
crear datos nuevos: mantener esquema compatible y corregir hacia delante.

Originales antes/despues: 1 usuario, 1 proyecto, 1 nodo literario, 3 personajes,
3 papeles dramaticos, 2 ubicaciones, 2 organizaciones y **1 referencia**. Demas
modelos de negocio cero y media sin archivos. SHA-256 de todas las filas y campos
originales de 22 modelos identico despues de migrate y de retirar QA.

## Pruebas automatizadas

88 nuevas: 76 funcionales en test_world_exports.py, 11 concurrentes en
test_world_export_concurrency.py y una de migracion en test_world_export_migration.py.
Cubren los doce alcances, descendientes, orden/direccion, inmutabilidad ante
cambios/borrado, idempotencia, checksum, formatos reales, XSS, metadatos sin
binarios, URLs privadas, IDs/asociaciones ajenos, estados del proyecto, CSRF,
formulario, constraint SQL, lifecycle, notificaciones, recuperacion, limites y
arboles profundos. Fixture compartida sin heredar otras clases de prueba.

La ejecucion focal de 241 pruebas detecto un error en el helper de prueba de
descarga: cerraba dos veces una respuesta streaming y Django cerraba la conexion
transaccional. Se corrigio el helper, se repitio esa prueba y paso; no se altero
el lifecycle para acomodarla. La suite final completa aprobo **1093/1093** en
**613.870 s**, incluyendo regresion WORK/FINAL/HTML/EPUB/preview. Registro local:
`backups/p13_full_tests.log`. Ninguna suite se ejecuto simultaneamente con otra.
Despues se ampliaron las claves de URL omitidas (autorizacion/firma abreviada)
y se repitieron las 76 pruebas funcionales F8: **76/76**, en **45.297 s**.

Comandos de aceptacion ejecutados (prefijo en todos):

```powershell
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec web python manage.py check
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py migrate
podman --connection telar-fabulas-dev compose exec web python manage.py test --keepdb --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose exec web python manage.py migrate
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
podman --connection telar-fabulas-dev compose ps
podman --connection telar-fabulas-dev info --format '{{.Host.Security.Rootless}}'
```

Resultados finales: sin incidencias, sin nuevas migraciones, sin operaciones
pendientes, pong de un worker, cinco servicios Up y rootless=true. El proveedor
Compose instalado es docker-compose.exe; el motor y la conexion usados son Podman,
no Docker Desktop. No se modifico la configuracion del proveedor.

## Prueba manual y visual

Proyecto temporal QA con Rosariel/Fernaud/Arkan, dos relaciones (MENTOR unilateral
y FRIEND mutua), dos organizaciones, afiliacion, dos ubicaciones, dos entradas
de mundo y dos referencias con asociaciones. Dos cuentas QA y un estilo propio.

Con worker/beat detenidos se solicitaron por HTTP real ocho trabajos: personaje,
geografia, organizaciones, mundo, referencias y compendio en MD/DOCX/PDF. Despues
se modificaron biografia, residencia, relacion, afiliacion, referencia y estilo;
se movio Puerto del Alba y se borro Rito del alba. Al arrancar worker/beat, los
ocho llegaron a READY con sus checksums originales. Los compendios mantuvieron
texto original, ruta anterior, entrada borrada y cuerpo 11pt en el estilo capturado.

Se descargaron los ocho archivos por HTTP: attachment y no-store. DOCX abierto
con python-docx y PDF con pypdf; contenido y orden comprobados. PDF de cinco
paginas renderizado con Poppler y revisado sin recortes/superposiciones; DOCX de
cinco paginas abierto y revisado en la vista de impresion de Word. Fuentes y
paginacion dependen del equipo; no se instalaron fuentes ni se editaron documentos
del usuario. LibreOffice no estaba disponible para render_docx.py.

Navegador integrado a 1280x900 y 390x844: enlace desde proyecto, selector de
alcance, campos condicionales, categoria, opt-out de correo y novena exportacion
de politica. PROCESSING -> READY; descargar no navego fuera de su detalle.
Historial comun con las nueve solicitudes, modalidad, alcance y caducidad.
Ancho movil de documento igual al viewport (390), sin desbordamiento de pagina.
La TUI conserva su navegador Chrome; no se automatizo Chrome en esta prueba.

Segunda cuenta: 404 en formulario y descargas; ruta privada anonima: 404. Se
adelanto expires_at de un job QA, se comprobo descarga 404 y cleanup -> DELETED;
otro se borro mediante POST autenticado. El resto se retiro por el lifecycle y
solo se eliminaron entidades/cuentas/sesiones/estilo temporales registrados.
Se compararon de nuevo las huellas originales: identicas.

Evidencia ficticia local bajo `backups/p13_qa/`: archivos descargados,
compendium-pdf-1.png a -5.png, form-mobile.png, history-desktop.png,
export-ready.png y docx-word-preview.png. Scripts QA/respaldo ignorados, no forman
parte del codigo a publicar ni acceden a servicios externos.

## Inventario de archivos

Creados (10):
- app/apps/exports/migrations/0004_world_exports.py
- app/apps/exports/world_exports.py
- app/apps/exports/world_forms.py
- app/apps/exports/world_views.py
- app/apps/exports/world_test_helpers.py
- app/apps/exports/test_world_exports.py
- app/apps/exports/test_world_export_concurrency.py
- app/apps/exports/test_world_export_migration.py
- app/templates/exports/world_export_form.html
- docs/refactoring/18-world-exports-validation.md

Modificados (16):
- app/apps/exports/admin.py
- app/apps/exports/forms.py
- app/apps/exports/job_services.py
- app/apps/exports/markdown.py
- app/apps/exports/models.py
- app/apps/exports/services.py
- app/apps/exports/snapshots.py
- app/apps/exports/test_lifecycle_migration.py
- app/apps/exports/urls.py
- app/apps/exports/views.py
- app/templates/exports/export_detail.html
- app/templates/exports/export_list.html
- app/templates/projects/project_detail.html
- README.md
- docs/refactoring/04-refactoring-roadmap.md
- docs/refactoring/05-risk-register.md

Los diez diff_*.txt previos siguen sin cambios ni seguimiento. No commit ni push.
Backups, credenciales temporales ya invalidadas, capturas y helpers QA estan
ignorados. La base y volumenes originales se conservan, incluido test_telar_fabulas.

## Pendientes

Medir carga/RSS/locks y definir cuotas operativas antes de produccion. Mantener
respaldo externo restaurable, TLS, estaticos y SMTP. El snapshot no empaqueta
fuentes ni fija binarios del renderer, por lo que un retry futuro conserva datos
pero no garantiza bytes/paginacion identicos. Indices DOCX/Markdown no calculan
paginas automaticamente; no hay exportacion ZIP/imagenes/adjuntos ni editor del
compendio. No se agregaron IA, OCR, mapas, grafos, pagos, Stripe ni papelera.

Siguiente fase recomendada: definir F9 (trial/pago manual), capacidades, cupos y
transicion de cuentas mediante una instruccion independiente; no activarla aqui.
