from collections import defaultdict

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


ALLOWED_CHILD_TYPES = {
    "BOOK": ("PART", "CHAPTER"),
    "PART": ("CHAPTER",),
    "CHAPTER": ("SCENE",),
    "SCENE": (),
    "FRAGMENT": (),
}
CURRENT_TYPES = ("BOOK", "PART", "CHAPTER", "SCENE")
LEGACY_MESSAGE = _("Este nodo conserva una estructura legada y es de solo lectura. Requiere revision antes de modificarlo.")


def load_structure(project_id, using="default"):
    from .models import ManuscriptNode

    return {row["id"]: row for row in ManuscriptNode.objects.using(using).filter(project_id=project_id).values(
        "id", "project_id", "parent_id", "node_type", "title", "position",
    )}


def validate_structure(row, structure):
    if row["node_type"] not in CURRENT_TYPES:
        raise ValidationError(LEGACY_MESSAGE)
    if row["node_type"] != "SCENE" and not (row["title"] or "").strip():
        raise ValidationError({"title": _("El titulo es obligatorio para libros, partes y capitulos.")})
    parent_id = row["parent_id"]
    if parent_id is None:
        if row["node_type"] != "BOOK":
            raise ValidationError({"parent": _("Solo un libro puede estar en la raiz del proyecto.")})
        return
    parent = structure.get(parent_id)
    if parent is None or parent["project_id"] != row["project_id"]:
        raise ValidationError({"parent": _("El padre debe pertenecer al mismo proyecto.")})
    if row["node_type"] not in ALLOWED_CHILD_TYPES.get(parent["node_type"], ()):
        raise ValidationError({"parent": _("El tipo de padre no es compatible con este nodo.")})


def validate_branch(node_id, structure):
    # Validate ancestors and the affected subtree without recursive traversal.
    seen = set()
    cursor = node_id
    while cursor is not None:
        if cursor in seen:
            raise ValidationError({"parent": _("No se permiten ciclos en el manuscrito.")})
        seen.add(cursor)
        row = structure.get(cursor)
        if row is None:
            raise ValidationError({"parent": _("El padre debe pertenecer al mismo proyecto.")})
        validate_structure(row, structure)
        cursor = row["parent_id"]
    children = defaultdict(list)
    for row in structure.values():
        children[row["parent_id"]].append(row["id"])
    pending, seen = [node_id], set()
    while pending:
        pk = pending.pop()
        if pk in seen:
            raise ValidationError({"parent": _("No se permiten ciclos en el manuscrito.")})
        seen.add(pk)
        validate_structure(structure[pk], structure)
        pending.extend(children[pk])


def validate_node_hierarchy(node, structure=None):
    if not node.project_id:
        raise ValidationError({"project": _("El nodo debe pertenecer a un proyecto.")})
    structure = dict(structure if structure is not None else load_structure(node.project_id, node._state.db or "default"))
    old = structure.get(node.pk)
    if old and old["node_type"] == "FRAGMENT":
        raise ValidationError(LEGACY_MESSAGE)
    key = node.pk or 0
    structure[key] = {"id": key, "project_id": node.project_id, "parent_id": node.parent_id,
                      "node_type": node.node_type, "title": node.title, "position": node.position}
    validate_branch(key, structure)
    structural = old is None or any(old[name] != structure[key][name] for name in ("parent_id", "node_type", "position"))
    if structural:
        parents = {node.parent_id, old["parent_id"] if old else node.parent_id}
        for sibling in structure.values():
            if sibling["id"] != key and sibling["parent_id"] in parents:
                try:
                    validate_branch(sibling["id"], structure)
                except ValidationError:
                    raise ValidationError(LEGACY_MESSAGE) from None


def editable_node_ids(structure):
    editable = set()
    for pk in structure:
        try:
            validate_branch(pk, structure)
        except ValidationError:
            continue
        editable.add(pk)
    return editable


def ordered_tree(nodes):
    """Include disconnected legacy rows once, without following foreign nodes."""
    nodes = list(nodes)
    by_id = {node.pk: node for node in nodes}
    children = defaultdict(list)
    for node in nodes:
        children[node.parent_id].append(node)
    roots = [node for node in nodes if node.parent_id not in by_id]
    seen, rows = set(), []
    for root in [*roots, *nodes]:
        if root.pk in seen:
            continue
        pending = [(root, 0)]
        while pending:
            node, level = pending.pop()
            if node.pk in seen:
                continue
            seen.add(node.pk)
            rows.append((node, level))
            pending.extend((child, level + 1) for child in reversed(children[node.pk]))
    return rows
