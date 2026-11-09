# F6.2: organizaciones y afiliaciones

Fecha: 2026-11-08. Prompt 09 aplicado sobre la base existente.
Entorno: Django 5.2.19, PostgreSQL 16, uv y Podman rootless; conexion explicita
`telar-fabulas-dev`. Sin dependencias nuevas, reset de PostgreSQL ni borrado de
volumenes. No se modifica la maquina anterior, TUI, Chrome, subir_repo.bat ni diffs.

## Modelo y decisiones

- Organization pertenece a Project y tiene un padre principal opcional. Nombre
  obligatorio, tipo, tipo personalizado OTHER, descripcion breve, desarrollo,
  posicion, sede opcional y timestamps. Tipos: RELIGIOUS, POLITICAL, BROTHERHOOD,
  GUILD, MILITARY, COMMERCIAL, ACADEMIC, SECRET_SOCIETY, OTHER.
- La sede es GeographicLocation del mismo proyecto, con SET_NULL. Parent usa
  PROTECT. Proyecto e identidad son permanentes; no hay traslados entre proyectos.
- CharacterOrganizationMembership relaciona Character y Organization del mismo
  proyecto. Incluye cargo, descripcion, ACTIVE (default), FORMER, HONORARY,
  SUSPENDED o UNKNOWN, ingreso/salida narrativos opcionales y timestamps.
- Las fechas son texto, no DateField. La unicidad incluye personaje, organizacion,
  cargo, estado, ingreso y salida. Resuelve conjuntamente la prohibicion de
  duplicados exactos y la autorizacion de periodos distintos del prompt. Se
  recortan espacios al inicio/final de cargo y periodos; no se interpreta calendario.
  La propuesta preliminar de pareja unica del documento 02 no aplica en F6.2.
- Borrar afiliacion nunca borra personaje ni organizacion. Character tiene
  CASCADE hacia sus afiliaciones; Organization esta protegida mientras tenga
  cualquier afiliacion, incluso FORMER, o subordinadas.
- Todos los textos nuevos usan gettext_lazy/trans. No se agregan catalogos .po.

## Jerarquia, bloqueos y consultas

Escrituras atomicas: Project select_for_update primero, despues fila y hermanos.
Estado y propietario se revalidan bajo bloqueo. Guardado normal, movimientos,
normalizacion, borrado y afiliaciones usan el mismo protocolo. La asignacion de
sede se serializa con el borrado geografico, que consulta referencias actuales.

Posiciones contiguas desde uno. La restriccion UNIQUE(project,parent,position)
usa NULLS NOT DISTINCT (PostgreSQL 16) para incluir raices. Antes de renumerar se
liberan temporalmente los slots afectados dentro de la misma transaccion.
Movimientos conservan ID, nombres, descripciones, sede, created_at y afiliaciones.
Edicion de texto no expone padre/posicion; un objeto viejo no revierte un movimiento.

Core.trees extrae solo los algoritmos ya usados en geography. Cada app conserva
su capa de permisos, bloqueo y reglas. No cambia manuscripts ni sus migraciones.
Arbol y ruta requieren una consulta cada uno, con recorrido iterativo. Arbol
omite detailed_description; integrantes usan select_related, sin consultas por
fila. Hijas, integrantes y organizaciones con sede paginan a 50. Los indices
incluyen proyecto/padre/posicion y las FK de afiliacion.

## Interfaz y permisos

El proyecto incorpora Organizaciones. Arbol nativo details/summary, crear,
editar, mover a raiz/otro padre, subir/bajar y eliminacion confirmada.
Detalle: ruta, tipo, organizacion superior, sede enlazada, descripciones,
subordinadas e integrantes con cargo, estado, periodo y descripcion.
La ficha del personaje incluye Afiliaciones con agregar/editar/eliminar;
la ubicacion lista las organizaciones con sede alli.

Rutas:

```text
/projects/<project_pk>/organizations/
/projects/<project_pk>/organizations/create/
/projects/<project_pk>/organizations/<organization_pk>/
/projects/<project_pk>/organizations/<organization_pk>/edit/
/projects/<project_pk>/organizations/<organization_pk>/delete/
/projects/<project_pk>/organizations/<organization_pk>/move/
/projects/<project_pk>/organizations/<organization_pk>/move-up/
/projects/<project_pk>/organizations/<organization_pk>/move-down/
/projects/<project_pk>/memberships/create/
/projects/<project_pk>/memberships/<membership_pk>/edit/
/projects/<project_pk>/memberships/<membership_pk>/delete/
```

