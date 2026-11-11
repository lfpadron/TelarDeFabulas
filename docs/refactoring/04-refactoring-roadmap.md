# Roadmap de refactorizacion v01

Fecha: 2026-11-11. Actualizado para Prompt 14 (F9). Cada fase posterior requiere
una instruccion independiente de implementacion.
No se estima duracion sin inventario de datos y presupuesto operativo. El orden
protege identidad/texto antes de introducir nuevas reglas comerciales.

## Fases y puertas de aceptacion

| Fase | Entrega acotada | Dependencias | Aceptacion verificable | Pruebas requeridas |
| --- | --- | --- | --- | --- |
| F0: baseline e inventario | Comando read-only de auditoria de datos, registro de migraciones aplicadas y ensayo de restauracion aislada | Podman disponible; D17 | Reporte de cantidades/casos legacy sin texto privado, DB/media recuperables, suite actual conocida | check, showmigrations, dry-run de migraciones, test completo, ping Celery; fixtures corruptos para el auditor |
| F1: proteccion de operaciones (implementada) | Politica central, storage privado, validacion Pillow, admin acotado, CSS/HTML seguros, estilos protegidos y roles atomicos | Inventario F0; matriz de proyecto aprobada en Prompt 03 | Propietario exclusivo, escrituras solo ACTIVE; FROZEN/PENDING leen/exportan/descargan; DELETED 404; no rutas publicas de media | Suite integrada y matriz de permisos, POST/CSRF, archivos, uploads, admin y formatos; detalle en 08 |
| F2: arbol e identidad (implementada) | Politica comun, descripcion breve, titulo opcional solo SCENE, movimientos bajo bloqueo de proyecto y orden normalizado de grupos validos | F0-F1; alcance aprobado en Prompt 04 | Mismos PK/texto/asociaciones; PART opcional; FRAGMENT conservado sin conversion ni renumeracion automatica | Matriz completa, modelo/forms/vistas/admin, ocho casos concurrentes PostgreSQL, migracion 0001 -> 0002 y cuatro formatos; detalle en 09 |
| F3: SceneVersion (implementada) | Expansion aditiva, copia exacta con huella, borrador activo, FINAL vigente, historial y revision esperada | F2; D04-D05 aprobadas en Prompt 05 | Texto/PK/FK conservados; cero o una vigente; nueva edicion no altera FINAL; HTTP 409 conserva texto enviado | 66 pruebas funcionales, 11 de migracion, 8 carreras PostgreSQL, suite 445; HTTP/Celery y UI desktop/movil; detalle en 10 |
| F4: selector y formatos (implementada) | Documento neutral, WORK/FINAL y snapshot en Prompt 06; Markdown en Prompt 07; HTML/DOCX/PDF/EPUB y preview compatibles | F3; D06/D15 | Misma seleccion, identidad y orden; texto legacy conservado en WORK | Snapshot inmutable, render y descargas; validaciones 11 y 12 |
| F5: lifecycle de exports (implementada) | REQUESTED/READY/DELETED, claim atomico, heartbeat/lease, recuperacion, retencion, limpieza manual/Beat y outbox | F4; D14-D15; storage privado F1 | Token descarta worker antiguo; cleanup espera descargas y no toca fuente; SMTP best-effort sin adjunto | PostgreSQL concurrente, Celery real, broker/disco/SMTP fallando, worker vs cleanup/download y temporales; validacion 12 |
| F6.1: geografia (implementada) | Ubicaciones con jerarquia flexible, orden unico, movimientos y residencia principal opcional | F1-F2; D08 resuelta para padre principal flexible por Prompt 08 | ID/texto/habitantes conservados, sin ciclos, borrado solo de hojas sin referencias | 84 nuevas: modelo/UI/seguridad, nueve carreras PostgreSQL y migracion aditiva; suite 624 y QA HTTP/visual; detalle en 13 |
| F6.2: organizaciones (implementada) | Jerarquia opcional, nueve tipos, sede principal y afiliaciones con cargo/estado/periodo textual | F6.1; alcance aprobado en Prompt 09 | ID/texto/afiliaciones conservados, sin ciclos ni referencias cruzadas; borrados bloqueados por relaciones | 97 nuevas: 89 funcionales, siete carreras PostgreSQL y una migracion; evidencia y suite integrada en 14 |
| F6.3: mundo (implementada) | Entradas planas de politica/religion/historia, orden por categoria y revision optimista | F6.1-F6.2; alcance aprobado en Prompt 10 | ID/texto conservados; revision obsoleta devuelve 409 y conserva formulario; admin protegido | 88 nuevas: 79 funcionales, ocho carreras PostgreSQL y una migracion; evidencia y suite integrada en 15 |
| F6.4: referencias (implementada) | Cinco tipos, adjuntos privados, asociaciones explicitas y limpieza durable | F6.1-F6.3; alcance aprobado en Prompt 11 | Un archivo reutilizado, cuota serializada, reemplazo tras commit y aislamiento por propietario/proyecto | 102 nuevas: archivos, SQL, permisos, UI/admin, diez carreras y migracion; suite integrada y evidencia en 16 |
| F7: relaciones de personajes (implementada) | Quince tipos interpersonales, direccion explicita, reciprocidad opcional en una fila y CRUD desde ambas fichas | F6; alcance acotado aprobado en Prompt 12 | Sin duplicados exactos/inversos mutuos, sin cruces de proyecto; fichas/roles/menciones/afiliaciones conservados | 94 nuevas: 83 funcionales, diez carreras PostgreSQL, migracion aditiva; QA escritorio/movil y evidencia integrada en 17 |
| F8: exportar entidades (implementada) | REFERENCE y doce alcances, con Markdown/DOCX/PDF, documento neutral y snapshot inmutable; sin binarios | F4/F6/F7; alcance aprobado en Prompt 13 | Fichas/catalogos/compendio fieles a la solicitud, historial y lifecycle compartidos, sin cruces ni manuscritos | 88 nuevas: 76 funcionales, 11 carreras y migracion; QA HTTP/Celery/desktop/movil/Word/PDF; detalle en 18 |
| F9: papelera de manuscritos (implementada) | Eliminacion logica y recuperacion de libros/partes/capitulos/escenas, visibilidad efectiva y admin protegido | F1-F8; alcance aprobado en Prompt 14 | Mismos PK/versiones/vinculos; restaurar ancestro no reactiva eliminaciones anteriores; nuevos exports excluyen ocultos | 77 nuevas: 67 funcionales, nueve carreras PostgreSQL y migracion; suite completa y QA real; detalle en 19 |
| F10: trial y pago manual (pospuesta) | Plan/Subscription/Payment, capacidades calculadas, transicion de cuentas heredadas y cupos configurables | F1/F5; D10-D14/D18-D19 | Trial con un proyecto y todas las funciones; vencido solo lectura/export; pagos manuales auditables | Reloj controlado, cupos concurrentes, cambio de plan y permisos en todas las apps |
| F11: Stripe y retencion de cuenta | PaymentEvent, webhooks idempotentes, avisos por periodo, conservacion anual y purga auditable | F10; D11-D14/D17 | Pago confirmado mantiene acceso; no doble credito; renovacion cancela purga; avisos sin solapamiento | Firma, repeticion/orden de eventos, pago vs purga, ano bisiesto y ensayo de eliminacion en copia |
| F12: capacidad y despliegue | Paginacion/carga progresiva, indices medidos, recursos de workers, observabilidad, TLS/static y restauracion | Medicion desde F0; integrar en cada fase | Presupuesto de latencia/RSS fijado y cumplido; check --deploy objetivo; operacion documentada | Datos representativos, EXPLAIN, carga web/export, caida de servicios y restauracion |
| F13: retirada de compatibilidad | Evaluar retiro de columnas legacy/FRAGMENT y limpieza de copias | Todas las fases afectadas estables; aprobacion independiente | Sin lectores/escritores legacy, sin casos ambiguos ni datos sin destino; backup recuperable | Rehearsal completo forward/rollback, comprobacion de texto/relaciones y corte ensayado |

