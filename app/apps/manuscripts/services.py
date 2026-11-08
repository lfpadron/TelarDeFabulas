from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import Action, check_project_permission, validate_project_action
from apps.projects.models import Project

from .hierarchy import ALLOWED_CHILD_TYPES, editable_node_ids, load_structure, validate_node_hierarchy
from .models import ManuscriptNode, count_words


def sibling_queryset(project, parent):
    return ManuscriptNode.objects.using(project._state.db).filter(project=project, parent=parent)


def ordered_siblings(project, parent):
    return sibling_queryset(project, parent).order_by("position", "created_at", "pk")


def lock_project(project_id, *, using="default", user=None, action=Action.EDIT):
    if not project_id:
        raise ValidationError(_("El nodo debe pertenecer a un proyecto."))
    project = Project.objects.using(using).select_for_update().get(pk=project_id)
    if user is not None:
        check_project_permission(user, project, action)
    validate_project_action(project, action)
    return project


def validate_parent_for_node(node, new_parent):
    validate_project_action(node.project)
    if new_parent is not None and new_parent.project_id != node.project_id:
        raise ValidationError(_("El nuevo padre debe pertenecer al mismo proyecto."))
    candidate = ManuscriptNode(project=node.project, parent=new_parent, node_type=node.node_type,
                               title=node.title, position=node.position)
    candidate.pk = node.pk
    candidate._state.db = node._state.db
    validate_node_hierarchy(candidate)


def get_valid_parent_queryset(project, node=None, *, node_type=None):
    kind = node_type or (node.node_type if node else None)
    valid_types = [parent for parent, children in ALLOWED_CHILD_TYPES.items() if kind in children] if kind else ("BOOK", "PART", "CHAPTER")
    structure = load_structure(project.pk, project._state.db or "default")
    ids = editable_node_ids(structure)
    if node and node.pk:
        ids.difference_update({node.pk, *node.descendant_ids()})
    return ManuscriptNode.objects.filter(project=project, pk__in=ids, node_type__in=valid_types).order_by("parent_id", "position", "created_at", "pk")


def _checked_siblings(project, parent, *, exclude_pk=None):
    if parent is not None and parent.project_id != project.pk:
        raise ValidationError(_("El padre debe pertenecer al mismo proyecto."))
    siblings = list(ordered_siblings(project, parent).exclude(pk=exclude_pk))
    structure = load_structure(project.pk, project._state.db or "default")
    for sibling in siblings:
        validate_node_hierarchy(sibling, structure)
    return siblings


def _write_positions(siblings, using):
    changed = []
    for position, sibling in enumerate(siblings, start=1):
        if sibling.position != position:
            sibling.position = position
            changed.append(sibling)
    if changed:
        ManuscriptNode.objects.using(using).bulk_update(changed, ["position"])
    return siblings


def normalize_positions(project, parent, *, user=None):
    using = project._state.db or "default"
    with transaction.atomic(using=using):
        project = lock_project(project.pk, using=using, user=user)
        return _write_positions(_checked_siblings(project, parent), using)


def clamp_position(new_position, sibling_count):
    if new_position in (None, ""):
        return sibling_count + 1
    try:
        position = int(new_position)
    except (TypeError, ValueError):
        raise ValidationError(_("La nueva posicion debe ser un numero entero.")) from None
    if position < 1:
        raise ValidationError(_("La posicion debe ser un entero positivo."))
    return min(position, sibling_count + 1)


