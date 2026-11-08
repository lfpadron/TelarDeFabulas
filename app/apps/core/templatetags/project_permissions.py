from django import template

from apps.core.permissions import Action, can_access_project


register = template.Library()


@register.simple_tag(takes_context=True)
def project_permissions(context, project):
    user = context["request"].user
    return {action.name.lower(): can_access_project(user, project, action) for action in Action}
