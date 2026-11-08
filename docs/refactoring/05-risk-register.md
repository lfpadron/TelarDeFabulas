# Registro de riesgos v01

Fecha: 2026-11-06. Probabilidad cualitativa estimada por codigo/flujo; no es una
medicion de incidentes. Impacto critico significa posible perdida de manuscrito,
historia o privacidad; alto, incumplimiento importante o indisponibilidad;
medio, fallo recuperable de flujo. P1 debe cerrarse antes del corte afectado;
P2 antes de exponer la funcionalidad comercial. La tabla conserva la evidencia
historica de la auditoria (sus numeros de linea pueden haber cambiado). El estado
actual tras Prompt 03 se detalla al final; no todos los riesgos estan cerrados.

## Riesgos existentes y de transicion

| ID / prioridad | Riesgo y evidencia | Probabilidad | Impacto | Mitigacion propuesta | Validacion de cierre |
| --- | --- | --- | --- | --- | --- |
| R01 / P1 | Perder texto fuera de SCENE o descartar FRAGMENT al cambiar modelo. `manuscripts/models.py:58` guarda content en todos los tipos; fixtures en `exports/tests.py:51` incluyen texto de libro/capitulo | Alta si se migra solo SCENE | Critico | Inventario por tipo, mantener originales, mapa de transformacion y copia exacta; no borrar FRAGMENT | Igualdad de PK/hash/longitud, vacios y Unicode; comparar todos los formatos y orden |
| R02 / P1 | Descargar manuscritos sin pasar por autorizacion usando media directa en DEBUG. `config/urls.py:24`; claves de export predecibles en `exports/models.py:11` y `tasks.py:25` | Alta en un entorno DEBUG accesible | Critico | Storage privado y descargas autenticadas; cubrir tambien imagenes y copias de migracion | Cliente anonimo/ajeno no accede por URL directa; propietario descarga adjunto |
| R03 / P1 | Borrado fisico permitido aunque proyecto este pendiente/eliminado: `manuscripts/views.py:173`, `characters/views.py:173`, `notes/views.py:141`. FROZEN tambien admite edicion; `User.status` no es politica de acceso | Alta | Critico | Politica compartida de lectura/escritura/borrado/export en servicios y admin; distinguir vencimiento de desactivacion | Matriz completa de POST directos por status de cuenta/proyecto, incluido usuario vencido |
| R04 / P1 | Guardado concurrente sobrescribe texto y/o parent antiguo. ModelForm guarda instancia sin revision, `manuscripts/forms.py:66` | Alta con varias pestanas | Critico | Revision esperada, actualizacion condicional, preservar texto del cliente en conflicto; separar texto/estructura | Dos clientes: segundo recibe conflicto y ningun contenido se pierde |
| R05 / P1 | Jerarquia inconsistente segun entrada: `models.py:100` no valida tipos; `services.py:54` valida solo movimientos y acepta raiz libre | Alta | Alto | Validador unico en creacion/edicion/movimiento/admin y migracion de excepciones | Todas las combinaciones padre-hijo; cambio de tipo con hijos; ciclo y padre ajeno |
| R06 / P1 | Orden duplicado/carrera o deadlock. `next_position` usa MAX+1; `move_node_up/down` normaliza fuera de atomic. `move_node` SI bloquea proyecto por join, pero otros escritores no siguen ese protocolo | Media | Alto | Bloquear proyecto primero en todos los cambios estructurales, orden fijo de locks, UNIQUE de posiciones despues de saneamiento | TransactionTestCase y conexiones separadas: mover/crear/editar simultaneos, sin duplicados ni perdida |
| R07 / P1 | Mismo proyecto y duplicados de menciones se validan solo en Python (`characters/models.py:230`); bulk/update o carreras pueden saltarlos | Media | Alto | UNIQUE real de triple; servicios para cambios de proyecto y asociaciones; decidir triggers acotados para reglas cruzadas | Intentos simultaneos y via ORM/admin; inventario de FK cruzadas y duplicados antes de constraint |
| R08 / P1 | Root eliminado cambia alcance de export en cola a todo el manuscrito. `ExportJob.root_node` SET_NULL, `exports/services.py:69` | Media | Alto | Scope explicito y snapshot/manifest; no usar NULL para significar a la vez raiz borrada y proyecto completo | Solicitar subarbol, eliminar/archivar raiz antes del worker: no exporta contenido adicional |
| R09 / P1 | Tarea duplicada o caida deja archivos/estados inconsistentes. `exports/tasks.py:15` empieza sin reclamar; excepciones antes del try y errores de Redis en `views.py:79` sin reconciliar | Media | Alto | Compare-and-set, token/lease, temporales exclusivos, reconciliador y errores observables | Doble entrega, fallo de broker, kill del worker y reintento no duplican archivo ni notificacion |
| R10 / P1 | Limpieza futura compite con generacion/descarga y borra un resultado nuevo | Media al anadir Beat | Critico | Solo terminales, token de intento, claves no reutilizadas, tombstone durable y borrado idempotente despues del commit | Barreras de concurrencia worker/cleanup/download; archivos originales intactos |
| R11 / P1 | Exportacion cambia segun ediciones de texto/estilo entre solicitud y ejecucion; no hay snapshot (`exports/services.py:40`, `docx.py:109`) | Alta en trabajo activo | Alto | Documento congelado con version/revision/orden/estilo; momento de captura explicito | Editar y mover durante export; resultado coherente con un unico snapshot |
| R12 / P1 | Borrar escena/personaje pierde menciones y desprende notas; borrar proyecto/usuario puede encontrar PROTECT o grandes cascadas. FileField no tiene limpieza propia | Media | Critico | Archivado y purga dedicada auditada; orden de dependencias, inventario de blobs y recuperacion | Borrado/restore de copia aislada conserva relaciones esperadas; no quedan archivos sin gestion |
| R13 / P1 | Respaldo de directorio no incluye necesariamente postgres_data/media_data. No hay rutina de backup/restore en repo | No determinada | Critico | Verificar respaldo de DB+media y ensayo aislado, RPO/RTO y politica de backups | Restauracion comprobada con hashes y referencias, sin tocar base original |
| R14 / P1 | Cambiar nombres de estados con workers viejos o activar retencion retroactiva elimina/abandona jobs | Media | Alto | Despliegue compatible o drenado; mapa de estados, gracia historica y limpieza dry-run | Jobs de todos los estados/formatos siguen legibles; ningun archivo borrado durante migracion |
| R15 / P1 | Texto/poblacion real desconocidos; historial aplicado y suite actual sin verificar por Podman detenido | Confirmada como limitacion | Alto | Repetir validaciones y auditoria de datos antes de aprobar migraciones | showmigrations y suite en PostgreSQL; informe cuantitativo firmado por revision |
| R16 / P2 | Memoria/tiempo excesivo: arbol y selector cargan todo con content, incluso preview y subarbol; renderer en bytes, sin cuotas ni limites de tarea | Alta con manuscritos extensos | Alto | Carga progresiva, paginacion, limites tempranos, temporales y presupuesto Celery | Prueba con volumen representativo, RSS/latencia, numero de consultas y cancelacion controlada |
| R17 / P2 | Un ciclo heredado puede hacer recursiva una exportacion sin fin; nodos sin raiz alcanzable se omiten (`services.py:53`, `views.py:37`) | Baja con flujos normales; desconocida en DB | Alto | Detectar ciclos y alcanzabilidad antes de corte; recorrido iterativo con seen/limites | Fixtures corruptos controlados generan diagnostico, sin perdida silenciosa |
| R18 / P2 | Imagen solo validada por extension, sin limite propio (`characters/models.py:46`); futuros links/adjuntos pueden ampliar superficie de lectura de archivos/red | Media | Alto | Bytes/MIME real, tamano/cuota, storage privado; fetcher restringido para renderizadores al admitir recursos | Archivo falso/grande, URL no permitida y path traversal rechazados; no solicitudes externas imprevistas |
| R19 / P2 | Produccion usa valores inseguros por defecto; cinco avisos de check --deploy; falta servicio de estaticos y readiness de web | Alta si se despliega sin configuracion | Alto | Fail-fast de secretos, TLS/cookies, estaticos privados/publicos separados, readiness y limites | check --deploy con config objetivo, inicio limpio y acceso admin/static |
| R20 / P2 | Borrar estilo usado genera ProtectedError no manejado, `styles/views.py:168`; opciones de estilo editables cambian exportaciones pendientes | Media | Medio | Mensaje/archivado de estilo y snapshot en job | Borrar estilo referenciado no devuelve 500 ni altera exports terminados |
| R21 / P2 | `CharacterForm.save` borra y recrea roles sin atomic (`characters/forms.py:96`), puede quedar conjunto parcial ante error | Media | Medio | Guardado transaccional de ficha y relaciones con cambios minimos | Fallo inyectado en insercion mantiene roles originales |
| R22 / P2 | Email con mayusculas puede duplicar identidad comercial; timezone libre y preferred_locale no aplicado; no hay password validators explicitos | Media | Alto para identidad; medio para perfil | Decidir normalizacion antes de UNIQUE funcional, validar zonas, activar preferencias y politica de passwords | Colisiones preexistentes reportadas sin fusionar cuentas; login/idioma/zona/pruebas de password |

