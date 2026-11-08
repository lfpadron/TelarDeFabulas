# Validacion F6.1: geografia y jerarquias territoriales

Fecha: 2026-11-08. Prompt 08, sobre el proyecto existente.
Podman rootless, conexion explicita `telar-fabulas-dev`, PostgreSQL 16.
No se reconstruyo el proyecto, se reiniciaron datos ni se borraron volumenes.

## Modelo y contratos

Nueva app `apps.geography`, registrada en settings y URLs.
GeographicLocation conserva PK estable y tiene project, parent opcional, tipo,
tipo personalizado opcional, name obligatorio (180), short_description opcional
(300), detailed_description libre, position positiva y fechas.

| Valor | Etiqueta |
| --- | --- |
| UNIVERSE | Universo |
| WORLD | Mundo |
| CONTINENT | Continente |
| EMPIRE | Imperio |
| KINGDOM | Reino |
| COUNTRY | Pais |
| PROVINCE | Provincia |
| CITY | Ciudad |
| OTHER | Otro, con tipo personalizado opcional |

No se impone matriz de tipos: cualquier ubicacion puede ser raiz o tener hijos;
Universo no es obligatorio. Un padre principal, siempre del mismo proyecto;
sin autoparentesco, ciclos ni traslados entre proyectos. No hay mapas/coordenadas.

Indices: FK project, FK parent, position y compuesto (project,parent,position).
UNIQUE inmediato (project,parent,position), NULLS NOT DISTINCT en PostgreSQL 16,
incluye raices. CHECK de tipo permitido, nombre no vacio, posicion >=1 y padre
distinto de la propia PK. El nombre solo con espacios se rechaza en validacion.

### Servicios y concurrencia

`save_location`, `move_location`, `move_location_up/down`, `normalize_positions`
y `delete_location` usan atomic y bloquean Project primero, luego la ubicacion
actual cuando existe. Releen el estado y validan estructura bajo ese bloqueo.
La creacion inserta en posicion solicitada o agrega al final; posiciones desde 1.
Mover y borrar normalizan origen/destino. Para no colisionar con UNIQUE inmediato,
las filas afectadas ocupan primero posiciones temporales libres dentro de la
misma transaccion y despues reciben la numeracion final. No recrean ubicaciones.

La edicion web de texto no expone padre ni posicion. Una instancia ORM antigua
que solo cambia texto preserva el movimiento ya confirmado; un cambio estructural
en conflicto se rechaza. Los servicios de movimiento releen la instancia actual
y solo escriben padre/orden/fecha, nunca copian descripciones antiguas.

Modelo y servicios son las entradas de negocio, incluyendo admin. El argumento
user de movimientos/borrado aplica propiedad; save sin actor es una entrada ORM
de confianza y valida estado/proyecto. Las vistas resuelven propietario antes.

### Personajes

Character.residence es FK nullable/blank con SET_NULL y etiqueta **Habitante de**.
Guardar personaje bloquea Project y valida residencia del mismo proyecto.
No cambia los demas campos de ficha, roles ni porcentaje de completitud.
Selector web/admin limitado al proyecto; detalle enlaza residencia y ubicacion
lista habitantes. Consultas de detalle/admin no exponen relaciones cruzadas
corruptas introducidas fuera de los servicios.

Solo residencia principal. Historial/periodos y multiples residencias requieren
otra fase; los IDs existentes permiten esa expansion sin recrear entidades.

### Borrado

Confirmacion GET y mutacion POST con CSRF. Se rechaza si hay hijos o habitantes,
con mensajes explicitos. parent usa PROTECT, nunca cascada de hijos. SET_NULL de
residence es defensa referencial: el flujo normal exige retirar/cambiar las
residencias antes del borrado. Personajes y fichas no se borran al quitar el lugar.
Admin desactiva bulk delete y revalida borrado mediante el mismo modelo/servicio.

## Interfaz, permisos y rendimiento

Rutas bajo `/projects/<project_pk>/geography/`: raiz, create, detalle por ID,
edit, delete, move, move-up y move-down. Todas autenticadas. Botones de orden
son POST; los demas formularios incluyen CSRF y no aceptan proyecto del cliente.
Navegacion desde detalle de proyecto, acciones segun permisos centrales.

| Estado/actor | Resultado |
| --- | --- |
| Propietario, ACTIVE | CRUD y movimientos |
| Propietario, FROZEN/PENDING_DELETION | Lectura; escritura 403 |
| DELETED | 404 |
| Usuario ajeno | 404, incluido admin con permisos/superusuario |
| Anonimo | Login |

