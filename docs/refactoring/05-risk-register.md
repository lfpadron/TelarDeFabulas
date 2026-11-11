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

## Actualizacion tras Prompt 09: F6.2

| Riesgo | Estado actual | Evidencia y limite |
| --- | --- | --- |
| R03 / R06 / R07 | Mitigados para organizaciones y afiliaciones | Politica central tambien en admin; Project bloqueado antes de escrituras; siete carreras PostgreSQL; UNIQUE de posiciones incluidas raices y UNIQUE de afiliacion con periodo. SQL directo sigue pudiendo crear ciclos o relaciones cruzadas |
| R04 | Movimiento conserva identidad y estructura concurrente | Edicion de texto no expone padre/posicion; save conserva un movimiento concurrente y rechaza conflictos estructurales. No hay revision optimista en descripciones ni afiliaciones: ultimo guardado completo gana |
| R12 | Borrado restringido por hijos, miembros y sedes | Organization.parent y Membership.organization PROTECT; servicio bloquea ubicacion usada como sede, SET_NULL como fallback. Borrar afiliacion conserva endpoints; borrar un personaje elimina sus afiliaciones por CASCADE. No se implementa purga de proyectos; debe resolver relaciones explicitamente |
| R13 | Respaldo local nuevamente ensayado | p09_pre_organizations.dump restaurado en base aislada y comparado por SHA-256; originales identicos tras QA. DB temporal y entidades QA retiradas. Cifrado, copias externas y retencion operacional siguen pendientes |
| R16 / R17 | Consultas acotadas, carga masiva pendiente | Arbol/ruta iterativos sin N+1 ni descripcion larga; 1100 niveles; integrantes y sedes paginados a 50. Arbol y opciones de formularios materializan el proyecto completo; falta medicion representativa de latencia/DOM |
| R32 / P2 | Ambiguedad de afiliacion repetida | La identidad duplicada incluye personaje, organizacion, cargo, estado y ambos textos de periodo. Periodos diferentes son validos; los textos no ordenan ni verifican calendarios ficticios. No hay historial automatico de ediciones ni eventos cronologicos |
| R33 / P2 | Dependencia compartida de arboles | Helpers pequenos de recorrido, orden y preservacion de estructura; 84 pruebas de geografia conservadas y regresion integrada. No hay modelo abstracto nuevo ni cambios de jerarquia literaria |

No se agregan alianzas, sedes secundarias, exportaciones de organizaciones, IA,
pagos ni tareas de purga. Un backup revertido perderia organizaciones creadas
despues: preservar las tablas y preferir correccion hacia delante; una reversa
de organizations.0001 elimina estas tablas y no es un rollback de datos seguro.
Evidencia, prueba manual e inventario en
[14-organizations-validation.md](14-organizations-validation.md).

## Actualizacion tras Prompt 10: F6.3

| Riesgo | Estado actual | Evidencia y limite |
| --- | --- | --- |
| R04 | Mitigado para WorldbuildingEntry, tambien en admin | Revision esperada y bloqueo Project -> entrada dentro de atomic; HTTP 409 conserva texto enviado. Ocho carreras con conexiones PostgreSQL separadas, incluidas admin/admin y admin/servicio. No implica historial completo ni cierre del riesgo en geografia, organizaciones u otras fichas |
| R03 / R06 / R07 | Mitigados para las entradas nuevas | Politica central owner/estado, 404 ajeno, sin traslado entre proyectos; UNIQUE(project,category,position), checks locales y orden normalizado. Insercion/movimiento/cambio de categoria/borrado serializados y prueba de rollback |
| R12 / R34 (nuevo P2) | Borrado individual definitivo, recuperacion pendiente | Confirmacion POST/CSRF/revision; no borra otras entidades. Admin no ofrece borrado; se usa la confirmacion del autor. No hay papelera ni historial: recuperar una entrada requiere respaldo hasta definir politica general |
| R13 | Respaldo previo e integridad comprobados | p10_pre_worldbuilding.dump, media y hashes originales; igualdad antes/despues de migrate y tras limpiar QA. No se ensaya una restauracion nueva en F6.3. Ninguna base/volumen eliminados; test_telar_fabulas conservada con --keepdb. Backups externos/cifrados y ensayo recurrente pendientes |
| R16 | Listado acotado; medicion de escala pendiente | 50 filas por categoria, seis consultas como maximo para los tres selectores, content diferido, sin N+1. Movimientos leen metadatos del grupo y actualizan solo filas alteradas, en lotes. Busqueda icontains sin indice de texto dedicado; falta presupuesto de latencia y memoria con proyectos grandes |
| R35 / P2 | Conflictos conservadores y recuperacion manual | Renumerar tambien incrementa revision de las filas cuya posicion cambia; un formulario puede quedar obsoleto por reordenamiento. Se preservan sus campos y se abre la revision actual aparte; no hay fusion automatica ni autoguardado durable del texto rechazado |