## Riesgos de funcionalidades propuestas

| ID / prioridad | Riesgo | Probabilidad | Impacto | Mitigacion propuesta | Validacion de cierre |
| --- | --- | --- | --- | --- | --- |
| R23 / P1 | Convertir FINISHED/is_publishable a FINAL inventa aprobacion o fecha; editar FINAL destruye referencia editorial | Alta sin politica | Critico | Mapeo aprobado, baseline intacta, final historica inmutable y bandera vigente independiente | Casos de estados contradictorios/vacios; dos FINAL historicas y solo una vigente |
| R24 / P1 | FREE/PREMIUM hardcoded contradice trial con todas las funciones y limita mal usuarios heredados | Alta al activar cobros | Alto | Servicio calculado de capacidades, cupos bajo lock y migracion comercial explicita | Trial usa estilos; vencido lee/exporta y no escribe; dos creaciones respetan cupo |
| R25 / P1 | Eventos Stripe duplicados/desordenados acreditan dos veces o revierten renovacion; pago manual no auditable | Media | Alto | PaymentEvent unico, firma, reconciliacion y confirmacion de actor/periodo | Repeticion, orden inverso, reembolso y pago manual generan estado correcto sin doble credito |
| R26 / P1 | Mezclar borrado solicitado a 90 dias con ano por impago, o purgar tras pago reciente, destruye trabajo | Alta sin separar causas | Critico | Retencion por episodio impago, revalidacion final, avisos y cancelacion de purga al renovar | Reloj simulado, ano bisiesto, renovacion concurrente y ejecucion repetida |
| R27 / P2 | Avisos 30/14/7 se solapan en ciclos mensuales o se repiten tras reiniciar Beat | Alta sin deduplicacion | Medio | Politica por periodo, clave unica y agrupacion de catch-up; no adjuntar manuscrito | Ciclos cortos, febrero, caida de scheduler y cambio de plan sin correos repetidos |
| R28 / P1 | Rollback despues de editar nuevas versiones restaura content viejo o borra historia nueva | Alta con reversa ingenua | Critico | Rollback de aplicacion con lector compatible, preservar tablas/columnas y conciliar escrituras posteriores | Ensayo de fallo a mitad de backfill y retorno despues de crear version nueva |

