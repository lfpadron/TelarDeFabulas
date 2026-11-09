from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import Action, check_project_permission, validate_project_action
from apps.core import trees
from apps.projects.models import Project

from .models import GeographicLocation


def _locations(project):
    return GeographicLocation.objects.using(project._state.db).filter(project=project)


def lock_project(project_id, *, using="default", user=None, action=Action.EDIT):
    if not project_id:
        raise ValidationError(_("La ubicación debe pertenecer a un proyecto."))
    project = Project.objects.using(using).select_for_update().get(pk=project_id)
    if user is not None:
        check_project_permission(user, project, action)
    validate_project_action(project, action)
    return project


def validate_parent(project, location_id, parent_id):
    parents = dict(_locations(project).values_list("pk", "parent_id"))
    trees.validate_parent_chain(parents, location_id, parent_id,
        _("La ubicación no puede depender de sí misma ni de sus descendientes."),
        _("El padre debe pertenecer al mismo proyecto."))


def get_valid_parent_queryset(project, location=None):
    if location is not None and location.project_id != project.pk:
        raise ValidationError(_("La ubicación debe pertenecer al proyecto actual."))
    excluded = trees.descendant_ids(_locations(project).values_list("pk", "parent_id"), location.pk if location else None)
    return _locations(project).exclude(pk__in=excluded).only("id", "name").order_by("name", "pk")


def _siblings(project, parent_id, exclude_pk=None):
    return trees.siblings(_locations(project), parent_id, exclude_pk)


def _park(project, rows):
    return trees.park_positions(_locations(project), rows)


def _number(project, rows):
    return trees.number_positions(_locations(project), rows)


def normalize_positions(project, parent=None, *, user=None):
    with transaction.atomic(using=project._state.db or "default"):
        project = lock_project(project.pk, using=project._state.db or "default", user=user)
        parent_id = parent.pk if parent else None
        validate_parent(project, None, parent_id)
        rows = _siblings(project, parent_id)
        _park(project, rows)
        _number(project, rows)
        return rows


def save_location(location, *args, **kwargs):
    using = kwargs.get("using") or router.db_for_write(GeographicLocation, instance=location)
    fields = kwargs.get("update_fields")
    if fields is not None and not fields:
        return
    with transaction.atomic(using=using):
        project = lock_project(location.project_id, using=using)
        existing = None
        if not location._state.adding:
            existing = GeographicLocation.objects.using(using).select_for_update().get(pk=location.pk)
            if existing.project_id != project.pk:
                raise ValidationError(_("No se permite trasladar ubicaciones a otro proyecto."))
            trees.preserve_current_structure(location, existing, fields,
                _("La ubicación fue movida. Recarga antes de cambiar su estructura."))
        location.project = project
        return trees.save_ordered_node(location, existing, *args, **kwargs)


def _locked_location(location, user=None, action=Action.EDIT):
    project = lock_project(location.project_id, using=location._state.db or "default", user=user, action=action)
    current = _locations(project).select_for_update().get(pk=location.pk)
    current.project = project
    return current


def _move_locked(location, parent, new_position):
    parent_id = parent.pk if parent else None
    validate_parent(location.project, location.pk, parent_id)
    return trees.move_ordered_node(_locations(location.project), location, parent_id, new_position)


def move_location(location, new_parent, new_position=None, *, user=None):
    with transaction.atomic(using=location._state.db or "default"):
        return _move_locked(_locked_location(location, user), new_parent, new_position)


def _move_by(location, offset, user):
    with transaction.atomic(using=location._state.db or "default"):
        location = _locked_location(location, user)
        siblings = _siblings(location.project, location.parent_id)
        index = next(i for i, row in enumerate(siblings) if row.pk == location.pk)
        position = max(1, min(len(siblings), index + 1 + offset))
        return _move_locked(location, location.parent, position)


def move_location_up(location, *, user=None):
    return _move_by(location, -1, user)


def move_location_down(location, *, user=None):
    return _move_by(location, 1, user)


def deletion_blockers(location):
    reasons = []
    if location.children.exists():
        reasons.append(_("No puedes eliminar una ubicación con ubicaciones hijas."))
    if location.residents.exists():
        reasons.append(_("No puedes eliminar una ubicación con personajes habitantes. Cambia o retira su residencia primero."))
    if location.headquartered_organizations.exists():
        reasons.append(_("No puedes eliminar una ubicación que es sede de organizaciones. Cambia o retira sus sedes primero."))
    return reasons


def delete_location(location, *, user=None, using=None, keep_parents=False):
    using = using or location._state.db or "default"
    with transaction.atomic(using=using):
        current = _locked_location(location, user, Action.DELETE)
        reasons = deletion_blockers(current)
        if reasons:
            raise ValidationError(reasons)
        siblings = _siblings(current.project, current.parent_id, current.pk)
        result = models.Model.delete(current, using=using, keep_parents=keep_parents)
        _park(current.project, siblings)
        _number(current.project, siblings)
        location.pk = None
        return result
