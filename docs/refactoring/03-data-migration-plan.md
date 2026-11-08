# Plan incremental de migracion de datos

Fecha: 2026-11-06. Actualizado tras Prompt 04 (F2). El plan de transformaciones
editoriales sigue siendo propuesto; solo se ejecuto la expansion acotada descrita
abajo. Los nombres de migraciones futuras son descriptivos. No reemplazar ni
editar las `0001_initial` existentes. Las evidencias iniciales de auditoria se
conservan como historico; 07, 08 y 09 registran los avances posteriores.

## Expansion aplicada en F2

En `telar-fabulas-dev`, el inventario previo encontro cero usuarios, proyectos,
nodos, notas, personajes, menciones y exportaciones. No hubo casos incompatibles
que transformar. El comando sigue siendo de solo lectura. No se reinicio la base,
no se borraron volumenes ni se toco la maquina anterior.

`manuscripts/0002_literary_hierarchy` agrega unicamente `short_description`
(`TextField(blank=True, default="")`) y cambia `title` a `blank=True` en el estado
de Django; la politica exige titulo en contenedores y lo hace opcional en escenas.
En PostgreSQL, `sqlmigrate` muestra ADD COLUMN text con valor inicial vacio y
retiro del default de esquema; el cambio de `title` no requiere SQL. No contiene
RunPython, conversiones, borrados ni reescrituras de PK, content, padres o estados.

Se probo la migracion 0001 -> 0002 sobre una base de pruebas aislada con FRAGMENT
legado, texto Unicode/saltos exactos, posiciones y estados heredados, notas,
menciones y referencia a export historico. Todos los campos anteriores y las
relaciones se conservaron; la descripcion nueva quedo vacia.

Esta entrega cubre solo descripcion/titulo de M1. SceneVersion, RefactoringRecord,
backfill y constraints de orden siguen pendientes. FRAGMENT no se convierte ni
borra; las ramas incompatibles quedan legibles/exportables y bloqueadas para
escritura. La normalizacion ocurre en operaciones validas, no en la migracion ni
como reparacion automatica de legado. Si se importan datos, repetir inventario y
detener el despliegue ante incompatibilidades para aprobar un tratamiento.

Rollback: conservar la columna aditiva y usar un lector compatible. No ejecutar
la reversa de 0002 sobre datos de trabajo: eliminaria descripciones nuevas.
El retroceso de esquema usado en la prueba ocurre solo en `test_telar_fabulas`.
Comandos y resultados: [09-manuscript-hierarchy-validation.md](09-manuscript-hierarchy-validation.md).

## Condiciones para iniciar

1. Recuperar acceso al entorno y registrar ps, check, showmigrations,
   makemigrations --check --dry-run, suite completa y ping de worker. F0-F2 ya
   recuperaron acceso a `telar-fabulas-dev`; repetir las comprobaciones antes de
   una nueva transformacion. La auditoria inicial sin socket no es el estado actual.
2. Identificar revision Git mas cambios locales, versiones de imagen/lock y
   configuracion efectiva sin registrar secretos. Conservar los cambios previos
   y diff_*.txt. El respaldo declarado del directorio no confirma respaldo de
   PostgreSQL/media, que viven en volumenes nombrados.
3. Crear respaldo coherente de DB y archivos, verificar checksums y restaurarlo
   en un entorno separado. No sobrescribir ni recrear la base del propietario.
   Fijar ventana de mantenimiento, RPO/RTO y responsable de retorno.
4. Obtener decisiones D01-D06 y D16 antes de transformar jerarquia o texto;
   las fases comerciales dependen de D10-D14/D18-D19.
5. Ensayar la migracion en copia aislada. El proceso de inventario debe ser de
   solo lectura por defecto y no mostrar texto privado en reportes compartidos.

## Inventario previo obligatorio

Ejecutar `python manage.py audit_refactoring`, implementado en F0 sin escrituras.
Su salida cuantitativa decide los lotes y los casos que requieren intervencion:

| Inspeccion | Medida y condicion de bloqueo |
| --- | --- |
| Identidad | Conjuntos de PK por modelo, FK y propietario; una FK a otro proyecto bloquea conversion automatica |
| Tipos/estados | Conteos por tipo/status/is_publishable y combinaciones; valores desconocidos se reportan, no se sustituyen |
| Raices | Proyectos vacios, raices no BOOK, BOOK con padre y padre incompatible con la matriz objetivo |
| Arbol | Ciclos, profundidad, nodos no alcanzables desde raiz y nodos con padre fuera del proyecto |
| Orden | Positions nulas, <=0, duplicadas y huecos por (project,parent), incluido parent NULL |
| Texto | Escenas con texto vacio, solo espacios, caracteres especiales y textos grandes; longitud UTF-8 y SHA-256 por fuente |
| Texto fuera de escenas | BOOK/PART/CHAPTER/FRAGMENT con content, orden de aparicion y descendientes; no confundirlo con descripcion |
| Asociaciones | Conteos y tuplas exactas de Note.node/character, CharacterMention y ExportJob.root_node; duplicados de menciones/papeles |
| Archivos | Existencia/tamano/hash por FileField y claves sin registro; nunca borrarlos durante inventario |
| Exportaciones | Estados, jobs en vuelo, archivos y raices desaparecidas; no reencolar automaticamente |
| Usuarios | Tipos, estados/is_active, proyectos usados, colisiones de email al normalizar; sin asignar suscripciones |

Guardar manifiesto privado por lote con source PK, original parent/type/position,
estado/flags/fechas originales, checksums y destino. Una tabla tecnica acotada
`RefactoringRecord` o registro durable equivalente permite reanudar y revertir
cambios estructurales sin depender de logs de consola. UNIQUE por operacion+PK
evita repetir una conversion; un source_hash distinto exige revision, no overwrite.
Su esquema y acceso se cerraran en el prompt de implementacion; no contiene texto
en logs publicos. El texto original seguira en sus columnas y en backups.

## Secuencia de esquema y datos

| Etapa | Cambios previstos | Puerta de salida |
| --- | --- | --- |
| M0: preflight | Solo lecturas, pruebas y copia de ensayo; sin cambios de esquema | Historial conocido, inventario y restauracion verificada |
| M1: expansion | ManuscriptNode.short_description; title blank en formulario/esquema de validacion; SceneVersion y RefactoringRecord; despues FK active_version nullable | El codigo anterior sigue leyendo sus columnas; tablas vacias no cambian comportamiento |
| M2: copia de escenas | Una version inicial por escena, texto exacto, metadata original y hashes; sin borrar Node.content | Cero diferencias de texto/identidad y cero escenas sin copia |
| M3: adaptacion del arbol | Conversiones aprobadas por lote, wrappers nuevos solo donde hagan falta; conservar PK originales | Sin ciclos/cruces, matriz objetivo o excepciones heredadas explicitamente registradas |
| M4: restricciones | Orden no nulo/positivo, unicidad de posiciones, constraints de versiones y duplicados de menciones resueltos | Validacion en PostgreSQL, incluidas escrituras concurrentes |
| M5: cambio de lectores/escritores | UI/servicios usan SceneVersion; selector unico de exports; columnas legacy quedan en solo lectura | Comparacion funcional y de archivos; edicion concurrente rechaza conflicto |
| M6: exports y nuevas entidades | Nuevos campos/estados de ExportJob, snapshots, recursos privados y tablas de mundo/relaciones por fase | Jobs viejos y archivos siguen accesibles; fixtures de compatibilidad pasan |
| M7: ciclo comercial | Plan, Subscription, Payment, PaymentEvent, NotificationLog; migracion de usuarios segun decision aprobada | Ninguna cuenta pierde acceso por inferencia de FREE/PREMIUM |
| M8: retirada futura | Retirar lectores legacy; evaluar columnas obsoletas tras periodo de verificacion | Aprobacion independiente, respaldo y ausencia demostrada de dependencias |

M6 se implementa en varias entregas, no en una migracion masiva. M8 no forma parte
de los primeros prompts. No retirar FRAGMENT ni content como efecto lateral de M1-M5.

## Copia de contenido a SceneVersion

Durante la copia no permitir escritores legacy concurrentes. Para una primera
migracion de este tamano se propone ventana de escritura pausada, lectura
disponible y workers de exportacion drenados. Si el inventario obliga a lotes
online, implementar primero control de revision y comprobar hash antes/despues;
un nodo modificado se marca para reprocesar. No asumir que un snapshot inicial
seguira vigente mientras otro formulario puede guardar.

Cada SCENE conserva su PK. Crear version_number=1 con scene_id igual al PK
existente y content identico: sin strip, conversion de saltos, normalizacion
Unicode ni interpretacion Markdown. Guardar checksum/longitud del UTF-8. Recalcular
word_count con una funcion estable de migracion y comparar con el valor anterior;
si discrepa, registrar ambos, no cambiar el texto para hacerlos coincidir.

