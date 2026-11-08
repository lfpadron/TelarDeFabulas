# Validacion de seguridad F1 (Prompt 03)

Fecha local: 2026-11-06. Entorno: Windows + Podman rootless, conexion explicita
`telar-fabulas-dev`, PostgreSQL 16, Python 3.12 y Django 5.2 LTS.

## Resultado

**297 pruebas aprobadas en 136.588 segundos**, sin fallos ni pruebas omitidas.
Son las 217 pruebas de entrada mas 80 nuevas. Los casos antiguos que esperaban
bloquear exportacion de PENDING_DELETION se ajustaron a la matriz solicitada; no
se eliminaron pruebas. Las respuestas de recursos DELETED son ahora 404 y las
escrituras propias en solo lectura 403, en vez de redirecciones ambiguas.

La aplicacion queda encendida en http://localhost:8000. Web, worker y Beat
arrancan; PostgreSQL/Redis estan healthy y Celery devuelve pong. Se verifico
rootless=true, UID web=1000 y montaje del mismo volumen
`telar-fabulas_media_data` en `/code/private_media`.

No se borraron volumenes ni bases de trabajo. No se modifico la maquina Podman
anterior. La suite crea y elimina exclusivamente su base temporal de pruebas.
Inventario final: cero usuarios, proyectos, nodos, personajes, notas, menciones
y exportaciones; cero archivos en el volumen privado de esta maquina nueva.
No hubo archivos historicos que copiar ni datos originales recuperados.
Los siete archivos `diff_*.txt` conservan sus hashes de entrada.

## Controles implementados

- Politica compartida en core: VIEW, CREATE, EDIT, DELETE, EXPORT, DOWNLOAD y
  RESTORE. Solo propietario autenticado y `is_active`; sin bypass por superusuario.
- ACTIVE permite modificar contenido. FROZEN/PENDING_DELETION permiten
  leer/exportar/descargar y restaurar, pero ninguna escritura narrativa.
  DELETED y estados desconocidos son inaccesibles.
- Recursos ajenos responden 404; escrituras propias no permitidas, 403.
  POST narrativo verifica el proyecto bajo lock dentro de atomic. CSRF y
  confirmaciones existentes se conservan; GET nunca elimina/restaura.
- Admin: consultas y FK acotadas; readonly por estado, bulk delete verificado,
  proyectos/usuarios no admiten borrado fisico en cascada. ExportJob es readonly.
  Ficha y papeles dramaticos se guardan en una transaccion.
- `PrivateMediaStorage` no genera URLs; las rutas publicas de media se eliminaron
  incluso en DEBUG. Imagen/descarga requieren IDs de recursos autorizados, no
  rutas arbitrarias. Validacion de prefijo, traversal, symlink fuera del storage,
  existencia y formato; 404 controlado, MIME real, nosniff y no-store.
- JPEG, PNG y WebP: Pillow verify y load, extension coherente, limite por archivo
  de 5 MB configurable y UUID. Se rechazan SVG, GIF nuevo, archivos falsos,
  truncados, enormes y advertencias de descompresion. Los GIF heredados validos
  siguen legibles y se preserva su referencia al editar solo texto.
- Texto de manuscrito escapado en templates/HTML/EPUB; fuentes/alineaciones/
  numeros CSS restringidos, CSP en HTML y iframe sandbox en preview. El
  fetcher de WeasyPrint rechaza archivos locales y recursos de red/data.
- Worker revalida propietario, proyecto, nodo y estilo antes de renderizar.
  Las excepciones no se muestran con rutas fisicas en el mensaje al usuario.
- Borrar un estilo referenciado conserva sus datos y presenta un mensaje.
  Referencias heredadas cruzadas hacia otros proyectos/estilos se excluyen de
  las consultas sin modificar datos; el auditor sigue disponible.

La matriz completa, URLs y actualizacion no destructiva del almacenamiento estan
en [README.md](../../README.md).

## Pruebas nuevas

| Modulo | Pruebas | Alcance |
| --- | --- | --- |
| core/tests/test_permissions.py | 29 | Matriz de estados/propiedad, peticiones directas a 17 operaciones, restauracion, CSRF, rollback de roles, referencias cruzadas, perfil y worker |
| core/tests/test_private_files.py | 31 | Sesion/propiedad, descarga de cuatro MIME, privacidad en DEBUG, traversal/symlink, archivo ausente, widget, UUID y uploads JPEG/PNG/WebP/corruptos |
| core/tests/test_admin_security.py | 12 | Propiedad incluso superusuario, readonly, FK, bulk delete, cascadas deshabilitadas, archivos privados y estilos |
| core/tests/test_rendering_security.py | 8 | Escape de HTML/EPUB, CSS, CSP, sandbox y limites de preview, fetcher PDF y errores privados |

