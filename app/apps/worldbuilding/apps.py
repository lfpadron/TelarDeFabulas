from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class WorldbuildingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.worldbuilding"
    verbose_name = _("Construcción de mundos")
