from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.characters.models import Character
from apps.manuscripts.models import ManuscriptNode
from apps.core.decorators import project_access
from apps.core.permissions import Action, local_project_relations

from .forms import NoteForm
from .models import Note


def get_project_note(project, note_pk):
    return get_object_or_404(local_project_relations(Note.objects.all()), pk=note_pk, project=project)


def filtered_notes(queryset, request):
    note_type = request.GET.get("type")
    status = request.GET.get("status")
    priority = request.GET.get("priority")
    if note_type in Note.NoteType.values:
        queryset = queryset.filter(note_type=note_type)
    if status in Note.NoteStatus.values:
        queryset = queryset.filter(status=status)
    if priority in Note.Priority.values:
        queryset = queryset.filter(priority=priority)
    return queryset


def create_initial_for_project(project, query):
    initial = {}
    node_pk = query.get("node")
    character_pk = query.get("character")
    if node_pk:
        node = ManuscriptNode.objects.filter(pk=node_pk, project=project).first()
        if node:
            initial["node"] = node.pk
    if character_pk:
        character = Character.objects.filter(pk=character_pk, project=project).first()
        if character:
            initial["character"] = character.pk
    return initial


@login_required
@project_access()
def note_list(request, project_pk):
    project = request.project
    notes = local_project_relations(Note.objects.filter(project=project)).select_related("node", "character")
    notes = filtered_notes(notes, request)
    return render(
        request,
        "notes/note_list.html",
        {
            "project": project,
            "notes": notes,
            "note_type_choices": Note.NoteType.choices,
            "status_choices": Note.NoteStatus.choices,
            "priority_choices": Note.Priority.choices,
            "current_type": request.GET.get("type", ""),
            "current_status": request.GET.get("status", ""),
            "current_priority": request.GET.get("priority", ""),
        },
    )


@login_required
@project_access(Action.CREATE)
def note_create(request, project_pk):
    project = request.project

    if request.method == "POST":
        form = NoteForm(request.POST, project=project)
        if form.is_valid():
            note = form.save()
            messages.success(request, _("Nota creada correctamente."))
            return redirect("notes:detail", project_pk=project.pk, note_pk=note.pk)
    else:
        form = NoteForm(project=project, initial=create_initial_for_project(project, request.GET))

    return render(
        request,
        "notes/note_form.html",
        {
            "form": form,
            "project": project,
            "title": _("Crear nota"),
            "submit_label": _("Crear nota"),
        },
    )


@login_required
@project_access()
def note_detail(request, project_pk, note_pk):
    project = request.project
    note = get_project_note(project, note_pk)
    return render(request, "notes/note_detail.html", {"project": project, "note": note})


@login_required
@project_access(Action.EDIT)
def note_edit(request, project_pk, note_pk):
    project = request.project
    note = get_project_note(project, note_pk)

    if request.method == "POST":
        form = NoteForm(request.POST, instance=note, project=project)
        if form.is_valid():
            note = form.save()
            messages.success(request, _("Nota actualizada correctamente."))
            return redirect("notes:detail", project_pk=project.pk, note_pk=note.pk)
    else:
        form = NoteForm(instance=note, project=project)

    return render(
        request,
        "notes/note_form.html",
        {
            "form": form,
            "project": project,
            "note": note,
            "title": _("Editar nota"),
            "submit_label": _("Guardar nota"),
        },
    )


@login_required
@project_access(Action.DELETE)
def note_delete(request, project_pk, note_pk):
    project = request.project
    note = get_project_note(project, note_pk)

    if request.method == "POST":
        note.delete()
        messages.success(request, _("Nota borrada correctamente."))
        return redirect("notes:list", project_pk=project.pk)

    return render(request, "notes/note_confirm_delete.html", {"project": project, "note": note})
