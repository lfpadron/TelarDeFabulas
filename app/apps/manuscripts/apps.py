from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ManuscriptsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.manuscripts"
    verbose_name = _("Manuscritos")
