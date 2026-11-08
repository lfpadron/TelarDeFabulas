import os
from pathlib import Path
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    value = os.getenv(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def env_int(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def bounded_env_int(name, default, maximum):
    try:
        value = int(os.getenv(name, str(default)))
        if not 1 <= value <= maximum:
            raise ValueError
        return value
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be an integer between 1 and {maximum}.") from None


APP_DIR = Path(__file__).resolve().parent.parent.parent
BASE_DIR = APP_DIR.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core.apps.CoreConfig",
    "apps.accounts.apps.AccountsConfig",
    "apps.projects.apps.ProjectsConfig",
    "apps.manuscripts.apps.ManuscriptsConfig",
    "apps.characters.apps.CharactersConfig",
    "apps.geography.apps.GeographyConfig",
    "apps.notes.apps.NotesConfig",
    "apps.exports.apps.ExportsConfig",
    "apps.styles.apps.StylesConfig",
    "apps.admin_dashboard.apps.AdminDashboardConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [APP_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "telar_fabulas"),
        "USER": os.getenv("POSTGRES_USER", "telar"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "telar_dev_password"),
        "HOST": os.getenv("POSTGRES_HOST", "postgres"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }
}

LANGUAGE_CODE = "es-mx"
LANGUAGES = [
    ("es-mx", "Español de México"),
    ("en-us", "English United States"),
]
LOCALE_PATHS = [APP_DIR / "locale"]

TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [APP_DIR / "static"]

MEDIA_URL = "/private_media/"
MEDIA_ROOT = Path(os.getenv("PRIVATE_MEDIA_ROOT", str(BASE_DIR / "private_media")))
STORAGES = {
    "default": {"BACKEND": "apps.core.storage.PrivateMediaStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
CHARACTER_IMAGE_MAX_MB = max(1, env_int("CHARACTER_IMAGE_MAX_MB", 5))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "profile"
LOGOUT_REDIRECT_URL = "home"

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "recover-exports": {"task": "apps.exports.recover_exports", "schedule": 60.0},
    "export-notifications": {"task": "apps.exports.send_pending_notifications", "schedule": 60.0},
    "expire-exports": {"task": "apps.exports.cleanup_expired_exports", "schedule": 86400.0},
}

EXPORT_PREVIEW_MAX_NODES = env_int("EXPORT_PREVIEW_MAX_NODES", 12)
EXPORT_PREVIEW_MAX_WORDS = env_int("EXPORT_PREVIEW_MAX_WORDS", 2500)
EXPORT_SNAPSHOT_MAX_BYTES = max(1024, env_int("EXPORT_SNAPSHOT_MAX_BYTES", 20 * 1024 * 1024))
EXPORT_SNAPSHOT_MAX_NODES = max(1, env_int("EXPORT_SNAPSHOT_MAX_NODES", 10000))

EXPORT_READY_RETENTION_DAYS = bounded_env_int("EXPORT_READY_RETENTION_DAYS", 7, 365)
EXPORT_FAILED_RETENTION_DAYS = bounded_env_int("EXPORT_FAILED_RETENTION_DAYS", 7, 365)
EXPORT_MAX_ATTEMPTS = bounded_env_int("EXPORT_MAX_ATTEMPTS", 3, 10)
EXPORT_STALE_MINUTES = bounded_env_int("EXPORT_STALE_MINUTES", 30, 1440)
EXPORT_RETRY_BASE_SECONDS = bounded_env_int("EXPORT_RETRY_BASE_SECONDS", 60, 3600)

EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.filebased.EmailBackend")
EMAIL_FILE_PATH = MEDIA_ROOT / "development-emails"
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = bounded_env_int("EMAIL_PORT", 587, 65535)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = 15
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "Telar de Fabulas <no-reply@localhost>")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
_public_url = urlsplit(PUBLIC_BASE_URL)
if (_public_url.scheme not in ("http", "https") or not _public_url.netloc
        or _public_url.username or _public_url.password or _public_url.query or _public_url.fragment
        or _public_url.path or any(c.isspace() for c in PUBLIC_BASE_URL)):
    raise ImproperlyConfigured("PUBLIC_BASE_URL must be an HTTP(S) origin without credentials or a path.")