Arbol nativo details/summary, nombres/tipos/descripciones cortas; las ramas se
cierran sin JavaScript. Recorrido iterativo emite aperturas/cierres, no templates
recursivos. El selector de arbol hace una consulta sin detailed_description;
la ruta completa hace una consulta de IDs/nombres/padres. No consulta por ancestro.
La indentacion visual se limita tras ocho niveles sin limitar el grafo.
Detalle pagina hijos y habitantes a 50 y limita campos del listado de personajes.
Texto del usuario escapado; textos visibles preparados con gettext_lazy/trans.
Locales iniciales es-mx/en-us, sin nuevos catalogos ni dependencias.

Admin: busqueda name/short_description/project__name/project__user__email;
filtros location_type/created_at/updated_at; listado name/project/location_type/
parent/position/updated_at. Proyecto, padre y posicion existentes son de solo
lectura en admin; reorganizar por la vista Mover, con el mismo servicio central.

## Migraciones, respaldo y datos

Plan revisado antes de aplicar:

1. `geography.0001_initial`: tabla, indices y constraints nuevos.
2. `characters.0003_character_residence`: FK opcional, sin backfill ni inferencias.

Ambas aplicadas correctamente. Ninguna altera texto, identidad, fechas o roles
anteriores. Unica cuenta/proyecto/nodo/personaje y un papel dramatico originales
conservados; cero versiones/notas/estilos/exports originales en esta base.
El personaje original queda con residence NULL. Media original sin archivos.
Esto describe solo la base de desarrollo, no la maquina anterior.

Antes de editar el esquema, web/worker/Beat estaban detenidos. Se obtuvieron:

- `backups/p08_pre_geography.dump`: pg_dump -Fc y catalogo pg_restore revisado.
- `backups/p08_private_media.tar.gz`: copia de media privado, vacio en esta base.
- `backups/p08_original_fingerprints.json`: cantidades/SHA-256, no texto literario.

El dump se restauro completo en `p08_restore_check_20261108`, una base aparte.
Las huellas de cuentas, proyecto, manuscrito/versiones, personaje/roles/menciones,
notas, estilos y exportaciones/snapshots coincidieron. La copia se retiro.
Al terminar QA, se verificaron otra vez las huellas en la base original, ignorando
solo el nuevo campo residence al comparar el esquema anterior; no hay residuos
geograficos ni cuentas de prueba. No se purgaron fuentes ni volumenes.

Reversion: no ejecutar migrate geography zero ni retirar characters.0003 si ya
hay ubicaciones/residencias nuevas: se perderian esas relaciones. Preferir
retorno de aplicacion con esquema expandido o restaurar una copia aislada y
conciliar nuevas escrituras. Los backups locales deben protegerse fuera de Git.

## Pruebas y QA

Suite integrada: **624 pruebas aprobadas en 293.873 s**, sin omisiones.
Base temporal separada de Django. **84 nuevas** respecto de 540:

- 74 funcionales de modelo, movimientos, residencia, vistas, seguridad y admin.
- Nueve TransactionTestCase con conexiones PostgreSQL separadas: crear/crear,
  mover/mover, crear/mover, mover la misma ubicacion, movimientos que intentan
  producir ciclo, subir/bajar, editar/mover, asignar residente/borrar ubicacion,
  crear hijo/borrar padre. Ningun ciclo, perdida ni duplicacion de posiciones.
- Una migracion historica: conserva byte a byte fichas/fechas/ruta de imagen,
  IDs y roles; el nuevo FK queda NULL y no se inventan ubicaciones.

Cobertura adicional: constraints SQL incluidas raices, estados, POST/CSRF, XSS,
relaciones ajenas, pagina de confirmacion, errores claros, permisos de admin,
formularios viejos, rollback y selectores de una consulta. Arbol/ruta probados
con una cadena de 1100 niveles sin recursion Python; detalle paginado comprobado.
Las 540 pruebas anteriores de personajes, manuscritos, versiones, formatos,
snapshots, permisos y ciclo de exportaciones tambien pasaron sin modificarlas.

### Escenario manual

Se crearon por HTTP real contra Gunicorn siete ubicaciones y dos personajes en
un proyecto temporal. La estructura inicial fue la indicada por el prompt:

```text
Mundo
  Continente
    Reino
      Provincia A
        Ciudad A
      Provincia B
        Ciudad B
```

Desde el navegador se colapso/expandio Provincia A y se movio Ciudad A a Provincia
B. La pagina de resultado mostro el arbol actualizado. Detalle: nueva ruta,
mismo ID, ambas descripciones originales y enlaces a Elena y Mateo. La ficha
de Elena conserva biografia y el vinculo Habitante de. La confirmacion de borrado
rechaza Ciudad A por sus habitantes, sin ofrecer boton de confirmacion.
HTTP y DB comprobaron ademas usuario ajeno 404, FROZEN/PENDING lectura y rechazo
de escrituras, DELETED 404 y no eliminacion de una ciudad con referencias.

