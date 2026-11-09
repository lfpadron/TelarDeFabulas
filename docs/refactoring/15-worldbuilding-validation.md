# F6.3: politica, religion e historia

Fecha: 2026-11-08. Prompt 10 aplicado sobre la estructura existente.
Entorno: Django 5.2.19, PostgreSQL 16, uv y Podman rootless, conexion explicita
`telar-fabulas-dev`. Sin dependencias nuevas, reinicio de PostgreSQL, borrado de
bases ni volumenes. La maquina anterior, TUI/Chrome, subir_repo.bat y diff_*.txt
se conservan. Los cambios pendientes de Prompt 09 no se revierten.

## Modelo y categorias

WorldbuildingEntry pertenece a Project (FK CASCADE) y conserva una identidad
estable. Campos: category, title (180), short_description opcional (300), content
TextField opcional, position, revision, created_at y updated_at. Categorias:
POLITICS/Politica, RELIGION/Religion y HISTORY/Historia. Multiples entradas por
categoria, sin limite artificial, jerarquia ni cronologia automatica.

Checks de DB: categoria valida, titulo con algun caracter no blanco, posicion
no negativa y revision positiva. UNIQUE(project,category,position) crea el indice
compuesto que sirve las consultas ordenadas; no se duplica con otro indice igual.
La FK tambien tiene su indice. Proyecto e ID no son editables; no hay traslado
entre proyectos. Texto plano conservado sin strip, incluidos CRLF, parrafos e
indentacion; templates escapan HTML y usan white-space: pre-wrap.

## Servicios, orden y concurrencia

create_entry, update_entry, move_entry_up/down, change_entry_category,
delete_entry y normalize_positions viven en services.py. Cada escritura abre
atomic, bloquea Project primero, revalida propietario/estado y despues bloquea
la entrada actual. El orden es contiguo desde cero por proyecto/categoria.
Al cambiar categoria se conserva ID/titulo/descripcion/contenido, se agrega al
final del destino y se normalizan ambos grupos en la misma transaccion.

Para satisfacer UNIQUE inmediato se aparcan temporalmente solo las posiciones
que cambian y luego se actualizan en lotes. No hay consultas por cada fila ni
lectura del contenido extenso para reordenar. La normalizacion lee metadatos de
la categoria completa; no es una operacion O(1) para grupos muy grandes.

Revision inicial 1. Una modificacion de texto/categoria/posicion la incrementa;
un guardado sin cambios o movimiento en el limite no. Renumerar incrementa la
revision de cada hermana cuya posicion cambia, conservando todo su texto. Crear
en posicion intermedia puede invalidar formularios de esas hermanas, una decision
conservadora explicita. La fila recien creada sigue en revision 1.

El formulario envia expected_revision oculto. El servicio comprueba esa revision
con la fila actual bajo bloqueo, no solo antes de entrar en la transaccion. Una
edicion obsoleta devuelve HTTP 409, no escribe ninguno de los campos y conserva
los valores enviados y su revision original. No se cambia silenciosamente la
revision del formulario rechazado. Se ofrece abrir la revision actual en otra
pestana, dejando el texto rechazado recuperable en la primera. No hay fusion,
autoguardado del conflicto ni historial completo; cerrar esa pestana descarta el
texto que solo existe en el formulario.

Tambien se exige revision en cambios de categoria, flechas y confirmacion de
borrado. Model.save conserva la revision original al cargar la instancia;
modificar la propiedad revision no permite convertir un objeto viejo en vigente.
Una instancia diferida sin revision no puede guardar a ciegas. Los servicios
devuelven la instancia actualizada; los llamadores deben usarla o refrescar.

## Interfaz, permisos y admin

En el detalle del proyecto aparece Construccion de mundos. Listado en tres
secciones, filtro de categoria y busqueda icontains por titulo/descripcion breve,
nunca por content. Cada seccion pagina a 50 y conserva filtros/paginas en los
enlaces. Como maximo seis consultas para conteo/datos de las tres categorias;
Exists calcula disponibilidad de flechas sin N+1, incluso con busqueda activa.
Content se difiere tanto en este listado como en el listado del admin.

Rutas bajo /projects/<project_pk>/worldbuilding/:

```text
                              listado
create/                       nueva entrada; ?category=HISTORY validado
<entry_pk>/                   detalle con fechas y texto
<entry_pk>/edit/               editar
<entry_pk>/change-category/    cambiar categoria
<entry_pk>/move-up/            subir (POST)
<entry_pk>/move-down/          bajar (POST)
<entry_pk>/delete/             confirmacion GET, borrado POST
```

Autenticacion requerida, CSRF en escrituras, respuestas privadas/no-store y
politicas centrales. ACTIVE permite escritura; FROZEN/PENDING_DELETION solo
lectura; DELETED y usuarios ajenos reciben 404. El ID de entrada siempre se
acota al proyecto. Ni BUSINESS_ADMIN ni TECH_ADMIN/superuser obtienen acceso
automatico a contenido ajeno. Los textos UI usan gettext_lazy/trans, preparados
para es-MX/en-US; no se crean catalogos ni se traduce texto literario.