F6-F7 y F10 pueden organizarse de forma independiente despues de sus dependencias,
pero no conviene mezclar jerarquia/versionado, billing y purga en una sola entrega.
F12 es trabajo continuo: las optimizaciones necesarias por memoria no esperan al
final si F0 revela manuscritos grandes. F13 es opcional y no habilita borrar datos
solo para simplificar el esquema.

## Contratos transversales

| Contrato | Debe mantenerse en cada fase |
| --- | --- |
| Propiedad | Toda consulta/descarga/escritura acotada a propietario/proyecto; admin explicito |
| Identidad | Ninguna migracion recrea un nodo original con otra PK |
| Texto | Fuente intacta hasta validar copia y cambio de lectores; conflictos visibles |
| Concurrencia | Pruebas PostgreSQL con conexiones separadas; TestCase secuencial no basta |
| Archivos | Una limpieza de export nunca toca manuscrito, versiones, imagenes ni referencias fuente |
| Compatibilidad | HTML/EPUB conservados y probados; no rebautizar un archivo historico como FINAL |
| Operacion | uv.lock reproducible, Podman rootless y Compose; sin nuevo servicio salvo necesidad medida |
| Reversion | Manifiesto y recuperacion documentados por entrega; no usar rollback de esquema que borre historia nueva |

