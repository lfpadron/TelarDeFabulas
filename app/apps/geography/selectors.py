from django.utils.translation import gettext_lazy as _

from apps.core.trees import build_path, build_tree_events

from .models import GeographicLocation


def tree_events(project):
    return build_tree_events(GeographicLocation.objects.filter(project=project).defer("detailed_description"), "location",
        _("La jerarquía geográfica contiene un ciclo. Requiere revisión."),
        _("La jerarquía geográfica contiene ubicaciones sin una raíz válida. Requiere revisión."))


def location_path(location):
    return build_path(GeographicLocation.objects.filter(project_id=location.project_id).only("id", "parent_id", "name"),
                      location.pk, _("La ruta geográfica no es válida. Requiere revisión."))
