# Telar de Fabulas

La fragua digital del novelista.

Base tecnica inicial de un SaaS Django con PostgreSQL, Redis, Celery, Celery Beat y Gunicorn, preparada para ejecutarse con Podman y mantenerse compatible con Docker Compose.

## Stack

- Python 3.12
- Django 5.2 LTS
- PostgreSQL 16
- Redis 7
- Celery
- Celery Beat
- Gunicorn
- uv
- python-docx
- WeasyPrint
- EbookLib
- Pillow (validacion del contenido de imagenes)
- Podman Compose / Docker Compose

## Requisitos

En Windows, se recomienda Podman Desktop:

- Podman Desktop con soporte Compose.
- Docker Desktop con WSL 2 habilitado como alternativa compatible.
- uv instalado y disponible en `PATH`.

La maquina de desarrollo validada es `telar-fabulas-dev`. Usar su conexion
explicitamente, sin cambiar ni eliminar la maquina anterior:

```powershell
podman machine start --update-connection=false telar-fabulas-dev
```

## Dependencias con uv

`pyproject.toml` y `uv.lock` son la fuente de verdad de dependencias.

Sincronizar entorno local:

```powershell
uv sync
```

Actualizar el lockfile despues de cambiar dependencias:

```powershell
uv lock
```

Ejecutar comandos Django desde el entorno de uv:

```powershell
uv run python app/manage.py check
```

## Configuracion

El archivo `.env` local no debe subirse al repositorio. Para preparar otro entorno,
copia la plantilla solo si todavia no existe tu configuracion:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Luego ajusta los valores de `.env`, especialmente:

- `DJANGO_SECRET_KEY`
- `POSTGRES_PASSWORD`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `CELERY_WORKER_CONCURRENCY`
- `PRIVATE_MEDIA_ROOT` (en Compose: `/code/private_media`)
- `CHARACTER_IMAGE_MAX_MB` (5 MB por defecto, minimo 1)

## Levantar el proyecto

```powershell
podman --connection telar-fabulas-dev compose up -d --build
```

La aplicacion queda disponible en:

```text
http://localhost:8000
```

La raiz debe mostrar:

```text
Telar de Fábulas está vivo.
```

Si necesitas usar Docker Desktop como alternativa:

```powershell
docker compose up --build
```

## TUI de control

La raiz del proyecto incluye `control_tui.bat`, una TUI local hecha con Textual para operar el sistema con Podman:

```powershell
.\control_tui.bat
```

La TUI permite:

- Arrancar la maquina de Podman.
- Construir la aplicacion.
- Encender los servicios.
- Abrir Google Chrome en `http://localhost:8000` con un perfil de pruebas controlado.
- Apagar la ventana de navegador controlada y detener los servicios.
- Ver logs de cada comando en pantalla.

Si Chrome está instalado en una ruta no estándar, define `TELAR_CHROME_PATH` antes de abrir la TUI.

La TUI usa su propia maquina y conexion `telar-fabulas-dev` para arrancar,
construir, encender, apagar y consultar el estado, sin cambiar la conexion global
de Podman. Si la maquina no existe, muestra un error y no usa otra en su lugar.
Para seleccionar otra maquina y su conexion del mismo nombre, define
`TELAR_PODMAN_MACHINE` antes de abrir la TUI.

Si la maquina existe pero aparece `connection "telar-fabulas-dev" not found`,
cierra y vuelve a abrir la TUI y pulsa **Arrancar podman**. El arranque comprueba
las conexiones y registra las que falten (`telar-fabulas-dev` y su variante
`-root`) con la clave, el puerto SSH y el UID de la maquina existente. Tambien
lo hace si la maquina ya esta encendida. Conserva las conexiones existentes y
la conexion predeterminada; no recrea la maquina ni elimina contenedores o datos.

En Windows, Compose usa la conexion local de esa maquina para evitar que una
conexion recuperada se interprete como SSH generico y solicite contrasena.
La consulta inicial de estado usa Podman directamente y se ejecuta en segundo
plano. Los comandos no reciben entrada interactiva, tienen tiempo limite y el
boton **Cerrar** permanece disponible durante las operaciones. El arranque
comprueba tanto Podman como Compose antes de indicar que estan listos.

Antes de arrancar una maquina detenida, la TUI elimina solo su socket temporal
obsoleto en `%TEMP%\podman`, que puede impedir el inicio de `win-sshproxy` en
Podman 6.1.4. Si la maquina ya esta encendida pero Compose falla, la TUI muestra
el error del puente local en lugar de indicar que todo esta listo.

En Windows, el arranque prepara el directorio de configuracion dentro de esa
distribucion WSL. Esto evita el error de `999-podman-machine-wsl-cgroupfs.conf`
al reutilizar maquinas despues de reinstalar Podman. Si la maquina ya esta
encendida, la TUI comprueba su conexion sin reiniciarla. Tambien busca Podman
en sus rutas habituales si la terminal conserva un `PATH` anterior a la
reinstalacion; puedes indicar otra ruta con `TELAR_PODMAN_PATH`.

## Migraciones

Con los contenedores arriba, abre otra terminal y ejecuta:

```powershell
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose exec web python manage.py migrate
```

La base actual ya usa `accounts.User`. No requiere reiniciar PostgreSQL ni borrar
volumenes. No usar `down -v` para actualizar esta version: borraria tambien media.
La migracion `characters/0002_validate_private_images` solo registra el validador
de uploads en el estado de Django; `sqlmigrate` devuelve una operacion SQL vacia.
No cambia tablas, PK ni referencias a archivos.

La migracion `manuscripts/0002_literary_hierarchy` agrega `short_description`
(texto vacio por defecto) y permite `title` vacio en el estado del modelo. La
validacion sigue exigiendo titulo para BOOK/PART/CHAPTER; solo SCENE es opcional.
No modifica PK, padres, posiciones, contenido, estados ni relaciones. No convierte
FRAGMENT. Antes de actualizar un entorno con datos, ejecutar el inventario y
detener el despliegue si aparecen incompatibilidades; no corregirlas en silencio:

```powershell
podman --connection telar-fabulas-dev compose exec web python manage.py audit_refactoring
podman --connection telar-fabulas-dev compose exec web python manage.py sqlmigrate manuscripts 0002
podman --connection telar-fabulas-dev compose exec web python manage.py migrate
```

Para cambios futuros, generar migraciones con `makemigrations` y revisar su SQL
antes de aplicarlas. No revertir 0002 en una base con descripciones nuevas:
la reversa eliminaria esa columna; conservar el esquema aditivo en un rollback.

F3 agrega `0003_scene_versions` (tabla, FK de borrador y restricciones) y
`0004_import_scene_versions` (copia exacta de escenas). No retira columnas ni
reescribe notas, menciones o exports historicos. Antes del despliegue: respaldo
privado de PostgreSQL/media, inventario, detener web/worker/beat y revisar el plan.
En mantenimiento, despues de respaldar y drenar trabajos en curso:

```powershell
podman --connection telar-fabulas-dev compose stop web worker beat
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py migrate
podman --connection telar-fabulas-dev compose up -d --build
```

PostgreSQL permanece activo durante el procedimiento.
El procedimiento y su validacion estan en
[10-scene-version-validation.md](docs/refactoring/10-scene-version-validation.md).
No volver a un binario que solo lee `ManuscriptNode.content`: no contiene las
ediciones nuevas. La reversa de 0004 se bloquea si existe historial.

## Crear superusuario

```powershell
podman --connection telar-fabulas-dev compose exec web python manage.py createsuperuser
```

El superusuario usa email como identificador principal. Despues entra al administrador:

```text
http://localhost:8000/admin/
```

## Cuentas y autenticacion

La app `accounts` define un usuario custom en `AUTH_USER_MODEL = "accounts.User"` y usa `email` como login.

