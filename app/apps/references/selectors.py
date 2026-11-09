from django.db.models import F, Q

from .models import ReferenceAssociation, TARGETS


def local_associations(query):
    for key in TARGETS:
        query = query.filter(Q(**{f"{key}__isnull": True}) | Q(**{f"{key}__project_id": F("reference__project_id")}))
    return query


def project_associations(project):
    return local_associations(ReferenceAssociation.objects.filter(reference__project=project)).select_related("reference", *TARGETS).defer(
        "reference__notes", "manuscript_node__content", "character__biography", "geographic_location__detailed_description",
        "organization__detailed_description", "worldbuilding_entry__content")
