from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from apps.core.decorators import project_access
from apps.core.permissions import Action

from .forms import CategoryForm, EntryFilterForm, EntryForm, RevisionForm
from .models import WorldbuildingEntry as Entry
from .selectors import entry_sections
from .services import RevisionConflict, change_entry_category, delete_entry, move_entry_down, move_entry_up


def get_entry(project, pk):
    return get_object_or_404(Entry, project=project, pk=pk)


@login_required
@require_safe
@project_access()
def entry_list(request, project_pk):
    form = EntryFilterForm(request.GET)
    valid = form.is_valid()
    sections = entry_sections(request.project, request.GET, category=form.cleaned_data["category"],
                              query=form.cleaned_data["q"]) if valid else []
    return render(request, "worldbuilding/list.html", {"project": request.project, "filter_form": form,
                  "sections": sections}, status=200 if valid else 400)


@login_required
@require_safe
@project_access()
def detail(request, project_pk, entry_pk):
    return render(request, "worldbuilding/detail.html", {"project": request.project, "entry": get_entry(request.project, entry_pk)})


def _entry_form(request, entry=None):
    editing = entry is not None
    category = request.GET.get("category", Entry.Category.POLITICS)
    if category not in Entry.Category.values:
        raise Http404
    form = EntryForm(request.POST if request.method == "POST" else None, instance=entry,
                     project=request.project, initial={"category": category} if not editing else None)
    if request.method == "POST" and form.is_valid():
        try:
            saved = form.save(user=request.user)
        except RevisionConflict as exc:
            form.revision_conflict = True
            form.add_error(None, exc)
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
        else:
            messages.success(request, _("Entrada guardada correctamente."))
            return redirect("worldbuilding:detail", project_pk=request.project.pk, entry_pk=saved.pk)
    return render(request, "worldbuilding/form.html", {"project": request.project, "entry": entry, "form": form,
        "conflict": form.revision_conflict, "title": _("Editar entrada") if editing else _("Nueva entrada"),
        "return_url": reverse("worldbuilding:detail", args=[request.project.pk, entry.pk]) if editing else reverse("worldbuilding:list", args=[request.project.pk])},
        status=409 if form.revision_conflict else 200)


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.CREATE)
def create(request, project_pk):
    return _entry_form(request)


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.EDIT)
def edit(request, project_pk, entry_pk):
    return _entry_form(request, get_entry(request.project, entry_pk))


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.EDIT)
def change_category(request, project_pk, entry_pk):
    entry = get_entry(request.project, entry_pk)
    form = CategoryForm(request.POST if request.method == "POST" else None,
                        initial={"category": entry.category, "expected_revision": entry.revision})
    conflict = False
    if request.method == "POST" and form.is_valid():
        try:
            change_entry_category(entry, form.cleaned_data["category"], expected_revision=form.cleaned_data["expected_revision"], user=request.user)
        except RevisionConflict as exc:
            conflict = True
            form.add_error(None, exc)
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
        else:
            messages.success(request, _("Categoría actualizada correctamente."))
            return redirect("worldbuilding:detail", project_pk=request.project.pk, entry_pk=entry.pk)
    return render(request, "worldbuilding/form.html", {"project": request.project, "entry": entry, "form": form,
        "conflict": conflict, "title": _("Cambiar categoría"), "return_url": reverse("worldbuilding:detail", args=[request.project.pk, entry.pk])},
        status=409 if conflict else 200)


@login_required
@require_POST
@project_access(Action.EDIT)
def reorder(request, project_pk, entry_pk, direction):
    entry = get_entry(request.project, entry_pk)
    form = RevisionForm(request.POST)
    status = 400
    if form.is_valid():
        try:
            (move_entry_up if direction == "up" else move_entry_down)(entry,
                expected_revision=form.cleaned_data["expected_revision"], user=request.user)
        except RevisionConflict as exc:
            form.add_error(None, exc)
            status = 409
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
        else:
            return redirect("worldbuilding:list", project_pk=request.project.pk)
    return render(request, "worldbuilding/conflict.html", {"project": request.project, "entry": entry, "form": form}, status=status)


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.DELETE)
def delete(request, project_pk, entry_pk):
    entry = get_entry(request.project, entry_pk)
    form = RevisionForm(request.POST if request.method == "POST" else None, initial={"expected_revision": entry.revision})
    status = 200
    if request.method == "POST" and form.is_valid():
        try:
            delete_entry(entry, expected_revision=form.cleaned_data["expected_revision"], user=request.user)
        except RevisionConflict as exc:
            form.add_error(None, exc)
            status = 409
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
        else:
            messages.success(request, _("Entrada eliminada correctamente."))
            return redirect("worldbuilding:list", project_pk=request.project.pk)
    return render(request, "worldbuilding/confirm_delete.html", {"project": request.project, "entry": entry, "form": form}, status=status)