Rutas disponibles:

```text
http://localhost:8000/register/
http://localhost:8000/login/
http://localhost:8000/profile/
```

El perfil permite editar email secundario, nombre, alias, idioma preferido y zona horaria. `user_type` y `status` quedan reservados para administracion.

## Proyectos

La app `projects` define la raiz de propiedad narrativa por usuario. Todas las vistas requieren sesion iniciada y un usuario solo puede acceder a sus propios proyectos.

Rutas disponibles:

```text
http://localhost:8000/projects/
http://localhost:8000/projects/create/
http://localhost:8000/projects/<id>/
http://localhost:8000/projects/<id>/edit/
http://localhost:8000/projects/<id>/delete/
http://localhost:8000/projects/<id>/restore/
```

Limites v01 por tipo de usuario:

- `FREE`: 1 proyecto no eliminado.
- `PREMIUM`: 10 proyectos no eliminados.
- `BUSINESS_ADMIN` y `TECH_ADMIN`: sin limite en esta fase.

Los proyectos con estado `DELETED` no cuentan para el limite. Los estados `ACTIVE`, `FROZEN` y `PENDING_DELETION` si cuentan.

El borrado es diferido: marcar para borrar cambia el proyecto a `PENDING_DELETION`, guarda la fecha de solicitud y programa el borrado real a 90 dias. No se borra texto ni archivos todavia. Un proyecto pendiente puede restaurarse, lo que vuelve el estado a `ACTIVE` y limpia las fechas de borrado diferido.

Pruebas de proyectos:

```powershell
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.projects
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.accounts apps.projects
```

## Manuscritos

La app `manuscripts` define el árbol narrativo base de cada proyecto. Cada nodo pertenece a un proyecto, puede tener un padre dentro del mismo proyecto y mantiene su posición entre hermanos.

Rutas disponibles:

```text
http://localhost:8000/projects/<id>/manuscript/
http://localhost:8000/projects/<id>/manuscript/create/
http://localhost:8000/projects/<id>/manuscript/<node_id>/
http://localhost:8000/projects/<id>/manuscript/<node_id>/edit/
http://localhost:8000/projects/<id>/manuscript/<node_id>/move/
http://localhost:8000/projects/<id>/manuscript/<node_id>/move-up/
http://localhost:8000/projects/<id>/manuscript/<node_id>/move-down/
http://localhost:8000/projects/<id>/manuscript/<node_id>/delete/
```

Tipos de nodo:

- `BOOK`: libro.
- `PART`: parte.
- `CHAPTER`: capítulo.
- `SCENE`: escena.
- `FRAGMENT`: legado de solo lectura, sin creacion ni conversion automatica.

Estados legados del nodo (las escenas usan las etapas de SceneVersion):

- `PENDING`: pendiente.
- `IN_PROGRESS`: en progreso.
- `DRAFT`: borrador.
- `REVIEW`: revisión.
- `FINISHED`: terminado.
- `PUBLISHABLE`: publicable.
- `PUBLISHED`: publicado.

El conteo de palabras de una escena se calcula al guardar su version con revision
esperada; en otros nodos se conserva el comportamiento de `content`. Mover un
nodo no recalcula ni reescribe su texto. Si no se captura posición, el sistema lo
agrega al final de sus hermanos. Solo se permite crear, editar o borrar nodos en
proyectos propios `ACTIVE`.

Cada proyecto admite varios libros. `Crear libro` crea una raiz y `Crear hijo`
preselecciona un padre y los tipos compatibles. Libros, partes y capitulos exigen
titulo; una escena puede guardarlo vacio y mostrar `Escena N` segun su posicion,
sin persistir esa etiqueta. Todos incluyen `short_description` en creacion,
edicion y detalle; el arbol muestra una version abreviada.

El borrado de nodos de manuscrito es físico en esta fase, pero solo se permite borrar nodos sin hijos.
La confirmacion de borrado de una escena advierte que tambien elimina todas sus
versiones, incluidas las definitivas, por CASCADE. No existe borrado individual
de versiones. Archivo y recuperacion de escenas eliminadas quedan pendientes.

Reordenamiento visual v01:

- `Subir`: mueve el nodo una posición arriba dentro de sus hermanos.
- `Bajar`: mueve el nodo una posición abajo dentro de sus hermanos.
- `Mover`: permite cambiar el padre del nodo y opcionalmente indicar una nueva posición.

Reglas de movimiento:

- Solo se pueden mover nodos dentro de proyectos propios.
- No se pueden mover nodos en proyectos `FROZEN`, `PENDING_DELETION` o `DELETED`.
- No se permite mover un nodo dentro de sí mismo ni debajo de uno de sus descendientes.
- El nuevo padre debe pertenecer al mismo proyecto.
- Al mover, se conservan ID, contenido, estado, publicación, conteo de palabras,
  notas, menciones y referencias/archivos de exportaciones historicas.
- Después de mover, las posiciones de hermanos se normalizan automáticamente.
- Editar texto no cambia padre, tipo ni posicion; para reestructurar se usa Mover.
- Una instancia antigua usada solo para editar texto no revierte un movimiento
  ya confirmado. En escenas, dos guardados con la misma revision producen un
  ganador y un conflicto explicito, nunca una sobrescritura silenciosa.

Jerarquía permitida:

- `BOOK`: raiz sin padre; contiene `PART` o `CHAPTER`.
- `PART`: bajo `BOOK`; contiene `CHAPTER`.
- `CHAPTER`: bajo `BOOK` o `PART`; contiene `SCENE`.
- `SCENE`: bajo `CHAPTER`; no admite hijos.
- `FRAGMENT`: legible, auditable y exportable; no editable ni eliminable desde
  los flujos normales. No se normalizan sus posiciones como efecto lateral.

`apps.manuscripts.hierarchy` concentra la politica usada por modelo, formularios,
vistas, servicios, admin y auditoria. Rechaza cruces de proyecto, ciclos y cambios
que invaliden descendientes. Las ramas incompatibles se muestran como legado;
las operaciones que necesitarian reordenarlas se bloquean para revision.

Crear, guardar, mover, normalizar y borrar usan transaccion y bloqueo de la fila
del proyecto antes del nodo. Esto serializa los escritores cooperantes del mismo
proyecto, incluso al insertar en un grupo vacio. Proyectos distintos no comparten
ese bloqueo. Las posiciones quedan consecutivas al confirmar la transaccion.
No se agrego una constraint UNIQUE sobre posiciones heredadas: SQL directo y
`QuerySet.update/bulk_create/delete` no son APIs de escritura de la aplicacion y
pueden saltarse estas protecciones. Las limitaciones estan detalladas en
[09-manuscript-hierarchy-validation.md](docs/refactoring/09-manuscript-hierarchy-validation.md).

El drag & drop visual avanzado queda pendiente para una fase posterior; esta fase prioriza estabilidad con botones y formulario.

Pruebas de manuscritos:

```powershell
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.manuscripts
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.accounts apps.projects apps.manuscripts apps.characters apps.notes apps.styles apps.exports
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
```

### Versiones de escena (F3)

Cada escena nueva recibe V1, `DRAFT`, revision 1. Sus metadatos se editan desde
`Editar`; el texto, desde `Editar borrador`. `SceneVersion` es la unica fuente
de texto de escenas para detalle, arbol, preview y los cuatro exportadores.
`ManuscriptNode.content/status/word_count/is_publishable` permanecen como legado
sin sincronizacion inversa. Los textos de contenedores y FRAGMENT no se convierten.

- `DRAFT` (Borrador) y `REVIEW` (En revision) son editables.
- `FINAL` (Definitivo) no es editable. Crear una version basada en ella para cambiar texto.
- `current_draft_version` identifica el borrador activo; `is_current_final`
  identifica la definitiva vigente con unicidad parcial en PostgreSQL.