Admin registra titulo/proyecto/categoria/posicion/revision/actualizacion, filtro
de categoria y busqueda titulo/descripcion/proyecto. ProjectOwnedAdmin mantiene
aislamiento y FK acotadas. En POST mantiene el lock de Project durante validacion
y save_model; reutiliza update_entry y devuelve 409 con formulario conservado.
No hay borrado individual ni masivo en admin; se usa la confirmacion del autor,
que incluye revision. Esto evita un segundo flujo de borrado sin esa proteccion.

## Migracion e integridad

Creada, inspeccionada y aplicada: worldbuilding.0001_initial. El plan mostro solo
CreateModel WorldbuildingEntry. No hay RunPython ni cambios en modelos anteriores.
El test de migracion aplica el esquema sobre fixtures historicos de cuentas,
proyectos, geografia, personajes, organizaciones y afiliaciones y compara todos
sus campos. Solo la base aislada de pruebas cambia de estado de migracion.

Respaldo previo local, ignorado por Git:

```text
backups/p10_pre_worldbuilding.dump
backups/p10_private_media.tar.gz
backups/p10_original_fingerprints.json
```

pg_dump -Fc conservado en el workspace. Huellas SHA-256 de todas las columnas
originales y archivos media comparadas despues de migrate y tras retirar QA:
iguales. Inventario conservado: 1 cuenta, 1 proyecto, 1 nodo, 2 personajes,
2 papeles dramaticos y 1 ubicacion. Cero versiones, menciones, organizaciones,
afiliaciones, notas, estilos, exportaciones, snapshots y archivos media.
Las cinco entradas QA fueron temporales; la tabla nueva queda vacia al cierre.
No se afirma un ensayo nuevo de restauracion en Prompt 10; los ensayos anteriores
estan documentados en sus fases. No se borra ninguna base, incluida test_telar_fabulas.

No usar migrate worldbuilding zero como rollback despues de crear contenido.
La reversa elimina la tabla; conservar esquema y respaldo y preferir correccion
hacia delante. No se habilitan purgas de fuentes ni reglas comerciales nuevas.

## Validacion automatizada

88 pruebas nuevas aprobadas: 79 funcionales, ocho concurrentes y una de migracion.
Pase focalizado final: 19.961 segundos. Suite integrada: **809 pruebas aprobadas**,
358.412 segundos, sin fallos; incluye regresion de geografia, organizaciones,
personajes, manuscritos, cuentas, notas, estilos y exportaciones.
--keepdb --noinput conserva la base de pruebas separada;
no ejecutar suites simultaneas sobre ella ni aceptar su destruccion.

Cobertura nueva:

- Modelo: categorias, obligatorios, espacios, contenido vacio/CRLF, orden automatico
  e insercion explicita, constraints/indice reales, identidad y proyecto inmutables.
- Servicios: todos los campos, subir/bajar/limites, reclasificacion, normalizacion,
  borrado exacto, estado fresco bajo lock y rollback de una renumeracion fallida.
- Revision: correcta/obsoleta/ausente/invalida, no-op, objetos viejos o diferidos,
  revision manipulada, edicion parcial, movimiento concurrente y no resurreccion.
- Web: tres secciones, filtro, busqueda sin contenido, GET validado, texto escapado,
  formulario sin editor enriquecido, 409 con todos los campos y revision original,
  confirmacion, POST-only, CSRF, headers privados y controles adaptables.
- Permisos: anonimo, ajeno, otro proyecto del mismo autor, tipos admin, todos los
  estados, campos del formulario y admin sin transferencia ni borrado masivo.
- Rendimiento: contenido diferido, consulta acotada con paginacion, flechas sin
  texto completo, busqueda sin alterar limites de orden y paginas invalidas.
- Carreras con conexiones PostgreSQL separadas: dos ediciones, dos creaciones,
  categoria vs texto, dos reclasificaciones al mismo destino, orden vs texto,
  borrar vs editar, admin vs admin y admin vs servicio.

El primer pase focalizado encontro un KeyError en el formulario admin de alta:
el campo revision oculto se retiraba aunque el admin lo incluia en sus fieldsets.
Se conserva como opcional al crear (el servicio impone revision 1). El pase de
88 completo, incluido admin add, queda aprobado; no se relajaron permisos.

## Prueba real y evidencia

Proyecto y dos cuentas QA aislados, nunca las credenciales del autor. Cinco
entradas creadas contra Gunicorn por HTTP con cookies/CSRF:
Consejo de Luz y Leyes del Reino (POLITICS), Culto de los Constructores (RELIGION),
Guerra de los Cristales y Gran Eclipse (HISTORY). CRLF y HTML literal conservados.