`QuerySet.update`, `bulk_*`, `QuerySet.delete` y SQL directo siguen siendo APIs
privilegiadas: pueden saltar el control de revision, permisos y normalizacion.
Los escritores web/admin/model.save usan los servicios protegidos. No hay defensa
contra SQL hostil ni nuevas tareas de purga. El lock de proyecto serializa tambien
ediciones en entradas diferentes, una eleccion conservadora que requiere medir
contencion antes de ampliar la concurrencia a gran escala.

El respaldo pre-migracion no contiene entradas creadas posteriormente. No revertir
worldbuilding a zero ni restaurar una copia antigua como rollback rutinario;
preservar el esquema y corregir hacia delante. Sin referencias, adjuntos, cobros,
IA, cronologia ni exportaciones nuevas. Evidencia e inventario en
[15-worldbuilding-validation.md](15-worldbuilding-validation.md).

## Actualizacion tras Prompt 11: F6.4

| Riesgo | Estado actual | Evidencia y limite |
| --- | --- | --- |
| R03 / R06 / R07 | Mitigados en referencias y asociaciones | Propietario/estado centralizados; cinco FK explicitas, CHECK exactamente una y UNIQUE parciales; proyecto identico validado bajo lock, incluidas entradas admin. SQL directo/bulk pueden saltar pertenencia y permisos; no exponerlos como API |
| R04 | Reemplazos y texto protegidos por revision | Project -> referencia, revision original requerida, 409 conserva campos; carrera de dos reemplazos y admin/servicio. No hay historial/fusion ni recuperacion del upload rechazado; debe seleccionarse de nuevo |
| R10 / R30 | Limpieza durable tras commit | UUID nuevo + fsync, commit DB, cola de borrado del anterior con reintento. Fallos de escritura conservan original; fallos fisicos quedan contabilizados. Filesystem y DB no son atomicos: caida o rollback externo puede dejar un UUID huerfano, reconciliable explicitamente tras 24 h; la cuota no incluye huerfanos aun no inventariados |
| R12 / R34 | Borrado definitivo acotado | Confirmacion POST/CSRF/revision; desvincular o borrar entidad conserva referencia/archivo. Character.delete bloquea Project antes del collector. No hay papelera ni purga general; backups/copias descargadas requieren su propia politica |
| R13 | Respaldo previo y huellas verificados | Dump PostgreSQL/media conservados, SHA-256 de todas las columnas originales y media iguales antes/despues. No se ensaya nueva restauracion en F6.4; base de pruebas conservada con --keepdb. Continuan pendientes backups externos/cifrados y ensayos recurrentes |
| R16 / R17 | Listados y cuota acotados; carga real pendiente | Paginacion 50, textos extensos diferidos, sin lectura de archivos ni N+1; cuota serializada frente a subidas concurrentes. Selectores de formularios aun materializan opciones del proyecto; bloqueo incluye validacion/I/O. Medir memoria/latencia/contencion con miles de entidades y uploads grandes |
| R36 / P2 | Validacion no equivale a antivirus | Pillow, pypdf estricto basico, ZIP/OOXML acotado, UTF-8; sin ejecucion/render/OCR ni fetch externo. Ataques complejos a parsers y contenido peligroso al abrir en clientes externos siguen siendo riesgo. Evaluar aislamiento/limites CPU, escaneo y actualizacion de dependencias antes de aceptar cargas publicas masivas |
| R37 / P2 | Cuota tecnica y capacidad fisica distintas | 10/20/500 MiB por defecto, cuota de referencias activas + limpieza pendiente. Reemplazo exige espacio para ambas versiones. No cubre otras apps, backups ni espacio libre real del disco; ENOSPC se controla, pero requiere monitorizar capacidad y cola de limpieza |