- Crear/restaurar hace una copia exacta nueva, con siguiente numero y `based_on`;
  la convierte en borrador activo sin tocar versiones anteriores.
- Finalizar conserva las definitivas historicas y retira solo su designacion
  vigente. Si finaliza el borrador activo, no se elige otro borrador automaticamente.
- Editar un borrador historico no lo convierte en activo. Para trabajar desde el,
  usar `Restaurar como nueva version`.
- Guardar exige la revision recibida al abrir el formulario. Un conflicto devuelve
  HTTP 409 y conserva el texto enviado; la version guardada puede abrirse aparte.

Rutas bajo `/projects/<id>/manuscript/<scene_id>/versions/`: historial, `create/`,
`<version_id>/`, `<version_id>/edit/`, `review/`, `finalize/` y `restore/` (estas tres
ultimas bajo `<version_id>/`). Crear/revisar/finalizar/restaurar son POST con CSRF.
Solo el propietario accede; ACTIVE permite editar, FROZEN/PENDING_DELETION leen,
DELETED devuelve 404. El admin de versiones es de solo lectura.

La migracion mapea PENDING/IN_PROGRESS/DRAFT a DRAFT, REVIEW/FINISHED a REVIEW y
PUBLISHABLE/PUBLISHED a FINAL vigente, incluso con texto vacio. Conserva bytes
UTF-8, fechas originales, PK y referencias; registra la huella del texto legado.
La fecha de finalizacion de una definitiva importada es la de importacion, no
una fecha historica inferida. Repetir la logica no duplica ni sobrescribe versiones.

HTML/DOCX/PDF/EPUB usan un snapshot durable capturado al solicitar. WORK elige
el borrador activo, o la definitiva vigente si no hay borrador; FINAL selecciona
solo definitivas vigentes. La preview utiliza el mismo selector, sin persistir
snapshots. Ningun formato vuelve a consultar el manuscrito vivo en el worker.

## Personajes

La app `characters` gestiona fichas de personajes por proyecto. Un personaje pertenece a un solo proyecto y queda preparado para relacionarse con nodos de manuscrito mediante menciones.

Rutas disponibles:

```text
http://localhost:8000/projects/<id>/characters/
http://localhost:8000/projects/<id>/characters/create/
http://localhost:8000/projects/<id>/characters/<character_id>/
http://localhost:8000/projects/<id>/characters/<character_id>/edit/
http://localhost:8000/projects/<id>/characters/<character_id>/delete/
http://localhost:8000/projects/<id>/mentions/create/
http://localhost:8000/projects/<id>/mentions/<mention_id>/edit/
http://localhost:8000/projects/<id>/mentions/<mention_id>/delete/
```

Importancia narrativa:

- `PRINCIPAL`: personaje central; su ficha exige más campos para considerarse completa.
- `SECUNDARIA`: personaje recurrente o de soporte.
- `FIGURANTE`: aparición breve o funcional.

Rol narrativo:

- `PROTAGONISTA`
- `DEUTERAGONISTA`
- `TRITAGONISTA`
- `ANTAGONISTA`
- `PERSONAJE_IMPORTANTE`
- `SECUNDARIO`
- `INCIDENTAL`
- `OTRO`

Si el rol narrativo no es `OTRO`, el campo de rol personalizado se limpia automáticamente.

Papel dramático:

- `HEROE`
- `HEROINA`
- `VILLANO`
- `INTERES_ROMANTICO`
- `MENTOR`
- `ALIADO`
- `RIVAL`
- `TRAIDOR`
- `PROTEGIDO`
- `CATALIZADOR`
- `NARRADOR`
- `ALIVIO_COMICO`
- `OTRO`

La interfaz actual permite seleccionar múltiples papeles dramáticos estándar. `OTRO` con papel personalizado queda preparado en el modelo y admin para una fase posterior.

Completitud:

`completion_percentage` se calcula en tiempo real y no se guarda en base de datos. Los campos considerados cambian según la importancia narrativa: los personajes principales requieren una ficha más completa que secundarios o figurantes. Este porcentaje solo informa; no bloquea el flujo de escritura.

Imagen:

El campo `image` acepta JPEG, PNG y WebP. Pillow verifica y decodifica el contenido;
la extension debe coincidir. Se rechazan archivos corruptos, SVG, GIF nuevos y
archivos que superen `CHARACTER_IMAGE_MAX_MB` (5 MB por defecto). El nombre interno
es un UUID bajo `private_media/characters/<project_id>/`. Los GIF ya almacenados
siguen siendo legibles si son validos y no se revalidan al editar solo texto.
La imagen se sirve exclusivamente desde la ruta autenticada
`/projects/<id>/characters/<character_id>/image/`, nunca mediante `image.url`.

Menciones:

`CharacterMention` relaciona personajes con nodos de manuscrito para responder dos preguntas: en qué partes aparece un personaje y qué personajes aparecen o se mencionan en una escena, capítulo o fragmento.

Desde el detalle de un nodo de manuscrito se puede agregar una mención preseleccionando el nodo:

```text
/projects/<id>/mentions/create/?node=<node_id>
```

Desde el detalle de un personaje se puede agregar una mención preseleccionando el personaje:

```text
/projects/<id>/mentions/create/?character=<character_id>
```

Tipos de mención:

- `APPEARS`: el personaje aparece físicamente o participa en el nodo.
- `MENTIONED`: el personaje es mencionado, pero no necesariamente aparece.
- `POV`: el nodo usa el punto de vista del personaje.
- `NARRATOR`: el personaje funciona como narrador del nodo.
- `IMPORTANT_FOR_SCENE`: el personaje es importante para la escena aunque su presencia sea indirecta.

Reglas v01:

- Un usuario solo puede gestionar menciones dentro de sus propios proyectos.
- Solo se crean, editan y borran menciones en proyectos propios `ACTIVE`.
- El personaje y el nodo deben pertenecer al mismo proyecto.
- No se permiten duplicados exactos de personaje, nodo y tipo de mención.
- Sí se permiten varios tipos de mención para el mismo personaje y nodo.
- La lista de personajes muestra conteo total de menciones y conteo de apariciones `APPEARS`.

Pruebas de personajes:

```powershell
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.characters
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.accounts apps.projects apps.manuscripts apps.characters apps.notes apps.styles apps.exports
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
```

## Notas, ideas y pendientes

La app `notes` gestiona material de trabajo del autor que no forma parte del texto final del manuscrito. Cada entrada pertenece a un proyecto y puede asociarse opcionalmente a un nodo de manuscrito, a un personaje, o a ambos.

Rutas disponibles:

```text
http://localhost:8000/projects/<id>/notes/
http://localhost:8000/projects/<id>/notes/create/
http://localhost:8000/projects/<id>/notes/<note_id>/
http://localhost:8000/projects/<id>/notes/<note_id>/edit/
http://localhost:8000/projects/<id>/notes/<note_id>/delete/
```

Tipos:

- `NOTE`: nota general de trabajo.
- `IDEA`: posibilidad narrativa o material por explorar.
- `TASK`: pendiente accionable.

Estados:

- `OPEN`: abierta.
- `IN_PROGRESS`: en progreso.
- `DONE`: terminada.
- `DISCARDED`: descartada.

Cuando una nota cambia a `DONE`, `completed_at` se llena automáticamente. Si vuelve a otro estado, `completed_at` se limpia.

Prioridades:

- `LOW`: baja.
- `MEDIUM`: media.
- `HIGH`: alta.
- `URGENT`: urgente.

Relaciones opcionales:

- Una nota puede estar ligada solo al proyecto.
- También puede asociarse a un `ManuscriptNode`.
- También puede asociarse a un `Character`.
- Puede tener nodo y personaje al mismo tiempo, siempre que ambos pertenezcan al mismo proyecto.

