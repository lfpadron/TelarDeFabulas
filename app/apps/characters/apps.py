from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CharactersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.characters"
    verbose_name = _("Personajes")