Las propuestas se desarrollan en [02-target-architecture.md](02-target-architecture.md)
y [03-data-migration-plan.md](03-data-migration-plan.md). Las decisiones que
condicionan su cierre estan en [06-decisions-required.md](06-decisions-required.md).
Los hallazgos estaticos no son incidentes confirmados. Las pruebas de esta fase
validan escenarios concretos, no certifican un despliegue de produccion completo.

## Actualizacion tras Prompt 03: F1

| Riesgo | Estado actual | Evidencia y limite |
| --- | --- | --- |
| R02 | Cerrado para las rutas actuales de Django/Compose | Sin `static(MEDIA_URL)`, storage sin URL publica, rutas autenticadas por ID, propietario y estado; pruebas anonimo/ajeno/DEBUG/traversal/symlink/404 y headers privados. Un proxy futuro no debe publicar media ni copias |
| R03 | Cerrado para estados de proyecto; cuenta pendiente | Core aplica la matriz a todas las vistas, movimientos, menciones y admin. FROZEN/PENDING no escriben ni borran; DELETED 404; RESTORE explicito. `is_active` es requisito. No se invento una politica de vencimiento para `User.status` |
| R06 | Mitigado parcialmente | POST narrativo bloquea proyecto dentro de atomic; subir/bajar validan antes de normalizar. F2 debe cubrir el resto de escritores estructurales, orden uniforme de locks y concurrencia PostgreSQL real |
| R12 | Mitigado parcialmente | Admin no borra usuarios ni proyectos fisicamente; exportaciones solo lectura. Siguen pendientes archivado/purga dedicada, blobs huerfanos y recuperacion |
| R15 | Cerrado solo para la base de desarrollo nueva | F0 inventario y 217 pruebas previas; F1 suite ampliada. No se recuperaron ni se auditaron los datos de la maquina anterior; no se afirma que estuvieran vacios |
| R18 | Mitigado para imagenes y renderizadores actuales | Pillow verifica/decodifica JPEG/PNG/WebP, maximo configurable 5 MB, UUID, extension real, rechazo SVG/GIF nuevo/corrupto/bombas. Fetcher PDF niega red/disco y CSS se restringe. Faltan cuotas acumuladas y presupuesto de recursos |
| R20 | Corregido el error de borrado; snapshot pendiente | ProtectedError produce mensaje y conserva estilo/export; estilos ajenos 404. Editar un estilo puede seguir afectando jobs futuros hasta F4 |
| R21 | Cerrado para ficha/roles en DB | `CharacterForm.save` transaccional y prueba de fallo inyectado conserva las filas originales; el filesystem no participa en rollback, gestion de huerfanos pendiente |
| R13 / R19 | Abiertos | Falta restauracion comprobada DB+media, configuracion objetivo de produccion, TLS, estaticos, readiness y limites. No se borraron volumenes |

