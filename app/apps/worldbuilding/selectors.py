from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q

from .models import WorldbuildingEntry as Entry


def entry_sections(project, params, *, category="", query=""):
    siblings = Entry.objects.filter(project=project, category=OuterRef("category"))
    queryset = Entry.objects.filter(project=project).defer("content").annotate(
        can_move_up=Exists(siblings.filter(position__lt=OuterRef("position"))),
        can_move_down=Exists(siblings.filter(position__gt=OuterRef("position"))),
    )
    if query:
        queryset = queryset.filter(Q(title__icontains=query) | Q(short_description__icontains=query))
    sections = []
    for value, label in Entry.Category.choices:
        if category and category != value:
            continue
        page_key = f"{value.lower()}_page"
        page = Paginator(queryset.filter(category=value).order_by("position", "pk"), 50).get_page(params.get(page_key))
        page_query = params.copy()
        page_query.pop(page_key, None)
        sections.append({"category": value, "label": label, "page": page,
                         "page_key": page_key, "page_query": page_query.urlencode()})
    return sections
