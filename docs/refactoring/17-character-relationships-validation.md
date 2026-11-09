# F7: relaciones entre personajes

Fecha: 2026-11-08. Prompt 12 sobre la estructura existente.
Django 5.2 LTS, PostgreSQL 16, uv y Podman rootless, conexion explicita
telar-fabulas-dev. Se conservan los cambios pendientes de Prompt 09/10/11.
No se reconstruyo el proyecto, reinicio PostgreSQL ni borro bases o volumenes.
Sin cambios a la maquina anterior, TUI/Chrome, subir_repo.bat o diff_*.txt.

## Modelo y tipos

CharacterRelationship vive en apps.characters; no se agrega una app nueva.
Campos: id, project, source_character, target_character, relationship_type,
custom_relationship_type, description, is_reciprocal, created_at, updated_at.
Las tres FK son obligatorias. Origen y destino deben ser distintos y pertenecer
al proyecto de la relacion, incluso cuando dos proyectos son del mismo autor.
No se permite trasladar una relacion a otro proyecto.

| Tipo | Etiqueta | Reciprocidad permitida |
| --- | --- | --- |
| FRIEND | Amistad | Si |
| ENEMY | Enemistad | Si |
| RIVAL | Rivalidad | Si |
| FAMILY | Familia | Si |
| PARENT | Progenitor | No |
| CHILD | Hijo/a | No |
| SIBLING | Hermano/a | Si |
| ROMANTIC_INTEREST | Interes romantico | Si |
| PARTNER | Pareja | Si |
| MENTOR | Mentor/a | No |
| STUDENT | Discipulo/a | No |
| ALLY | Alianza | Si |
| TRUST | Confianza | Si |
| DISTRUST | Desconfianza | Si |
| OTHER | Otro | Si |

Default de tipo FRIEND y de reciprocidad False. OTHER requiere etiqueta no
blanca de hasta 180 caracteres; se recortan sus espacios exteriores. Para los
otros tipos se limpia esa etiqueta, no se sustituye el tipo definido. Description
es texto libre opcional, escapado al mostrarlo; se conservan espacios/saltos.
Las etiquetas reales de modelo/formulario/template usan gettext_lazy/trans.

Una relacion no es un papel dramatico, mencion ni afiliacion. Se conservan
Character, CharacterDramaticRole, CharacterMention y CharacterOrganizationMembership,
incluido el papel INTERES_ROMANTICO y el calculo de completitud anterior.

## Direccion, reciprocidad y duplicados

Origen -> destino expresa solo lo que el origen siente/establece hacia el destino.
Una reciproca se almacena en una sola fila y se muestra origen <-> destino en
ambas fichas. Se conserva el origen elegido por el autor; el indice canonico no
reescribe endpoints. No se crean filas inversas ni parejas semanticas PARENT/CHILD
o MENTOR/STUDENT. La amistad tampoco es mutua por defecto.

Para el mismo tipo y personajes A/B:

| Existente | Intento | Resultado |
| --- | --- | --- |
| A -> B | A -> B | Rechazado: duplicado exacto |
| A -> B | B -> A | Permitido: dos sentimientos independientes |
| A -> B | B <-> A | Rechazado: la mutua solapa el vinculo existente |
| A <-> B | B -> A | Rechazado: ya esta incluido en la mutua |
| A <-> B | B <-> A | Rechazado: misma pareja reciproca |
| Cualquier relacion de tipo X | Misma pareja, tipo Y | Permitido |

La identidad exacta es origen/destino/tipo, no descripcion/reciprocidad/etiqueta
personalizada. Dos OTHER con etiquetas distintas siguen siendo duplicados en
la misma direccion. Para convertir dos unilaterales opuestas en una mutua, el
autor debe decidir cual conservar y eliminar la otra; no se fusionan textos.

Restricciones SQL:
- FK de proyecto/origen/destino, con indices individuales generados por Django.
- CHECK de extremos distintos, tipo permitido y cuatro tipos no reciprocos.
- CHECK de etiqueta OTHER no blanca; etiqueta vacia para los tipos estandar.
- UNIQUE(source_character,target_character,relationship_type).
- UNIQUE funcional parcial de Least(origen,destino), Greatest(origen,destino)
  y tipo, solo para is_reciprocal=True.