### Controles adicionales verificados

- ModelAdmin filtra contenidos por propietario y no tiene bypass de superusuario.
  FK de formularios acotadas a proyectos activos propios, bulk delete revalida,
  imagen/archivo no generan links directos. El admin de cuentas sigue siendo una
  herramienta privilegiada para gestionar identidades, no una API de contenido.
- HTML/EPUB escapan texto; CSS usa valores restringidos; preview conserva sandbox
  y limites. PDF no obtiene recursos externos. Errores de worker no muestran
  excepciones con rutas/secretos al usuario. El ciclo de reintento y logs
  operativos completos siguen en R09/F5.
- Relaciones heredadas corruptas hacia otro proyecto/estilo se excluyen de
  consultas web/admin, sin corregir ni borrar registros. El auditor sigue siendo
  necesario; constraints y saneamiento se mantienen en R05/R07/F2.
- Django actualizado dentro de LTS a 5.2.19 mediante uv; Pillow 12.2.0 queda como
  dependencia directa. No se agregaron servicios ni dependencias de Podman.

Validacion final: 297 pruebas aprobadas en PostgreSQL/Podman rootless, check sin
problemas, migraciones al dia y Celery pong. Los resultados y el alcance estan en
[08-security-validation.md](08-security-validation.md). R01, R04-R05, R07-R11,
R14, R16-R17, R22-R28 no se cierran por esta entrega. Las operaciones ORM
`update`/`bulk_*`, shell y acceso directo a PostgreSQL requieren confianza y no
constituyen una API autorizada; evitar exponerlos desde entradas futuras.

## Actualizacion tras Prompt 07: F5

