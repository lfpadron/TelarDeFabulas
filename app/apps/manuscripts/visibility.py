from collections import defaultdict

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


TRASH_MESSAGE = _("El nodo está en la papelera o tiene un ancestro eliminado. Restáuralo antes de modificarlo.")


def hidden_node_roots(rows):
    """Map hidden IDs to their nearest tombstone in one iterative traversal."""
    rows = list(rows)
    children = defaultdict(list)
    direct = {row["id"] for row in rows if row["deleted_at"] is not None}
    for row in rows:
        children[row["parent_id"]].append(row["id"])
    hidden = {}
    for root in direct:
        pending = [root]
        while pending:
            pk = pending.pop()
            if pk in hidden or pk != root and pk in direct:
                continue
            hidden[pk] = root
            pending.extend(children[pk])
    return hidden


def hidden_node_ids(project_ids, using="default"):
    from .models import ManuscriptNode

    rows = ManuscriptNode.objects.using(using).filter(project_id__in=project_ids).order_by().values("id", "parent_id", "deleted_at")
    return set(hidden_node_roots(rows))


def require_visible_node(node):
    if node.pk and node.pk in hidden_node_ids([node.project_id], node._state.db or "default"):
        raise ValidationError(TRASH_MESSAGE)


def get_visible_manuscript_tree(project):
    from .hierarchy import ordered_tree
    from .models import ManuscriptNode

    return ordered_tree(ManuscriptNode.objects.using(project._state.db).filter(project=project).visible()
                        .defer("content").order_by("position", "created_at", "pk"))
