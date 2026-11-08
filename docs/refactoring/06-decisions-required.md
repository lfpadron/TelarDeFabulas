# Decisiones pendientes

Fecha: 2026-11-06. Este registro distingue reglas recibidas de propuestas.
Ninguna recomendacion de esta auditoria se considera aprobacion comercial ni
autoriza ejecutar una migracion. Se puede implementar diagnostico de solo lectura
antes de resolverlas; no se pueden aplicar transformaciones ambiguas de datos.

## Reglas ya aprobadas en el anexo

- Conservar Django, Podman rootless y compatibilidad Compose; evolucionar el repo.
- Proyecto con libros; parte opcional; escenas solamente dentro de capitulos;
  identidad y relaciones se conservan al mover. Descripcion breve disponible;
  titulo de escena opcional. FRAGMENT no se elimina en esta fase.
- Versiones independientes DRAFT/REVIEW/FINAL; una sola definitiva vigente;
  export final desde esa definitiva y rechazo de sobrescritura concurrente.
- Conservar cuentas y fichas; incorporar mundo, relaciones y referencias privadas.
- Oferta comercial de Markdown/DOCX/PDF, conservando HTML/EPUB existentes.
- Estados REQUESTED/PROCESSING/FAILED/READY/DELETED; retencion inicial de exports
  listos/fallidos de 7 dias; correo asincrono opcional sin manuscrito adjunto.
- Trial sin tarjeta con un proyecto y todas las funciones; al vencer, lectura y
  exportacion. Suscripcion mensual/anual, pago manual/Stripe y cupo configurable.
- Un ano de conservacion tras vencimiento impago, avisos previos y purga auditable.
- Esta entrega se limita a auditoria, documentacion y validacion no destructiva.

## Decisiones de datos y narrativa

| ID | Decision que falta | Recomendacion para evaluar | Por que necesita confirmacion / fase |
| --- | --- | --- | --- |
| D01 | Primer libro de proyecto nuevo, proyectos historicos vacios, titulos de contenedores creados y obligatoriedad de descripcion | Crear primer libro junto al proyecto nuevo; pedir titulo o usar uno provisional reconocido como tal. Mantener descripcion vacia en legado hasta completar | No inventar titulo/descripcion del autor. Resolver antes de normalizar arbol |
| D02 | Destino de FRAGMENT segun parent/hijos y existencia real | Conservar legado; convertir hojas a SCENE con el mismo PK solo con mapa aprobado; casos anidados se revisan individualmente | Fusionar o desglosar cambia narrativa y asociaciones. Bloquea retiro de FRAGMENT |
| D03 | Texto actual de BOOK/PART/CHAPTER | Proponer escenas de apertura manteniendo fuente original y orden; no convertirlo en resumen ni copiar menciones por inferencia | El texto puede ser prologo, epigrafe o manuscrito. Resolver despues del inventario y antes del selector final |
| D04 | Mapeo de FINISHED/PUBLISHABLE/PUBLISHED, flags contradictorios y fecha de finalizacion desconocida | FINISHED candidato a REVIEW; PUBLISHABLE/PUBLISHED candidatos a FINAL solo tras confirmar; vacios sin vigente. Registrar procedencia de fechas | Un estado antiguo no prueba aprobacion final. Bloquea activacion de export final |
| D05 | Edicion activa por escena, inmutabilidad de baseline/FINAL, nuevas versiones y retencion de borradores/autoguardados | Active_version por escena para el propietario unico; FINAL y baseline importada inmutables; al editarlas crear DRAFT. Conservar todas las versiones en v01 | Version editorial y cada pulsacion/autoguardado son conceptos distintos. Aclarar experiencia y volumen antes de UI de versiones |
| D06 | Escenas sin definitiva, escenas sin titulo y exportacion de fichas en modalidad final | Omitir escenas sin definitiva con informe explicito; impedir archivo final sin contenido. Titulo vacio no se inventa en el documento. Entidades no narrativas se exportan como trabajo hasta definir semantica final | No se establecio si encabezados vacios se mantienen ni si fichas requieren estado editorial. Bloquea criterios de aceptacion del selector |

## Mundo, archivos y relaciones

| ID | Decision que falta | Recomendacion para evaluar | Por que necesita confirmacion / fase |
| --- | --- | --- | --- |
| D07 | Limites por imagen/adjunto/proyecto, extensiones admitidas, metadatos bibliograficos e inclusion de materiales en exports | Parametros independientes, storage privado y comprobacion real de tipo; permitir referencia bibliografica sin archivo. Definir si exporta descripcion/enlace o incluye copia | No hay tamanos ni cuota contratada en el anexo. Definir antes de habilitar uploads y exportar adjuntos |
| D08 | Significado de jerarquia geografica flexible | Permitir saltar niveles, con mismo proyecto y sin ciclos. Confirmar si relaciones de niveles iguales/inversos son legitimas | Geografia politica y fisica no siempre comparten orden; no imponer reglas no aprobadas |
| D09 | Relaciones de personajes, afiliaciones multiples, tipos de residencia y roles por libro o por proyecto | Conservar roles actuales por personaje/proyecto; amistad simetrica, interes romantico direccional; vinculos explicitos para organizaciones/lugares | Debe definirse cardinalidad/historia; no inferir relaciones de texto ni duplicar los roles existentes |