911 pruebas aprobadas; 102 nuevas con diez carreras PostgreSQL y migracion aditiva.
QA real valida permisos, tres asociaciones/un archivo, descarga adjunta, reemplazo,
desvinculacion y borrado sin tocar entidades. Beat programa limpieza cada minuto;
registros fallidos usan backoff hasta un dia y requieren alerta operacional si
persisten. --orphans es manual, solo UUID de referencias de mas de 24 h; no es una
papelera ni recupera archivos. Solo el servicio debe escribir en PRIVATE_MEDIA_ROOT;
se rechazan symlinks, pero no se promete defensa frente a otro proceso local hostil
con acceso de escritura al mismo volumen.

No restaurar el dump previo ni revertir references a zero para resolver fallos
tras crear materiales; conservar esquema/datos y preferir correccion hacia delante.
No se implementan bibliografia automatica, OCR, IA, exportacion de referencias,
almacenamiento externo ni planes comerciales. Evidencia e inventario en
[16-references-validation.md](16-references-validation.md).

## Actualizacion tras Prompt 12: F7

| Riesgo | Estado actual | Evidencia y limite |
| --- | --- | --- |
| R03 / R06 / R07 | Mitigados para relaciones interpersonales | Propietario/estado centralizados, extremos del mismo proyecto, sin autorrelaciones; UNIQUE exacto, UNIQUE funcional parcial para mutuas y checks SQL. Project bloqueado en servicios/model.save/admin antes de validar duplicados y escribir. Diez carreras PostgreSQL |
| R04 | Integridad serializada; texto sin revision optimista | No se crean duplicados por dos POST simultaneos. Un guardado parcial conserva los demas campos actuales; dos formularios completos siguen ultimo guardado gana. No hay aviso 409, historial ni fusion de descripciones en este modelo |
| R12 / R34 | Borrado definitivo acotado | Confirmacion POST/CSRF, propiedad/estado revalidados; borrar relacion conserva personajes/otros vinculos. Character.delete bloquea Project antes del collector y CASCADE retira solo sus relaciones. Sin papelera ni purga general; restaurar requiere respaldo |
| R13 | Respaldo previo y huellas conservados | p12_pre_relationships.dump, media y SHA-256 originales iguales tras migrate y QA. No se ensayo restauracion nueva; base de pruebas conservada con --keepdb. Operacion externa/cifrada/recurrente pendiente |
| R16 / R17 | Paginacion y consultas acotadas | 50 relaciones por grupo, select_related y solo metadatos; selector en una consulta y prueba con 1200 vinculos. Los selectores de formulario cargan todos los personajes; falta medir latencia/DOM y contencion del lock de proyecto bajo carga representativa |
| R38 / P2 | Semantica de reciprocidad intencionalmente limitada | Una fila mutua; PARENT/CHILD/MENTOR/STUDENT siempre direccionales. Dos unilaterales opuestas del mismo tipo son validas, pero no coexisten con una mutua. Convertirlas exige decidir que descripcion conservar. OTHER sigue siendo un tipo unico por direccion, no uno por etiqueta personalizada |

La constraint funcional protege dos mutuas invertidas. La incompatibilidad entre
una mutua y una unilateral inversa, asi como la pertenencia cruzada de FK, requiere
los validadores y el bloqueo cooperante de Project: no se implementaron triggers.
QuerySet.update/bulk_*/delete y SQL directo siguen siendo entradas privilegiadas,
no una API de negocio. No hay garantia contra SQL hostil ni inferencia semantica
de progenitor/hijo, mentor/discipulo o sentimientos mutuos.

