# Roadmap de refactorizacion v01

Fecha: 2026-11-06. Actualizado tras Prompt 04 (F2). Cada fase posterior requiere
una instruccion independiente de implementacion.
No se estima duracion sin inventario de datos y presupuesto operativo. El orden
protege identidad/texto antes de introducir nuevas reglas comerciales.

## Fases y puertas de aceptacion

| Fase | Entrega acotada | Dependencias | Aceptacion verificable | Pruebas requeridas |
| --- | --- | --- | --- | --- |
| F0: baseline e inventario | Comando read-only de auditoria de datos, registro de migraciones aplicadas y ensayo de restauracion aislada | Podman disponible; D17 | Reporte de cantidades/casos legacy sin texto privado, DB/media recuperables, suite actual conocida | check, showmigrations, dry-run de migraciones, test completo, ping Celery; fixtures corruptos para el auditor |
| F1: proteccion de operaciones (implementada) | Politica central, storage privado, validacion Pillow, admin acotado, CSS/HTML seguros, estilos protegidos y roles atomicos | Inventario F0; matriz de proyecto aprobada en Prompt 03 | Propietario exclusivo, escrituras solo ACTIVE; FROZEN/PENDING leen/exportan/descargan; DELETED 404; no rutas publicas de media | Suite integrada y matriz de permisos, POST/CSRF, archivos, uploads, admin y formatos; detalle en 08 |
| F2: arbol e identidad (implementada) | Politica comun, descripcion breve, titulo opcional solo SCENE, movimientos bajo bloqueo de proyecto y orden normalizado de grupos validos | F0-F1; alcance aprobado en Prompt 04 | Mismos PK/texto/asociaciones; PART opcional; FRAGMENT conservado sin conversion ni renumeracion automatica | Matriz completa, modelo/forms/vistas/admin, ocho casos concurrentes PostgreSQL, migracion 0001 -> 0002 y cuatro formatos; detalle en 09 |
| F3: SceneVersion | Expansion, backfill verificado, version activa, historial, finalizacion y guardado con revision esperada | F2; D04-D05 | Copia exacta de todo texto de escenas; cero o una vigente; borrador no destruye FINAL; UI recupera conflictos | Hash/Unicode/vacios, numeracion concurrente, doble finalizacion, mover escena con historial y rollback |
| F4: selector y formatos | Documento neutral, modalidades trabajo/final, snapshot, Markdown; adaptar HTML/DOCX/PDF/EPUB y preview | F3; D06/D15 | Todos los formatos usan la misma seleccion; trabajo accesible aun vencido; final solo vigente; sin duplicar legacy | Diferencias por modalidad, titulo opcional, scope eliminado, movimiento/edicion durante snapshot, render y adjuntos |
| F5: lifecycle de exports | REQUESTED/READY/DELETED, reclamacion/lease, recuperacion, retencion de 7 dias, limpieza manual/Beat y NotificationLog | F4; D14-D15; storage privado F1 | Reentrega segura, cleanup nunca borra fuente ni compite con PROCESSING; correo de resultado sin adjunto | Worker real+Redis, duplicados, caidas, storage/broker fallando, worker vs cleanup/download y temporales |
| F6: mundo y referencias | Geography/Organizations/Worldbuilding/References, relaciones tipadas, limites y descarga privada | F1-F2; D07-D08 | Jerarquia geografica sin ciclos; varios bloques por categoria; adjuntos privados y limites medidos | Aislamiento por proyecto, ciclos concurrentes, MIME/tamano/cuota, FK de referencias y limpieza de copia |
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

Continuar con **F3: SceneVersion**, no con suscripciones. Resolver D04-D05 antes
de copiar texto o asignar versiones/estados editoriales. Repetir el inventario,
respaldar y ensayar la copia exacta en una base aislada antes de cambiar lectores.
El Prompt 04 fija jerarquia, titulo opcional de escena y conservacion de FRAGMENT;
no autoriza convertir fragmentos ni texto de contenedores (D03 sigue pendiente).

F1 ya fija FROZEN y PENDING_DELETION como solo lectura para el contenido, con
exportacion/descarga y restauracion explicitamente permitidas al propietario.
No define expiracion de cuenta ni transforma `User.status` en suscripcion.

F2 ya serializa escritores estructurales por proyecto y revalida el estado despues
de obtener el bloqueo. No es control optimista de texto ni snapshot de exportacion.
La unicidad de posiciones se garantiza por el protocolo cooperante, no por una
constraint SQL nueva; M4 sigue pendiente de inventario/saneamiento aprobado.
No se reparan ciclos heredados en segundo plano. SceneVersion queda en F3 con
copia de ensayo, control de revision y estrategia de retorno aprobada.