## Estado de ejecucion

- F0: inventario de solo lectura implementado. Prompt 02 valido 217 pruebas sobre
  una base nueva sin contenido de negocio en `telar-fabulas-dev`. La maquina
  anterior se conserva; no se recuperaron sus datos. El ensayo de restauracion
  de datos originales sigue pendiente (R13), no se da por aprobado con una DB vacia.
- F1: implementada segun Prompt 03. Se agrego `apps.core` sin modelos propios;
  no se alteraron jerarquia, texto ni reglas comerciales de conservacion.
  Validacion final: 297 pruebas aprobadas, check limpio, migracion no destructiva
  aplicada, ningun cambio de modelos pendiente y Celery pong en Podman rootless.
  Detalle, archivos y resultados en [08-security-validation.md](08-security-validation.md).
- Las evidencias de F0 y de la auditoria inicial quedan como historico sin
  reescribir sus resultados. El auditor ya no confunde DEBUG con una ruta de
  media publica: comprueba la URL configurada realmente instalada.
- F2: implementada segun Prompt 04, sin SceneVersion ni cambios comerciales.
  Se conserva ManuscriptNode y sus relaciones; se agrega `short_description`.
  La politica BOOK > PART opcional > CHAPTER > SCENE se aplica en todos los
  escritores normales. FRAGMENT y ramas incompatibles quedan de solo lectura.
  Exportadores conservados, encabezados segun profundidad y orden compartido.
  Validacion final: 360 pruebas aprobadas, migracion 0002 aplicada, check limpio,
  sin cambios de esquema pendientes y Celery pong; Podman sigue rootless.
  Las pruebas HTTP contra Gunicorn/Celery verificaron el escenario de movimientos
  y las cuatro descargas; la prueba visual de Chrome quedo bloqueada por la
  herramienta de control del navegador. No se afirma validacion visual completada.
  Resultados, limitaciones e inventario en
  [09-manuscript-hierarchy-validation.md](09-manuscript-hierarchy-validation.md).
- F3: implementada segun Prompt 05. Migraciones 0003/0004 aplicadas sin reiniciar
  PostgreSQL ni borrar volumenes; respaldo restaurado en una base QA aislada.
  Inventario actual: una cuenta preservada y cero escenas previas, por lo que el
  backfill local copio cero filas. El caso con contenido se ensayo con fixtures
  historicos sobre una base de pruebas, sin usar datos privados del propietario.
  SceneVersion es fuente unica de texto de escenas; legacy permanece intacto.
  Definitivas historicas conservadas, borrador activo independiente, numeracion
  serializada y conflicto de revision con recuperacion del texto en formulario.
  Los cuatro formatos y preview usan seleccion materializada por render; aun no
  existe snapshot durable de la solicitud. Validacion: 445 pruebas aprobadas,
  ocho carreras nuevas PostgreSQL, cuatro trabajos Celery/descargas HTTP y prueba
  visual en navegador integrado a 1280x900 y 390x844, incluido conflicto en dos
  pestanas. Chrome no estuvo disponible para automatizacion en esta sesion.
  Datos temporales retirados, cuenta original verificada por huella identica.
  Resultados, archivos y limites en
  [10-scene-version-validation.md](10-scene-version-validation.md).

Validar siempre con conexion explicita:

