from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _

from apps.manuscripts.models import ManuscriptNode
from apps.projects.models import Project

from .forms import CharacterForm, CharacterMentionForm
from .models import Character, CharacterMention


def get_user_project(user, project_pk):
    return get_object_or_404(Project, pk=project_pk, user=user)


def get_project_character(project, character_pk):
    return get_object_or_404(Character, pk=character_pk, project=project)


def get_project_mention(project, mention_pk):
    return get_object_or_404(
        CharacterMention.objects.select_related("character", "node"),
        pk=mention_pk,
        character__project=project,
        node__project=project,
    )


def project_allows_character_changes(project):
    return project.status not in (Project.ProjectStatus.DELETED, Project.ProjectStatus.PENDING_DELETION)


def get_reference_for_project(model, project, raw_pk, error_message):
    if raw_pk in (None, ""):
        return None
    try:
        int(raw_pk)
    except (TypeError, ValueError):
        raise Http404(error_message)
    return get_object_or_404(model, pk=raw_pk, project=project)


def safe_next_url(request):
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return None


def mention_return_url(request, project, mention=None, initial_character=None, initial_node=None):
    next_url = safe_next_url(request)
    if next_url:
        return next_url
    if initial_node is not None:
        return reverse("manuscripts:detail", kwargs={"project_pk": project.pk, "node_pk": initial_node.pk})
    if initial_character is not None:
        return reverse("characters:detail", kwargs={"project_pk": project.pk, "character_pk": initial_character.pk})
    if mention is not None:
        return reverse("characters:detail", kwargs={"project_pk": project.pk, "character_pk": mention.character_id})
    return reverse("characters:list", kwargs={"project_pk": project.pk})


@login_required
def character_list(request, project_pk):
    project = get_user_project(request.user, project_pk)
    characters = (
        Character.objects.filter(project=project)
        .annotate(
            mention_count=Count("mentions", distinct=True),
            appearance_count=Count(
                "mentions",
                filter=Q(mentions__mention_type=CharacterMention.MentionType.APPEARS),
                distinct=True,
            ),
        )
        .order_by("name")
        .prefetch_related("dramatic_roles")
    )
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
    character_mentions = character.mentions.select_related("node").order_by(
        "node__parent_id",
        "node__position",
        "node__title",
        "mention_type",
    )
    return render(
        request,
        "characters/character_detail.html",
        {
            "project": project,
            "character": character,
            "character_mentions": character_mentions,
            "can_manage_mentions": project_allows_character_changes(project),
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


@login_required
def mention_create(request, project_pk):
    project = get_user_project(request.user, project_pk)
    if not project_allows_character_changes(project):
        messages.error(request, _("No se pueden gestionar menciones en proyectos eliminados o pendientes de borrado."))
        return redirect("projects:detail", pk=project.pk)

    if request.method == "POST":
        get_reference_for_project(Character, project, request.POST.get("character"), _("Personaje no encontrado."))
        get_reference_for_project(ManuscriptNode, project, request.POST.get("node"), _("Nodo no encontrado."))
        form = CharacterMentionForm(request.POST, project=project)
        if form.is_valid():
            mention = form.save()
            messages.success(request, _("Mención creada correctamente."))
            return redirect(mention_return_url(request, project, mention=mention))
        return_url = safe_next_url(request) or reverse("characters:list", kwargs={"project_pk": project.pk})
    else:
        initial_character = get_reference_for_project(
            Character,
            project,
            request.GET.get("character"),
            _("Personaje no encontrado."),
        )
        initial_node = get_reference_for_project(
            ManuscriptNode,
            project,
            request.GET.get("node"),
            _("Nodo no encontrado."),
        )
        form = CharacterMentionForm(
            project=project,
            initial_character=initial_character,
            initial_node=initial_node,
        )
        return_url = mention_return_url(request, project, initial_character=initial_character, initial_node=initial_node)

    return render(
        request,
        "characters/mention_form.html",
        {
            "form": form,
            "project": project,
            "title": _("Agregar mención"),
            "submit_label": _("Guardar mención"),
            "return_url": return_url,
        },
    )


@login_required
def mention_edit(request, project_pk, mention_pk):
    project = get_user_project(request.user, project_pk)
    mention = get_project_mention(project, mention_pk)
    if not project_allows_character_changes(project):
        raise Http404(_("No se pueden gestionar menciones en proyectos eliminados o pendientes de borrado."))

    if request.method == "POST":
        get_reference_for_project(Character, project, request.POST.get("character"), _("Personaje no encontrado."))
        get_reference_for_project(ManuscriptNode, project, request.POST.get("node"), _("Nodo no encontrado."))
        form = CharacterMentionForm(request.POST, project=project, instance=mention)
        if form.is_valid():
            mention = form.save()
            messages.success(request, _("Mención actualizada correctamente."))
            return redirect(mention_return_url(request, project, mention=mention))
    else:
        form = CharacterMentionForm(project=project, instance=mention)

    return render(
        request,
        "characters/mention_form.html",
        {
            "form": form,
            "project": project,
            "mention": mention,
            "title": _("Editar mención"),
            "submit_label": _("Guardar mención"),
            "return_url": mention_return_url(request, project, mention=mention),
        },
    )


@login_required
def mention_delete(request, project_pk, mention_pk):
    project = get_user_project(request.user, project_pk)
    mention = get_project_mention(project, mention_pk)
    if not project_allows_character_changes(project):
        raise Http404(_("No se pueden gestionar menciones en proyectos eliminados o pendientes de borrado."))

    if request.method == "POST":
        return_url = mention_return_url(request, project, mention=mention)
        mention.delete()
        messages.success(request, _("Mención quitada correctamente."))
        return redirect(return_url)

    return render(
        request,
        "characters/mention_confirm_delete.html",
        {
            "project": project,
            "mention": mention,
            "return_url": mention_return_url(request, project, mention=mention),
        },
    )
