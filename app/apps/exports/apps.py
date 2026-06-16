from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ExportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.exports"
    verbose_name = _("Exportaciones")
