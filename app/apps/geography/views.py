from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from apps.core.decorators import project_access
from apps.core.permissions import Action, local_project_relations

from .forms import GeographicLocationForm, MoveLocationForm
from .models import GeographicLocation
from .selectors import location_path, tree_events
from .services import delete_location, deletion_blockers, move_location, move_location_down, move_location_up


def get_location(project, pk):
    return get_object_or_404(local_project_relations(GeographicLocation.objects.all()), project=project, pk=pk)


@login_required
@require_safe
@project_access()
def tree(request, project_pk):
    try:
        events = tree_events(request.project)
    except ValidationError as exc:
        events = []
        messages.error(request, " ".join(exc.messages))
    return render(request, "geography/tree.html", {"project": request.project, "events": events})


@login_required
@require_safe
@project_access()
def detail(request, project_pk, location_pk):
    location = get_location(request.project, location_pk)
    try:
        path = location_path(location)
    except ValidationError as exc:
        path = []
        messages.error(request, " ".join(exc.messages))
    children = location.children.filter(project=request.project).defer("detailed_description")
    residents = location.residents.filter(project=request.project).only("id", "name", "alias").order_by("name", "pk")
    organizations = local_project_relations(location.headquartered_organizations.filter(project=request.project)).only(
        "id", "name", "organization_type", "custom_organization_type").order_by("name", "pk")
    return render(request, "geography/detail.html", {
        "project": request.project, "location": location, "path": path,
        "children": Paginator(children, 50).get_page(request.GET.get("children_page")),
        "residents": Paginator(residents, 50).get_page(request.GET.get("residents_page")),
        "organizations": Paginator(organizations, 50).get_page(request.GET.get("organizations_page")),
    })


def _edit_form(request, location=None):
    initial = {}
    if location is None and request.method == "GET" and request.GET.get("parent"):
        raw = request.GET["parent"]
        if not raw.isdigit():
            raise Http404
        initial["parent"] = get_location(request.project, raw).pk
    form = GeographicLocationForm(request.POST if request.method == "POST" else None,
                                  instance=location, project=request.project, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            location = form.save()
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
        else:
            messages.success(request, _("Ubicación guardada correctamente."))
            return redirect("geography:detail", project_pk=request.project.pk, location_pk=location.pk)
    return render(request, "geography/form.html", {"project": request.project, "location": location,
        "form": form, "title": _("Editar ubicación") if location else _("Crear ubicación")})


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.CREATE)
def create(request, project_pk):
    return _edit_form(request)


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.EDIT)
def edit(request, project_pk, location_pk):
    return _edit_form(request, get_location(request.project, location_pk))


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.EDIT)
def move(request, project_pk, location_pk):
    location = get_location(request.project, location_pk)
    form = MoveLocationForm(request.POST if request.method == "POST" else None,
                            project=request.project, location=location)
    if request.method == "POST" and form.is_valid():
        try:
            move_location(location, form.cleaned_data["parent"], form.cleaned_data["position"], user=request.user)
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
        else:
            messages.success(request, _("Ubicación movida correctamente."))
            return redirect("geography:tree", project_pk=request.project.pk)
    return render(request, "geography/form.html", {"project": request.project, "location": location,
                   "form": form, "title": _("Mover ubicación")})


@login_required
@require_POST
@project_access(Action.EDIT)
def reorder(request, project_pk, location_pk, direction):
    location = get_location(request.project, location_pk)
    try:
        (move_location_up if direction == "up" else move_location_down)(location, user=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("geography:tree", project_pk=request.project.pk)


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.DELETE)
def delete(request, project_pk, location_pk):
    location = get_location(request.project, location_pk)
    if request.method == "POST":
        try:
            delete_location(location, user=request.user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, _("Ubicación eliminada correctamente."))
            return redirect("geography:tree", project_pk=request.project.pk)
    return render(request, "geography/confirm_delete.html", {"project": request.project,
                   "location": location, "blockers": deletion_blockers(location)})