```powershell
podman --connection telar-fabulas-dev compose ps
podman --connection telar-fabulas-dev compose exec web python manage.py check
podman --connection telar-fabulas-dev compose exec web python manage.py showmigrations
podman --connection telar-fabulas-dev compose exec web python manage.py makemigrations --check --dry-run
podman --connection telar-fabulas-dev compose exec web python manage.py test --keepdb --noinput
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
```

La suite Django usa una base de pruebas separada; confirmar nombre/alias antes
de ejecutarla en un entorno nuevo. Desde Prompt 10 se conserva con --keepdb,
sin borrar bases de datos. Estos comandos no autorizan migrar la base de negocio
ni limpiar volumenes. No aceptar la destruccion de una base previa a ciegas.

## Recomendacion para el siguiente prompt

Prompt 14 sustituye la anterior propuesta de F9 comercial por **papelera de
manuscritos**. Trial/pago manual se pospone a F10: capacidades, cupos, fechas y
transicion de cuentas existentes requieren aprobacion antes de implementar.
Se recomienda consolidar respaldos restaurables y medir capacidad antes de
produccion; no activar pagos ni purgas de fuentes en esta entrega.
F8 ya exporta entidades y relaciones expresamente seleccionadas, sin adjuntos
binarios ni manuscritos dentro del compendio. Los pagos no forman parte de F8.
F6.1-F6.4 y F7 estan implementadas: geografia, residencia principal, organizaciones,
sede principal, afiliaciones, entradas de mundo, referencias privadas y relaciones
interpersonales. El alcance aprobado de F7 no agrega lugares secundarios,
imagenes, grafos, cronologias ni relaciones entre organizaciones.
Resultados en [13-geography-validation.md](13-geography-validation.md) y
[14-organizations-validation.md](14-organizations-validation.md) y
[15-worldbuilding-validation.md](15-worldbuilding-validation.md) y
[16-references-validation.md](16-references-validation.md) y
[17-character-relationships-validation.md](17-character-relationships-validation.md) y
[18-world-exports-validation.md](18-world-exports-validation.md).
F4/F5 estan implementadas: cinco estados, leases renovables,
reintentos limitados, auditoria, notificacion opcional y borrado/caducidad seguros.
Markdown, DOCX y PDF son visibles; HTML/EPUB y preview permanecen compatibles.
Prompt 07 agrega exports.0003 sin borrar datos ni resetear volumenes; el respaldo
se restauro en una base aislada y las huellas originales se conservaron.
Resultados, inventario y limites en [12-export-lifecycle-validation.md](12-export-lifecycle-validation.md).
D03 y las reglas comerciales siguen pendientes. No activar purgas de fuentes
ni cobros como consecuencia de esta entrega.

F1 ya fija FROZEN y PENDING_DELETION como solo lectura para el contenido, con
exportacion/descarga y restauracion explicitamente permitidas al propietario.
No define expiracion de cuenta ni transforma `User.status` en suscripcion.

F2 serializa escritores estructurales por proyecto y revalida el estado despues
de obtener el bloqueo. F3 reutiliza ese orden de locks e incorpora control
optimista de texto. F4 extiende el protocolo para capturar exportaciones durables;
atomic por si solo bajo READ COMMITTED no ofrece esa garantia.
La unicidad de posiciones del manuscrito se garantiza por el protocolo
cooperante, no por una constraint SQL nueva; M4 sigue pendiente de inventario/
saneamiento aprobado. La tabla nueva de geografia si usa UNIQUE inmediato con
NULLS NOT DISTINCT, incluyendo raices; no cambia el esquema del manuscrito.
No se reparan ciclos heredados en segundo plano. F3 conserva el esquema aditivo
en un retorno; una reversa que descartaria historial se rechaza explicitamente.

## Cierre F6.1

Prompt 08 agrega geography.0001 y characters.0003, sin modificar datos previos.
Suite: 624 pruebas aprobadas (84 nuevas), check limpio, sin migraciones pendientes
y Celery pong; cinco servicios activos y una sola instancia de Beat.
Prueba real: siete ubicaciones y dos personajes temporales creados por HTTP;
Ciudad A movida desde el navegador a Provincia B, con ID, textos y residentes
intactos. Permisos y estados verificados; QA retirado y hashes originales iguales.
Respaldo DB/media previo, restauracion aislada comprobada y retirada de la copia.
Proxima entrega no debe introducir cobros ni purgas de fuentes.