Las pruebas existentes de HTML, DOCX, PDF, EPUB, preview, cuentas, proyectos,
manuscritos, personajes, notas, estilos y auditoria tambien pasaron.
Las pruebas de archivo usan directorios temporales aislados; no generan
manuscritos ni usuarios de demostracion en la base de trabajo.

## Comandos ejecutados

Todos los comandos Compose utilizaron el prefijo
`podman --connection telar-fabulas-dev compose`, sin cambiar la conexion global.

| Comando (sufijo Compose) | Resultado final |
| --- | --- |
| up -d --build | Construccion y arranque correctos, imagenes OCI y mismo YAML compatible con Docker |
| exec -T web python manage.py check | Sin problemas |
| exec -T web python manage.py makemigrations characters --name validate_private_images | Una migracion de estado para el validador |
| exec -T web python manage.py sqlmigrate characters 0002 | BEGIN / no-op / COMMIT, revisado antes de aplicar |
| exec -T web python manage.py migrate | characters.0002_validate_private_images OK |
| exec -T web python manage.py makemigrations --check --dry-run | No changes detected |
| exec -T web python manage.py test apps.core.tests.test_permissions --noinput | Primer bloque: 27/27 |
| exec -T web python manage.py test apps.core --noinput --failfast | Bloque ampliado: 77/77 |
| exec -T web python manage.py test --noinput | Ultima ejecucion: 297/297, 136.588 s |
| exec -T worker celery -A config inspect ping | pong; un worker online |
| exec -T web python manage.py audit_refactoring | Solo lectura; cero registros; ningun hallazgo HIGH/CRITICAL ni DEBUG_MEDIA_ROUTE |
| ps; logs --tail=8 beat worker (ejecutados por separado) | Cinco servicios Up; Beat iniciado y worker ready |
| exec -T web id -u | 1000 |
| exec -T web sh -c 'find /code/private_media -type f &#124; wc -l' | 0 archivos |

Ademas: `uv lock --upgrade-package django`; `podman --connection
telar-fabulas-dev info --format '{{.Host.Security.Rootless}}'`; inspeccion de
montajes y healthchecks; `git -c core.autocrlf=false diff --check` sin errores.
Sondas HTTP reales de Windows: raiz 200, rutas `/media/...` y
`/private_media/...` 404. Las pruebas Django complementan estas sondas con
archivos existentes y sesiones de propietario/ajeno.

Durante el desarrollo se corrigio un doble cierre de FileResponse en el helper
de pruebas, que cerraba la conexion de PostgreSQL del TestCase. Se repitio la
suite completa despues de corregirlo; no fue un reinicio de la base de trabajo.
Compose usa el proveedor docker-compose instalado en Windows para comunicarse
con Podman; el motor verificado es Podman rootless, no Docker Desktop.

## Dependencias y configuracion

