# Telar de Fabulas

La fragua digital del novelista.

Base tecnica inicial de un SaaS Django con PostgreSQL, Redis, Celery, Celery Beat y Gunicorn, preparada para ejecutarse con Podman y mantenerse compatible con Docker Compose.

## Stack

- Python 3.12
- Django 5.2 LTS
- PostgreSQL 16
- Redis 7
- Celery
- Celery Beat
- Gunicorn
- uv
- Podman Compose / Docker Compose

## Requisitos

En Windows, se recomienda Podman Desktop:

- Podman Desktop con soporte Compose.
- Docker Desktop con WSL 2 habilitado como alternativa compatible.
- uv instalado y disponible en `PATH`.

Si usas Podman por primera vez:

```powershell
podman machine start
```

## Dependencias con uv

`pyproject.toml` y `uv.lock` son la fuente de verdad de dependencias.

Sincronizar entorno local:

```powershell
uv sync
```

Actualizar el lockfile despues de cambiar dependencias:

```powershell
uv lock
```

Ejecutar comandos Django desde el entorno de uv:

```powershell
uv run python app/manage.py check
```

## Configuracion

El repositorio incluye un `.env` de desarrollo para levantar el proyecto de inmediato. Para preparar otro entorno, copia la plantilla:

```powershell
Copy-Item .env.example .env
```

Luego ajusta los valores de `.env`, especialmente:

- `DJANGO_SECRET_KEY`
- `POSTGRES_PASSWORD`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `CELERY_WORKER_CONCURRENCY`

## Levantar el proyecto

```powershell
podman compose up --build
```

La aplicacion queda disponible en:

```text
http://localhost:8000
```

La raiz debe mostrar:

```text
Telar de Fábulas está vivo.
```

Si necesitas usar Docker Desktop como alternativa:

```powershell
docker compose up --build
```

## TUI de control

La raiz del proyecto incluye `control_tui.bat`, una TUI local hecha con Textual para operar el sistema con Podman:

```powershell
.\control_tui.bat
```

La TUI permite:

- Arrancar la maquina de Podman.
- Construir la aplicacion.
- Encender los servicios.
- Abrir Google Chrome en `http://localhost:8000` con un perfil de pruebas controlado.
- Apagar la ventana de navegador controlada y detener los servicios.
- Ver logs de cada comando en pantalla.

Si Chrome está instalado en una ruta no estándar, define `TELAR_CHROME_PATH` antes de abrir la TUI.

## Migraciones

Con los contenedores arriba, abre otra terminal y ejecuta:

```powershell
podman compose exec web python manage.py makemigrations
podman compose exec web python manage.py migrate
```

Como `accounts` usa un usuario custom con email como login, en desarrollo puede ser necesario reiniciar el volumen de PostgreSQL si ya habias migrado con el usuario default de Django:

```powershell
podman compose down -v
podman compose up -d --build
podman compose exec web python manage.py migrate
```

Ese comando borra la base de datos local de desarrollo.

## Crear superusuario

```powershell
podman compose exec web python manage.py createsuperuser
```

El superusuario usa email como identificador principal. Despues entra al administrador:

```text
http://localhost:8000/admin/
```

## Cuentas y autenticacion

La app `accounts` define un usuario custom en `AUTH_USER_MODEL = "accounts.User"` y usa `email` como login.

Rutas disponibles:

```text
http://localhost:8000/register/
http://localhost:8000/login/
http://localhost:8000/profile/
```

El perfil permite editar email secundario, nombre, alias, idioma preferido y zona horaria. `user_type` y `status` quedan reservados para administracion.

## Proyectos

La app `projects` define la raiz de propiedad narrativa por usuario. Todas las vistas requieren sesion iniciada y un usuario solo puede acceder a sus propios proyectos.

Rutas disponibles:

```text
http://localhost:8000/projects/
http://localhost:8000/projects/create/
http://localhost:8000/projects/<id>/
http://localhost:8000/projects/<id>/edit/
http://localhost:8000/projects/<id>/delete/
http://localhost:8000/projects/<id>/restore/
```

Limites v01 por tipo de usuario:

- `FREE`: 1 proyecto no eliminado.
- `PREMIUM`: 10 proyectos no eliminados.
- `BUSINESS_ADMIN` y `TECH_ADMIN`: sin limite en esta fase.

Los proyectos con estado `DELETED` no cuentan para el limite. Los estados `ACTIVE`, `FROZEN` y `PENDING_DELETION` si cuentan.