Desde el detalle de un nodo de manuscrito se puede crear una nota preasociada con:

```text
/projects/<id>/notes/create/?node=<node_id>
```

Desde el detalle de un personaje se puede crear una nota preasociada con:

```text
/projects/<id>/notes/create/?character=<character_id>
```

La lista permite filtros simples por querystring:

```text
?type=NOTE
?type=IDEA
?type=TASK
?status=OPEN
?priority=HIGH
```

Pruebas de notas:

```powershell
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.notes
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.accounts apps.projects apps.manuscripts apps.characters apps.notes
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
```

## Estilos de exportacion

La app `styles` gestiona plantillas de estilo usadas por las exportaciones a HTML, DOCX, PDF y EPUB.

Rutas disponibles:

```text
http://localhost:8000/styles/
http://localhost:8000/styles/create/
http://localhost:8000/styles/<style_id>/
http://localhost:8000/styles/<style_id>/edit/
http://localhost:8000/styles/<style_id>/duplicate/
http://localhost:8000/styles/<style_id>/delete/
```

Sembrar o actualizar los estilos del sistema:

```powershell
podman --connection telar-fabulas-dev compose exec web python manage.py seed_system_styles
```

El comando es idempotente y deja disponibles cuatro estilos base:

- Sobrio.
- Creativo.
- Elegante.
- Medio loco.

Reglas v01:

- Usuarios `FREE`: pueden ver y usar estilos del sistema, pero no crear, editar, duplicar ni borrar estilos.
- Usuarios `PREMIUM`: pueden crear estilos personalizados, editar los propios, duplicar estilos del sistema o propios, y borrar sus estilos.
- `BUSINESS_ADMIN` y `TECH_ADMIN`: pueden gestionar estilos personales; el tipo de
  negocio no concede permisos Django. El admin requiere `is_staff` y permisos
  explicitos; solo un superusuario puede editar estilos del sistema.

Borrar un estilo usado por una exportacion muestra un mensaje y conserva el
estilo, sin devolver un error 500. Los estilos personales ajenos responden 404.

Si necesitas convertir un usuario de pruebas a premium, entra a:

```text
http://localhost:8000/admin/accounts/user/
```

y cambia el campo `user_type` a `PREMIUM`.

Pruebas de estilos:

```powershell
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.styles
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.accounts apps.projects apps.manuscripts apps.characters apps.notes apps.styles
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
```

## Exportaciones

La app `exports` gestiona solicitudes de exportación mediante `ExportJob`. Cada trabajo pertenece a un usuario y proyecto, puede exportar todo el manuscrito o un subárbol desde un nodo raíz, y usa una plantilla de `styles`.

Rutas disponibles:

```text
http://localhost:8000/projects/<project_id>/exports/
http://localhost:8000/projects/<project_id>/exports/create/
http://localhost:8000/projects/<project_id>/exports/preview/
http://localhost:8000/projects/<project_id>/exports/<export_id>/
http://localhost:8000/projects/<project_id>/exports/<export_id>/download/
http://localhost:8000/projects/<project_id>/exports/<export_id>/retry/
http://localhost:8000/projects/<project_id>/exports/<export_id>/delete/
```

Estados de `ExportJob`:

- `REQUESTED`: solicitud y snapshot conservados, con envio pendiente o ya encolado.
- `PROCESSING`: worker Celery generando el archivo.
- `READY`: archivo generado y listo para descarga hasta su caducidad.
- `FAILED`: hubo error; el detalle muestra `error_message`.
- `DELETED`: archivo, temporales y snapshot eliminados; se conserva auditoria minima.

Modalidades:

- `WORK`: borrador activo DRAFT/REVIEW, o definitiva vigente en su ausencia.
  Una escena sin ninguna version conserva su encabezado sin contenido.
- `FINAL`: solo definitivas vigentes y sus ancestros BOOK/PART/CHAPTER necesarios.
  Omite escenas sin definitiva y contenedores vacios. Si no hay definitivas,
  muestra validacion y no crea un trabajo. No incluye texto legado de contenedores.
- `Revisar seleccion` muestra conteos antes de crear. FINAL exige confirmar la
  seleccion y advierte las exclusiones; si cambian los conteos, pide revisar otra vez.

Cada solicitud conserva texto exacto, version/revision, orden, titulos, descripcion,
idioma y todos los ajustes del estilo en `ExportSnapshot`, con SHA-256 y proteccion
SQL contra UPDATE. Editar, mover o borrar una escena despues no cambia la captura.
La clave del formulario evita duplicar trabajos al reenviar la misma solicitud.
Celery se publica despues del commit. Si Redis falla, se conserva REQUESTED con un
mensaje y Beat reintenta. `Reintentar envio` realiza POST con CSRF y reutiliza el snapshot original.
No reenviar manualmente trabajos historicos sin snapshot: su archivo sigue
descargable, pero no se reconstruye a partir del contenido actual.

Limites adicionales en `.env` (valores por defecto):

```text
EXPORT_SNAPSHOT_MAX_BYTES=20971520
EXPORT_SNAPSHOT_MAX_NODES=10000
```

El limite de bytes corresponde al JSON canonico UTF-8 de toda la seleccion;
el de nodos protege la carga de metadatos del proyecto completo. Un exceso
rechaza toda la solicitud sin dejar un trabajo incompleto. No son cuotas de cuenta.

Formatos v01:

- La interfaz ofrece `MARKDOWN` (`.md`, UTF-8), `DOCX` (python-docx) y `PDF` (WeasyPrint).
- `HTML` y `EPUB` siguen disponibles internamente; sus archivos historicos se
  descargan hasta caducar. HTML sigue siendo un solo adjunto con CSS incrustado.
- Todos consumen el mismo snapshot WORK/FINAL. Markdown escapa sintaxis de texto
  plano, conserva parrafos y sigue la profundidad real sin saltar niveles.
- Nuevos archivos: `private_media/exports/<user>/<project>/<job>/<token>.<extension>`.
  Cada intento escribe primero un `.part` exclusivo y publica con rename atomico.
  Los nombres de archivos historicos no se modifican durante la migracion.

### Ciclo de vida y correo (Prompt 07)

Transiciones: REQUESTED -> PROCESSING -> READY/FAILED; FAILED -> REQUESTED
solo cuando admite reintento; READY/FAILED -> DELETED. REQUESTED admite cancelacion
segura. PROCESSING no admite borrado. Los servicios usan locks PostgreSQL en orden
proyecto/trabajo; el token impide que un worker antiguo publique otro resultado.

```dotenv
EXPORT_READY_RETENTION_DAYS=7
EXPORT_FAILED_RETENTION_DAYS=7
EXPORT_MAX_ATTEMPTS=3
EXPORT_STALE_MINUTES=30
EXPORT_RETRY_BASE_SECONDS=60
PUBLIC_BASE_URL=http://localhost:8000
EMAIL_BACKEND=django.core.mail.backends.filebased.EmailBackend
```

Rangos: retencion 1-365 dias, intentos 1-10, lease 1-1440 minutos y base de
backoff 1-3600 segundos. Valores invalidos impiden arrancar. Reintentos: 60, 120,
240... segundos, maximo una hora; no se reinicia el contador al reintentar.
OSError/errores operativos de DB son transitorios, excepto errores de permisos.
Validaciones, permisos, snapshot ausente/corrupto y errores no clasificados son
definitivos. El detalle siempre muestra mensajes genericos, nunca una traza.

Beat recupera solicitudes abandonadas y leases vencidos cada minuto. El heartbeat
se renueva cada 30 segundos como maximo, durante todo el render. Un fallo del
broker no consume intentos de render; su solicitud queda visible y recuperable.
Un FAILED transitorio espera su backoff antes de volver a REQUESTED.

