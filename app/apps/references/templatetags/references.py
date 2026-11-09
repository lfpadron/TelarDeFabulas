from urllib.parse import urlencode

from django import template
from django.core.paginator import Paginator

from apps.core.permissions import can_access_project
from apps.references.models import TARGETS
from apps.references.selectors import project_associations
from apps.references.services import entity_field

register = template.Library()


@register.inclusion_tag("references/_entity_section.html", takes_context=True)
def reference_section(context, project, entity):
    request = context["request"]
    if entity.project_id != project.pk or not can_access_project(request.user, project):
        return {}
    key = entity_field(entity)
    query = project_associations(project).filter(**{key: entity})
    return {"project": project, "request": request, "user": request.user,
            "entity_query": urlencode({TARGETS[key][1]: entity.pk}),
            "reference_page": Paginator(query, 50).get_page(request.GET.get("references_page"))}