Navegador integrado a 1280x900: navegacion desde proyecto, tres secciones, subir
Leyes del Reino, reclasificarlo a Historia y comprobar ID/textos intactos; filtro
Politica y busqueda Consejo. Dos pestanas editaron Consejo: la primera guardo,
la segunda mostro conflicto conservando titulo, descripcion y contenido propios.
El registro mantuvo el texto de la primera. Tambien se ensayaron dos sesiones
HTTP con cookies independientes: segundo POST 409, sin perdida silenciosa.

Movil 390x844: listado, categoria preseleccionada, formulario y guardado de Gran
Eclipse. Capturas inspeccionadas y ancho DOM comprobado (sin scroll horizontal
de pagina ni controles fuera del viewport). No se altera el navegador Chrome
de la TUI; la prueba visual se hizo en el navegador integrado.

HTTP real: admin negocio ajeno 404 en lectura/escrituras; FROZEN/PENDING lectura
200 y escrituras 403; DELETED 404. Borrado/movimiento con revision vieja 409.
GET de confirmacion conserva la entrada; POST elimina solo Gran Eclipse y
mantiene ID/texto de las otras cuatro, con posiciones continuas.

Datos, cuentas y sesiones temporales retirados; huellas originales identicas.
Credenciales temporales state.json retiradas. Evidencia local ignorada por Git:

```text
backups/p10_qa/results.json
backups/p10_qa/list-desktop.png
backups/p10_qa/conflict-desktop.png
backups/p10_qa/list-mobile.png
backups/p10_qa/form-mobile.png
backups/p10_qa/detail-mobile.png
```

## Comandos y operacion

Todos con podman --connection telar-fabulas-dev compose:

```powershell
exec web python manage.py makemigrations worldbuilding
exec web python manage.py test apps.worldbuilding --keepdb --noinput
up -d --build
exec web python manage.py check
exec web python manage.py migrate --plan
exec web python manage.py migrate
exec web python manage.py test --keepdb --noinput
exec web python manage.py makemigrations --check --dry-run
exec worker celery -A config inspect ping
ps
```

Ademas: pg_dump y copia al workspace, scripts QA y comparacion de huellas,
git diff --check e info de Podman. Check sin problemas, sin cambios de modelos
ni migraciones pendientes. Celery devuelve pong, cinco servicios activos y una
sola instancia de Beat; Rootless=true. PostgreSQL/Redis no se reiniciaron durante
esta fase. Compose utiliza el proveedor instalado docker-compose.exe contra
Podman; esto no cambia el motor a Docker Desktop.

## Inventario de archivos

22 creados versionables:

```text
app/apps/worldbuilding/__init__.py
app/apps/worldbuilding/apps.py
app/apps/worldbuilding/models.py
app/apps/worldbuilding/services.py
app/apps/worldbuilding/forms.py
app/apps/worldbuilding/selectors.py
app/apps/worldbuilding/views.py
app/apps/worldbuilding/urls.py
app/apps/worldbuilding/admin.py
app/apps/worldbuilding/tests.py
app/apps/worldbuilding/test_concurrency.py
app/apps/worldbuilding/test_migrations.py
app/apps/worldbuilding/migrations/__init__.py
app/apps/worldbuilding/migrations/0001_initial.py
app/templates/worldbuilding/base.html
app/templates/worldbuilding/list.html
app/templates/worldbuilding/detail.html
app/templates/worldbuilding/form.html
app/templates/worldbuilding/confirm_delete.html
app/templates/worldbuilding/conflict.html
app/templates/admin/worldbuilding/worldbuildingentry/change_form.html
docs/refactoring/15-worldbuilding-validation.md
```

Seis modificados en esta fase:

```text
app/config/settings/base.py
app/config/urls.py
app/templates/projects/project_detail.html
README.md
docs/refactoring/04-refactoring-roadmap.md
docs/refactoring/05-risk-register.md
```

El inventario se compara con las huellas al iniciar Prompt 10, no con git HEAD:
el arbol de trabajo ya contenia cambios pendientes de Prompt 09. Auxiliares QA
y respaldos quedan en backups/ ignorado. Sin commit ni push automaticos.

## Limites y siguiente fase

- No hay papelera ni historial completo. El texto rechazado permanece solo en el
  formulario y debe conciliarse antes de cerrar la pestana.
- Geografia/organizaciones y otras fichas anteriores no reciben control de
  revision retroactivamente; R04 sigue abierto para esos textos.
- update/bulk_*/QuerySet.delete/SQL directo pueden saltar servicios y permisos;
  son operaciones privilegiadas, no una API de negocio.
- El lock de Project serializa escritores. Falta medir contencion, busqueda
  icontains y renumeracion con volumen representativo. No se incorpora cache.
- Backups externos/cifrados, TLS, cuotas y observabilidad siguen pendientes.
- Sin cronologia, relaciones entre entradas, referencias, adjuntos, IA, pagos,
  editor enriquecido ni exportacion de worldbuilding.

Siguiente fase sugerida: F6.4, referencias, con alcance propio y decisiones de
tipos, relaciones, permisos, storage privado y limites antes de admitir adjuntos.
