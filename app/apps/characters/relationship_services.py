from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import Action, check_project_permission, get_user_project, validate_project_action
from apps.projects.models import Project
from .models import Character, CharacterRelationship

EDITABLE_FIELDS = ("source_character", "target_character", "relationship_type", "custom_relationship_type", "description", "is_reciprocal")
ENDPOINTS = ("source_character", "target_character")


def _lock_project(pk, using, user=None, action=Action.EDIT):
    project = Project.objects.using(using).select_for_update().filter(pk=pk).first()
    if project is None:
        raise ValidationError(_("La relación debe pertenecer a un proyecto existente."))
    if user is not None:
        check_project_permission(user, project, action)
    validate_project_action(project, action)
    return project


def _persist(project_id, *, relationship=None, user=None, using="default", **data):
    if not set(data) <= set(EDITABLE_FIELDS) | {f"{key}_id" for key in ENDPOINTS}:
        raise ValidationError(_("La relación contiene campos no editables."))
    with transaction.atomic(using=using):
        project = _lock_project(project_id, using, user, Action.EDIT if relationship else Action.CREATE)
        if relationship is None:
            current = CharacterRelationship(project=project)
        else:
            current = CharacterRelationship.objects.using(using).select_for_update().filter(pk=relationship.pk, project=project).first()
            if current is None:
                raise ValidationError(_("La relación ya no existe en este proyecto."))
            current.project = project
        for key, value in data.items():
            setattr(current, key, value)
        for key in ENDPOINTS:
            character = Character.objects.using(using).filter(pk=getattr(current, f"{key}_id"), project=project).only("id", "name", "project_id").first()
            if character is None:
                raise ValidationError({key: _("Selecciona un personaje de este proyecto.")})
            setattr(current, key, character)
        current.full_clean()
        models.Model.save(current, using=using)
        return current


def create_relationship(project, *, user=None, **data):
    return _persist(project.pk, user=user, using=project._state.db or "default", **data)


def update_relationship(relationship, *, user=None, **data):
    return _persist(relationship.project_id, relationship=relationship, user=user, using=relationship._state.db or "default", **data)


def save_relationship(instance, *args, **kwargs):
    if args or kwargs.get("using") not in (None, "default"):
        raise ValidationError(_("Operación de guardado no permitida."))
    if instance._state.adding and (instance.pk is not None or kwargs.get("force_update")):
        raise ValidationError(_("El identificador se asigna automáticamente."))
    if not instance._state.adding and kwargs.get("force_insert"):
        raise ValidationError(_("La relación ya existe."))
    fields = kwargs.get("update_fields")
    if fields is not None and not fields:
        return
    selected = set(EDITABLE_FIELDS) if fields is None else {key.removesuffix("_id") if key in {f"{name}_id" for name in ENDPOINTS} else key for key in fields}
    if not selected <= set(EDITABLE_FIELDS):
        raise ValidationError(_("La relación contiene campos no editables."))
    data = {f"{key}_id" if key in ENDPOINTS else key: getattr(instance, f"{key}_id" if key in ENDPOINTS else key) for key in selected}
    saved = _persist(instance.project_id, relationship=None if instance._state.adding else instance, **data)
    for field in instance._meta.concrete_fields:
        setattr(instance, field.attname, getattr(saved, field.attname))
    instance._state.adding, instance._state.db = False, saved._state.db


def delete_relationship(relationship, *, user=None, using=None, keep_parents=False):
    using = using or relationship._state.db or "default"
    with transaction.atomic(using=using):
        project = _lock_project(relationship.project_id, using, user, Action.DELETE)
        current = CharacterRelationship.objects.using(using).select_for_update().filter(pk=relationship.pk, project=project).first()
        if current is None:
            raise ValidationError(_("La relación ya no existe en este proyecto."))
        result = models.Model.delete(current, using=using, keep_parents=keep_parents)
        relationship.pk = None
        return result


def get_relationships_for_character(character, *, user=None):
    from .relationship_selectors import project_relationships
    project = get_user_project(user, character.project_id) if user is not None else character.project
    validate_project_action(project, Action.VIEW)
    return project_relationships(project).filter(Q(source_character=character) | Q(target_character=character))
