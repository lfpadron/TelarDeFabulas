from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import Action, check_project_permission, validate_project_action
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
    seen = {location_id} if location_id else set()
    while parent_id is not None:
        if parent_id in seen:
            raise ValidationError({"parent": _("La ubicación no puede depender de sí misma ni de sus descendientes.")})
        if parent_id not in parents:
            raise ValidationError({"parent": _("El padre debe pertenecer al mismo proyecto.")})
        seen.add(parent_id)
        parent_id = parents[parent_id]


def get_valid_parent_queryset(project, location=None):
    if location is not None and location.project_id != project.pk:
        raise ValidationError(_("La ubicación debe pertenecer al proyecto actual."))
    children = {}
    for pk, parent_id in _locations(project).values_list("pk", "parent_id"):
        children.setdefault(parent_id, []).append(pk)
    excluded = set()
    pending = [location.pk] if location and location.pk else []
    while pending:
        pk = pending.pop()
        if pk not in excluded:
            excluded.add(pk)
            pending.extend(children.get(pk, ()))
    return _locations(project).exclude(pk__in=excluded).only("id", "name").order_by("name", "pk")


def _siblings(project, parent_id, exclude_pk=None):
    return list(_locations(project).filter(parent_id=parent_id).exclude(pk=exclude_pk)
                .only("id", "position").order_by("position", "pk"))


def _position(value, count):
    if value in (None, ""):
        return count + 1
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise ValidationError(_("La posición debe ser un entero positivo.")) from None
    if number < 1 or str(number) != str(value):
        raise ValidationError(_("La posición debe ser un entero positivo."))
    return min(number, count + 1)


def _park(project, rows):
    # Free every affected slot before final numbering (including NULL/root siblings).
    maximum = _locations(project).aggregate(value=Max("position"))["value"] or 0
    for offset, row in enumerate(rows, start=1):
        row.position = maximum + offset
    if rows:
        GeographicLocation.objects.using(project._state.db).bulk_update(rows, ["position"])
    return maximum + len(rows) + 1


def _number(project, rows):
    for position, row in enumerate(rows, start=1):
        row.position = position
    if rows:
        GeographicLocation.objects.using(project._state.db).bulk_update(rows, ["position"])


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
            loaded = getattr(location, "_loaded_structure", {})
            for key in ("parent_id", "position"):
                if fields is not None and key not in fields and key.removesuffix("_id") not in fields:
                    setattr(location, key, getattr(existing, key))
                elif key in loaded and getattr(location, key) == loaded[key]:
                    setattr(location, key, getattr(existing, key))
                elif key in loaded and getattr(existing, key) != loaded[key]:
                    raise ValidationError(_("La ubicación fue movida. Recarga antes de cambiar su estructura."))
        location.project = project
        target = _siblings(project, location.parent_id, location.pk)
        structural = existing is None or (existing.parent_id, existing.position) != (location.parent_id, location.position)
        location.position = _position(location.position, len(target)) if structural else existing.position
        location.full_clean(validate_constraints=False)
        if structural:
            source = _siblings(project, existing.parent_id, location.pk) if existing and existing.parent_id != location.parent_id else []
            index = location.position - 1
            parked = target + source + ([existing] if existing else [])
            location.position = _park(project, parked)
        if fields is not None:
            kwargs["update_fields"] = set(fields) | {"position"}
        result = models.Model.save(location, *args, **kwargs)
        if structural:
            target.insert(index, location)
            _number(project, target)
            _number(project, source)
        location._loaded_structure = {key: getattr(location, key) for key in ("parent_id", "position")}
        return result


def _locked_location(location, user=None, action=Action.EDIT):
    project = lock_project(location.project_id, using=location._state.db or "default", user=user, action=action)
    current = _locations(project).select_for_update().get(pk=location.pk)
    current.project = project
    return current


def _move_locked(location, parent, new_position):
    parent_id = parent.pk if parent else None
    validate_parent(location.project, location.pk, parent_id)
    source = _siblings(location.project, location.parent_id, location.pk)
    target = source if location.parent_id == parent_id else _siblings(location.project, parent_id, location.pk)
    index = _position(new_position, len(target)) - 1
    _park(location.project, source + ([] if source is target else target) + [location])
    location.parent_id = parent_id
    location.updated_at = timezone.now()
    _locations(location.project).filter(pk=location.pk).update(parent_id=parent_id, updated_at=location.updated_at)
    target.insert(index, location)
    _number(location.project, target)
    if source is not target:
        _number(location.project, source)
    location.refresh_from_db()
    return location


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
