"""Ordered project trees. Write helpers require the caller's project lock and atomic block."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


def validate_parent_chain(parents, node_id, parent_id, cycle_message, missing_message):
    seen = {node_id} if node_id else set()
    while parent_id is not None:
        if parent_id in seen:
            raise ValidationError({"parent": cycle_message})
        if parent_id not in parents:
            raise ValidationError({"parent": missing_message})
        seen.add(parent_id)
        parent_id = parents[parent_id]


def descendant_ids(parent_pairs, node_id):
    children = {}
    for pk, parent_id in parent_pairs:
        children.setdefault(parent_id, []).append(pk)
    excluded, pending = set(), [node_id] if node_id else []
    while pending:
        pk = pending.pop()
        if pk not in excluded:
            excluded.add(pk)
            pending.extend(children.get(pk, ()))
    return excluded


def siblings(queryset, parent_id, exclude_pk=None):
    return list(queryset.filter(parent_id=parent_id).exclude(pk=exclude_pk)
                .only("id", "position").order_by("position", "pk"))


def clamp_position(value, count):
    if value in (None, ""):
        return count + 1
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise ValidationError(_("La posición debe ser un entero positivo.")) from None
    if number < 1 or str(number) != str(value):
        raise ValidationError(_("La posición debe ser un entero positivo."))
    return min(number, count + 1)


def park_positions(queryset, rows):
    # Free affected slots before final numbering, including NULL/root siblings.
    maximum = queryset.aggregate(value=Max("position"))["value"] or 0
    for offset, row in enumerate(rows, start=1):
        row.position = maximum + offset
    if rows:
        queryset.bulk_update(rows, ["position"])
    return maximum + len(rows) + 1


def number_positions(queryset, rows):
    for position, row in enumerate(rows, start=1):
        row.position = position
    if rows:
        queryset.bulk_update(rows, ["position"])


def preserve_current_structure(node, current, update_fields, conflict_message):
    loaded = getattr(node, "_loaded_structure", {})
    for key in ("parent_id", "position"):
        if update_fields is not None and key not in update_fields and key.removesuffix("_id") not in update_fields:
            setattr(node, key, getattr(current, key))
        elif key in loaded and getattr(node, key) == loaded[key]:
            setattr(node, key, getattr(current, key))
        elif key in loaded and getattr(current, key) != loaded[key]:
            raise ValidationError(conflict_message)


def save_ordered_node(node, existing, *args, **kwargs):
    queryset = type(node).objects.using(node.project._state.db).filter(project_id=node.project_id)
    target = siblings(queryset, node.parent_id, node.pk)
    structural = existing is None or (existing.parent_id, existing.position) != (node.parent_id, node.position)
    node.position = clamp_position(node.position, len(target)) if structural else existing.position
    node.full_clean(validate_constraints=False)
    if structural:
        source = siblings(queryset, existing.parent_id, node.pk) if existing and existing.parent_id != node.parent_id else []
        index = node.position - 1
        node.position = park_positions(queryset, target + source + ([existing] if existing else []))
    if kwargs.get("update_fields") is not None:
        kwargs["update_fields"] = set(kwargs["update_fields"]) | {"position"}
    result = models.Model.save(node, *args, **kwargs)
    if structural:
        target.insert(index, node)
        number_positions(queryset, target)
        number_positions(queryset, source)
    node._loaded_structure = {key: getattr(node, key) for key in ("parent_id", "position")}
    return result


def move_ordered_node(queryset, node, parent_id, new_position):
    source = siblings(queryset, node.parent_id, node.pk)
    target = source if node.parent_id == parent_id else siblings(queryset, parent_id, node.pk)
    index = clamp_position(new_position, len(target)) - 1
    park_positions(queryset, source + ([] if source is target else target) + [node])
    node.parent_id = parent_id
    node.updated_at = timezone.now()
    queryset.filter(pk=node.pk).update(parent_id=parent_id, updated_at=node.updated_at)
    target.insert(index, node)
    number_positions(queryset, target)
    if source is not target:
        number_positions(queryset, source)
    node.refresh_from_db()
    return node


def build_tree_events(rows, node_key, cycle_message, unreachable_message):
    rows = list(rows)
    children = {}
    for row in rows:
        children.setdefault(row.parent_id, []).append(row)
    events, seen = [], set()
    pending = [("open", row, 0, index, len(children.get(None, [])))
               for index, row in reversed(list(enumerate(children.get(None, []))))]
    while pending:
        kind, row, depth, index, count = pending.pop()
        if kind == "close":
            events.append({"kind": kind})
            continue
        if row.pk in seen:
            raise ValidationError(cycle_message)
        seen.add(row.pk)
        events.append({"kind": kind, node_key: row, "indent": depth < 8,
                       "can_move_up": index > 0, "can_move_down": index < count - 1})
        pending.append(("close", row, depth, index, count))
        descendants = children.get(row.pk, [])
        pending.extend(("open", child, depth + 1, i, len(descendants))
                       for i, child in reversed(list(enumerate(descendants))))
    if len(seen) != len(rows):
        raise ValidationError(unreachable_message)
    return events


def build_path(rows, pk, error_message):
    rows = {row.pk: row for row in rows}
    path, seen = [], set()
    while pk is not None:
        if pk in seen or pk not in rows:
            raise ValidationError(error_message)
        seen.add(pk)
        path.append(rows[pk])
        pk = rows[pk].parent_id
    return list(reversed(path))
