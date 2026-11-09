from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import Action, check_project_permission, validate_project_action
from apps.projects.models import Project

from .models import WorldbuildingEntry as Entry


EDITABLE_FIELDS = frozenset(("title", "category", "short_description", "content"))


class RevisionConflict(ValidationError):
    def __init__(self):
        super().__init__(_("Esta entrada cambió desde que la abriste. La operación no se guardó para evitar sobrescribir cambios recientes."))


def check_revision(current, expected_revision):
    if type(expected_revision) is not int or current.revision != expected_revision:
        raise RevisionConflict()


def validate_category(category):
    if category not in Entry.Category.values:
        raise ValidationError({"category": _("Selecciona una categoría válida.")})


def _lock_project(project_id, using, user=None, action=Action.EDIT):
    project = Project.objects.using(using).select_for_update().filter(pk=project_id).first()
    if project is None:
        raise ValidationError(_("La entrada debe pertenecer a un proyecto existente."))
    if user is not None:
        check_project_permission(user, project, action)
    validate_project_action(project, action)
    return project


def _entries(project):
    return Entry.objects.using(project._state.db).filter(project=project)


def _locked_entry(entry, using, user=None, action=Action.EDIT, metadata_only=False):
    project = _lock_project(entry.project_id, using, user, action)
    queryset = _entries(project).select_for_update()
    if metadata_only:
        queryset = queryset.only("id", "project_id", "category", "position", "revision", "updated_at")
    current = queryset.filter(pk=entry.pk).first()
    if current is None:
        raise ValidationError(_("La entrada ya no existe en este proyecto."))
    current.project = project
    return current


def _category_rows(project, category, exclude_pk=None):
    return list(_entries(project).filter(category=category).exclude(pk=exclude_pk)
                .only("id", "category", "position", "revision").order_by("position", "pk"))


def _apply_order(project, groups, *, skip_revision_pk=None):
    changes = [(row, category, position) for category, rows in groups for position, row in enumerate(rows)
               if (row.category, row.position) != (category, position)]
    if not changes:
        return
    queryset = _entries(project)
    maximum = queryset.aggregate(value=Max("position"))["value"] or 0
    now = timezone.now()
    # Park only changed rows, so immediate uniqueness holds during swaps and moves.
    for offset, (row, _, _) in enumerate(changes, start=1):
        row.position = maximum + offset
    queryset.bulk_update([row for row, _, _ in changes], ["position"])
    for row, category, position in changes:
        row.category, row.position = category, position
        if row.pk != skip_revision_pk:
            row.revision += 1
        row.updated_at = now
    queryset.bulk_update([row for row, _, _ in changes], ["category", "position", "revision", "updated_at"])


def _sync_instance(entry, current):
    for field in entry._meta.concrete_fields:
        setattr(entry, field.attname, getattr(current, field.attname))
    entry._state.db, entry._state.adding = current._state.db, False
    entry._loaded_revision = current.revision


def save_entry(entry, *, user=None, using=None, force_insert=False, force_update=False, update_fields=None):
    using = using or router.db_for_write(Entry, instance=entry)
    if update_fields is not None and not update_fields:
        return
    if not entry._state.adding:
        if force_insert:
            raise ValidationError(_("El identificador de entrada ya existe."))
        fields = set(update_fields) if update_fields is not None else EDITABLE_FIELDS
        if not fields <= EDITABLE_FIELDS:
            raise ValidationError(_("Solo se pueden editar el título, la categoría, la descripción y el contenido."))
        current = update_entry(entry, user=user, using=using,
            expected_revision=getattr(entry, "_loaded_revision", None), **{key: getattr(entry, key) for key in fields})
        _sync_instance(entry, current)
        return
    if entry.pk is not None or force_update or update_fields is not None:
        raise ValidationError(_("El identificador de una entrada nueva se asigna automáticamente."))
    with transaction.atomic(using=using):
        project = _lock_project(entry.project_id, using, user, Action.CREATE)
        entry.project = project
        validate_category(entry.category)
        rows = _category_rows(project, entry.category)
        position = entry.position
        if position is not None and (type(position) is not int or position < 0):
            raise ValidationError({"position": _("La posición debe ser un entero no negativo.")})
        index = len(rows) if position is None else min(position, len(rows))
        entry.position = (_entries(project).aggregate(value=Max("position"))["value"] or 0) + 1
        entry.revision = 1
        entry.full_clean(validate_constraints=False)
        models.Model.save(entry, using=using, force_insert=True)
        rows.insert(index, entry)
        _apply_order(project, [(entry.category, rows)], skip_revision_pk=entry.pk)
        entry._loaded_revision = entry.revision


