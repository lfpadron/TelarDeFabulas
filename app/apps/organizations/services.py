from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.utils.translation import gettext_lazy as _

from apps.core import trees
from apps.core.permissions import Action, check_project_permission, validate_project_action
from apps.projects.models import Project

from .models import Organization


def _organizations(project):
    return Organization.objects.using(project._state.db).filter(project=project)


def lock_project(project_id, *, using="default", user=None, action=Action.EDIT):
    if not project_id:
        raise ValidationError(_("La organización debe pertenecer a un proyecto."))
    project = Project.objects.using(using).select_for_update().get(pk=project_id)
    if user is not None:
        check_project_permission(user, project, action)
    validate_project_action(project, action)
    return project


def validate_parent(project, organization_id, parent_id):
    trees.validate_parent_chain(dict(_organizations(project).values_list("pk", "parent_id")), organization_id, parent_id,
        _("La organización no puede depender de sí misma ni de sus subordinadas."),
        _("La organización superior debe pertenecer al mismo proyecto."))


def get_valid_parent_queryset(project, organization=None):
    if organization is not None and organization.project_id != project.pk:
        raise ValidationError(_("La organización debe pertenecer al proyecto actual."))
    queryset = _organizations(project)
    excluded = trees.descendant_ids(queryset.values_list("pk", "parent_id"), organization.pk if organization else None)
    return queryset.exclude(pk__in=excluded).only("id", "name").order_by("name", "pk")


def normalize_positions(project, parent=None, *, user=None):
    with transaction.atomic(using=project._state.db or "default"):
        project = lock_project(project.pk, using=project._state.db or "default", user=user)
        parent_id = parent.pk if parent else None
        validate_parent(project, None, parent_id)
        queryset = _organizations(project)
        rows = trees.siblings(queryset, parent_id)
        trees.park_positions(queryset, rows)
        trees.number_positions(queryset, rows)
        return rows


def save_organization(organization, *args, user=None, **kwargs):
    using = kwargs.get("using") or router.db_for_write(Organization, instance=organization)
    fields = kwargs.get("update_fields")
    if fields is not None and not fields:
        return
    with transaction.atomic(using=using):
        project = lock_project(organization.project_id, using=using, user=user)
        existing = None
        if organization.pk:
            existing = Organization.objects.using(using).select_for_update().filter(pk=organization.pk).first()
            if existing and organization._state.adding:
                raise ValidationError(_("El identificador de organización ya existe."))
            if not existing and not organization._state.adding:
                raise ValidationError(_("La organización ya no existe."))
        if existing:
            if existing.project_id != project.pk:
                raise ValidationError(_("No se permite trasladar organizaciones a otro proyecto."))
            trees.preserve_current_structure(organization, existing, fields,
                _("La organización fue movida. Recarga antes de cambiar su estructura."))
            if fields is not None:
                for key in ("organization_type", "custom_organization_type", "headquarters_id"):
                    if key not in fields and key.removesuffix("_id") not in fields:
                        setattr(organization, key, getattr(existing, key))
                kwargs["update_fields"] = set(fields) | {"custom_organization_type"}
        organization.project = project
        return trees.save_ordered_node(organization, existing, *args, **kwargs)


def _locked_organization(organization, user=None, action=Action.EDIT):
    project = lock_project(organization.project_id, using=organization._state.db or "default", user=user, action=action)
    current = _organizations(project).select_for_update().get(pk=organization.pk)
    current.project = project
    return current


def _move_locked(organization, parent, position):
    parent_id = parent.pk if parent else None
    validate_parent(organization.project, organization.pk, parent_id)
    return trees.move_ordered_node(_organizations(organization.project), organization, parent_id, position)


def move_organization(organization, new_parent, new_position=None, *, user=None):
    with transaction.atomic(using=organization._state.db or "default"):
        return _move_locked(_locked_organization(organization, user), new_parent, new_position)


def _move_by(organization, offset, user):
    with transaction.atomic(using=organization._state.db or "default"):
        organization = _locked_organization(organization, user)
        siblings = trees.siblings(_organizations(organization.project), organization.parent_id)
        index = next(i for i, row in enumerate(siblings) if row.pk == organization.pk)
        return _move_locked(organization, organization.parent, max(1, min(len(siblings), index + 1 + offset)))


def move_organization_up(organization, *, user=None):
    return _move_by(organization, -1, user)


def move_organization_down(organization, *, user=None):
    return _move_by(organization, 1, user)


def deletion_blockers(organization):
    reasons = []
    if organization.children.exists():
        reasons.append(_("No puedes eliminar una organización con organizaciones subordinadas."))
    if organization.memberships.exists():
        reasons.append(_("No puedes eliminar una organización con afiliaciones de personajes, incluidas las anteriores."))
    return reasons


def delete_organization(organization, *, user=None, using=None, keep_parents=False):
    using = using or organization._state.db or "default"
    with transaction.atomic(using=using):
        current = _locked_organization(organization, user, Action.DELETE)
        reasons = deletion_blockers(current)
        if reasons:
            raise ValidationError(reasons)
        queryset = _organizations(current.project)
        siblings = trees.siblings(queryset, current.parent_id, current.pk)
        result = models.Model.delete(current, using=using, keep_parents=keep_parents)
        trees.park_positions(queryset, siblings)
        trees.number_positions(queryset, siblings)
        organization.pk = None
        return result