## Cierre F6.2

Prompt 09 agrega organizations.0001_initial sin cambiar tablas ni datos previos.
Se comparte solo el algoritmo de orden y recorrido con geografia; los escritores
conservan sus bloqueos, permisos y validaciones propios. Manuscritos no cambia.
La regla inicial de pareja unica propuesta en el documento 02 queda reemplazada
por el alcance aprobado: varios cargos y periodos por personaje/organizacion,
con unicidad exacta que incluye cargo, estado, ingreso y salida narrativos.

Prueba real con Consejo de Luz, Guardia de Cristal, Academia, Rosariel y Fernaud:
creacion HTTP; movimiento y cambio de cargo/estado desde navegador integrado;
sedes bidireccionales, permisos y bloqueos verificados. Datos temporales retirados,
respaldo restaurado en base aislada y huellas originales identicas.
Suite integrada: 721 pruebas aprobadas, 97 nuevas; check limpio, sin migraciones
pendientes y Celery pong. Inventario y limites en el documento 14.

## Cierre F6.3

Prompt 10 agrega worldbuilding.0001_initial, sin alterar tablas ni datos previos.
Un solo modelo plano, tres categorias, contenido de texto libre, busqueda y
paginacion. Orden unico por proyecto/categoria desde cero; no se reutiliza una
abstraccion de arboles. Project se bloquea antes de la fila y se revalida el estado.
Revision original obligatoria para editar, reclasificar, mover y borrar; HTTP 409
conserva los campos enviados. Admin mantiene el bloqueo entre validacion y guardado.

QA real: cinco entradas creadas por HTTP, movimiento y reclasificacion con ID/texto
intactos, conflicto en dos pestanas y dos sesiones HTTP, permisos por estado,
borrado individual y edicion movil. Datos QA retirados; huellas originales iguales.
Respaldo DB/media previo conservado, sin ensayo nuevo de restauracion en esta fase.
No se borro ninguna base ni volumen; incluso la base de pruebas queda conservada.
Suite integrada: 809 pruebas aprobadas, 88 nuevas; resultados en el documento 15. Check limpio,
sin migraciones pendientes, Celery pong y cinco servicios Podman rootless activos.
Papelera, historial completo y politica de adjuntos siguen fuera de este alcance.

## Cierre F6.4

Prompt 11 agrega references.0001_initial sin modificar tablas ni datos previos.
ReferenceMaterial, ReferenceAssociation y una cola tecnica de limpieza durable.
Cinco FK tipadas con CHECK exactamente una y unicidad por referencia/destino.
Cuota tecnica serializada por Project, MIME/tamano verificados, archivos UUID
privados y descargas como adjuntos. Un reemplazo confirma DB antes de limpiar
el archivo anterior; fallo fisico reintentable por Beat. Revision optimista para
textos/reemplazos, tambien en admin, y Character.delete comparte el bloqueo de
proyecto para evitar carreras al crear vinculos.

Suite integrada: 911 pruebas aprobadas (102 nuevas). QA real en navegador a
1280x900 y 390x844: Mapa del Reino con tres vinculos y un archivo, descarga exacta,
reemplazo movil, acceso ajeno denegado, desvinculacion y borrado independientes.
Solo se retiraron datos QA; hashes de originales iguales antes/despues. Backups
DB/media conservados; sin ensayo nuevo de restauracion ni borrado de bases o
volumenes. Cinco servicios rootless activos, check limpio, esquema al dia,
Celery pong y tarea de limpieza consumida correctamente. Unicamente pypdf como
dependencia nueva, con lock uv. Detalles y limites en el documento 16.

## Cierre F7

Prompt 12 agrega characters.0004_characterrelationship, sin modificar tablas ni
datos anteriores. Quince tipos, OTHER personalizado, origen/destino explicitos,
reciproca en una sola fila y cuatro tipos estrictamente direccionales. No se
crean inversas semanticas. UNIQUE exacto y funcional parcial para parejas mutuas;
servicios y admin bloquean Project antes de validar ambas direcciones y escribir.

