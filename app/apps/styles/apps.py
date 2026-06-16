from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class StylesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.styles"
    verbose_name = _("Estilos")
