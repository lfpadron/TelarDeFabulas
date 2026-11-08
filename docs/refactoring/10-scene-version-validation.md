# Validacion F3: versiones de escena

Fecha local: 2026-11-07 (America/Mexico_City). Prompt 05 de refactorizacion v01.
Entorno: `telar-fabulas-dev`, Podman rootless, Django 5.2.19, PostgreSQL 16,
Python 3.12, Redis/Celery/Beat. Se conserva el proyecto existente, uv.lock,
dependencias, Compose y la maquina anterior. No hubo reset de PostgreSQL ni
eliminacion de volumenes. No se realizo commit ni push.

## Resultado

- SceneVersion operativo con historial independiente y borrador activo separado
  de definitiva vigente. FINAL no se sobrescribe mediante los flujos normales.
- Migraciones 0003 y 0004 aplicadas; check limpio y sin migraciones pendientes.
- 445 pruebas aprobadas: 360 anteriores adaptadas + 85 nuevas.
- Ocho carreras nuevas con conexiones independientes a PostgreSQL aprobadas.
- Recorrido V1-V4, conflicto entre dos sesiones HTTP, preview y cuatro descargas
  reales procesadas por Celery aprobados. Movimiento conserva todo el historial.
- Revision visual de historial, edicion, definitiva y conflicto en el navegador
  integrado: escritorio 1280x900 y movil 390x844. Texto del segundo formulario
  permanece disponible y la definitiva no ofrece edicion directa.
- Chrome no estuvo disponible en el inventario de navegadores automatizables;
  no se afirma prueba visual en Chrome. La TUI y su apertura de Chrome no cambiaron.

## Modelo y reglas

`SceneVersion` tiene scene, version_number, editorial_stage, content, word_count,
revision, created_at, updated_at y finalized_at. Agrega `is_current_final`,
`based_on` para procedencia de copia/restauracion y `legacy_source_hash` para la
importacion. `scene` conserva la FK al ManuscriptNode original con CASCADE.

Cada escena nueva recibe V1 DRAFT, revision 1, aun vacia. DRAFT y REVIEW admiten
edicion; cada guardado o cambio a revision incrementa revision. FINAL conserva
texto, conteo y fechas: se modifica creando otra version. Finalizar una editable
incrementa revision, registra finalized_at y retira solo la designacion vigente
anterior, nunca su etapa FINAL ni su texto. Se permite volver a designar una
FINAL historica: cambia solo la bandera, sin inventar otra fecha de aprobacion.

`ManuscriptNode.current_draft_version` apunta a DRAFT/REVIEW de la misma escena.
Crear/restaurar asigna una nueva copia DRAFT como activa, con numero maximo + 1.
Editar un borrador historico no lo activa silenciosamente. Finalizar el activo
limpia el puntero; no selecciona otro borrador arbitrariamente. Finalizar otra
version no elimina el borrador activo existente.

Restricciones SQL revisadas con sqlmigrate:

| Restriccion | Garantia |
| --- | --- |
| scene_version_number_unique | Numero unico dentro de cada escena |
| scene_one_current_final | Unica bandera vigente por escena, indice parcial |
| scene_one_legacy_import | Maximo una importacion marcada por escena |
| scene_version_number_positive | Numero >= 1 |
| scene_version_revision_positive | Revision >= 1 |
| scene_version_stage_valid | DRAFT, REVIEW o FINAL |
| scene_current_final_stage | Vigente implica FINAL |
| scene_finalized_date_valid | FINAL tiene fecha; editable no la tiene |

