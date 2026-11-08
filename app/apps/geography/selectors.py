from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import GeographicLocation


def tree_events(project):
    rows = list(GeographicLocation.objects.filter(project=project).defer("detailed_description"))
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
            raise ValidationError(_("La jerarquía geográfica contiene un ciclo. Requiere revisión."))
        seen.add(row.pk)
        events.append({"kind": kind, "location": row, "indent": depth < 8,
                       "can_move_up": index > 0, "can_move_down": index < count - 1})
        pending.append(("close", row, depth, index, count))
        descendants = children.get(row.pk, [])
        pending.extend(("open", child, depth + 1, i, len(descendants))
                       for i, child in reversed(list(enumerate(descendants))))
    if len(seen) != len(rows):
        raise ValidationError(_("La jerarquía geográfica contiene ubicaciones sin una raíz válida. Requiere revisión."))
    return events


def location_path(location):
    rows = {row.pk: row for row in GeographicLocation.objects.filter(project_id=location.project_id)
            .only("id", "parent_id", "name")}
    path, seen = [], set()
    pk = location.pk
    while pk is not None:
        if pk in seen or pk not in rows:
            raise ValidationError(_("La ruta geográfica no es válida. Requiere revisión."))
        seen.add(pk)
        path.append(rows[pk])
        pk = rows[pk].parent_id
    return list(reversed(path))
