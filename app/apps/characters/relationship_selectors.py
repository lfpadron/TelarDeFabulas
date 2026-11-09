from django.core.paginator import Paginator
from django.db.models import F
from django.utils.translation import gettext_lazy as _

from .models import CharacterRelationship


def local_relationships(query):
    return query.filter(source_character__project_id=F("project_id"), target_character__project_id=F("project_id"))


def project_relationships(project):
    return local_relationships(CharacterRelationship.objects.filter(project=project)).select_related("source_character", "target_character").only(
        "id", "project_id", "source_character_id", "target_character_id", "relationship_type", "custom_relationship_type", "is_reciprocal", "updated_at",
        "source_character__id", "source_character__name", "source_character__project_id", "target_character__id", "target_character__name", "target_character__project_id")


def relationship_groups(character, params):
    from .relationship_services import get_relationships_for_character
    query = get_relationships_for_character(character)
    return [
        {"title": title, "page_key": key, "page": Paginator(rows, 50).get_page(params.get(key))}
        for title, key, rows in (
            (_("Relaciones salientes"), "outgoing_page", query.filter(source_character=character, is_reciprocal=False)),
            (_("Relaciones entrantes"), "incoming_page", query.filter(target_character=character, is_reciprocal=False)),
            (_("Relaciones mutuas"), "mutual_page", query.filter(is_reciprocal=True)),
        )
    ]