def save_node(node, *args, **kwargs):
    using = kwargs.get("using") or router.db_for_write(ManuscriptNode, instance=node)
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not update_fields:
        return
    with transaction.atomic(using=using):
        project = lock_project(node.project_id, using=using)
        existing = None
        if not node._state.adding:
            existing = ManuscriptNode.objects.using(using).select_for_update().get(pk=node.pk)
            if existing.project_id != project.pk:
                raise ValidationError(_("No se permite trasladar nodos a otro proyecto."))
            loaded = getattr(node, "_loaded_structure", {})
            # Text-only saves preserve a move committed since this instance was loaded.
            for name in ("parent_id", "node_type", "position"):
                if update_fields is not None and name.removesuffix("_id") not in update_fields and name not in update_fields:
                    setattr(node, name, getattr(existing, name))
                elif name in loaded and getattr(node, name) == loaded[name]:
                    setattr(node, name, getattr(existing, name))
                elif name in loaded and getattr(existing, name) != loaded[name]:
                    raise ValidationError(_("El nodo fue movido o modificado. Recarga antes de cambiar su estructura."))
            if existing.node_type == "SCENE":
                if node.node_type != "SCENE":
                    raise ValidationError(_("Una escena con historial no cambia de tipo."))
                for name in ("content", "status", "word_count", "is_publishable"):
                    if update_fields is None or name in update_fields:
                        if getattr(node, name) != getattr(existing, name):
                            raise ValidationError(_("El texto y la etapa de una escena se editan desde sus versiones con control de revisión."))
                    setattr(node, name, getattr(existing, name))
            elif node.node_type == "SCENE":
                raise ValidationError(_("La conversión de nodos existentes a escena requiere una migración explícita."))
            # Only version services may switch the working version pointer.
            if update_fields is not None and ("current_draft_version" in update_fields or "current_draft_version_id" in update_fields):
                raise ValidationError(_("La versión de trabajo se selecciona mediante los servicios de versiones."))
            node.current_draft_version_id = existing.current_draft_version_id
        node.project = project
        if existing is None or node.node_type != "SCENE":
            node.word_count = count_words(node.content)
        node.full_clean()
        structural = existing is None or (existing.parent_id, existing.node_type, existing.position) != (node.parent_id, node.node_type, node.position)
        if structural:
            siblings = _checked_siblings(project, node.parent, exclude_pk=node.pk)
            node.position = clamp_position(node.position, len(siblings))
            siblings.insert(node.position - 1, node)
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | ({"word_count"} if "content" in update_fields else set())
            if structural:
                kwargs["update_fields"].add("position")
        result = models.Model.save(node, *args, **kwargs)
        if existing is None and node.node_type == "SCENE":
            from .version_services import _create_version_locked

            _create_version_locked(node, node.content)
        if structural:
            _write_positions(siblings, using)
            if existing and existing.parent_id != node.parent_id:
                _write_positions(_checked_siblings(project, existing.parent), using)
        node._loaded_structure = {name: getattr(node, name) for name in ("project_id", "parent_id", "node_type", "position")}
        return result


def _locked_node(node, *, user=None):
    using = node._state.db or "default"
    project = lock_project(node.project_id, using=using, user=user)
    current = ManuscriptNode.objects.using(using).select_for_update().get(pk=node.pk)
    if current.project_id != project.pk:
        raise ValidationError(_("No se permite trasladar nodos a otro proyecto."))
    current.project = project
    return current


def _move_locked(node, new_parent, new_position):
    if new_parent is not None:
        new_parent = ManuscriptNode.objects.using(node._state.db).get(pk=new_parent.pk)
    validate_parent_for_node(node, new_parent)
    old_parent = node.parent
    source = _checked_siblings(node.project, old_parent, exclude_pk=node.pk)
    target = source if node.parent_id == (new_parent.pk if new_parent else None) else _checked_siblings(node.project, new_parent, exclude_pk=node.pk)
    position = clamp_position(new_position, len(target))
    target.insert(position - 1, node)
    node.parent = new_parent
    node.updated_at = timezone.now()
    ManuscriptNode.objects.using(node._state.db).filter(pk=node.pk).update(parent=new_parent, updated_at=node.updated_at)
    _write_positions(target, node._state.db)
    if target is not source:
        _write_positions(source, node._state.db)
    node.refresh_from_db()
    return node


def move_node(node, new_parent, new_position=None, *, user=None):
    with transaction.atomic(using=node._state.db or "default"):
        return _move_locked(_locked_node(node, user=user), new_parent, new_position)


def _move_by(node, offset, user):
    with transaction.atomic(using=node._state.db or "default"):
        node = _locked_node(node, user=user)
        validate_node_hierarchy(node)
        siblings = _checked_siblings(node.project, node.parent)
        index = next(index for index, sibling in enumerate(siblings) if sibling.pk == node.pk)
        return _move_locked(node, node.parent, max(1, min(len(siblings), index + 1 + offset)))


def move_node_up(node, *, user=None):
    return _move_by(node, -1, user)


def move_node_down(node, *, user=None):
    return _move_by(node, 1, user)


def delete_node(node, *, using=None, keep_parents=False, user=None):
    using = using or node._state.db or "default"
    with transaction.atomic(using=using):
        current = _locked_node(node, user=user)
        validate_node_hierarchy(current)
        if current.children.exists():
            raise ValidationError(_("No puedes borrar un nodo que tiene hijos."))
        siblings = _checked_siblings(current.project, current.parent, exclude_pk=current.pk)
        result = models.Model.delete(current, using=using, keep_parents=keep_parents)
        _write_positions(siblings, using)
        node.pk = None
        return result


def sibling_move_flags(node):
    siblings = list(ordered_siblings(node.project, node.parent).values_list("pk", flat=True))
    if node.pk not in siblings:
        return {"can_move_up": False, "can_move_down": False}
    index = siblings.index(node.pk)
    return {"can_move_up": index > 0, "can_move_down": index < len(siblings) - 1}