La unicidad funcional usa la API de
[UniqueConstraint de Django 5.2](https://docs.djangoproject.com/en/5.2/ref/models/constraints/#uniqueconstraint).
El caso mutua vs unilateral inversa y las FK del mismo proyecto necesitan
validacion bajo bloqueo; no se prometen mediante un CHECK entre tablas ni se
introducen triggers. ORM bulk/update/delete y SQL directo son APIs privilegiadas.

## Servicios y concurrencia

relationship_services.py ofrece create_relationship, update_relationship,
delete_relationship y get_relationships_for_character. Los servicios con user
revalidan propiedad con la politica central. model.save/delete tambien pasan
por servicios para integridad/estado; sin actor son una entrada interna de confianza.

Orden de escritura: atomic -> Project select_for_update -> relacion actual ->
personajes actuales del proyecto -> full_clean -> guardar/borrar. Se revalida
estado despues de tomar el lock. Edicion toma la fila actual, rechaza campos no
editables, proyecto diferente y filas eliminadas; no resucita copias obsoletas.
Un guardado parcial conserva los campos actuales que no se pidio modificar.
La validacion de inversa y el guardado se serializan por proyecto, incluso para
relaciones de distinto tipo. El admin toma el mismo lock antes de validar POST.

No hay revision optimista, historial ni fusion de texto en este modelo. Dos
ediciones completas validas siguen ultimo guardado gana; la confirmacion de
borrado tampoco detecta una edicion intermedia. El lock garantiza invariantes,
no avisa al autor de una descripcion sobreescrita. Este limite queda en R04/R34.

Eliminar relacion requiere confirmacion GET y POST/CSRF autorizado. No borra
personajes ni otros vinculos. FK CASCADE de ambos extremos retira las relaciones
del personaje eliminado, conservando los otros personajes. Character.delete ya
bloqueaba Project desde F6.4: se reutiliza sin modificarlo. No hay borrado masivo
de relaciones en admin, papelera ni purga general de proyectos.

## Interfaz, consultas y permisos

Rutas bajo /projects/<project_pk>/:
- characters/<character_pk>/relationships/ y relationships/create/.
- relationships/<relationship_pk>/, edit/ y delete/.

Ficha y listado independiente muestran tres grupos: salientes, entrantes y
mutuas. Las mutuas no se repiten en los otros grupos. Flechas con nombre accesible,
enlaces a ambas fichas, tipo y acciones de consulta/edicion/eliminacion.
Desde la ficha se preselecciona origen, pero el POST se valida de nuevo. Ambos
selectores se limitan al proyecto; cambiar origen dentro de el esta permitido.

Detalle muestra descripcion completa y fechas. No hay descripcion en listados:
select_related y only cargan metadata y nombres, tampoco textos largos de las
fichas. Filtro defensivo excluye relaciones corruptas entre proyectos sin borrar
datos. Paginacion independiente de 50 por grupo con outgoing_page, incoming_page
y mutual_page; los enlaces conservan parametros y vuelven al encabezado.
Consulta de selector con los nombres en una sola query, sin N+1. La prueba de
1200 vinculos verifica 24 paginas y solo 50 filas en el grupo consultado; la
respuesta web con tres grupos usa como maximo 12 queries en la prueba.

Formularios nativos Django y CSS local responsive, sin JavaScript ni libreria
nueva. La descripcion conserva saltos de linea; no se renderiza HTML del usuario.
Retorno opcional character solo admite un ID local validado, sin next arbitrario.
get_user_project, project_access y ProjectOwnedAdmin siguen siendo la autoridad.

| Proyecto / actor | Consulta | Escritura |
| --- | --- | --- |
| ACTIVE, propietario | Si | Si |
| FROZEN, propietario | Si | 403 |
| PENDING_DELETION, propietario | Si | 403 |
| DELETED | 404 | 404 |
| Autor ajeno, incluido administrador | 404 | 404 |

Admin registra el modelo, muestra origen/destino/tipo/reciprocidad/proyecto/fecha,
filtra por tipo/reciprocidad y busca nombres. Listados y FK acotados a propietario;
al seleccionar proyecto el POST limita ambos personajes a el. El proyecto de
una relacion existente no se edita. Consultas readonly no ofrecen escritura.
GET de alta admin puede mostrar personajes de varios proyectos activos propios;
ninguna combinacion entre proyectos se puede guardar. Sin bypass de superusuario.

## Migracion y proteccion de originales

characters.0004_characterrelationship depende de characters.0003_character_residence
y projects.0001_initial. Solo CreateModel con sus indices/checks/UNIQUE; no
RunPython, alteraciones de tablas previas ni edicion de migraciones historicas.
Plan inspeccionado antes de aplicar; solo creaba este modelo. Migracion aplicada.

Se detuvieron solo web/worker/beat para respaldar y migrar. PostgreSQL y Redis
permanecieron activos. Copias locales ignoradas por Git:
- backups/p12_pre_relationships.dump, pg_dump -Fc copiado al workspace.
- backups/p12_private_media.tar.gz.
- backups/p12_original_fingerprints.json, SHA-256 de todas las columnas originales
  por PK y de cada archivo media.

Huellas identicas tras migrate y tras limpiar QA: una cuenta, un proyecto, un
nodo, tres personajes, tres papeles dramaticos, dos ubicaciones y dos organizaciones.
Cero versiones, menciones, afiliaciones, worldbuilding, notas, estilos, exports,
snapshots, referencias/asociaciones/limpieza y archivos originales. La tabla
CharacterRelationship queda vacia tras retirar solamente los datos temporales.
No se ensayo una restauracion nueva. No se borro ninguna base ni volumen; la
suite conserva test_telar_fabulas con --keepdb. No se opero la maquina anterior.

No revertir characters.0004 con contenido ni restaurar el dump previo como
rollback rutinario: perderia relaciones posteriores. Preferir correccion hacia
delante y respaldar DB/media conjuntamente.

## Pruebas automatizadas

94 nuevas aprobadas en PostgreSQL: 83 funcionales, diez carreras con conexiones
separadas y una migracion aditiva. Pase focalizado final: 39.058 s.
Suite integrada: **1005 pruebas aprobadas**, 549.805 s, sin fallos ni saltos.
Se conserva la regresion de cuentas, manuscritos/versiones, menciones, afiliaciones,
geografia, organizaciones, mundo, referencias, notas, estilos y exportaciones.
Los mensajes de fallo de disco/exportacion/limpieza en el log son escenarios
simulados de pruebas, no fallos del resultado. Log local:
backups/p12_full_tests.log. No ejecutar suites simultaneas.

Cobertura: 15 tipos, default unilateral, OTHER, extremos/proyectos/autorrelacion,
constraints SQL, duplicado exacto/inverso y varios tipos, CRUD y servicios,
textos/PK/otros vinculos conservados, formularios/CSRF/metodos/retornos, estados,
roles de cuenta, admin scoped/readonly/borrado individual, relaciones corruptas
ocultas, ambas fichas, tres grupos y paginacion sin N+1.

Las diez carreras:
1. Dos altas exactas.
2. Dos mutuas invertidas.
3. Mutua contra unilateral inversa.
4. Dos unilaterales opuestas permitidas.
5. Promocion a mutua contra alta inversa.
6. Edicion de tipo contra alta del mismo tipo.
7. Alta contra borrado de personaje.
8. Edicion contra borrado de relacion, sin resurreccion.
9. Alta admin contra servicio.
10. Borrado admin de relacion contra borrado de personaje.

La prueba de migracion usa solo la DB de tests, baja characters a 0003 y crea
fixtures historicos de cuenta/proyecto/personaje/roles/mencion/residencia,
organizacion/afiliacion, referencia/vinculo y manuscrito/SceneVersion vigente.
Compara todas sus columnas despues de 0004 y restaura los leaf targets al terminar.
No es una restauracion del backup de negocio ni una modificacion de originales.

## QA HTTP y navegador

Dos cuentas y un proyecto temporales con Rosariel, Fernaud y Arkan. Relaciones:
Rosariel -> Fernaud TRUST; Fernaud <-> Rosariel FRIEND; Arkan -> Rosariel ENEMY;
Rosariel -> Arkan RIVAL. Las ultimas tres se crearon con HTTP real y CSRF contra
Gunicorn; TRUST desde el navegador, usando Agregar relacion en la ficha.

Navegador integrado a 1280x900: origen preseleccionado y opciones locales;
creacion de TRUST; grupos correctos; navegacion a Fernaud confirma entrante
TRUST y mutua FRIEND sin una segunda fila. Intento de amistad mutua invertida
rechazado con error de formulario. A 390x844: listado, formulario y edicion de
descripcion desde la ficha destino; detalle confirma mismo ID, origen, destino,
tipo y direccion. Capturas inspeccionadas, sin scroll horizontal ni controles
fuera del viewport; consola sin errores. TUI y su configuracion Chrome intactas.

HTTP real adicional: cuatro filas y una sola FRIEND; administrador de negocio
ajeno recibe 404 en todas las rutas GET/POST; FROZEN/PENDING solo lectura y
DELETED 404. Duplicado inverso y PARENT reciproco rechazados. GET de confirmacion
conserva RIVAL; POST lo elimina, conservando exactamente otros vinculos,
personajes y papeles dramaticos. Se retiraron unicamente los datos/sesiones QA;
state.json con credenciales temporales eliminado y huellas originales iguales.

Evidencia local ignorada por Git: backups/p12_qa/results.json, list-desktop.png,
fernaud-desktop.png, duplicate-desktop.png, list-mobile.png, form-mobile.png,
detail-mobile.png y scripts backups/p12_qa.py, p12_ops.py.

## Operacion validada

Todos los comandos usan la conexion Podman explicitamente. Antes de iniciar
escritores se aplico migrate con compose run --rm --no-deps web; despues:

```powershell
podman --connection telar-fabulas-dev compose up -d --build
podman --connection telar-fabulas-dev compose exec web python manage.py check
podman --connection telar-fabulas-dev compose exec web python manage.py migrate --plan
podman --connection telar-fabulas-dev compose exec web python manage.py migrate --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py test apps.characters.test_relationships apps.characters.test_relationship_concurrency apps.characters.test_relationship_migrations --keepdb --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py test --keepdb --noinput
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
podman --connection telar-fabulas-dev compose ps
podman --connection telar-fabulas-dev info --format '{{.Host.Security.Rootless}}'
```

Check sin incidencias; plan final vacio, sin migraciones/cambios de modelos
pendientes; Celery pong, un worker y cinco servicios activos. Rootless=true.
Compose usa docker-compose.exe como proveedor contra Podman, no motor Docker.
git diff --check sin errores de whitespace; advertencias LF/CRLF de Windows.
No se agregan dependencias, servicios, tareas Celery ni cambios a uv.lock.

## Inventario de esta fase

16 archivos versionables creados, medidos contra el inicio de Prompt 12:

```text
app/apps/characters/migrations/0004_characterrelationship.py
app/apps/characters/relationship_forms.py
app/apps/characters/relationship_selectors.py
app/apps/characters/relationship_services.py
app/apps/characters/relationship_views.py
app/apps/characters/test_relationship_concurrency.py
app/apps/characters/test_relationship_migrations.py
app/apps/characters/test_relationships.py
app/templates/characters/relationships/_direction.html
app/templates/characters/relationships/_groups.html
app/templates/characters/relationships/base.html
app/templates/characters/relationships/confirm_delete.html
app/templates/characters/relationships/detail.html
app/templates/characters/relationships/form.html
app/templates/characters/relationships/list.html
docs/refactoring/17-character-relationships-validation.md
```

Ocho archivos modificados respecto del mismo baseline:

```text
README.md
app/apps/characters/admin.py
app/apps/characters/models.py
app/apps/characters/urls.py
app/apps/characters/views.py
app/templates/characters/character_detail.html
docs/refactoring/04-refactoring-roadmap.md
docs/refactoring/05-risk-register.md
```

Backups, scripts de QA y capturas son locales ignorados, no entregables del repo.
Los archivos nuevos/modificados de fases anteriores no se atribuyen a F7.
No se editaron sus contenidos salvo los ocho archivos listados arriba.

## Riesgos y siguiente fase

Se mantienen R04/R34 (ultimo guardado completo gana, sin historial/papelera),
R13 (respaldos externos/cifrados y restauracion recurrente), R16/R17 (medicion
de escala, contencion por proyecto y selectores con todos los personajes) y
R38 (semantica limitada y conversion manual de dos unilaterales a una mutua).
No hay garantia contra escrituras SQL fuera de los servicios cooperantes.
La prueba de 1200 filas valida paginacion/consultas, no es un benchmark de carga.

Siguiente fase recomendada: F8, exportacion de entidades, con matriz explicita
de entidades/formatos y politica de adjuntos, reutilizando seleccion/snapshots.
Exportar relaciones requiere alcance aprobado; no se incluye por implicacion.
No se implementan grafo interactivo, relaciones entre organizaciones,
cronologias, inferencias, IA, suscripciones, Stripe ni exportacion de relaciones.