Relaciones salientes/entrantes/mutuas en las fichas, paginacion 50 por grupo,
metadatos sin descripciones largas, detalle completo y CRUD con permisos centrales.
El borrado individual conserva endpoints y otras relaciones; borrar un personaje
solo elimina sus vinculos. Ultimo guardado completo gana; sin revision optimista,
historial ni papelera en este modelo. No modifica menciones ni exportaciones.

Suite integrada: **1005 pruebas aprobadas**, 94 nuevas incluidas diez carreras
PostgreSQL y una migracion aditiva. Check limpio, esquema al dia, Celery pong y
cinco servicios Podman rootless activos.
QA real: Rosariel/Fernaud/Arkan, cuatro relaciones, reciprocidad/direccion en
ambas fichas, duplicado rechazado, edicion movil, permisos y borrado independiente.
Datos temporales retirados y huellas de originales/media identicas. Respaldo
previo conservado, sin restauracion nueva ni borrado de bases/volumenes.
Inventario, resultados integrados y limites en el documento 17.

## Cierre F8

Prompt 13 agrega exports.0004_world_exports: alcance en ExportJob, conteo de
entidades en ExportSnapshot, modalidad REFERENCE y CHECK de combinaciones
validas. Mantiene las filas, archivos y manifiestos historicos; no agrega tablas.
El esquema 2 de snapshot guarda secciones con identidad, profundidad, orden,
texto y estilo; los lectores de esquema 1 WORK/FINAL permanecen compatibles.
Proyecto y estilo se bloquean durante la captura; el worker solo renderiza el
documento inmutable y conserva el lifecycle, la cola y el storage de F5.

Doce alcances, tres formatos, referencias solo por metadatos y URLs publicas
sin credenciales conocidas. Catalogos estables, subarbol opcional, relaciones
direccionales y mutuas sin inversas inventadas; compendio sin texto literario.
Limites existentes compartidos, consultas por lotes y arboles iterativos.

Suite integrada: **1093 pruebas aprobadas**, 88 nuevas; 613.870 segundos en
PostgreSQL. Check limpio, esquema al dia, Celery pong y cinco servicios rootless.
Ocho solicitudes HTTP antes de editar fuentes/estilo y borrar una entrada;
archivos de tres formatos conservaron la captura. Novena solicitud desde movil,
descarga sin navegar fuera del detalle. Aislamiento, caducidad y POST de borrado
verificados. PDF de cinco paginas inspeccionado y DOCX de cinco paginas en Word.
Datos temporales retirados; huellas originales y media identicas. Respaldo previo
conservado, sin ensayo nuevo de restauracion ni borrado de bases/volumenes.
Resultados, inventario y limites pendientes en el documento 18.

## Cierre F9

Prompt 14 agrega manuscripts.0005_manuscript_trash: deleted_at/deleted_by e
indice, sin cambiar IDs, contenido, SceneVersion ni datos originales. No requiere
deletion_batch_id: solo el nodo directo recibe sello; los descendientes heredan
ocultamiento. Restaurar ancestro conserva eliminaciones independientes previas.
Rescate aislado bajo padre valido del mismo proyecto, movimientos reutilizados,
transaccion y lock Project -> nodo; orden visible normalizado. Admin sin borrado
fisico individual/masivo y contenido oculto sin edicion ni nuevas versiones.

Visibilidad efectiva por lotes para arbol, selectores, notas, menciones,
referencias, WORK/FINAL y preview; snapshots historicos intactos. No se crean
tareas de purga ni se extiende la papelera a otras entidades. FROZEN/PENDING solo
consultan; restaurar contenido requiere EDIT, no cambia el estado del proyecto.

Suite integrada: **1170 pruebas aprobadas**, 77 nuevas; 564.355 segundos en
PostgreSQL. Check limpio, esquema al dia y Celery pong en Podman rootless.
QA HTTP/navegador escritorio-movil: eliminar A, eliminar capitulo, restaurar
capitulo recupera B sin A; recuperar A conserva seis versiones completas, sus
borradores y definitivas. Seis jobs reales; WORK/FINAL antes y despues identicos.
Solo QA retirado; huellas originales de 22 modelos y media iguales. Backups
previos conservados, sin nuevo ensayo de restauracion ni borrado de bases/volumenes.
Inventario, comandos, evidencia y riesgos en el documento 19. Se recomienda
consolidar respaldos/capacidad antes de produccion; cobros siguen pospuestos.
