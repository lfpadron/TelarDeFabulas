# Roadmap de refactorizacion v01

Fecha: 2026-11-08. Actualizado tras Prompt 08 (F6.1). Cada fase posterior requiere
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
| F6.2+: mundo y referencias | Organizations/Worldbuilding/References, relaciones tipadas, limites y descarga privada | F6.1; D07 | Varios bloques por categoria, adjuntos privados y limites medidos | Aislamiento por proyecto, MIME/tamano/cuota, FK de referencias y limpieza de copia |
| F7: relaciones de personajes | Afiliaciones, lugares, amistad/interes romantico y varias imagenes por referencia | F6; D09 | Fichas/roles/imagenes anteriores conservados; relaciones no duplican conceptos existentes | Simetria/direccion, propietario, duplicados, copias de imagen con hash y porcentaje de ficha |
| F8: exportar entidades | Reutilizar selector para geografia, organizaciones, entradas, personajes y referencias | F4/F6/F7; D06-D07 | Alcance de seccion/entidad exacto, archivos privados incluidos solo segun seleccion/politica | Matriz entidad/formato, enlaces/adjuntos, aislamiento, orden y grandes volumenes |
| F9: trial y pago manual | Plan/Subscription/Payment, capacidades calculadas, transicion de cuentas heredadas y cupos configurables | F1/F5; D10-D14/D18-D19 | Trial con un proyecto y todas las funciones; vencido solo lectura/export; pagos manuales auditables | Reloj controlado, cupos concurrentes, cambio de plan y permisos en todas las apps |
| F10: Stripe y retencion de cuenta | PaymentEvent, webhooks idempotentes, avisos por periodo, conservacion anual y purga auditable | F9; D11-D14/D17 | Pago confirmado mantiene acceso; no doble credito; renovacion cancela purga; avisos sin solapamiento | Firma, repeticion/orden de eventos, pago vs purga, ano bisiesto y ensayo de eliminacion en copia |
| F11: capacidad y despliegue | Paginacion/carga progresiva, indices medidos, recursos de workers, observabilidad, TLS/static y restauracion | Medicion desde F0; integrar en cada fase | Presupuesto de latencia/RSS fijado y cumplido; check --deploy objetivo; operacion documentada | Datos representativos, EXPLAIN, carga web/export, caida de servicios y restauracion |
| F12: retirada de compatibilidad | Evaluar retiro de columnas legacy/FRAGMENT y limpieza de copias | Todas las fases afectadas estables; aprobacion independiente | Sin lectores/escritores legacy, sin casos ambiguos ni datos sin destino; backup recuperable | Rehearsal completo forward/rollback, comprobacion de texto/relaciones y corte ensayado |

F6-F7 y F9 pueden organizarse de forma independiente despues de sus dependencias,
pero no conviene mezclar jerarquia/versionado, billing y purga en una sola entrega.
F11 es trabajo continuo: las optimizaciones necesarias por memoria no esperan al
final si F0 revela manuscritos grandes. F12 es opcional y no habilita borrar datos
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
podman --connection telar-fabulas-dev compose exec web python manage.py test
podman --connection telar-fabulas-dev compose exec worker celery -A config inspect ping
```

La suite Django usa una base de pruebas separada; confirmar nombre/alias antes
de ejecutarla en un entorno nuevo. Si existe una base de pruebas anterior, no
aceptar su destruccion a ciegas. Estos comandos no autorizan migrar la base de
negocio ni limpiar volumenes.

## Recomendacion para el siguiente prompt

Continuar con **F6.2: organizaciones**, mediante un alcance acotado y permisos
por proyecto. F6.1 esta implementada: geografia flexible y residencia principal;
sin mapas, coordenadas, relaciones multiples ni nuevas exportaciones.
Resultados en [13-geography-validation.md](13-geography-validation.md).
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
