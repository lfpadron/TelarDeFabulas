from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.projects.models import Project

from .forms import CharacterForm
from .models import Character


def get_user_project(user, project_pk):
    return get_object_or_404(Project, pk=project_pk, user=user)


def get_project_character(project, character_pk):
    return get_object_or_404(Character, pk=character_pk, project=project)


def project_allows_character_changes(project):
    return project.status not in (Project.ProjectStatus.DELETED, Project.ProjectStatus.PENDING_DELETION)


@login_required
def character_list(request, project_pk):
    project = get_user_project(request.user, project_pk)
    characters = Character.objects.filter(project=project).order_by("name").prefetch_related("dramatic_roles")
    return render(request, "characters/character_list.html", {"project": project, "characters": characters})


@login_required
def character_create(request, project_pk):
    project = get_user_project(request.user, project_pk)
    if not project_allows_character_changes(project):
        messages.error(request, _("No se pueden crear personajes en proyectos eliminados o pendientes de borrado."))
        return redirect("projects:detail", pk=project.pk)

    if request.method == "POST":
        form = CharacterForm(request.POST, request.FILES, project=project)
        if form.is_valid():
            character = form.save()
            messages.success(request, _("Personaje creado correctamente."))
            return redirect("characters:detail", project_pk=project.pk, character_pk=character.pk)
    else:
        form = CharacterForm(project=project)

    return render(
        request,
        "characters/character_form.html",
        {
            "form": form,
            "project": project,
            "title": _("Crear personaje"),
            "submit_label": _("Crear personaje"),
        },
    )


@login_required
def character_detail(request, project_pk, character_pk):
    project = get_user_project(request.user, project_pk)
    character = get_project_character(project, character_pk)
    linked_notes = character.work_notes.select_related("node").order_by("-updated_at", "title")
    return render(
        request,
        "characters/character_detail.html",
        {
            "project": project,
            "character": character,
            "linked_notes": linked_notes,
        },
    )


@login_required
def character_edit(request, project_pk, character_pk):
    project = get_user_project(request.user, project_pk)
    character = get_project_character(project, character_pk)
    if not project_allows_character_changes(project):
        raise Http404(_("No se pueden editar personajes en proyectos eliminados o pendientes de borrado."))

    if request.method == "POST":
        form = CharacterForm(request.POST, request.FILES, instance=character, project=project)
        if form.is_valid():
            character = form.save()
            messages.success(request, _("Personaje actualizado correctamente."))
            return redirect("characters:detail", project_pk=project.pk, character_pk=character.pk)
    else:
        form = CharacterForm(instance=character, project=project)

    return render(
        request,
        "characters/character_form.html",
        {
            "form": form,
            "project": project,
            "character": character,
            "title": _("Editar personaje"),
            "submit_label": _("Guardar personaje"),
        },
    )


@login_required
def character_delete(request, project_pk, character_pk):
    project = get_user_project(request.user, project_pk)
    character = get_project_character(project, character_pk)

    if request.method == "POST":
        character.delete()
        messages.success(request, _("Personaje borrado correctamente."))
        return redirect("characters:list", project_pk=project.pk)

    return render(request, "characters/character_confirm_delete.html", {"project": project, "character": character})