El checkbox de correo esta activado en solicitudes nuevas. Solo READY o FAILED
definitivo generan un registro durable en `ExportNotification`; Beat lo entrega
cada minuto, con hasta ocho intentos. Idiomas es-mx/en-us segun el usuario, sin
texto literario, titulo de proyecto, snapshot ni adjuntos. Enlaces de detalle
requieren login. Un fallo SMTP no cambia READY a FAILED.

Por defecto NO se envia SMTP: el backend escribe en
`private_media/development-emails/`. Para produccion configurar `EMAIL_BACKEND`
SMTP y `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
`EMAIL_USE_TLS`, `EMAIL_USE_SSL`, `DEFAULT_FROM_EMAIL`, `PUBLIC_BASE_URL` en `.env`.
No activar TLS y SSL simultaneamente. No publicar ese directorio ni sus copias.
La deduplicacion es **best-effort**, no exactamente una vez: si SMTP acepta un
mensaje y el proceso cae antes de registrar `sent_at`, puede repetirse. Tras ocho
fallos revisar el registro y la configuracion de correo; no se promete entrega.

Eliminar usa POST+CSRF. Primero bloquea nuevas descargas, luego elimina archivos,
temporales y snapshot, y finalmente confirma DELETED. Una descarga en curso
mantiene un lock compartido hasta cerrar el archivo; el borrado espera sin
interrumpirla. Si falla el disco, `cleanup_error` conserva el incidente y Beat
reintenta. Nunca se borra texto fuente, versiones, notas ni personajes.

`cleanup_expired_exports` corre cada 24 horas y solo caduca READY/FAILED. El acceso
se bloquea desde `expires_at`, aunque la limpieza diaria aun no haya corrido.
La migracion `exports.0003_export_lifecycle` convierte PENDING/DONE a
REQUESTED/READY, conserva archivos y snapshots y concede a los historicos un
plazo completo desde la migracion. Su correo queda desactivado para evitar avisos
retroactivos. No se reinicia PostgreSQL ni se borran volumenes.

Auditoria: `ExportAttempt` (token, numero y resultado), `ExportEvent` (transicion,
fecha y codigo) y `ExportNotification` (entrega). Acceso SQL/admin es privilegiado;
las escrituras directas no sustituyen los servicios del ciclo de vida.

Validacion y limites: [12-export-lifecycle-validation.md](docs/refactoring/12-export-lifecycle-validation.md).

Previsualización HTML limitada:

- Disponible en `/projects/<project_id>/exports/preview/`.
- Permite elegir modalidad WORK/FINAL, nodo raíz y plantilla de estilo.
- Renderiza en memoria el mismo HTML base, pero no crea `ExportJob` ni `ExportSnapshot`, no encola Celery y no escribe archivos en `private_media`.
- Si la vista se recorta, muestra: `Vista previa limitada. Exporta el archivo completo para ver todo el manuscrito.`
- Los límites son configurables por entorno:

```text
EXPORT_PREVIEW_MAX_NODES=12
EXPORT_PREVIEW_MAX_WORDS=2500
```

Reglas principales:

- Un usuario solo puede exportar sus propios proyectos.
- Se permite exportar proyectos propios `ACTIVE`, `FROZEN` y `PENDING_DELETION`.
- Los proyectos `DELETED` no permiten lectura, exportacion ni descarga.
- Si se elige nodo raíz, se exporta ese nodo y sus descendientes.
- Si no se elige nodo raíz, se exportan todos los nodos raíz del proyecto y sus descendientes.
- Markdown, HTML, DOCX, PDF y EPUB solo incluyen manuscrito; no incluyen notas, ideas, pendientes, personajes ni metadata interna.
- Los cinco formatos recorren el mismo orden estable del arbol y admiten
  `BOOK > CHAPTER > SCENE` y `BOOK > PART > CHAPTER > SCENE`. Los encabezados
  siguen la profundidad real; las escenas sin titulo usan la etiqueta visible.
- Mover un nodo no regenera ni altera exportaciones terminadas o pendientes.
- Usuarios `FREE` pueden usar estilos del sistema.
- Usuarios `PREMIUM` pueden usar estilos del sistema y estilos propios.

Limitaciones actuales:

- El índice DOCX es una lista simple; el índice dinámico de Word queda pendiente.
- El índice PDF reutiliza el índice simple del HTML; índice avanzado pendiente.
- La numeración de páginas DOCX queda pendiente.
- Las fuentes del PDF usan las fuentes disponibles en el sistema; fuentes embebidas quedan pendientes.
- EPUB no embebe fuentes; los lectores aplican sus propias reglas de margen y paginación.
- Validación EPUB externa queda pendiente.
- La coordinacion de archivos necesita PostgreSQL directo y almacenamiento local
  compartido entre web/worker. Un pool en modo transaccion o storage S3 requiere
  adaptar los locks de descarga y la publicacion. Cada descarga activa usa una
  conexion PostgreSQL adicional; medir capacidad antes de produccion.
- El snapshot no fija versiones de librerias ni fuentes instaladas. Congela
  contenido y configuracion, no promete igualdad binaria tras actualizar el runtime.

Verificar el worker Celery:

```powershell
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
```

Pruebas de exportaciones:

```powershell
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.exports
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.accounts apps.projects apps.manuscripts apps.characters apps.notes apps.styles apps.exports
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
```

## Verificar Celery

Revisa que el worker responda:

```powershell
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
```

Debe responder con un `pong`.

Tambien puedes revisar logs:

```powershell
podman --connection telar-fabulas-dev compose logs worker
podman --connection telar-fabulas-dev compose logs beat
```

## Servicios

- `web`: Django servido por Gunicorn en el puerto 8000.
- `postgres`: base de datos PostgreSQL con volumen persistente.
- `redis`: broker Redis para Celery.
- `worker`: worker de Celery.
- `beat`: scheduler de Celery Beat.

Nginx queda pendiente para la configuracion de produccion.

## Permisos y archivos privados (refactorizacion F1)

`apps.core.permissions` centraliza la politica. Todas estas operaciones requieren
un propietario autenticado y activo (`is_active` de Django):

| Estado del proyecto | Ver | Crear/editar/borrar contenido | Exportar/descargar | Restaurar |
| --- | --- | --- | --- | --- |
| ACTIVE | Si | Si | Si | No |
| FROZEN | Si | No | Si | Si |
| PENDING_DELETION | Si | No | Si | Si |
| DELETED | No | No | No | No |

Recursos ajenos, eliminados o estados desconocidos responden 404; una escritura
prohibida en un proyecto propio responde 403. Se aplica en vistas, formularios,
servicios de movimiento y admin, no solo ocultando botones. Restaurar es una
excepcion explicita que vuelve a `ACTIVE`; no cambia la regla de 90 dias.
Las escrituras narrativas por POST revalidan bajo bloqueo del proyecto y dentro
de una transaccion. Los GET de borrado solo muestran confirmacion; POST exige CSRF.

El admin tampoco concede acceso a proyectos ajenos por ser superusuario. No
permite borrar fisicamente proyectos ni usuarios por cascada; las exportaciones
son de solo lectura. Los roles dramaticos se guardan atomicamente con la ficha.
El perfil no acepta `user_type`, `status` ni permisos administrativos del cliente.
No se introduce una politica nueva para `User.status` ni suscripciones en esta fase.

`static/` conserva archivos publicos de la aplicacion. `private_media/` almacena
imagenes y exportaciones. El storage privado no genera URLs publicas; ni
`/media/` ni `/private_media/` se sirven directamente, incluso con DEBUG.
Las rutas de imagen y `/projects/<id>/exports/<export_id>/download/` comprueban
propietario, estado, relacion y existencia. Usan MIME correcto, `nosniff`,
`Cache-Control: private, no-store`, `Vary: Cookie` y nombres de descarga seguros.
No aceptan rutas del cliente y rechazan traversal o enlaces fuera del storage.

El texto literario se escapa como texto, no HTML. Se restringen los valores CSS,
la previsualizacion mantiene el iframe sandbox y sus limites, y el renderer PDF
no puede obtener recursos de red ni archivos locales. Las descargas HTML siguen
siendo un solo archivo con CSS incrustado y una politica CSP restrictiva.

### Actualizar el almacenamiento sin perder archivos

Compose conserva el nombre del proyecto `telar-fabulas` y el volumen `media_data`.
Solo cambia el punto de montaje de `/code/media` a `/code/private_media` para web
y worker. Las claves relativas en PostgreSQL no cambian. No renombrar volumenes,
no ejecutar `down -v`, no borrar directorios y no modificar la maquina anterior.

En un entorno con archivos, respaldar PostgreSQL y media y verificar su
restauracion en una copia aislada antes del despliegue. Detener nuevas solicitudes,
dejar terminar las exportaciones y detener web/worker/beat durante el cambio:

```powershell
podman --connection telar-fabulas-dev compose stop web worker beat
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec web python manage.py migrate
podman --connection telar-fabulas-dev compose exec web python manage.py audit_refactoring
```

Con el volumen existente no hay que copiar archivos: comprobar referencias,
cantidades y hashes antes/despues del montaje. Si se usaba un directorio local
`media/` fuera de Compose, copiar su contenido a `private_media/` conservando rutas
relativas, sin sobreescribir destinos; comparar cantidades y SHA-256 antes de
configurar `PRIVATE_MEDIA_ROOT`. Conservar el original como respaldo privado.
No confundir ese directorio local con el volumen, ni copiar archivos a la imagen
OCI. El proxy de produccion no debe publicar ninguno de los dos directorios.

### Validacion reproducible

```powershell
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec web python manage.py check
podman --connection telar-fabulas-dev compose exec web python manage.py test
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
```

La validacion F1 del 2026-11-06 aprobo 297 pruebas; se conserva en
[08-security-validation.md](docs/refactoring/08-security-validation.md).
La validacion F2 aprobo **360 pruebas**, check limpio, migraciones al dia y Celery
pong. Las pruebas de concurrencia PostgreSQL y el escenario HTTP con Celery real
se registran en
[09-manuscript-hierarchy-validation.md](docs/refactoring/09-manuscript-hierarchy-validation.md).
La suite usa una base temporal separada, no la base de trabajo. La revision visual
de F2 en Chrome quedo bloqueada por la herramienta de control.
F3 aprobo **445 pruebas** (85 nuevas), incluidas 11 de migracion y 8 de concurrencia.
El escenario HTTP V1-V4, las cuatro descargas via Celery y el movimiento con
historial pasaron; tambien la revision visual de historial, definitiva y conflicto
en escritorio/movil con el navegador integrado. Chrome no estuvo disponible en
la automatizacion de esta sesion. Detalle en
[10-scene-version-validation.md](docs/refactoring/10-scene-version-validation.md).
F4 (Prompt 06) aprobo **482 pruebas**: 37 nuevas, incluidas ocho carreras
PostgreSQL y una migracion historica. Se generaron y descargaron ocho archivos
reales WORK/FINAL con Celery, conservando texto, orden y estilo anteriores a la
ejecucion. Evidencia e inventario de esta entrega en
[11-export-snapshot-validation.md](docs/refactoring/11-export-snapshot-validation.md).
F5 (Prompt 07) aprobo **540 pruebas**: 58 nuevas, incluidas nueve pruebas de
concurrencia/caida y una migracion historica. Markdown/DOCX/PDF WORK y FINAL,
recuperacion, correo local, borrado y caducidad se validaron con Celery real.
No se enviaron correos reales; los datos originales conservaron sus hashes.
Inventario y resultados en
[12-export-lifecycle-validation.md](docs/refactoring/12-export-lifecycle-validation.md).
Podman sigue rootless, web usa `appuser`, y Compose sigue siendo compatible con
Docker. Cambiar el prefijo a `docker compose` permite usar Docker sin cambiar YAML.

## Estructura

```text
.
├── compose.yaml
├── Dockerfile
├── .env.example
├── pyproject.toml
├── uv.lock
├── control_tui.bat
├── tools/
│   └── control_tui.py
└── app/
    ├── manage.py
    ├── config/
    │   ├── settings/
    │   │   ├── base.py
    │   │   ├── dev.py
    │   │   └── prod.py
    │   ├── urls.py
    │   ├── wsgi.py
    │   ├── asgi.py
    │   └── celery.py
    └── apps/
        ├── core/
        ├── accounts/
        ├── projects/
        ├── manuscripts/
        ├── characters/
        ├── geography/
        ├── organizations/
        ├── notes/
        ├── exports/
        ├── styles/
        └── admin_dashboard/