| Riesgo | Estado actual | Evidencia y limite |
| --- | --- | --- |
| R08 / R11 / R20 | Mitigados para exportaciones con snapshot | F4 congela contenido, seleccion y estilo; F5 reintenta sin recapturar. Historicos sin snapshot conservan su archivo hasta caducar, no se regeneran |
| R09 | Mitigado con lease y fencing | Claim PostgreSQL atomico, heartbeat renovable, maximo de intentos, backoff, recovery Beat y auditoria. Dos workers no reclaman el mismo intento; el antiguo no publica. Si un proceso queda vivo tras perder lease, puede terminar calculos inutiles, pero no escribir ni publicar |
| R10 | Mitigado en storage local compartido | Tombstone bloquea nuevas descargas, lock compartido de sesion durante streaming y exclusivo no bloqueante para cleanup. DELETED solo despues de borrar archivos y snapshot. Fallo fisico queda pendiente y se reintenta. No compatible sin adaptar con PgBouncer transaction pooling o S3 |
| R13 | Ensayo local cerrado; operacion de produccion pendiente | Respaldo DB+media antes de la migracion; pg_restore aislado y hashes de fuentes comparados. Faltan calendario, cifrado, ubicacion externa, retencion y ensayo recurrente |
| R14 | Mitigado para este despliegue drenado | web/worker/Beat detenidos ordenadamente antes de migrar, PENDING->REQUESTED y DONE->READY, gracia completa a historicos, sin correo retroactivo ni borrado durante migracion |
| R16 / R19 | Abiertos para produccion | Faltan medidas de memoria/latencia con novelas grandes, time limits, cuotas, TLS y hardening. Cada descarga consume una conexion PostgreSQL adicional; un renderer bloqueado que mantiene heartbeat requiere intervencion operacional |
| R29 / P2 | Entrega de correo best-effort | Outbox unico por job/evento/intento, claim de envio, Message-ID estable y hasta ocho intentos. SMTP y DB no son atomicos: caida tras aceptar SMTP puede duplicar. Error de correo nunca cambia READY; agotamiento requiere revision administrativa |
| R30 / P2 | Filesystem y PostgreSQL no son una sola transaccion | Rutas por intento, fsync+rename atomico y clave durable permiten recuperar un parcial o archivo publicado antes del commit. Borrado fisico previo al commit se puede repetir; no hay promesa de recuperacion frente a perdida de disco/backup |

Evidencia y limites en [12-export-lifecycle-validation.md](12-export-lifecycle-validation.md).
Se mantiene una sola instancia de Beat. La disponibilidad del scheduler/broker y
los registros de limpieza/correo requieren monitorizacion antes de produccion.
Los backups y copias que un usuario ya descargo no se purgan al borrar el archivo
activo: deben tener su propia politica. F5 no borra fuentes ni elimina cuentas.

## Actualizacion tras Prompt 08: F6.1

| Riesgo | Estado actual | Evidencia y limite |
| --- | --- | --- |
| R03 / R06 / R07 | Mitigados en las entradas geograficas | Propietario y estado centralizados; bloqueo de Project antes de crear/mover/borrar o guardar residencia; nueve carreras PostgreSQL. UNIQUE inmediato de posiciones con NULLS NOT DISTINCT y checks locales. Ciclos y pertenencia cruzada se validan en servicios, no mediante triggers |
| R04 | Movimiento protegido de formularios antiguos | Editar descripciones no expone padre/posicion; save conserva movimientos concurrentes o rechaza conflicto estructural. No hay revision optimista del texto geografico: dos ediciones simultaneas de descripcion siguen siendo ultimo guardado gana |
| R12 | Borrado geografico restringido | PROTECT para hijos, servicio rechaza residentes, confirmacion/POST/CSRF; bulk delete desactivado en admin. Character.residence usa SET_NULL como defensa referencial, nunca CASCADE. Una futura purga de proyectos debe resolver el arbol explicitamente |
| R13 | Respaldo de esta fase ensayado | p08_pre_geography.dump restaurado en base aislada, hashes de datos originales iguales; copia temporal retirada. Sigue pendiente la operacion de backups externa/recurrente de produccion |
| R16 / R17 | Consultas acotadas, volumen web pendiente | Arbol y ruta iterativos, metadatos sin desarrollo detallado, una consulta por selector; prueba de 1100 niveles. Detalles paginan hijos/habitantes a 50. Arbol y selectores aun materializan todo el proyecto; falta carga progresiva y presupuesto de latencia/DOM para grandes volumenes |
| R31 / P2 | Historial de residencia no modelado | Solo FK principal opcional por personaje. Cambiarla no deja historial territorial; una fase posterior puede agregar periodos sin recrear personajes/ubicaciones |

624 pruebas aprobadas, aislamiento incluido admin, QA HTTP y navegador integrado
en escritorio/movil. No se modificaron fuentes originales, exportadores ni
reglas comerciales. Evidencia en [13-geography-validation.md](13-geography-validation.md).
`QuerySet.update`, `bulk_*`, `QuerySet.delete` y SQL directo siguen siendo APIs
privilegiadas: pueden saltar validaciones del grafo y el rechazo de borrado por
habitantes. No exponerlas como escritores de negocio; las entradas web/admin
usan los servicios/modelos protegidos. La restriccion SQL de orden no valida
proyecto del padre ni ciclos indirectos. No se afirma proteccion contra SQL hostil.