Preservar created_at/updated_at de origen en el manifiesto y asignar los de la
version inicial de forma explicita segun la politica aprobada. `auto_now_add` no
debe inventar una fecha historica de escritura. Registrar aparte imported_at.
Si el original no trae fecha de finalizacion, no inferirla de updated_at: registrar
finalized_at al confirmar/importar la definitiva y marcar su procedencia.

Tabla propuesta, pendiente de D04:

| Estado anterior | Etapa inicial propuesta | Precaucion |
| --- | --- | --- |
| PENDING, IN_PROGRESS, DRAFT | DRAFT | Conservar estado original en manifiesto |
| REVIEW | REVIEW | No convertir a definitiva |
| FINISHED | REVIEW | Terminado no demuestra aprobacion para publicacion |
| PUBLISHABLE, PUBLISHED | Candidato a FINAL | Solo tras aprobar criterio y comprobar contenido; guardar is_publishable original |
| Cualquier estado con flags contradictorios | Revision de caso; copia preservada DRAFT/REVIEW segun decision | Nunca elegir FINAL solo porque un booleano este activo |
| Escena vacia o solo espacios | Copia exacta DRAFT, provisionalmente sin vigente | Una escena vacia no justifica descartar la fila ni inventar contenido |

No ejecutar una conversion editorial ambigua por defecto. Se puede completar la
copia de seguridad del texto sin activar exportacion final; los candidatos quedan
pendientes de confirmar. Tras fijar la politica, activar como maximo una vigente
por escena y asignar active_version. La version inicial puede ser activa aunque
sea FINAL: para empezar otra redaccion, el servicio crea una copia DRAFT.

Implementar copia idempotente con clave de procedencia: si ya existe la version
de importacion, comparar source_hash, content y referencias. Nunca reemplazar una
version existente porque su numero sea 1. Si hay escrituras nuevas, detener el
lote para conciliacion. En el primer corte, conservar la copia importada como
baseline inmutable y crear otra version al editarla.