```

## Geografia territorial (F6.1)

Desde el detalle de un proyecto, abrir **Geografia**:

```text
/projects/<project_pk>/geography/
```

Permite crear ubicaciones raiz o hijas, consultar/editar sus descripciones,
moverlas a otro padre o a la raiz, subir/bajar entre hermanas y eliminar hojas
sin habitantes. El arbol es colapsable con HTML nativo, sin librerias nuevas.
Tipos: UNIVERSE, WORLD, CONTINENT, EMPIRE, KINGDOM, COUNTRY, PROVINCE, CITY y OTHER
(con nombre de tipo personalizado opcional). No hay niveles obligatorios.

El campo **Habitante de** de la ficha de personaje es opcional y solo ofrece
ubicaciones del mismo proyecto. Los enlaces funcionan en ambos sentidos:
personaje -> residencia y ubicacion -> habitantes. Mover conserva ID,
descripciones y habitantes. La edicion de descripcion no cambia el padre;
usar **Mover** para reorganizar. Una ubicacion con hijos, habitantes o sedes de
organizaciones no se elimina; primero mover los hijos y retirar/cambiar las
residencias y sedes.

Solo el propietario accede. ACTIVE permite escribir; FROZEN y PENDING_DELETION
son de lectura; DELETED devuelve 404. El admin conserva este aislamiento,
incluidos superusuarios. Las mutaciones requieren POST y CSRF.

Migraciones aditivas: `geography.0001_initial` y
`characters.0003_character_residence`. No requieren reset ni borrado de volumen.
Para actualizar otra instalacion, respaldar DB/media y detener escritores antes
de aplicar el plan revisado:

```powershell
podman --connection telar-fabulas-dev compose stop web worker beat
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py migrate
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.geography
podman --connection telar-fabulas-dev compose exec web python manage.py test
```

F6.1 aprobo **624 pruebas**, 84 nuevas (74 funcionales, nueve de concurrencia y
una de migracion). Se verifico el movimiento de Ciudad A entre provincias con
dos habitantes, la vista escritorio/movil y las huellas originales sin cambios.
Modelo, inventario de archivos, comandos, respaldo y limites en
[13-geography-validation.md](docs/refactoring/13-geography-validation.md).
Por ahora solo existe residencia principal; el historial queda para otra fase.

## Organizaciones y afiliaciones (F6.2)

Desde el detalle del proyecto, abrir **Organizaciones**:

```text
/projects/<project_pk>/organizations/
```

Organizaciones raiz o subordinadas con un padre principal opcional, nueve tipos,
descripcion breve y desarrollo detallado. OTHER admite un tipo personalizado;
al elegir otro tipo, ese campo se limpia. El arbol es colapsable; **Mover** cambia
el padre o lleva a la raiz, y las flechas reordenan hermanas. Los movimientos
conservan ID, descripciones, sede e integrantes y rechazan ciclos.

La **Sede principal** es opcional y debe pertenecer al mismo proyecto. La ficha
de la ubicacion muestra las organizaciones asentadas alli. No hay sedes multiples.

La ficha de personaje incorpora **Afiliaciones**. Tambien se agregan desde
**Integrantes** en una organizacion. Cada registro tiene cargo opcional, estado
ACTIVE, FORMER, HONORARY, SUSPENDED o UNKNOWN, descripcion y fechas narrativas de
ingreso/salida como texto libre. Un personaje puede tener varios cargos y
organizaciones. Se rechaza la misma combinacion personaje/organizacion/cargo/
estado/periodo; un periodo diferente permite otra afiliacion historica, sin
crear un sistema cronologico de eventos.

No se borran organizaciones con hijas o afiliaciones, incluidas las anteriores.
Eliminar una afiliacion requiere confirmacion/POST/CSRF y conserva personaje y
organizacion. Solo el propietario accede, tambien en admin: ACTIVE escribe,
FROZEN/PENDING_DELETION leen, DELETED y usuarios ajenos reciben 404.

Migracion aditiva: `organizations.0001_initial`. No modifica tablas anteriores ni
necesita reset de PostgreSQL. Respaldar DB/media e inspeccionar el plan antes de
actualizar otra instalacion. Para evitar peticiones durante la migracion, detener
los escritores y usar un contenedor puntual:

```powershell
podman --connection telar-fabulas-dev compose stop web worker beat
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py migrate
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec web python manage.py check
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.organizations apps.geography
podman --connection telar-fabulas-dev compose exec web python manage.py test
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
```

F6.2 aprobo **721 pruebas**, incluidas 97 nuevas: 89 funcionales, siete carreras
PostgreSQL y una de migracion. QA real HTTP/navegador escritorio/movil completado;
datos temporales retirados y huellas originales identicas. Resultados,
inventario de archivos, respaldo y limites de esta fase en
[14-organizations-validation.md](docs/refactoring/14-organizations-validation.md).
No hay dependencias nuevas ni cambios a uv, TUI, Chrome o exportadores.

## Politica, religion e historia (F6.3)

Desde el detalle del proyecto, abrir **Construccion de mundos**:

```text
/projects/<project_pk>/worldbuilding/
```

Entradas independientes en Politica, Religion e Historia. Cada una tiene titulo,
descripcion breve opcional y contenido de texto plano, con saltos de linea
conservados y HTML escapado. No hay jerarquia, cronologia automatica ni limite
artificial de entradas. El listado busca por titulo/descripcion, filtra por
categoria y pagina a 50 entradas por seccion, sin cargar contenido extenso.

**Nueva entrada**, **Editar**, flechas **Subir/Bajar** y **Cambiar categoria**
conservan identidad y texto. El orden es relativo a proyecto/categoria y usa
posiciones contiguas desde cero. Cambiar categoria agrega al final del destino
y normaliza ambos grupos bajo bloqueo transaccional del proyecto.

Cada entrada tiene una revision, inicialmente 1. Editar, mover o renumerar una
fila incrementa su revision; guardar sin cambios no la incrementa. Los formularios
envian la revision original. Un conflicto devuelve HTTP 409 sin sobrescribir el
registro y mantiene el texto enviado en el formulario; se puede abrir la revision
actual en otra pestana para comparar y conciliar. No hay fusion automatica ni
historial completo. El admin usa el mismo servicio y control de concurrencia.

**Eliminar** exige confirmacion, POST, CSRF y revision vigente. Solo elimina esa
entrada y normaliza su categoria. No hay papelera ni recuperacion automatica;
estas requieren una politica posterior. Para evitar un borrado administrativo
sin revision, el admin no ofrece borrado individual ni masivo: usar la pantalla
del autor. `QuerySet.update`, `bulk_*`, `QuerySet.delete` y SQL directo son APIs
privilegiadas y no deben exponerse como escritores de negocio.

Solo el propietario accede, sin excepcion por ser administrador. ACTIVE permite
modificar; FROZEN/PENDING_DELETION solo leer; DELETED y usuarios ajenos reciben 404.
UI preparada para es-MX/en-US, sin traducir automaticamente el texto del autor.

Migracion aditiva: `worldbuilding.0001_initial`. Solo crea una tabla, constraints
e indices; no modifica datos anteriores. Respaldar DB/media y revisar el plan
antes de actualizar otra instalacion. No revertir a zero una tabla con contenido.

```powershell
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec web python manage.py check
podman --connection telar-fabulas-dev compose exec web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose exec web python manage.py migrate
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.worldbuilding --keepdb --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py test --keepdb --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
podman --connection telar-fabulas-dev compose ps
```

En esta fase se usa `--keepdb`: la base de pruebas separada se conserva, sin
borrar ninguna base ni volumen. No usar `down -v` ni reinicializar PostgreSQL.
En una instalacion con usuarios concurrentes, suspender trafico de escritura
durante la migracion; los comandos de desarrollo anteriores no son un despliegue
de produccion sin interrupciones.

F6.3 aprobo **809 pruebas**, 88 nuevas: 79 funcionales, ocho carreras reales en
PostgreSQL y una de migracion. Evidencia de QA de escritorio/movil, inventario y
riesgos en [15-worldbuilding-validation.md](docs/refactoring/15-worldbuilding-validation.md).
Sin nuevas dependencias ni cambios a uv, TUI, Chrome, exportadores o reglas comerciales.

## Referencias y materiales (F6.4)

Desde el detalle del proyecto, abrir **Referencias y materiales**:

```text
/projects/<project_pk>/references/
```

Bibliografia, enlaces, imagenes, documentos y otros materiales. Se pueden crear,
editar, buscar por titulo/descripcion/autor/editorial, filtrar por tipo y eliminar
con confirmacion. El listado y los vinculos paginan a 50. El texto se escapa y
conserva sus saltos de linea. Bibliografia y Otro pueden existir sin archivo;
Enlace requiere HTTP/HTTPS; Imagen y Documento requieren un archivo compatible.

Una referencia pertenece a un solo proyecto, pero puede vincularse a varios
nodos del manuscrito, personajes, ubicaciones, organizaciones y entradas de
construccion de mundos. Sus fichas muestran **Referencias y materiales** con
**Ver referencia**, **Asociar referencia existente**, **Crear nueva referencia**
y **Desvincular**. Asociar no copia el archivo; desvincular o borrar la entidad
conserva la referencia. No se permiten vinculos entre proyectos, ni del mismo
autor, ni duplicados exactos.

Archivos privados bajo `PRIVATE_MEDIA_ROOT/references/<project_id>/<uuid>.<ext>`.
Sin URLs publicas ni rutas fisicas en formularios/admin. Descargar requiere
sesion y propiedad del proyecto; siempre entrega un adjunto con cache privada,
incluidas imagenes, sin sustituir la pagina por el documento. Los enlaces
externos solo admiten HTTP/HTTPS y nunca se descargan automaticamente.

Formatos: JPEG/PNG/WebP verificados por Pillow; PDF con firma/estructura basica
verificadas por pypdf; DOCX con ZIP/OOXML, CRC y limites de descompresion; TXT/MD
en UTF-8. Se rechazan vacios, corruptos, extensiones incompatibles, nombres
peligrosos, formatos ejecutables, HTML/SVG y documentos cifrados o con macros.
MIME y tamano proceden de los bytes, no de lo declarado por el navegador.
La validacion no es un antivirus ni garantiza que un documento descargado sea
inofensivo al abrirlo con software externo.

Limites en `.env` (MiB, valores enteros positivos):

```env
REFERENCE_IMAGE_MAX_MB=10
REFERENCE_DOCUMENT_MAX_MB=20
REFERENCE_PROJECT_STORAGE_MAX_MB=500
```

La cuota suma archivos de referencias vigentes y pendientes de limpieza de ese
proyecto. Subidas concurrentes se serializan bajo bloqueo de Project. Un reemplazo
necesita espacio para ambos archivos hasta confirmar y limpiar el anterior.
Estas son cuotas tecnicas de referencias, no limites comerciales ni un cupo
compartido con imagenes de personajes/exportaciones. Recrear web/worker/beat
despues de cambiar variables de entorno.

Cada guardado usa la revision original. Si otro formulario gano, HTTP 409
conserva los textos enviados sin sobrescribir; un archivo rechazado debe volver
a seleccionarse. El nuevo archivo se escribe antes del commit; el anterior se
borra solo despues. Los fallos de borrado quedan registrados y Celery Beat
programa reintentos cada minuto con espera creciente. No hay papelera.

Comandos de limpieza controlada:

```powershell
podman --connection telar-fabulas-dev compose exec web python manage.py cleanup_reference_files
# Solo huerfanos UUID de referencias, sin registro y con antiguedad minima de 24 h:
podman --connection telar-fabulas-dev compose exec web python manage.py cleanup_reference_files --orphans
```

El segundo comando es explicito para reconciliar caidas de proceso o rollbacks
externos; no recorre ni borra exportaciones, imagenes de personajes o fuentes.
Supervisar la cola de limpieza y respaldar DB/media antes de mantenimiento.

Permisos centrales, tambien en admin: ACTIVE permite escribir;
FROZEN/PENDING_DELETION permiten consulta/descarga, no cambios; DELETED y usuarios
ajenos reciben 404. Ni BUSINESS_ADMIN ni TECH_ADMIN acceden al contenido ajeno.
Confirmaciones de borrado via POST/CSRF y revision. El admin de referencias no
ofrece borrado directo/masivo; usar la confirmacion del autor.

Migracion aditiva `references.0001_initial`: materiales, asociaciones y cola
tecnica de limpieza, sin cambios a tablas anteriores. Dependencia nueva pypdf,
resuelta con uv en `uv.lock`. No requiere reset de PostgreSQL.

```powershell
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec web python manage.py check
podman --connection telar-fabulas-dev compose exec web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose exec web python manage.py migrate
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.references --keepdb --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py test --keepdb --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
podman --connection telar-fabulas-dev compose ps
```

En instalaciones con trafico, respaldar DB/media y detener escritores antes de
migrar: usar `compose build web worker beat`, `compose stop web worker beat` y
`compose run --rm --no-deps web python manage.py migrate --plan` / `migrate`;
despues `compose up -d`. Nunca `down -v`, ni borrar bases, ni revertir una tabla
con materiales a zero. Los backups anteriores no contienen contenido posterior.

F6.4 aprobo **911 pruebas**, 102 nuevas, incluidas diez de concurrencia PostgreSQL
y una de migracion. QA real: carga/descarga desde navegador, tres asociaciones
con un solo archivo, reemplazo movil, desvinculacion, permisos y borrado seguro.
Datos temporales retirados, originales verificados por SHA-256. Inventario,
comandos, resultados y riesgos en
[16-references-validation.md](docs/refactoring/16-references-validation.md).

## Relaciones entre personajes (F7)

En la ficha de un personaje, abrir **Relaciones** o **Agregar relacion**.
Se preselecciona el origen; ambos selectores solo admiten personajes del proyecto
actual. El listado separa relaciones salientes, entrantes y mutuas, con direccion
explicita y enlaces a ambas fichas. Cada grupo pagina a 50; la descripcion completa
se consulta en **Ver relacion**, sin cargar textos extensos en los listados.

Tipos: FRIEND, ENEMY, RIVAL, FAMILY, PARENT, CHILD, SIBLING, ROMANTIC_INTEREST,
PARTNER, MENTOR, STUDENT, ALLY, TRUST, DISTRUST y OTHER. OTHER requiere un tipo
personalizado; cambiar a un tipo definido limpia ese campo. No se modifica el
papel dramatico, la completitud, las menciones ni las afiliaciones del personaje.

- Una relacion unilateral expresa solo origen -> destino.
- Una reciproca se guarda en **un solo registro** y aparece en ambas fichas.
- PARENT, CHILD, MENTOR y STUDENT no admiten reciprocidad.
- No se crean relaciones inversas ni equivalencias semanticas automaticamente.
- Origen/destino/tipo no se pueden repetir. Tipos diferentes si pueden coexistir.
- Dos unilaterales opuestas son validas; si alguna es reciproca, no se permite
  una segunda inversa del mismo tipo. Para convertir dos unilaterales en una
  mutua, decidir cual conservar y eliminar la otra con confirmacion.
- No hay autorrelaciones ni cruces entre proyectos, aunque tengan el mismo autor.

Rutas:

```text
/projects/<project_pk>/characters/<character_pk>/relationships/
/projects/<project_pk>/characters/<character_pk>/relationships/create/
/projects/<project_pk>/relationships/<relationship_pk>/
/projects/<project_pk>/relationships/<relationship_pk>/edit/
/projects/<project_pk>/relationships/<relationship_pk>/delete/
```

Editar conserva el identificador. Eliminar requiere confirmacion, POST y CSRF;
solo borra ese vinculo, nunca sus personajes ni otras relaciones. Eliminar un
personaje elimina sus relaciones por CASCADE, sin borrar los otros personajes.
El borrado es definitivo, sin papelera. Dos ediciones completas simultaneas
siguen la regla de ultimo guardado gana: no hay revision optimista ni historial
en este modelo. Los bloqueos protegen integridad y duplicados, no fusionan textos.

Permisos centrales tambien en Django admin: ACTIVE permite escribir;
FROZEN/PENDING_DELETION son de solo lectura; DELETED y autores ajenos reciben 404,
incluidos administradores. El admin busca por nombres, filtra tipo/reciprocidad
y valida ambos extremos. No ofrece borrado masivo de relaciones.

Migracion aditiva `characters.0004_characterrelationship`: solo tabla, indices
y restricciones nuevas, sin modificar datos anteriores. No necesita reiniciar
PostgreSQL ni borrar volumenes. Sin dependencias, servicios o cambios de uv nuevos.

```powershell
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec web python manage.py check
podman --connection telar-fabulas-dev compose exec web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose exec web python manage.py migrate
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.characters.test_relationships apps.characters.test_relationship_concurrency apps.characters.test_relationship_migrations --keepdb --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py test --keepdb --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
```

En una instalacion con trafico, respaldar y detener web/worker/beat antes de
migrar mediante `compose run --rm --no-deps web`, como en F6.4. No revertir esta
migracion con relaciones guardadas ni restaurar una copia antigua como rollback
rutinario; preservar datos y corregir hacia delante. No ejecutar suites simultaneas
contra la misma base de pruebas; `--keepdb` la conserva.

F7 aprobo **1005 pruebas integradas** y agrega 94: 83 funcionales, diez de
concurrencia PostgreSQL y una de migracion aditiva. QA real en escritorio/movil con Rosariel, Fernaud y Arkan:
direccion, reciprocidad, edicion, duplicados, permisos y eliminacion independiente.
Datos temporales retirados; originales y media comprobados por SHA-256.
Resultado integrado, inventario y limites en
[17-character-relationships-validation.md](docs/refactoring/17-character-relationships-validation.md).

## Siguiente fase sugerida

Continuar con **F8: exportacion de entidades**, definiendo primero la matriz de
entidades/formatos, seleccion y politica de adjuntos privados. Reutilizar el
selector y snapshots de exportacion existentes. Exportar relaciones requiere
alcance aprobado en otra fase; F7 no lo implementa. Tampoco agrega grafos,
cronologias, inferencias ni relaciones entre organizaciones.
Suscripciones, comparacion visual y conversiones de FRAGMENT o texto legado
requieren fases independientes. Antes de produccion faltan TLS, limites de
recursos, monitorizacion, SMTP real y politica operativa de respaldos/cuotas.