1005 pruebas integradas aprobadas; 94 nuevas, con diez carreras PostgreSQL y una
migracion aditiva. QA real verifica ambas fichas, duplicados, edicion movil,
permisos por estado y borrado independiente; originales intactos tras retirar QA.

No revertir characters.0004 con relaciones creadas ni restaurar el dump previo
como rollback rutinario; preservar esquema/datos y corregir hacia delante. No se
agregan grafos, relaciones entre organizaciones, cronologias, IA, cobros ni
exportacion de relaciones. Evidencia de pruebas, QA e inventario en
[17-character-relationships-validation.md](17-character-relationships-validation.md).

## Actualizacion tras Prompt 13: F8

| Riesgo | Estado actual | Evidencia y limite |
| --- | --- | --- |
| R02 / R03 / R07 | Mitigados para consulta | Politica central, entidad y asociaciones del proyecto, ID ajeno rechazado; archivos sin URL publica, attachment/no-store y 404 para otro usuario. ACTIVE/FROZEN/PENDING exportan; DELETED no |
| R08 / R11 / R20 | Captura estable | Esquema 2 inmutable con alcance, identidad, jerarquia, textos y estilo. Project y Style bloqueados; once carreras PostgreSQL. Ocho jobs reales conservan contenido despues de editar/mover/borrar; el worker no reconstruye desde entidades vivas |
| R09 / R10 / R14 | Infraestructura existente reutilizada | Ninguna tarea periodica nueva; leases, token, heartbeat, retry, outbox, retencion y limpieza comunes. Pruebas REFERENCE de estados, recuperacion, opt-in/out, descarga, borrado y caducidad; regresion completa WORK/FINAL/HTML/EPUB/preview |
| R13 / R28 | Respaldo e integridad comprobados; reversa protegida | Dump/media previos conservados, huellas de campos originales identicas. No se ensayo restauracion nueva. 0004 no modifica manifiestos; bloquea revertir si hay REFERENCE, incluso tombstones. Corregir hacia delante |
| R16 / R17 | Limites y lotes; falta ensayo de carga | MAX_NODES incluye entidades/contexto/vinculos; MAX_BYTES controla fuentes y manifiesto. Arbol de 1052 ubicaciones sin recursion, consultas constantes al agregar 60 personajes. No es una cuota RSS: renderizadores materializan bytes, selectores web no estan paginados y falta medir latencia/memoria/contencion con contenido real |
| R18 | Sin lectura de recursos fuente | Whitelist de campos; no FileField ni imagenes; metadatos y nombre original seguro. URLs HTTP(S) privadas/con credenciales reconocibles omitidas, fetcher PDF restringido. No es DLP para secretos que el autor haya escrito en prosa o en una URL opaca |

1093 pruebas integradas aprobadas, 88 nuevas. PDF inspeccionado visualmente y
DOCX abierto en Word; fuentes/paginacion pueden variar entre equipos. El snapshot
congela configuracion y texto, no binarios de fuentes ni versiones de librerias;
su checksum no promete regeneracion byte a byte del PDF/DOCX. Indice DOCX estatico,
sin paginas calculadas, y Markdown textual; no se modifica esa politica historica.
Profundidad documental conservada, encabezados renderizados hasta seis niveles.

Los locks siguen siendo cooperantes: usar servicios/model.save y transacciones
del proyecto en futuros escritores, no SQL/bulk privilegiado como API de negocio.
Texto duplicado en snapshots consume disco hasta su retencion; sigue pendiente
medir cuotas por cuenta y operacion externa de respaldos. No hay ZIP, binarios
incrustados, IA, mapas, grafos, OCR, pagos ni papelera general. Detalle en
[18-world-exports-validation.md](18-world-exports-validation.md).

## Actualizacion tras Prompt 14: F9