Preseleccion ?character= y ?organization= validada y acotada al proyecto. El
retorno acepta solo character/organization y genera URL local, no un next externo.
Autenticacion requerida; owner exclusivo; ACTIVE permite escribir,
FROZEN/PENDING_DELETION solo leer y DELETED es 404. No hay bypass de superusuario
ni admin negocio. POST y CSRF para mutaciones. Respuestas privadas/no-store.
Admin registra ambos modelos, filtros tipo/estado, busquedas por nombre/proyecto,
FK acotadas, proyectos inmutables y eliminacion masiva desactivada.

## Migracion e integridad

Creada, inspeccionada y aplicada: `organizations.0001_initial`. Crea solo dos
tablas con FK, indices y constraints. No contiene RunPython ni cambia tablas de
geography o characters. Se adapto el test historico geografico para excluir el
nuevo descendiente del grafo al probar un estado anterior; ninguna migracion
historica de produccion fue editada.

Respaldo previo (ignorado por Git):

```text
backups/p09_pre_organizations.dump
backups/p09_private_media.tar.gz
backups/p09_original_fingerprints.json
```

Restauracion probada en `p09_restore_check_20261108`; SHA-256 de todas las columnas
de los registros originales coincidente. Solo esa base aislada fue retirada.
Inventario original y final: 1 cuenta, 1 proyecto, 1 nodo, 2 personajes,
2 papeles dramaticos, 1 ubicacion; 0 versiones, menciones, notas, estilos,
exportaciones y snapshots. Media: 0 archivos. Originales comparados antes,
despues de migrate y despues de retirar QA, sin cambios.

No ejecutar migrate organizations zero como rollback: elimina datos de las
tablas nuevas. Preferir una correccion hacia delante y conservar esquema y
respaldos. No se activa purga de fuentes ni se modifican reglas comerciales.

## Validacion automatizada

181 pruebas focalizadas aprobadas: 97 nuevas y las 84 previas de geografia.
Las nuevas se dividen en 89 funcionales, siete concurrentes y una de migracion.
Suite integrada final: **721 pruebas aprobadas**, 319.580 segundos, sin fallos.
Incluye regresion de cuentas, proyectos, manuscritos, personajes, notas,
geografia, estilos y exportaciones. Base de pruebas separada retirada por Django
al finalizar. Check limpio, makemigrations sin cambios, migracion aplicada,
Celery pong y cinco servicios activos, con una sola instancia de Beat.

Cobertura nueva:

- Modelo: tipos, OTHER/limpieza, obligatorios, padres/sedes cruzados, ciclos,
  identidad, orden automatico/explicito, normalizacion, checks/unique de DB.
- Movimiento: padre, raiz, subir/bajar, limites, conflictos, conservacion de
  identidad/texto/sede/afiliaciones; queryset de padres sin descendientes.
- Afiliaciones: multiples organizaciones, integrantes, cargos y periodos;
  duplicados modelo/DB, estados, edicion, borrado y conservacion de endpoints.
- UI: preseleccion, errores, redirecciones locales, texto escapado, tablas,
  navegacion, fichas bidireccionales, confirmacion y bloqueo de borrados.
- Seguridad: anonimo, ajeno, administrador, estados, modelos con estado stale,
  servicios con actor, formularios/admin, CSRF y referencias cruzadas corruptas.
- Rendimiento: arbol y ruta de una consulta, 1100 niveles sin recursion,
  integrantes sin N+1 y paginacion sin aumento lineal de consultas.
- Concurrencia PostgreSQL: creacion, movimiento, ciclos competidores, texto vs
  movimiento, afiliacion duplicada, afiliacion vs borrado y sede vs borrado.
- Migracion: conserva filas historicas de cuentas/proyectos/geografia/personajes/
  papeles dramaticos, incluidas referencias de imagen y texto exacto.

## Prueba real

Cuenta y proyecto temporales aislados. HTTP contra Gunicorn con cookies/CSRF
creo Ciudad de Cristal, Consejo de Luz, Guardia de Cristal y Academia de los
Constructores; Rosariel y Fernaud; y las tres afiliaciones solicitadas.
Rosariel: Consejera del Consejo y Comandante de Guardia. Fernaud: Investigador
de Academia. Todas se crearon ACTIVE y con fecha narrativa de texto.

En navegador integrado se movio Guardia bajo Academia y se cambio su cargo a
Capitana, estado FORMER y salida Antes del Gran Eclipse. Se verificaron ruta,
ID, descripciones y las tres afiliaciones intactas, ficha de Rosariel,
sede del Consejo, lista geografica inversa y bloqueo de borrar la ubicacion.
Tambien se probo el colapso nativo y formularios. Escritorio 1280x900 y movil
390x844; sin desbordamiento de pagina. La tabla tiene ancho minimo y scroll
horizontal propio para mantener legibles los campos y acciones.