## Suscripciones y operaciones

| ID | Decision que falta | Recomendacion para evaluar | Por que necesita confirmacion / fase |
| --- | --- | --- | --- |
| D10 | Duracion/inicio de trial y tratamiento de cuentas FREE/PREMIUM existentes | Parametrizar dias; decidir si comienza al registrarse o al primer uso. Mantener acceso heredado hasta asignacion comercial explicita | No inferir pagos ni vencer retroactivamente usuarios. Bloquea cualquier migracion comercial |
| D11 | Precios/moneda/impuestos, cupos, cambio de plan, renovacion/cancelacion, pago manual y devoluciones | Plan con condiciones versionadas; confirmacion manual con actor, referencia y periodo cubierto; conservar datos si baja el cupo | Son decisiones comerciales. No se ha aprobado un limite de paga ni se asume que siga siendo 10 |
| D12 | Calendario de recordatorios mensuales/anuales y recuperacion tras caida de Beat | Anual [30,14,7]; mensual [7] por defecto, ambos parametrizables; una clave por periodo/umbral y un aviso consolidado tras interrupcion | Evita solapamiento entre ciclos y correos en rafaga; requiere aprobacion de comunicacion |
| D13 | Un ano calendario vs 365 dias, calendario de avisos de purga, pausas/excepciones y relacion con borrado voluntario de 90 dias | Separar causas; fijar unpaid_since al inicio del episodio; renovacion cancela purga. Conservar datos por el periodo aprobado, sin acortarlo por configuracion nueva | No activar eliminacion automatica con fechas inferidas. Bloquea Beat de purga de cuenta |
| D14 | Correo transaccional: proveedor/remitente, direccion principal/secundaria, avisos obligatorios vs optativos e idioma/zona | Exports con opt-in por resultado; otros avisos con politica explicita. Email principal verificado como destino inicial; sin manuscritos ni secretos en correo | Evitar divulgar a una direccion no verificada; definir entrega/reintentos antes de activar envios |
| D15 | Momento de snapshot, default de export de trabajo, reintentos y gracia de exports historicos | Capturar al iniciar worker e indicar fecha; trabajo usa version activa salvo seleccion explicita. Reintento con nuevo intento/job trazable. Gracia antes de aplicar limpieza a historicos | Cambia lo que recibe el autor y cuando caducan archivos ya creados. No regenerar historicos con texto actual |
| D16 | Hasta donde reforzar reglas cruzadas en PostgreSQL y politica de archivado/borrado de escena | Constraints locales + servicios transaccionales como base; evaluar triggers pequenos para misma escena/proyecto si se exige proteccion ante SQL directo. Archivar escena antes que purgar versiones | CHECK no valida otras filas. El alcance de triggers y cambios de borrado exige una decision tecnica explicita |
| D17 | RPO/RTO, frecuencia/destino/retencion de backups, restauracion de media y borrados definitivos | DB+archivos+manifiesto cifrados fuera de los volumenes; ensayo aislado. Definir expiracion de copias y reejecucion de registros de borrado al restaurar | El respaldo de directorio declarado no garantiza recuperar datos; coste y plazos operativos no definidos |
| D18 | Facultades de BUSINESS_ADMIN/TECH_ADMIN, acceso a manuscritos y excepciones comerciales | Separar roles administrativos de permisos de contenido; acceso excepcional auditado, sin convertir tipo de usuario en acceso general | El admin actual usa is_staff/permisos Django. No otorgar acceso adicional por inferencia |
| D19 | Normalizacion/unicidad de email, verificacion, politica de passwords y validacion/activacion de locale/timezone | Inventariar colisiones antes de normalizar; no fusionar cuentas automaticamente; validadores estandar y zonas IANA | Puede afectar identificadores existentes y notificaciones. Resolver antes de billing/envios |

## Orden de resolucion

Primero disponer del inventario real y cerrar D01-D06/D16. D07-D09 corresponden a
mundo y referencias; D15 a exportaciones. D10-D14/D18-D19 preceden a la fase
comercial. D17 debe resolverse antes de cualquier migracion de datos.

El diagnostico read-only, las pruebas de regresion y las correcciones de acceso
que mantengan reglas actuales pueden desarrollarse sin inventar estos valores.
Para cada decision registrar fecha, responsable, opcion aprobada y revision del
plan. No usar la ausencia de respuesta como aprobacion de conversion o borrado.