El borrado es diferido: marcar para borrar cambia el proyecto a `PENDING_DELETION`, guarda la fecha de solicitud y programa el borrado real a 90 dias. No se borra texto ni archivos todavia. Un proyecto pendiente puede restaurarse, lo que vuelve el estado a `ACTIVE` y limpia las fechas de borrado diferido.

Pruebas de proyectos:

```powershell
podman compose exec web python manage.py test apps.projects
podman compose exec web python manage.py test apps.accounts apps.projects
```

## Manuscritos

La app `manuscripts` define el árbol narrativo base de cada proyecto. Cada nodo pertenece a un proyecto, puede tener un padre dentro del mismo proyecto y mantiene su posición entre hermanos.

Rutas disponibles:

```text
http://localhost:8000/projects/<id>/manuscript/
http://localhost:8000/projects/<id>/manuscript/create/
http://localhost:8000/projects/<id>/manuscript/<node_id>/
http://localhost:8000/projects/<id>/manuscript/<node_id>/edit/
http://localhost:8000/projects/<id>/manuscript/<node_id>/delete/
```

Tipos de nodo:

- `BOOK`: libro.
- `PART`: parte.
- `CHAPTER`: capítulo.
- `SCENE`: escena.
- `FRAGMENT`: fragmento.

Estados de nodo:

- `PENDING`: pendiente.
- `IN_PROGRESS`: en progreso.
- `DRAFT`: borrador.
- `REVIEW`: revisión.
- `FINISHED`: terminado.
- `PUBLISHABLE`: publicable.
- `PUBLISHED`: publicado.

El conteo de palabras se calcula automáticamente desde `content`. Si no se captura posición, el sistema asigna la siguiente posición disponible entre hermanos. No se permite crear o editar nodos en proyectos `DELETED` o `PENDING_DELETION`.

El borrado de nodos de manuscrito es físico en esta fase, pero solo se permite borrar nodos sin hijos. El reordenamiento visual tipo drag and drop queda pendiente para una fase posterior.

Pruebas de manuscritos:

```powershell
podman compose exec web python manage.py test apps.manuscripts
podman compose exec web python manage.py test apps.accounts apps.projects apps.manuscripts
podman compose exec web python manage.py makemigrations --check --dry-run
```

## Personajes

La app `characters` gestiona fichas de personajes por proyecto. Un personaje pertenece a un solo proyecto y queda preparado para relacionarse con nodos de manuscrito mediante menciones.

Rutas disponibles:

```text
http://localhost:8000/projects/<id>/characters/
http://localhost:8000/projects/<id>/characters/create/
http://localhost:8000/projects/<id>/characters/<character_id>/
http://localhost:8000/projects/<id>/characters/<character_id>/edit/
http://localhost:8000/projects/<id>/characters/<character_id>/delete/
```

Importancia narrativa:

- `PRINCIPAL`: personaje central; su ficha exige más campos para considerarse completa.
- `SECUNDARIA`: personaje recurrente o de soporte.
- `FIGURANTE`: aparición breve o funcional.

Rol narrativo:

- `PROTAGONISTA`
- `DEUTERAGONISTA`
- `TRITAGONISTA`
- `ANTAGONISTA`
- `PERSONAJE_IMPORTANTE`
- `SECUNDARIO`
- `INCIDENTAL`
- `OTRO`

Si el rol narrativo no es `OTRO`, el campo de rol personalizado se limpia automáticamente.

Papel dramático:

- `HEROE`
- `HEROINA`
- `VILLANO`
- `INTERES_ROMANTICO`
- `MENTOR`
- `ALIADO`
- `RIVAL`
- `TRAIDOR`
- `PROTEGIDO`
- `CATALIZADOR`
- `NARRADOR`
- `ALIVIO_COMICO`
- `OTRO`

La interfaz actual permite seleccionar múltiples papeles dramáticos estándar. `OTRO` con papel personalizado queda preparado en el modelo y admin para una fase posterior.

Completitud:

`completion_percentage` se calcula en tiempo real y no se guarda en base de datos. Los campos considerados cambian según la importancia narrativa: los personajes principales requieren una ficha más completa que secundarios o figurantes. Este porcentaje solo informa; no bloquea el flujo de escritura.

Imagen:

El campo `image` acepta archivos con extensiones comunes (`jpg`, `jpeg`, `png`, `gif`, `webp`) y se guarda bajo `media/characters/<project_id>/...`. El límite de tamaño queda pendiente para una configuración posterior.

