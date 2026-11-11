from django.db.models import F, Q

from .models import ReferenceAssociation, TARGETS


def visible_associations(query):
    from apps.manuscripts.visibility import hidden_node_ids

    hidden = hidden_node_ids(query.order_by().values("reference__project_id"), query.db)
    return query.exclude(manuscript_node_id__in=hidden)


def local_associations(query, *, include_hidden=False):
    for key in TARGETS:
        query = query.filter(Q(**{f"{key}__isnull": True}) | Q(**{f"{key}__project_id": F("reference__project_id")}))
    return query if include_hidden else visible_associations(query)


def project_associations(project, *, include_hidden=False):
    return local_associations(ReferenceAssociation.objects.filter(reference__project=project), include_hidden=include_hidden).select_related("reference", *TARGETS).defer(
        "reference__notes", "manuscript_node__content", "character__biography", "geographic_location__detailed_description",
        "organization__detailed_description", "worldbuilding_entry__content")
