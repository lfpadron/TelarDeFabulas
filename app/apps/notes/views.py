from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.characters.models import Character
from apps.manuscripts.models import ManuscriptNode
from apps.projects.models import Project

from .forms import NoteForm
from .models import Note


def get_user_project(user, project_pk):
    return get_object_or_404(Project, pk=project_pk, user=user)


def get_project_note(project, note_pk):
    return get_object_or_404(Note, pk=note_pk, project=project)


def project_allows_note_changes(project):
    return project.status not in (Project.ProjectStatus.DELETED, Project.ProjectStatus.PENDING_DELETION)


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
def note_list(request, project_pk):
    project = get_user_project(request.user, project_pk)
    notes = Note.objects.filter(project=project).select_related("node", "character")
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
def note_create(request, project_pk):
    project = get_user_project(request.user, project_pk)
    if not project_allows_note_changes(project):
        messages.error(request, _("No se pueden crear notas en proyectos eliminados o pendientes de borrado."))
        return redirect("projects:detail", pk=project.pk)

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
def note_detail(request, project_pk, note_pk):
    project = get_user_project(request.user, project_pk)
    note = get_project_note(project, note_pk)
    return render(request, "notes/note_detail.html", {"project": project, "note": note})


@login_required
def note_edit(request, project_pk, note_pk):
    project = get_user_project(request.user, project_pk)
    note = get_project_note(project, note_pk)
    if not project_allows_note_changes(project):
        raise Http404(_("No se pueden editar notas en proyectos eliminados o pendientes de borrado."))

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
def note_delete(request, project_pk, note_pk):
    project = get_user_project(request.user, project_pk)
    note = get_project_note(project, note_pk)

    if request.method == "POST":
        note.delete()
        messages.success(request, _("Nota borrada correctamente."))
        return redirect("notes:list", project_pk=project.pk)

    return render(request, "notes/note_confirm_delete.html", {"project": project, "note": note})