| Riesgo | Estado actual | Evidencia y limite |
| --- | --- | --- |
| R12 / R34 | Mitigados para manuscritos, no para todas las entidades | Borrado logico de BOOK/PART/CHAPTER/SCENE; solo se marca el nodo directo. Restaurar ancestro no revive eliminaciones previas. Admin sin borrado individual/masivo; no se crean purgas literarias ni papelera general |
| R03 / R06 / R07 | Permisos y jerarquia revalidados | Project -> nodo dentro de atomic, mismo propietario/proyecto, destino activo compatible, sin ciclos y posiciones visibles normalizadas. FROZEN/PENDING solo consultan; DELETED/ajenos 404. Nueve pruebas de concurrencia PostgreSQL |
| R04 / R08 / R11 | Identidad y versiones conservadas | No cambia ninguna fila SceneVersion, su revision, sus fechas ni la definitiva vigente/borrador activo. WORK/FINAL/preview nuevos excluyen ocultos; los snapshots previos no se recapturan. Seis versiones y seis jobs reales comprobados |
| R13 / R28 | Respaldo e integridad comprobados; migracion aditiva | Dump/media previos y huellas de 22 modelos conservados. 0005 agrega dos columnas e indice, sin cambiar IDs/textos/versiones; reversa bloqueada si hay tombstones. No se ensaya una restauracion nueva; respaldos externos/cifrados y ensayo recurrente pendientes |
| R16 / R17 | Visibilidad por lotes, carga real pendiente | Recorrido iterativo de metadatos sin N+1 por nodo; listados sin texto de escena. Papelera pagina a 50 despues de materializar metadatos, y selectores cargan el proyecto. Medir memoria, latencia y contencion del lock con proyectos grandes |
| R39 / P2 | Retencion conservadora puede crecer indefinidamente | No hay caducidad ni borrado definitivo de manuscritos. La limpieza de archivos exportados no toca fuentes literarias. Medir uso de PostgreSQL y definir politica comercial/legal por separado, con aprobacion explicita antes de purgar |
| R40 / P2 | Futuros lectores/escritores deben respetar visibilidad | Manager base conserva todas las filas para integridad, historial y respaldos. Usar .visible() en lectura ordinaria y servicios con Project bloqueado para escribir. QuerySet.update/delete, bulk_* y SQL siguen siendo APIs privilegiadas, no rutas de negocio |
| R41 / P2 | Ruta conservada, no historial independiente | La ubicacion se calcula desde FK originales conservadas; renombrar/mover un ancestro activo puede cambiar la ruta mostrada. Restaurar limpia el sello directo, sin mantener un registro separado de cada ciclo. Un padre ausente/oculto exige destino valido; estructura legacy invalida requiere revision, no reparacion automatica |

Las posiciones retenidas por nodos ocultos pueden coincidir con posiciones del
grupo visible renumerado. El auditor cuenta toda la papelera, pero comprueba
duplicados solo entre hermanos visibles. La unicidad estructural sigue siendo
cooperante; no se introduce una constraint SQL que confunda ambos conjuntos.

La restauracion de manuscritos usa permiso EDIT, no la transicion RESTORE del
proyecto: no habilita escrituras en proyectos congelados o pendientes de borrado.
Notas, menciones y asociaciones ocultas permanecen vinculadas y reaparecen al
restaurar. No se reasigna una definitiva ni se crean versiones por recuperar.

El esquema debe conservarse si se retrocede el despliegue; codigo anterior a F9
ignoraria los sellos y volveria a mostrar contenido oculto. Preferir correccion
hacia delante, no una version antigua ni un dump previo sobre trabajo posterior.
Prueba manual, resultados integrados, comandos e inventario en
[19-manuscript-trash-validation.md](19-manuscript-trash-validation.md).

1170 pruebas integradas aprobadas, 77 nuevas; check limpio, esquema al dia y
Celery pong. QA real retirado con huellas originales/media identicas. Ninguna
base ni volumen eliminados; no cambian maquinas anteriores ni archivos Git
protegidos por el alcance (`subir_repo.bat` y `diff_*.txt`).
