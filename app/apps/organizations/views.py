from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from apps.characters.models import Character
from apps.core.decorators import project_access
from apps.core.permissions import Action, local_project_relations

from .forms import MembershipForm, MoveOrganizationForm, OrganizationForm
from .membership_services import delete_membership, save_membership
from .models import Organization
from .selectors import organization_path, project_memberships, tree_events
from .services import delete_organization, deletion_blockers, move_organization, move_organization_down, move_organization_up, save_organization


def get_organization(project, pk):
    return get_object_or_404(local_project_relations(Organization.objects.select_related("headquarters")), project=project, pk=pk)


def get_reference(model, project, raw_pk):
    if raw_pk in (None, ""):
        return None
    if not str(raw_pk).isascii() or not str(raw_pk).isdigit() or len(str(raw_pk)) > 18:
        raise Http404
    return get_object_or_404(local_project_relations(model.objects.all()), project=project, pk=raw_pk)


@login_required
@require_safe
@project_access()
def tree(request, project_pk):
    try:
        events = tree_events(request.project)
    except ValidationError as exc:
        events = []
        messages.error(request, " ".join(exc.messages))
    return render(request, "organizations/tree.html", {"project": request.project, "events": events})


@login_required
@require_safe
@project_access()
def detail(request, project_pk, organization_pk):
    organization = get_organization(request.project, organization_pk)
    try:
        path = organization_path(organization)
    except ValidationError as exc:
        path = []
        messages.error(request, " ".join(exc.messages))
    children = organization.children.filter(project=request.project).defer("detailed_description")
    memberships = project_memberships(request.project).filter(organization=organization)
    return render(request, "organizations/detail.html", {
        "project": request.project, "organization": organization, "path": path,
        "children": Paginator(children, 50).get_page(request.GET.get("children_page")),
        "memberships": Paginator(memberships, 50).get_page(request.GET.get("memberships_page")),
    })


def _organization_form(request, organization=None):
    initial = {}
    if organization is None and request.method == "GET":
        parent = get_reference(Organization, request.project, request.GET.get("parent"))
        if parent:
            initial["parent"] = parent.pk
    form = OrganizationForm(request.POST if request.method == "POST" else None,
                            instance=organization, project=request.project, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            organization = form.save(commit=False)
            save_organization(organization, user=request.user)
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
        else:
            messages.success(request, _("Organización guardada correctamente."))
            return redirect("organizations:detail", project_pk=request.project.pk, organization_pk=organization.pk)
    return render(request, "organizations/form.html", {"project": request.project, "organization": organization,
        "form": form, "title": _("Editar organización") if organization else _("Crear organización"),
        "return_url": reverse("organizations:tree", args=[request.project.pk])})


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.CREATE)
def create(request, project_pk):
    return _organization_form(request)


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.EDIT)
def edit(request, project_pk, organization_pk):
    return _organization_form(request, get_organization(request.project, organization_pk))


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.EDIT)
def move(request, project_pk, organization_pk):
    organization = get_organization(request.project, organization_pk)
    form = MoveOrganizationForm(request.POST if request.method == "POST" else None,
                                project=request.project, organization=organization)
    if request.method == "POST" and form.is_valid():
        try:
            move_organization(organization, form.cleaned_data["parent"], form.cleaned_data["position"], user=request.user)
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
        else:
            messages.success(request, _("Organización movida correctamente."))
            return redirect("organizations:tree", project_pk=request.project.pk)
    return render(request, "organizations/form.html", {"project": request.project, "organization": organization,
        "form": form, "title": _("Mover organización"), "return_url": reverse("organizations:tree", args=[request.project.pk])})


@login_required
@require_POST
@project_access(Action.EDIT)
def reorder(request, project_pk, organization_pk, direction):
    organization = get_organization(request.project, organization_pk)
    try:
        (move_organization_up if direction == "up" else move_organization_down)(organization, user=request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("organizations:tree", project_pk=request.project.pk)


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.DELETE)
def delete(request, project_pk, organization_pk):
    organization = get_organization(request.project, organization_pk)
    if request.method == "POST":
        try:
            delete_organization(organization, user=request.user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, _("Organización eliminada correctamente."))
            return redirect("organizations:tree", project_pk=request.project.pk)
    return render(request, "organizations/confirm_delete.html", {"project": request.project,
        "organization": organization, "blockers": deletion_blockers(organization)})


def _membership_return_url(project, origin, character=None, organization=None):
    if origin == "character" and character is not None:
        return reverse("characters:detail", args=[project.pk, character.pk])
    if organization is not None:
        return reverse("organizations:detail", args=[project.pk, organization.pk])
    return reverse("organizations:tree", args=[project.pk])


def _membership_form(request, membership=None):
    initial = {}
    character = organization = None
    values = request.POST if request.method == "POST" else request.GET
    for key, model in (("character", Character), ("organization", Organization)):
        obj = get_reference(model, request.project, values.get(key))
        if obj:
            initial[key] = obj.pk
            if key == "character":
                character = obj
            else:
                organization = obj
    origin = values.get("return_to") or ("character" if character and not organization else "organization")
    origin = "character" if origin == "character" else "organization"
    if membership:
        character, organization = membership.character, membership.organization
    form = MembershipForm(request.POST if request.method == "POST" else None,
                          instance=membership, project=request.project, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            membership = form.save(commit=False)
            save_membership(membership, user=request.user)
        except ValidationError as exc:
            form.add_error(None, ValidationError(exc.messages))
        else:
            messages.success(request, _("Afiliación guardada correctamente."))
            return redirect(_membership_return_url(request.project, origin, membership.character, membership.organization))
    return render(request, "organizations/form.html", {"project": request.project, "form": form,
        "title": _("Editar afiliación") if membership else _("Agregar afiliación"), "return_to": origin,
        "return_url": _membership_return_url(request.project, origin, character, organization)})


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.CREATE)
def membership_create(request, project_pk):
    return _membership_form(request)


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.EDIT)
def membership_edit(request, project_pk, membership_pk):
    membership = get_object_or_404(project_memberships(request.project), pk=membership_pk)
    return _membership_form(request, membership)


@login_required
@require_http_methods(["GET", "POST"])
@project_access(Action.DELETE)
def membership_delete(request, project_pk, membership_pk):
    membership = get_object_or_404(project_memberships(request.project), pk=membership_pk)
    values = request.POST if request.method == "POST" else request.GET
    origin = "character" if values.get("return_to") == "character" else "organization"
    return_url = _membership_return_url(request.project, origin, membership.character, membership.organization)
    if request.method == "POST":
        delete_membership(membership, user=request.user)
        messages.success(request, _("Afiliación eliminada correctamente."))
        return redirect(return_url)
    return render(request, "organizations/membership_confirm_delete.html", {"project": request.project,
        "membership": membership, "return_url": return_url, "return_to": origin})