Permisos reales via HTTP: ajeno 404, FROZEN/PENDING lectura y POST 403,
DELETED 404. Borrado de organizacion con hijas/afiliaciones y ubicacion con sede
bloqueados. Cuentas, proyecto, organizaciones, personajes, sede, afiliaciones y
sesiones temporales retirados; cuenta y datos originales conservados.
La preferencia de Chrome de la TUI no fue alterada; QA visual uso el navegador
integrado, no se afirma una prueba automatizada especifica en Chrome.

Evidencia local ignorada por Git: backups/p09_qa/results.json y capturas
tree-desktop.png, membership-desktop.png, character-mobile.png y
headquarters-mobile.png. Las credenciales temporales se retiraron con state.json.

## Comandos ejecutados

Todos sobre `podman --connection telar-fabulas-dev compose`:

```powershell
up -d postgres redis
run --rm --no-deps web python manage.py makemigrations organizations
run --rm --no-deps web python manage.py test apps.organizations apps.geography --noinput
up -d --build
exec web python manage.py check
exec web python manage.py migrate --plan
exec web python manage.py migrate
exec web python manage.py test --noinput
exec web python manage.py makemigrations --check --dry-run
exec worker celery -A config inspect ping
```

Ademas: pg_dump -Fc, copia del respaldo al workspace, createdb/pg_restore de la
base aislada, comparacion de huellas, dropdb de esa copia, scripts QA temporales
y reinicio web para refrescar templates. Las imagenes se reconstruyeron al cierre
para incorporar el ajuste final de la tabla movil. Una primera suite integrada fue
interrumpida por ese reinicio; se repitio completa recreando exclusivamente
test_telar_fabulas. El primer pase focalizado ajusto tres expectativas de test:
POST en vistas solo GET devuelve 405; el aislamiento se verifica con los metodos
admitidos. No se debilitaron permisos para corregir las expectativas.

## Inventario de archivos

24 creados versionables:

```text
app/apps/core/trees.py
app/apps/organizations/__init__.py
app/apps/organizations/apps.py
app/apps/organizations/models.py
app/apps/organizations/services.py
app/apps/organizations/membership_services.py
app/apps/organizations/selectors.py
app/apps/organizations/forms.py
app/apps/organizations/views.py
app/apps/organizations/urls.py
app/apps/organizations/admin.py
app/apps/organizations/tests.py
app/apps/organizations/test_concurrency.py
app/apps/organizations/test_migrations.py
app/apps/organizations/migrations/__init__.py
app/apps/organizations/migrations/0001_initial.py
app/templates/organizations/base.html
app/templates/organizations/tree.html
app/templates/organizations/form.html
app/templates/organizations/detail.html
app/templates/organizations/_memberships.html
app/templates/organizations/confirm_delete.html
app/templates/organizations/membership_confirm_delete.html
docs/refactoring/14-organizations-validation.md
```

14 modificados:

```text
app/apps/core/permissions.py
app/apps/geography/selectors.py
app/apps/geography/services.py
app/apps/geography/views.py
app/apps/geography/test_migrations.py
app/apps/characters/views.py
app/config/settings/base.py
app/config/urls.py
app/templates/projects/project_detail.html
app/templates/characters/character_detail.html
app/templates/geography/detail.html
README.md
docs/refactoring/04-refactoring-roadmap.md
docs/refactoring/05-risk-register.md
```

Auxiliares de validacion y respaldos quedan en backups/ ignorado, no en el
paquete de la aplicacion. No se realiza commit ni push en esta fase.

## Limites y siguiente fase

- No hay historial automatico de ediciones de afiliacion, calendarios validados,
  alianzas, rivalidades, multiples sedes, jurisdicciones ni exportacion de entidades.
- Descripciones y afiliaciones no tienen control optimista de revision; dos
  ediciones completas simultaneas aplican ultimo guardado gana.
- update/bulk_create/bulk_update/QuerySet.delete/SQL directo son operaciones
  privilegiadas, no escritores de negocio. Pueden saltar validacion cruzada,
  ciclos y advertencia de sede (SET_NULL conserva organizaciones).
- Selectores de arbol/formulario aun materializan el proyecto; hacen falta
  mediciones realistas y carga progresiva para volumenes grandes.
- Backups externos/cifrados, TLS, cuotas, observabilidad y purga de fuentes
  siguen pendientes. No se certifica produccion completa con estas pruebas.

Siguiente entrega sugerida: F6.3, entradas de construccion de mundo por categoria
y proyecto, sin introducir adjuntos, cobros ni exportaciones nuevas en esa fase.