def create_entry(project, *, user=None, **data):
    if not set(data) <= EDITABLE_FIELDS | {"position"}:
        raise ValidationError(_("La entrada contiene campos no editables."))
    entry = Entry(project=project, **data)
    save_entry(entry, user=user)
    return entry


def update_entry(entry, *, expected_revision, user=None, using=None, **changes):
    if not set(changes) <= EDITABLE_FIELDS:
        raise ValidationError(_("La entrada contiene campos no editables."))
    using = using or entry._state.db or "default"
    with transaction.atomic(using=using):
        current = _locked_entry(entry, using, user)
        check_revision(current, expected_revision)
        previous_category = current.category
        changed = any(getattr(current, key) != value for key, value in changes.items())
        for key, value in changes.items():
            setattr(current, key, value)
        current.full_clean(validate_constraints=False)
        if not changed:
            return current
        if current.category != previous_category:
            target_category = current.category
            source = _category_rows(current.project, previous_category, current.pk)
            target = _category_rows(current.project, target_category, current.pk)
            current.category = previous_category
            _apply_order(current.project, [(previous_category, source), (target_category, target + [current])], skip_revision_pk=current.pk)
        current.revision += 1
        models.Model.save(current, using=using, update_fields=[*EDITABLE_FIELDS, "position", "revision", "updated_at"])
        current._loaded_revision = current.revision
        return current


def change_entry_category(entry, category, *, expected_revision, user=None):
    validate_category(category)
    return update_entry(entry, category=category, expected_revision=expected_revision, user=user)


def _move_by(entry, offset, *, expected_revision, user=None):
    using = entry._state.db or "default"
    with transaction.atomic(using=using):
        current = _locked_entry(entry, using, user, metadata_only=True)
        check_revision(current, expected_revision)
        rows = _category_rows(current.project, current.category)
        index = next(i for i, row in enumerate(rows) if row.pk == current.pk)
        target = max(0, min(len(rows) - 1, index + offset))
        rows[index], rows[target] = rows[target], rows[index]
        _apply_order(current.project, [(current.category, rows)])
        current.refresh_from_db(fields=["position", "revision", "updated_at"])
        return current


def move_entry_up(entry, *, expected_revision, user=None):
    return _move_by(entry, -1, expected_revision=expected_revision, user=user)


def move_entry_down(entry, *, expected_revision, user=None):
    return _move_by(entry, 1, expected_revision=expected_revision, user=user)


def normalize_positions(project, category, *, user=None):
    validate_category(category)
    using = project._state.db or "default"
    with transaction.atomic(using=using):
        project = _lock_project(project.pk, using, user)
        _apply_order(project, [(category, _category_rows(project, category))])


def delete_entry(entry, *, expected_revision=None, user=None, using=None, keep_parents=False):
    using = using or entry._state.db or "default"
    if expected_revision is None:
        expected_revision = getattr(entry, "_loaded_revision", None)
    with transaction.atomic(using=using):
        current = _locked_entry(entry, using, user, Action.DELETE, metadata_only=True)
        check_revision(current, expected_revision)
        rows = _category_rows(current.project, current.category, current.pk)
        result = models.Model.delete(current, using=using, keep_parents=keep_parents)
        _apply_order(current.project, [(current.category, rows)])
        entry.pk = None
        return result
