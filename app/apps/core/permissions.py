from enum import StrEnum

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _


class Action(StrEnum):
    VIEW = "VIEW"
    CREATE = "CREATE"
    EDIT = "EDIT"
    DELETE = "DELETE"
    EXPORT = "EXPORT"
    DOWNLOAD = "DOWNLOAD"
    RESTORE = "RESTORE"


VISIBLE_STATUSES = ("ACTIVE", "FROZEN", "PENDING_DELETION")
READ_ONLY_MESSAGE = _("Este proyecto es de solo lectura. No se puede modificar su contenido.")
ACTION_STATUSES = {
    Action.VIEW: VISIBLE_STATUSES,
    Action.CREATE: ("ACTIVE",),
    Action.EDIT: ("ACTIVE",),
    Action.DELETE: ("ACTIVE",),
    Action.EXPORT: VISIBLE_STATUSES,
    Action.DOWNLOAD: VISIBLE_STATUSES,
    Action.RESTORE: ("FROZEN", "PENDING_DELETION"),
}


def project_allows_action(project, action):
    return project is not None and project.status in ACTION_STATUSES.get(action, ())


def can_access_project(user, project, action=Action.VIEW):
    return bool(
        user and user.is_authenticated and user.is_active and user.pk and project is not None
        and project.user_id == user.pk and project_allows_action(project, action)
    )


def can_view_project(user, project):
    return can_access_project(user, project, Action.VIEW)


def can_edit_project(user, project):
    return can_access_project(user, project, Action.EDIT)


def can_export_project(user, project):
    return can_access_project(user, project, Action.EXPORT)


def can_download_export(user, export_job):
    return bool(
        can_access_project(user, export_job.project, Action.DOWNLOAD)
        and export_job.user_id == user.pk and export_job.downloadable
    )


def check_project_permission(user, project, action=Action.VIEW):
    if not can_view_project(user, project):
        raise Http404(_("Proyecto no encontrado."))
    if not can_access_project(user, project, action):
        raise PermissionDenied(READ_ONLY_MESSAGE)


def validate_project_action(project, action=Action.EDIT):
    if not project_allows_action(project, action):
        raise ValidationError(READ_ONLY_MESSAGE)


def visible_projects(user):
    from apps.projects.models import Project

    if not user or not user.is_authenticated or not user.is_active:
        return Project.objects.none()
    return Project.objects.filter(user=user, status__in=VISIBLE_STATUSES)


def get_user_project(user, project_pk, action=Action.VIEW, *, for_update=False):
    queryset = visible_projects(user)
    if for_update:
        queryset = queryset.select_for_update()
    project = get_object_or_404(queryset, pk=project_pk)
    check_project_permission(user, project, action)
    return project


def local_project_relations(queryset, project_path="project"):
    """Broken legacy links must not reveal another project's titles or content."""
    for field in queryset.model._meta.fields:
        if field.name == "node" and field.related_model._meta.label_lower == "manuscripts.manuscriptnode":
            from apps.manuscripts.visibility import hidden_node_ids

            hidden = hidden_node_ids(queryset.order_by().values(f"{project_path}_id"), queryset.db)
            queryset = queryset.exclude(node_id__in=hidden)
        if field.name == "style_template":
            queryset = queryset.filter(
                Q(style_template__is_system=True)
                | Q(style_template__user=F(f"{project_path}__user"))
            )
        if field.name not in {"parent", "node", "root_node", "character", "residence", "headquarters", "organization"}:
            continue
        queryset = queryset.filter(
            Q(**{f"{field.name}__isnull": True}) | Q(**{f"{field.name}__project": F(project_path)})
        )
    return queryset


def user_can_manage_personal_styles(user):
    return bool(user and user.is_authenticated and user.is_active and user.user_type in (
        "PREMIUM", "BUSINESS_ADMIN", "TECH_ADMIN",
    ))