- `Django>=5.2.19,<5.3`, resuelto 5.2.19; actualizacion dentro de la misma LTS.
  Referencia: [anuncio oficial de seguridad del 3 de noviembre](https://www.djangoproject.com/weblog/2026/nov/03/security-releases/).
- `Pillow>=12.2,<13`, resuelto 12.2.0; antes ya era transitivo, ahora dependencia
  directa de la validacion. Referencia: [verificacion de imagenes de Pillow](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.verify).
- `uv.lock` actualizado sin renovar el resto de dependencias.
- Core registrado en INSTALLED_APPS, sin tablas propias.
- `STORAGES.default`: PrivateMediaStorage. StaticFilesStorage permanece publico.
- `PRIVATE_MEDIA_ROOT=/code/private_media` en Compose, o directorio absoluto
  equivalente fuera de contenedores. `CHARACTER_IMAGE_MAX_MB=5`.
- El archivo `.env` existente no se altero; nuevos valores tienen defaults
  compatibles y aparecen en `.env.example`. Dockerfile/ignores evitan incluir
  media privada en imagenes o Git.
- Se conserva el volumen `media_data`; solo cambia el destino del montaje para
  web y worker. No requiere cambiar las claves FileField en PostgreSQL.
- Migracion unica: `characters/0002_validate_private_images.py`. No modifica
  tablas ni contenido; actualiza metadatos de Django para el nuevo validador.

## Archivos creados (20)

Rutas relativas a la raiz del proyecto:

```text
app/apps/characters/migrations/0002_validate_private_images.py
app/apps/characters/validators.py
app/apps/core/__init__.py
app/apps/core/admin.py
app/apps/core/apps.py
app/apps/core/decorators.py
app/apps/core/files.py
app/apps/core/permissions.py
app/apps/core/storage.py
app/apps/core/templates/core/widgets/private_file_input.html
app/apps/core/templatetags/__init__.py
app/apps/core/templatetags/project_permissions.py
app/apps/core/tests/__init__.py
app/apps/core/tests/helpers.py
app/apps/core/tests/test_admin_security.py
app/apps/core/tests/test_permissions.py
app/apps/core/tests/test_private_files.py
app/apps/core/tests/test_rendering_security.py
app/apps/core/widgets.py
docs/refactoring/08-security-validation.md
```

## Archivos modificados (55)

Inventario comparado con hashes al iniciar Prompt 03, no contra HEAD: habia
cambios previos del usuario y de F0 que se conservaron.

```text
.dockerignore
.env.example
.gitignore
Dockerfile
README.md
app/apps/accounts/admin.py
app/apps/characters/admin.py
app/apps/characters/forms.py
app/apps/characters/models.py
app/apps/characters/tests.py
app/apps/characters/urls.py
app/apps/characters/views.py
app/apps/exports/admin.py
app/apps/exports/epub.py
app/apps/exports/forms.py
app/apps/exports/models.py
app/apps/exports/pdf.py
app/apps/exports/services.py
app/apps/exports/tasks.py
app/apps/exports/tests.py
app/apps/exports/views.py
app/apps/manuscripts/admin.py
app/apps/manuscripts/audit.py
app/apps/manuscripts/forms.py
app/apps/manuscripts/models.py
app/apps/manuscripts/services.py
app/apps/manuscripts/tests.py
app/apps/manuscripts/views.py
app/apps/notes/admin.py
app/apps/notes/forms.py
app/apps/notes/models.py
app/apps/notes/tests.py
app/apps/notes/views.py
app/apps/projects/admin.py
app/apps/projects/forms.py
app/apps/projects/models.py
app/apps/projects/tests.py
app/apps/projects/views.py
app/apps/styles/admin.py
app/apps/styles/views.py
app/config/settings/base.py
app/config/urls.py
app/templates/characters/character_detail.html
app/templates/characters/character_list.html
app/templates/manuscripts/manuscript_tree.html
app/templates/manuscripts/node_detail.html
app/templates/notes/note_detail.html
app/templates/notes/note_list.html
app/templates/projects/project_detail.html
app/templates/projects/project_list.html
compose.yaml
docs/refactoring/04-refactoring-roadmap.md
docs/refactoring/05-risk-register.md
pyproject.toml
uv.lock
```

No se modificaron las migraciones iniciales ni los documentos historicos
01/02/03/06/07, los reportes de inventario de F0, la TUI o archivos diff.

## Pendientes y siguiente fase

No es una certificacion de produccion. Siguen abiertos TLS/proxy/estaticos,
secretos seguros, readiness, backups restaurables, cuotas acumuladas y limites
de recursos. No publicar private_media desde el proxy; las validaciones de
imagen no sustituyen el aislamiento y los headers de descarga. Referencia:
[seguridad de archivos subidos en Django](https://docs.djangoproject.com/en/5.2/topics/security/#user-uploaded-content).

La proteccion de estado no resuelve ediciones concurrentes de texto ni agrega
constraints estructurales. Los comandos ORM directos y administracion de la
base son herramientas de confianza, no interfaces autorizadas para usuarios.
Snapshots, idempotencia/recuperacion de tareas, retencion y limpieza de blobs
siguen en F4/F5. Los archivos reemplazados no se purgan automaticamente en F1.

Recomendacion: F2, validador uniforme del arbol e identidad, despues de resolver
D01-D03/D16 y repetir el inventario si se cargan datos. No se implementaron
SceneVersion, nueva jerarquia, worldbuilding, suscripciones, Stripe, IA ni
nuevos exportadores. Ver [roadmap](04-refactoring-roadmap.md) y
[riesgos abiertos](05-risk-register.md).