Menciones:

`CharacterMention` deja preparada la relación entre personajes y nodos de manuscrito. En esta fase no hay interfaz completa por escena; el modelo y admin validan que personaje y nodo pertenezcan al mismo proyecto.

Pruebas de personajes:

```powershell
podman compose exec web python manage.py test apps.characters
podman compose exec web python manage.py test apps.accounts apps.projects apps.manuscripts apps.characters
podman compose exec web python manage.py makemigrations --check --dry-run
```

## Notas, ideas y pendientes

La app `notes` gestiona material de trabajo del autor que no forma parte del texto final del manuscrito. Cada entrada pertenece a un proyecto y puede asociarse opcionalmente a un nodo de manuscrito, a un personaje, o a ambos.

Rutas disponibles:

```text
http://localhost:8000/projects/<id>/notes/
http://localhost:8000/projects/<id>/notes/create/
http://localhost:8000/projects/<id>/notes/<note_id>/
http://localhost:8000/projects/<id>/notes/<note_id>/edit/
http://localhost:8000/projects/<id>/notes/<note_id>/delete/
```

Tipos:

- `NOTE`: nota general de trabajo.
- `IDEA`: posibilidad narrativa o material por explorar.
- `TASK`: pendiente accionable.

Estados:

- `OPEN`: abierta.
- `IN_PROGRESS`: en progreso.
- `DONE`: terminada.
- `DISCARDED`: descartada.

Cuando una nota cambia a `DONE`, `completed_at` se llena automáticamente. Si vuelve a otro estado, `completed_at` se limpia.

Prioridades:

- `LOW`: baja.
- `MEDIUM`: media.
- `HIGH`: alta.
- `URGENT`: urgente.

Relaciones opcionales:

- Una nota puede estar ligada solo al proyecto.
- También puede asociarse a un `ManuscriptNode`.
- También puede asociarse a un `Character`.
- Puede tener nodo y personaje al mismo tiempo, siempre que ambos pertenezcan al mismo proyecto.

Desde el detalle de un nodo de manuscrito se puede crear una nota preasociada con:

```text
/projects/<id>/notes/create/?node=<node_id>
```

Desde el detalle de un personaje se puede crear una nota preasociada con:

```text
/projects/<id>/notes/create/?character=<character_id>
```

La lista permite filtros simples por querystring:

```text
?type=NOTE
?type=IDEA
?type=TASK
?status=OPEN
?priority=HIGH
```

Pruebas de notas:

```powershell
podman compose exec web python manage.py test apps.notes
podman compose exec web python manage.py test apps.accounts apps.projects apps.manuscripts apps.characters apps.notes
podman compose exec web python manage.py makemigrations --check --dry-run
```

## Verificar Celery

Revisa que el worker responda:

```powershell
podman compose exec worker celery -A config inspect ping
```

Debe responder con un `pong`.

Tambien puedes revisar logs:

```powershell
podman compose logs worker
podman compose logs beat
```

## Servicios

- `web`: Django servido por Gunicorn en el puerto 8000.
- `postgres`: base de datos PostgreSQL con volumen persistente.
- `redis`: broker Redis para Celery.
- `worker`: worker de Celery.
- `beat`: scheduler de Celery Beat.

Nginx queda pendiente para la configuracion de produccion.

## Estructura

```text
.
├── compose.yaml
├── Dockerfile
├── .env.example
├── pyproject.toml
├── uv.lock
├── control_tui.bat
├── tools/
│   └── control_tui.py
└── app/
    ├── manage.py
    ├── config/
    │   ├── settings/
    │   │   ├── base.py
    │   │   ├── dev.py
    │   │   └── prod.py
    │   ├── urls.py
    │   ├── wsgi.py
    │   ├── asgi.py
    │   └── celery.py
    └── apps/
        ├── accounts/
        ├── projects/
        ├── manuscripts/
        ├── characters/
        ├── notes/
        ├── exports/
        ├── styles/
        └── admin_dashboard/
```

## Siguiente fase sugerida

1. Implementar `styles` para guías de estilo, tono y voz narrativa.
2. Agregar interfaz completa para menciones de personajes por escena.
3. Preparar reordenamiento de nodos del árbol narrativo.
4. Incorporar tareas reales de exportacion con Celery.
5. Diseñar tablero futuro para pendientes sin implementarlo aún.
# TelarDeFabulas