RunPython debe obtener modelos historicos con apps.get_model y usar el alias de
schema_editor.connection. Calcular explicitamente conteos, fechas y validaciones:
los modelos historicos no ejecutan los metodos save personalizados. Mantener
disponibles managers/upload_to referenciados por migraciones viejas.
[Migraciones historicas de Django](https://docs.djangoproject.com/en/5.2/topics/migrations/#historical-models).

Para tablas grandes, separar expansion DDL y backfill reanudable por PK/lotes con
checkpoints. Si se usa un comando de backfill, una migracion/check de cierre debe
verificar completitud antes del cambio de lectores; no marcar exito solo porque
la tabla nueva exista. Controlar lock timeout y duracion de las transacciones.

## FRAGMENT, estructura heredada y texto de contenedores

El preflight F2 no encontro estos casos en la base nueva. Eso no demuestra que
un respaldo externo este limpio: volver a inventariar si se importa contenido.
No eliminar, concatenar ni reasignar automaticamente ningun FRAGMENT en F2.

| Caso | Transformacion candidata para aprobacion | Conservacion requerida |
| --- | --- | --- |
| FRAGMENT hoja bajo CHAPTER | Cambiar ese mismo nodo a SCENE; versionar su contenido | Mismo id, notas y menciones permanecen ligadas |
| FRAGMENT bajo BOOK/PART o en raiz | Crear contenedores faltantes y convertir el mismo nodo a SCENE, si el autor lo acepta | Mapear nuevos padres y posicion; no recrear el fragmento con otro id |
| FRAGMENT bajo SCENE o con hijos | Mantener como legado hasta aprobar desglose/orden de escenas | No fusionar texto ni mover menciones automaticamente; bloquear retiro de FRAGMENT |
| SCENE en raiz o bajo BOOK/PART | Crear BOOK/CHAPTER faltantes o seleccionar un capitulo existente, segun manifiesto aprobado | Conservar scene id y secuencia relativa |
| BOOK/PART/CHAPTER con content | Mantener original; proponer escena de apertura con PK nuevo y contenedores necesarios | Copiar texto exacto, registrar source_node_id; no convertir todo en short_description |
| Ciclo, padre ajeno o jerarquia contradictoria | Resolver manualmente en copia y aprobar mapa | No ocultar ni borrar nodos para que el arbol parezca valido |

Los textos de libro/parte/capitulo actualmente se exportan ANTES de los hijos.
Si pasan a escena de apertura, esa escena debe quedar antes de los hijos que
tenian texto. El selector debe elegir una sola fuente (legacy o escena derivada),
para no duplicar ni omitir ese contenido. Notas y menciones de contenedores se
conservan sobre los nodos originales; su significado no se transfiere por suponer
que todo era una escena. Titulo de wrapper y descripcion requieren politica D01/D03.

Para empates de position proponer orden estable position/created_at/pk y registrar
el orden anterior. No afirmar que el orden historico de empates era determinista:
el exportador previo a F2 no desempataba por PK. F2 incorpora el desempate para
lectura, sin reescribir positions heredadas. Aprobar las secuencias dudosas antes
de normalizar. Conservar referencias en ExportJob aun si su destino se archiva.

## Compatibilidad y restricciones

Mantener Node.content/status/is_publishable/word_count como campos legacy durante
la transicion; son candidatos a obsolescencia SOLO para texto/estado de escenas.
El futuro de content en contenedores depende de D03. No duplicar escrituras sin
definir fuente de verdad. Propuesta: tras el corte, SceneVersion es la unica
fuente de texto editable y Node.content queda congelado como respaldo heredado.
Adaptar vistas/admin/exportadores antes de reabrir escrituras; impedir que un
proceso antiguo siga guardando Node.content. Comparar el nuevo export de trabajo
con el anterior antes de introducir las reglas de export final.

Agregar restricciones en pasos independientes despues del saneamiento:

- UNIQUE de numero por escena y vigente parcial; CHECK de etapa, contador,
  revision y bandera/finalized_at; FK active_version en migracion posterior a
  CreateModel para resolver referencia circular.
- Posiciones no nulas/positivas y unicidad incluyendo raices; adaptar servicios
  antes de habilitarlas. Ciclos, tipo del padre y vinculo a misma escena se
  validan aparte, no mediante CHECK de otra fila.
- UNIQUE(character,node,mention_type) despues de inventariar duplicados.
  No borrar duplicados sin registrar IDs y confirmar que no contienen datos
  distintos; producir mapa de conciliacion.
- Invariantes de propietario de estilos y pares de relaciones nuevos; indice de
  caducidad de jobs y unicidad de eventos/notificaciones en sus propias fases.

No aplicar una constraint de jerarquia estricta sobre filas FRAGMENT sin resolver.
Durante compatibilidad puede aceptar solo las excepciones legacy inventariadas;
no habilitar creacion de nuevas excepciones para sortear la migracion.

## Migracion de exports y almacenamiento

Mapeo de estado: PENDING -> REQUESTED, PROCESSING -> PROCESSING,
DONE -> READY, FAILED -> FAILED; DELETED es nuevo. Conservar PK, timestamps,
formato, archivo y propietario. HTML/EPUB no se eliminan ni se regeneran.

Agregar modo WORK por defecto a jobs heredados porque incluian todo el texto,
sin reclasificarlos como exportaciones finales. Jobs ya terminados mantienen el
archivo original; una procedencia legacy indica que no existe snapshot retroactivo.
No construir un supuesto snapshot historico con el manuscrito actual.

Antes del cambio de estados, detener nuevos encargos y drenar workers viejos o
introducir lector compatible para ambos nombres. Capturar REQUESTED/PROCESSING y
task IDs disponibles; resolver abandonados caso por caso, no reejecutar todos.
Revisar roots eliminadas; nunca tratar una FK perdida como permiso para exportar
todo el proyecto. En jobs nuevos separar scope del estado actual de la FK.

Primero desplegar lifecycle/idempotencia; despues activar borrado manual y Beat.
Calcular expires_at desde finished_at para trabajos nuevos. Para historicos, aprobar
periodo inicial de gracia o retencion retroactiva (D15) antes de llenar fechas:
una migracion no debe borrar todos los archivos antiguos al arrancar Beat.
Mantener la limpieza desactivada hasta revisar un dry-run.

Migracion de media a privado: inventario, copia a clave privada unica, comparar
bytes/hash y probar descarga autorizada; cambiar puntero solo tras verificar.
Mantener original durante ventana controlada de rollback, restringiendo tambien
su acceso publico. Borrar duplicados solo en operacion posterior aprobada. No
usar rutas proporcionadas por usuarios ni borrar directorios compartidos.

## Entidades de mundo y ciclo comercial

Crear tablas de geografia, organizaciones, entradas, referencias y relaciones
sin transformar texto libre existente. No inferir organizaciones, lugares,
amistades o parejas analizando biografias. Las fichas y papeles originales siguen
siendo validos; las nuevas relaciones empiezan vacias. Una imagen existente puede
convertirse en referencia mediante copia verificada y mapa, nunca moviendola a
ciegas. Decidir si una ficha puede conservar la imagen legacy durante transicion.

Conservar accounts.User y AUTH_USER_MODEL. Las nuevas tablas comerciales se
agregan sin actualizar user_type/status ni fijar fechas de vencimiento por
antiguedad del usuario. Una cuenta PREMIUM no demuestra pago, periodo ni precio;
una FREE anterior no debe aparecer vencida retroactivamente. D10 define acceso
heredado, inicio de prueba y regularizacion. Registrar la fuente de cada asignacion.

No reinterpretar scheduled_deletion_at de proyecto (90 dias por solicitud) como
retention_until de suscripcion (un ano de impago). El procedimiento de purga
debe distinguir causas, renovaciones y avisos y respetar el bloqueo PROTECT de
arbol/estilos/versiones. Diseñar orden de purga y archivo fisico en una fase propia.

## Verificaciones despues de cada lote

Exigir cero diferencias no explicadas, con evidencia legible por responsable:

1. Mismos PK originales y misma propiedad por proyecto; ningun registro perdido.
2. Una copia por escena original; igualdad exacta de contenido, hash/longitud,
   incluyendo vacios, espacios, saltos y caracteres no ASCII.
3. Tuplas y conteos de notas/menciones conservados; mapa de IDs nuevos cuando
   haya wrappers o escenas derivadas. Los enlaces existentes siguen resolviendo.
4. Sin ciclos ni padres cruzados; matriz validada; posiciones ordenadas sin
   duplicados y mismo recorrido aprobado. Todos los nodos siguen alcanzables o
   estan identificados en el informe de excepciones accesible al propietario.
5. Numeros de version unicos, maximo una vigente, active_version de misma escena;
   contador calculado consistente y finalizaciones con procedencia conocida.
6. Exports de trabajo en HTML/DOCX/PDF/EPUB preservan contenido/orden esperado;
   final excluye borradores. Markdown pasa casos de escape y titulos opcionales.
7. Archivos conservan hash o transformacion aprobada, descargas privadas funcionan
   y limpieza simulada solo enumera archivos de jobs elegibles.
8. Pruebas PostgreSQL de dos editores, dos promociones/movimientos y cleanup vs
   worker; suite de regresion y restauracion en copia aislada.

## Rollback y condiciones de parada

| Momento | Retorno viable | Limite |
| --- | --- | --- |
| Antes de M2 | Volver al codigo anterior dejando columnas/tablas aditivas | No hace falta borrar tablas nuevas |
| Durante backfill sin escritores nuevos | Reanudar desde manifiesto o revertir solo filas creadas por ese lote verificadas por hash | Nunca borrar versiones por numero sin comprobar procedencia |
| Tras M3 sin nuevas escrituras | Restaurar parent/type/position desde mapa, en transaccion, conservando nuevos registros hasta conciliar dependencias | No eliminar wrappers ya usados por otros datos |
| Despues del cambio a versiones | Desactivar funciones nuevas y usar lector compatible o modo lectura; conservar tablas nuevas y capturar trabajo posterior | No volver a un binario que solo lee Node.content ni hacer copia inversa sobre texto nuevo |
| Despues de archivos privados | Revertir punteros solo a copias verificadas y con igual privacidad | No reabrir media publica para facilitar rollback |
| Tras purga o retirada de columnas | Restauracion controlada a entorno aparte y conciliacion de trabajo posterior | No reversible con migrate inverso; backup puede no contener cambios posteriores |

Parar ante discrepancia de checksum, FK cruzada, ciclo, estado no mapeado,
archivo ausente, escritura concurrente durante copia, falla de constraints o
trabajo posterior no conciliado. Un reverse_code no debe eliminar historia nueva;
rechazar reversa destructiva o mantener expansion instalada. Documentar que
recuperar de un backup antiguo sin conciliar puede perder trabajo posterior.

Toda eliminacion de content legacy, FRAGMENT, version o archivo fuente exige una
fase independiente, retencion aprobada y evidencia de recuperacion. Los pasos
editoriales futuros no se han ejecutado; la expansion F2 aplicada esta delimitada
al inicio de este documento y no autoriza transformaciones adicionales.
