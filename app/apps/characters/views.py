from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_safe

from apps.manuscripts.models import ManuscriptNode
from apps.organizations.selectors import project_memberships
from apps.core.decorators import project_access
from apps.core.files import open_private_file, private_file_response
from apps.core.permissions import Action, can_edit_project, local_project_relations

from .forms import CharacterForm, CharacterMentionForm
from .models import Character, CharacterMention
from .relationship_selectors import relationship_groups
from .validators import IMAGE_CONTENT_TYPES, verified_image_format


def get_project_character(project, character_pk):
    return get_object_or_404(
        local_project_relations(Character.objects.select_related("residence")),
        pk=character_pk, project=project,
    )


def get_project_mention(project, mention_pk):
    return get_object_or_404(
        local_project_relations(CharacterMention.objects.filter(character__project=project).select_related("character", "node"), "character__project"),
        pk=mention_pk,
        character__project=project,
        node__project=project,
    )


def get_reference_for_project(model, project, raw_pk, error_message):
    if raw_pk in (None, ""):
        return None
    try:
        int(raw_pk)
    except (TypeError, ValueError):
        raise Http404(error_message)
    query = model.objects.filter(project=project)
    if model is ManuscriptNode:
        query = query.visible()
    return get_object_or_404(query, pk=raw_pk)


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
@project_access()
def character_list(request, project_pk):
    project = request.project
    visible_nodes = ManuscriptNode.objects.filter(project=project).visible()
    characters = (
        Character.objects.filter(project=project)
        .annotate(
            mention_count=Count("mentions", filter=Q(mentions__node__in=visible_nodes), distinct=True),
            appearance_count=Count(
                "mentions",
                filter=Q(mentions__mention_type=CharacterMention.MentionType.APPEARS, mentions__node__in=visible_nodes),
                distinct=True,
            ),
        )
        .order_by("name")
        .prefetch_related("dramatic_roles")
    )
    return render(request, "characters/character_list.html", {"project": project, "characters": characters})


@login_required
@project_access(Action.CREATE)
def character_create(request, project_pk):
    project = request.project

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
@project_access()
def character_detail(request, project_pk, character_pk):
    project = request.project
    character = get_project_character(project, character_pk)
    linked_notes = local_project_relations(character.work_notes.filter(project=project)).select_related("node").order_by("-updated_at", "title")
    character_mentions = local_project_relations(character.mentions.filter(node__project=project), "character__project").select_related("node").order_by(
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
            "can_manage_mentions": can_edit_project(request.user, project),
            "linked_notes": linked_notes,
            "relationship_groups": relationship_groups(character, request.GET),
            "memberships": Paginator(project_memberships(project).filter(character=character), 50).get_page(request.GET.get("memberships_page")),
        },
    )


@login_required
@project_access(Action.EDIT)
def character_edit(request, project_pk, character_pk):
    project = request.project
    character = get_project_character(project, character_pk)

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
@project_access(Action.DELETE)
def character_delete(request, project_pk, character_pk):
    project = request.project
    character = get_project_character(project, character_pk)

    if request.method == "POST":
        character.delete()
        messages.success(request, _("Personaje borrado correctamente."))
        return redirect("characters:list", project_pk=project.pk)

    return render(request, "characters/character_confirm_delete.html", {"project": project, "character": character})


@login_required
@project_access(Action.CREATE)
def mention_create(request, project_pk):
    project = request.project

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
@project_access(Action.EDIT)
def mention_edit(request, project_pk, mention_pk):
    project = request.project
    mention = get_project_mention(project, mention_pk)

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
@project_access(Action.DELETE)
def mention_delete(request, project_pk, mention_pk):
    project = request.project
    mention = get_project_mention(project, mention_pk)

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


@login_required
@project_access(Action.DOWNLOAD)
@require_safe
def character_image(request, project_pk, character_pk):
    character = get_project_character(request.project, character_pk)
    image_file = open_private_file(character.image, f"characters/{request.project.pk}/")
    try:
        image_format = verified_image_format(image_file, allow_legacy_gif=True)
    except (ValidationError, OSError):
        image_file.close()
        raise Http404(_("Imagen no disponible.")) from None
    return private_file_response(
        image_file, content_type=IMAGE_CONTENT_TYPES[image_format],
        filename=f"character-{character.pk}.{image_format.lower()}",
    )
