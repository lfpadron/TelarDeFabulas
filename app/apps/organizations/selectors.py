from django.utils.translation import gettext_lazy as _

from apps.core.permissions import local_project_relations
from apps.core.trees import build_path, build_tree_events

from .models import CharacterOrganizationMembership, Organization


def tree_events(project):
    return build_tree_events(Organization.objects.filter(project=project).defer("detailed_description"), "organization",
        _("La jerarquía de organizaciones contiene un ciclo. Requiere revisión."),
        _("La jerarquía de organizaciones contiene elementos sin una raíz válida. Requiere revisión."))


def organization_path(organization):
    return build_path(Organization.objects.filter(project_id=organization.project_id).only("id", "parent_id", "name"),
                      organization.pk, _("La ruta de la organización no es válida. Requiere revisión."))


def project_memberships(project):
    return local_project_relations(CharacterOrganizationMembership.objects.filter(
        organization__project=project, character__project=project), "organization__project"
    ).select_related("character", "organization").only(
        "id", "character_id", "character__name", "organization_id", "organization__name",
        "position_title", "membership_status", "description", "joined_at_text", "left_at_text",
    )