La FK asegura existencia; tipo SCENE, origen/puntero de la misma escena e
inmutabilidad se validan en modelo/servicios. No se agregan triggers. Las
[restricciones condicionales de Django](https://docs.djangoproject.com/en/5.2/ref/models/constraints/)
se respaldan con indices/checks reales en PostgreSQL, no solo full_clean.

## Servicios, seguridad y concurrencia

`version_services.py` separa la logica editorial de movimientos estructurales:
create_scene_version, restore_scene_version, update_scene_version,
finalize_scene_version, get_current_draft_version, get_current_final_version,
select_scene_versions y get_scene_content_for_export.

Cada escritor inicia una transaccion y bloquea proyecto, escena y version, en ese
orden. Revalida propietario, proyecto ACTIVE y jerarquia despues del bloqueo.
Numeracion, revision y finalizacion ocurren dentro de la transaccion. El bloqueo
de proyecto serializa tambien una edicion frente a un movimiento o congelacion.
Un fallo al finalizar revierte igualmente el retiro de la definitiva anterior.

La revision recibida debe ser un entero igual al almacenado. Conflicto: HTTP 409,
mensaje traducible, formulario ligado al POST original y texto escapado intacto.
El enlace a la version guardada abre otra pestana para consultarla sin descartar
el formulario. No se hace reintento que fuerce la sobrescritura ni se registra
texto literario en logs. Crear/copiar/restaurar/finalizar tambien verifican la
revision del origen o destino para evitar aprobar un texto distinto al consultado.

Solo el propietario accede: ajeno/DELETED -> 404; FROZEN/PENDING_DELETION permiten
lectura, no escritura; ACTIVE permite escribir. Se reutiliza la politica central.
Las mutaciones usan POST con CSRF. SceneVersionAdmin es de solo lectura incluso
para superusuario y restringe su queryset al propietario. El admin del nodo
separa los campos legados de escena en un grupo colapsado de solo lectura.

## Migracion y respaldo

Inventario anterior y posterior a limpieza QA: 1 usuario; 0 proyectos, nodos,
personajes, notas, menciones o exports; 0 SceneVersion tras limpiar QA. Por ello
0004 copio **0 escenas reales**. No se demuestra una migracion de un manuscrito
privado existente; el backfill con datos se valido en fixtures historicos aislados.
No se importaron ni modificaron los datos de la maquina Podman anterior.

Respaldo privado local, excluido de Git y del contexto OCI:

```text
backups/p05_pre_scene_versions_20261107.dump
SHA-256: 4c5052f766a194270a0ccadf7107407521ba64a4667613194c956f501be63812
```

Se creo con pg_dump -Fc, se copio sin redireccion binaria de PowerShell y se
restauro con pg_restore --exit-on-error en `qa_restore_p05_20261107`. Se verificaron
la cuenta, su huella exacta, cero proyectos y el esquema previo sin SceneVersion.
Solo esa base temporal de restauracion se retiro. La huella de todos los campos
de la cuenta original coincide antes y despues de migracion y QA. El respaldo
se conserva; no se publica su contenido. No habia archivos de negocio asociados
que migrar. Una restauracion representativa de los datos de la maquina anterior
sigue pendiente, no queda sustituida por este ensayo acotado.

`0003_scene_versions` crea tabla, puntero y constraints. `0004_import_scene_versions`
usa [modelos historicos](https://docs.djangoproject.com/en/5.2/topics/migrations/#historical-models),
alias de schema_editor y una transaccion. Conserva exactamente content, PK, padres,
estado, word_count legado, flags y fechas del nodo, notas, menciones y exports.
Calcula conteo para la nueva version y copia created_at/updated_at del nodo.
finalized_at de FINAL importada es el momento de importacion, no una inferencia
de updated_at. La fecha de ejecucion se registra en django_migrations.

| Estado legado | Etapa V1 | Borrador activo | Definitiva vigente |
| --- | --- | --- | --- |
| PENDING, IN_PROGRESS, DRAFT | DRAFT | V1 | Ninguna |
| REVIEW, FINISHED | REVIEW | V1 | Ninguna |
| PUBLISHABLE, PUBLISHED | FINAL | Ninguno | V1 |

FINISHED no demuestra aprobacion. La regla depende de status y se aplica tambien
a vacios/espacios; is_publishable no decide la etapa. Un status desconocido aborta
el backfill completo. BOOK/PART/CHAPTER/FRAGMENT con texto no se convierten; el
auditor existente los reporta para una fase posterior. Sus campos no cambian.

Idempotencia: la huella SHA-256 identifica la copia importada. Al repetir se
compara contra el legado congelado; si difiere, se exige revision manual. No se
sobrescribe una version importada que despues fue editada. Si ya hay versiones
sin marca de importacion se conservan, sin apropiarse de una V1 existente.
No hay baseline inmutable adicional para DRAFT/REVIEW: el respaldo original
permanece en Node.content y en el dump; FINAL si es inmutable en la aplicacion.

No ejecutar migracion inversa sobre una base con historia. 0004 lanza
IrreversibleError si hay alguna version, evitando que 0003 descarte la tabla.
Solo las pruebas aisladas con tabla vacia retroceden al esquema anterior.
Para volver de despliegue, conservar esquema aditivo y lector compatible; un
binario antiguo que solo lee Node.content ocultaria todas las ediciones nuevas.

## Compatibilidad y exportaciones

SceneVersion es la fuente unica del texto de escenas. Se retiraron content y
estados legados del formulario de edicion de escena; el formulario de metadatos
no acepta sobrescritura textual. Model.save del nodo rechaza cambios a legado de
una escena existente. SceneVersion.save/delete directos rechazan operacion fuera
del servicio. Los servicios internos guardan bajo locks y revision esperada.
No existe sincronizacion bidireccional con Node.content.

Detalle/arbol muestran version y contador de trabajo. HTML, DOCX, PDF, EPUB y
preview usan borrador activo, o definitiva si no existe borrador. La seleccion de
IDs, revisiones y contenido de todas las escenas se materializa en una consulta
SQL por render y se consume sin volver a consultar cada escena. Un cambio de
texto posterior no altera el contenido ya seleccionado por ese render.
Si una escena carece de version de trabajo y definitiva, se informa el problema;
no se vuelve silenciosamente al texto legado.

`select_scene_versions(mode="FINAL")` solo elige definitivas vigentes; no recurre
a borradores. `ordered_project_nodes(mode="FINAL")` omite escenas sin FINAL,
pero todavia conserva encabezados y texto legado de contenedores. Esto prepara
la modalidad; no equivale a una politica de publicacion completa ni se habilita
como selector en la UI. Archivos historicos no se regeneran ni reclasifican.

La cola sigue leyendo al ejecutar. Entre solicitud y ejecucion pueden cambiar
texto, arbol y estilo. F4 debe guardar snapshot durable de texto+revision+ID,
estructura/orden/titulos y estilo en la solicitud; solo IDs no congelan DRAFT.
El snapshot de versiones de F3 es por consulta/render, no una transaccion global
que congele tambien todas las lecturas de estructura y estilo.

## Validacion ejecutada

Todos los comandos Podman usaron `--connection telar-fabulas-dev`.
En mantenimiento: `compose stop web worker beat`, sin detener postgres/redis.
Se generaron las migraciones con `compose run --rm --no-deps web python manage.py
makemigrations manuscripts --name scene_versions`; 0004 se escribio manualmente.
Se inspeccionaron `migrate --plan` y `sqlmigrate manuscripts 0003` con el mismo
prefijo run; despues se aplico `migrate`, ambas con resultado OK.

Validacion desde los servicios reconstruidos:

```powershell
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec web python manage.py check
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations manuscripts
podman --connection telar-fabulas-dev compose exec web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose exec web python manage.py migrate
podman --connection telar-fabulas-dev compose exec web python manage.py test
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
podman --connection telar-fabulas-dev compose exec web python manage.py audit_refactoring
```

check sin incidencias; makemigrations sin cambios; plan vacio y migrate sin
operaciones pendientes; Celery responde pong. Podman rootless=true y web corre
como appuser uid=1000. Compose usa el proveedor docker-compose instalado para
hablar con Podman, no cambia el motor a Docker. Advertencia Bake/BuildKit del
proveedor no impidio construir las tres imagenes con uv sync --locked.

Pruebas nuevas: 66 en test_versions, 11 en test_version_migrations y 8 en
test_version_concurrency. Se adaptaron pruebas anteriores de movimiento/XSS
para que el texto de escenas pase por el nuevo servicio, conservando sus
aserciones originales. Los intentos por la ruta antigua se prueban como rechazo.
Suite completa previa al despliegue: 445 OK en 197.716 s, sobre test_telar_fabulas.
Se repitio desde `compose exec web` despues del despliegue y del ajuste visual:
445 OK en 199.548 s.
Tras el ultimo ajuste acotado del admin (evitar el campo scene repetido en solo
lectura), se reconstruyeron las imagenes y se ejecutaron test_versions y
core.tests.test_admin_security: 78 OK en 6.493 s. La pagina local devolvio HTTP
200 desde Windows; los cinco servicios quedaron activos, postgres/redis healthy
y el worker final respondio pong. `git diff --check` no encontro incidencias.
Los 404 a /media y /private_media durante tests son pruebas de bloqueo esperadas.

Las ocho carreras PostgreSQL cubren numeracion doble, dos editores, doble FINAL,
edicion vs finalizacion, restauraciones simultaneas, crear borrador vs finalizar,
mover vs editar y revalidacion de FROZEN tras esperar lock. Resultado: un ganador
por revision, numeros unicos, una sola vigente y ningun texto aprobado sustituido.

La migracion se ensayo con los siete estados, texto Unicode no normalizado,
CRLF/tabuladores, vacios/espacios, contador legado distinto, fechas originales,
texto no-SCENE, notas, menciones, export historico, repeticion tras editar, origen
preexistente, status desconocido, hash cambiado y reversa protegida.

## Aceptacion HTTP y visual

Se creo una cuenta/proyecto privados exclusivamente QA. El cliente HTTP uso dos
CookieJars, login y CSRF reales contra Gunicorn, no Django TestClient ni Celery
eager. Se creo Libro -> Capitulo -> Escena por las rutas de la aplicacion.

1. V1 inicial, edicion con revision y copia V2.
2. V2 a REVIEW y FINAL; copia V3 y edicion sin cambiar ningun campo de V2.
3. Restaurar V1 crea V4; V1-V3 permanecen intactas.
4. Dos formularios de V4 con igual revision: primero 302, segundo 409, texto
   enviado retenido y escapado; base conserva solo el primer guardado.
5. Preview muestra V4 y cuatro jobs Celery terminan DONE; descarga HTTP 200 y
   Content-Disposition attachment en todos los formatos.
6. Escena movida a un segundo capitulo: IDs y filas de las cuatro versiones
   identicos, nota/mencion siguen asociadas y exports previos mantienen archivo.
7. Navegador integrado: historial V4 activo/V2 final, fechas compactas, editor y
   definitiva en movil sin desbordamiento; conflicto visible entre dos pestanas
   conserva el texto de la segunda. Logout realizado al terminar.

| Descarga QA | Bytes | Comprobacion |
| --- | --- | --- |
| HTML | 1824 | CSS incrustado y texto V4, sin texto legado ni V3 |
| DOCX | 36896 | Paquete abierto con python-docx; texto V4 |
| PDF | 6492 | Firma PDF/EOF; render WeasyPrint real y fuente versionada probada |
| EPUB | 3480 | ZIP/XHTML valido para lectura; texto V4 |

Se retiraron unicamente la cuenta, proyecto, versiones, nota, personaje/mencion,
estilo, cuatro archivos/jobs y sesiones QA. El script desechable se retiro y
nunca se incluyo en la imagen ni Git. El backup anterior se conserva privado.
La limpieza final deja 1 cuenta original identica y 0 registros de negocio.
El auditor no encuentra invalidos; conserva LEGACY_SUBSCRIPTION_POLICY pendiente,
que esta fase no intenta resolver.

## Archivos creados

```text
app/apps/manuscripts/migrations/0003_scene_versions.py
app/apps/manuscripts/migrations/0004_import_scene_versions.py
app/apps/manuscripts/version_services.py
app/apps/manuscripts/version_views.py
app/apps/manuscripts/test_versions.py
app/apps/manuscripts/test_version_migrations.py
app/apps/manuscripts/test_version_concurrency.py
app/templates/manuscripts/_version_actions.html
app/templates/manuscripts/version_history.html
app/templates/manuscripts/version_detail.html
app/templates/manuscripts/version_edit.html
docs/refactoring/10-scene-version-validation.md
```

Adicional local no versionado: el dump de respaldo indicado arriba.

## Archivos modificados

```text
.dockerignore
.gitignore
README.md
app/apps/core/tests/test_rendering_security.py
app/apps/exports/services.py
app/apps/exports/docx.py
app/apps/exports/epub.py
app/apps/manuscripts/models.py
app/apps/manuscripts/services.py
app/apps/manuscripts/forms.py
app/apps/manuscripts/views.py
app/apps/manuscripts/urls.py
app/apps/manuscripts/admin.py
app/apps/manuscripts/tests.py
app/apps/manuscripts/test_hierarchy.py
app/apps/manuscripts/test_concurrency.py
app/apps/manuscripts/test_migrations.py
app/templates/base.html
app/templates/manuscripts/manuscript_tree.html
app/templates/manuscripts/node_detail.html
app/templates/manuscripts/node_confirm_delete.html
docs/refactoring/03-data-migration-plan.md
docs/refactoring/04-refactoring-roadmap.md
```

Se conservan los cambios previos de subir_repo.bat y los ocho diff_*.txt sin
reescribirlos, verificado por SHA-256 contra el inventario inicial del directorio.
No se modificaron .env, dependencias, configuracion comercial ni
migraciones anteriores. Los cambios CSS se limitan a las pantallas nuevas.

## Limites y siguiente fase

- No hay comparacion visual, editor enriquecido, colaboracion ni autosave. Guardar
  edita una DRAFT/REVIEW; no crea una version por cada pulsacion o guardado.
- SQL directo, bulk_create/update/delete y llamadas internas que eluden los
  servicios son operaciones privilegiadas, no APIs soportadas. Los constraints
  garantizan unicidad/checks, no inmutabilidad de contenido ni reglas entre filas.
- El borrado explicito de una escena hoja sigue siendo fisico y elimina sus
  versiones por CASCADE. La confirmacion advierte que incluye definitivas y no
  tiene undo. Archivo/recuperacion y retencion requieren otra fase; no hay purga.
- Locks por proyecto priorizan integridad; proyectos muy grandes requieren medir
  duracion, memoria, consultas y backfill por lotes antes de adoptar edicion masiva.
- El auditor F0 sigue midiendo campos legados del nodo; no es inventario completo
  de versiones ni sustituye las pruebas/invariantes de F3.
- Texto de contenedores/FRAGMENT, jerarquia heredada y sus decisiones siguen
  pendientes; la migracion no los normaliza ni los convierte en escenas.
- No hay snapshot durable de cola ni selector final completo. **Siguiente fase:
  F4, seleccion comun trabajo/final y snapshot de contenido/estructura/estilo**,
  antes de nuevos formatos, suscripciones o limpieza automatica.
