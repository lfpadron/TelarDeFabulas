from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods, require_safe

from apps.core.decorators import project_access
from apps.core.permissions import Action, local_project_relations
from .models import Character, CharacterRelationship
from .relationship_forms import CharacterRelationshipForm
from .relationship_selectors import local_relationships, relationship_groups
from .relationship_services import delete_relationship


def _character(project, pk):
    character = get_object_or_404(local_project_relations(Character.objects.filter(project=project)).only("id", "name", "project_id"), pk=pk)
    character.project = project
    return character


def _relationship(project, pk):
    return get_object_or_404(local_relationships(CharacterRelationship.objects.filter(project=project)).select_related(
        "source_character", "target_character").defer(*[
            f"{endpoint}__{field.name}" for endpoint in ("source_character", "target_character")
            for field in Character._meta.fields if field.name not in ("id", "name", "project")]), pk=pk)


def _context_character(request, relationship):
    pk = request.GET.get("character")
    if pk is None:
        return _character(request.project, relationship.source_character_id)
    if not pk.isascii() or not pk.isdigit() or len(pk) > 18:
        raise Http404
    return _character(request.project, pk)


@login_required
@require_safe
@project_access()
def relationship_list(request, project_pk, character_pk):
    character = _character(request.project, character_pk)
    return render(request, "characters/relationships/list.html", {"project": request.project, "character": character,
        "relationship_groups": relationship_groups(character, request.GET)})


@login_required
@require_safe
@project_access()
def detail(request, project_pk, relationship_pk):
    relationship = _relationship(request.project, relationship_pk)
    return render(request, "characters/relationships/detail.html", {"project": request.project, "relationship": relationship,
        "character": _context_character(request, relationship)})


def _form(request, character, relationship=None):
    form = CharacterRelationshipForm(request.POST if request.method == "POST" else None, project=request.project,
        instance=relationship, source_character=character if relationship is None else None)
    if request.method == "POST" and form.is_valid():
        try:
            relationship = form.save(user=request.user)
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
        else:
            messages.success(request, _("Relación guardada correctamente."))
            return redirect("characters:relationship_list", project_pk=request.project.pk, character_pk=character.pk)
    return render(request, "characters/relationships/form.html", {"project": request.project, "character": character,
        "relationship": relationship, "form": form, "title": _("Editar relación") if relationship else _("Agregar relación")})


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.CREATE)
def create(request, project_pk, character_pk):
    return _form(request, _character(request.project, character_pk))


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.EDIT)
def edit(request, project_pk, relationship_pk):
    relationship = _relationship(request.project, relationship_pk)
    return _form(request, _context_character(request, relationship), relationship)


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.DELETE)
def delete(request, project_pk, relationship_pk):
    relationship = _relationship(request.project, relationship_pk)
    character = _context_character(request, relationship)
    if request.method == "POST":
        delete_relationship(relationship, user=request.user)
        messages.success(request, _("Relación eliminada. Los personajes se conservan."))
        return redirect("characters:relationship_list", project_pk=request.project.pk, character_pk=character.pk)
    return render(request, "characters/relationships/confirm_delete.html", {"project": request.project,
        "character": character, "relationship": relationship})
