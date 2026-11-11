from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import get_user_project

from .hierarchy import validate_node_hierarchy
from .models import ManuscriptNode
from .services import _checked_siblings, _locked_node, _move_locked, _write_positions
from .visibility import hidden_node_roots, require_visible_node


ORIGINAL_PARENT = object()


def soft_delete_node(node, *, user=None, using=None):
    using = using or node._state.db or "default"
    with transaction.atomic(using=using):
        current = _locked_node(node, user=user, allow_hidden=True)
        if current.deleted_at is not None:
            return current
        require_visible_node(current)
        validate_node_hierarchy(current)
        siblings = _checked_siblings(current.project, current.parent, exclude_pk=current.pk)
        current.deleted_at = timezone.now()
        current.deleted_by = user
        ManuscriptNode.objects.using(using).filter(pk=current.pk).update(
            deleted_at=current.deleted_at, deleted_by=current.deleted_by)
        _write_positions(siblings, using)
        node.deleted_at, node.deleted_by_id = current.deleted_at, current.deleted_by_id
        return current


def restore_node(node, *, new_parent=ORIGINAL_PARENT, position=None, user=None):
    using = node._state.db or "default"
    with transaction.atomic(using=using):
        current = _locked_node(node, user=user, allow_hidden=True)
        query = ManuscriptNode.objects.using(using).filter(project=current.project)
        if query.visible().filter(pk=current.pk).exists():
            return current
        parent = current.parent if new_parent is ORIGINAL_PARENT else new_parent
        if parent is not None:
            parent = query.filter(pk=parent.pk).first()
            if parent is None:
                raise ValidationError(_("El destino debe pertenecer al mismo proyecto."))
            require_visible_node(parent)
        # Clear only this tombstone. Earlier independent deletions remain untouched.
        query.filter(pk=current.pk).update(deleted_at=None, deleted_by=None)
        current.deleted_at, current.deleted_by_id = None, None
        current = _move_locked(current, parent, current.position if position is None else position)
        # Normalize newly visible groups; hidden descendants retain their stored order.
        restored_ids = {current.pk, *current.descendant_ids()}
        visible = list(query.visible().filter(parent_id__in=restored_ids).only(
            "id", "parent_id", "position", "created_at").order_by("position", "created_at", "pk"))
        groups = defaultdict(list)
        for child in visible:
            groups[child.parent_id].append(child)
        for siblings in groups.values():
            _write_positions(siblings, using)
        return current


def get_trash_items(project, *, user):
    project = get_user_project(user, project.pk)
    nodes = list(ManuscriptNode.objects.using(project._state.db).filter(project=project).only(
        "id", "project_id", "parent_id", "node_type", "title", "position", "deleted_at", "deleted_by_id"
    ).order_by("position", "created_at", "pk"))
    by_id = {node.pk: node for node in nodes}
    hidden = hidden_node_roots({"id": n.pk, "parent_id": n.parent_id, "deleted_at": n.deleted_at} for n in nodes)
    children = defaultdict(list)
    for node in nodes:
        children[node.parent_id].append(node.pk)
    items = []
    for node in nodes:
        if node.pk not in hidden:
            continue
        path, seen, cursor = [], {node.pk}, node.parent_id
        while cursor in by_id and cursor not in seen:
            seen.add(cursor)
            ancestor = by_id[cursor]
            path.append(str(ancestor.display_title))
            cursor = ancestor.parent_id
        affected, pending = set(), list(children[node.pk])
        while pending:
            pk = pending.pop()
            if pk in affected or by_id[pk].deleted_at is not None:
                continue
            affected.add(pk)
            pending.extend(children[pk])
        root = by_id[hidden[node.pk]]
        items.append({"node": node, "direct": node.deleted_at is not None, "deleted_at": root.deleted_at,
                      "location": " / ".join(reversed(path)) or str(_("Raíz del proyecto")),
                      "affected_count": len(affected), "deleted_root": root})
    return items
