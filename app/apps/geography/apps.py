from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class GeographyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.geography"
    verbose_name = _("Geografía")