Revision visual: navegador integrado, 1280x900 y 390x844, arbol y detalle sin
desbordamiento horizontal. No se cambio Chrome en la TUI. Capturas y resultados
sinteticos quedan en `backups/p08_qa/`, excluidos de Git. Proyecto, cuentas,
ubicaciones, personajes y sesiones temporales retirados; no quedan credenciales
temporales activas. Se eliminaron unicamente datos de este escenario.

## Comandos ejecutados

Siempre sobre telar-fabulas-dev; Docker Compose es el proveedor de Compose del
equipo, pero el motor y los volumenes son Podman rootless, no Docker Desktop.

```powershell
podman --connection telar-fabulas-dev compose up -d postgres redis
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py makemigrations geography characters
podman --connection telar-fabulas-dev compose run --rm --no-deps web python manage.py test apps.geography --noinput
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

Check limpio, esquema al dia, Celery pong, cinco servicios activos y un solo Beat.
Tambien se ejecutaron pg_dump/pg_restore y scripts privados de inventario/QA en
backups. Servidor final disponible en http://localhost:8000.

### Incidencia local de arranque

La maquina estaba apagada. Al iniciarla, win-sshproxy salia con codigo 0 y Compose
no encontraba el pipe, aunque podman ps funcionaba. Un reinicio normal no basto.
Se detuvo solo telar-fabulas-dev, se retiro unicamente su socket temporal
`%LOCALAPPDATA%\Temp\podman\telar-fabulas-dev-api.sock` y se inicio de nuevo:
Compose recuperado, rootless conservado. No se tocaron conexiones, sockets ni
volumenes de la maquina anterior. Incidencia coincidente con el
[reporte de Podman](https://github.com/podman-container-tools/podman/issues/30102).
No se cambio la TUI ni se instalo otro proveedor de Compose.

## Archivos de esta entrega

Comparacion por SHA-256 contra el inicio del turno, no contra HEAD (habia cambios
de fases anteriores pendientes). **21 nuevos y 12 modificados**.

Nuevos:

```text
app/apps/geography/__init__.py
app/apps/geography/apps.py
app/apps/geography/models.py
app/apps/geography/services.py
app/apps/geography/selectors.py
app/apps/geography/forms.py
app/apps/geography/views.py
app/apps/geography/urls.py
app/apps/geography/admin.py
app/apps/geography/tests.py
app/apps/geography/test_concurrency.py
app/apps/geography/test_migrations.py
app/apps/geography/migrations/__init__.py
app/apps/geography/migrations/0001_initial.py
app/apps/characters/migrations/0003_character_residence.py
app/templates/geography/base.html
app/templates/geography/tree.html
app/templates/geography/form.html
app/templates/geography/detail.html
app/templates/geography/confirm_delete.html
docs/refactoring/13-geography-validation.md
```

Modificados:

```text
README.md
app/apps/characters/models.py
app/apps/characters/forms.py
app/apps/characters/views.py
app/apps/characters/admin.py
app/apps/core/permissions.py
app/config/settings/base.py
app/config/urls.py
app/templates/characters/character_detail.html
app/templates/projects/project_detail.html
docs/refactoring/04-refactoring-roadmap.md
docs/refactoring/05-risk-register.md
```

Evidencia operacional ignorada por Git: `backups/p08_ops.py`, `p08_qa.py`, dump,
tar, huellas, capturas y results.json. No se modificaron subir_repo.bat, diff_*.txt,
TUI, pyproject.toml, uv.lock, Dockerfile, compose.yaml ni archivos de exportacion.

## Riesgos y siguiente fase

- Arbol y selects cargan metadatos de todo el proyecto. Para decenas de miles de
  ubicaciones faltan carga progresiva, busqueda/paginacion de selectores y medidas
  de latencia/DOM. No se agrego cache ni dependencia de arbol.
- El bloqueo por proyecto serializa escritores, una eleccion conservadora; medir
  contencion antes de colaboracion multiusuario. Descripciones no tienen revision
  optimista; dos ediciones de texto pueden sobrescribirse, sin afectar movimientos.
- update/bulk/QuerySet.delete/SQL directo son privilegiados y pueden saltar las
  reglas de grafo o borrado con habitantes. No son APIs de negocio. El UNIQUE de
  orden protege PostgreSQL, no reemplaza la validacion cruzada de proyecto/ciclos.
- Historial de residencias pendiente. Purga futura de proyectos debe tratar los
  PROTECT del arbol explicitamente. No hay purgas nuevas en esta entrega.
- Backups recurrentes externos, TLS, cuotas, SMTP real y dimensionamiento siguen
  pendientes para produccion; las validaciones actuales son locales.
- Siguiente fase recomendada: **F6.2 organizaciones**, conservando propietario,
  proyecto e identidad. No se implementaron organizaciones, politica/religion/
  historia, referencias, mapas, IA, pagos ni nuevas exportaciones.
