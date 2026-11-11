from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import project_access
from apps.core.permissions import Action, can_edit_project

from .forms import ManuscriptNodeForm, ManuscriptNodeMoveForm
from .hierarchy import ALLOWED_CHILD_TYPES, LEGACY_MESSAGE, editable_node_ids, load_structure, ordered_tree
from .models import ManuscriptNode, SceneVersion
from .services import move_node, move_node_down, move_node_up
from .trash import soft_delete_node
from .version_services import get_current_draft_version, get_current_final_version, select_scene_versions


def get_project_node(project, node_pk):
    return get_object_or_404(ManuscriptNode.objects.filter(project=project).visible(), pk=node_pk)


def require_editable_node(node):
    if node.pk not in editable_node_ids(load_structure(node.project_id)):
        raise PermissionDenied(LEGACY_MESSAGE)


def build_tree_rows(nodes):
    nodes = list(nodes)
    structure = {node.pk: {name: getattr(node, name) for name in
                           ("id", "project_id", "parent_id", "node_type", "title", "position")} for node in nodes}
    editable = editable_node_ids(structure)
    versions = select_scene_versions(nodes, include_content=False)
    children_by_parent = {}
    for node in nodes:
        children_by_parent.setdefault(node.parent_id, []).append(node)

    rows = []
    for node, level in ordered_tree(nodes):
        siblings = children_by_parent[node.parent_id]
        index = siblings.index(node)
        movable = node.pk in editable and all(sibling.pk in editable for sibling in siblings)
        rows.append({"node": node, "level": level, "indent": min(level, 8) * 16,
                     "version": versions.get(node.pk),
                     "editorial_label": dict(SceneVersion.EditorialStage.choices).get(versions.get(node.pk, {}).get("editorial_stage")),
                     "editable": node.pk in editable, "can_move": movable,
                     "can_move_up": movable and index > 0,
                     "can_move_down": movable and index < len(siblings) - 1,
                     "can_create_child": node.pk in editable and bool(ALLOWED_CHILD_TYPES.get(node.node_type)),
                     "can_delete": movable})
    return rows


def safe_next_url(request):
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return None


def node_return_url(request, project, node):
    return safe_next_url(request) or reverse("manuscripts:detail", kwargs={"project_pk": project.pk, "node_pk": node.pk})


def get_parent_from_request_or_404(project, raw_parent):
    if raw_parent in (None, ""):
        return None
    try:
        int(raw_parent)
    except (TypeError, ValueError):
        raise Http404(_("Nuevo padre no encontrado."))
    return get_object_or_404(ManuscriptNode.objects.filter(project=project).visible(), pk=raw_parent)


@login_required
@project_access()
def manuscript_tree(request, project_pk):
    project = request.project
    nodes = ManuscriptNode.objects.filter(project=project).visible().defer("content").order_by("position", "created_at", "pk")
    rows = build_tree_rows(nodes)
    return render(
        request,
        "manuscripts/manuscript_tree.html",
        {
            "project": project,
            "tree_rows": rows,
            "can_create_book": all(row["editable"] for row in rows if row["node"].parent_id is None),
        },
    )


@login_required
@project_access(Action.CREATE)
def node_create(request, project_pk):
    project = request.project
    parent = get_parent_from_request_or_404(project, request.GET.get("parent") or request.POST.get("parent"))
    if parent:
        require_editable_node(parent)
        if not ALLOWED_CHILD_TYPES[parent.node_type]:
            raise PermissionDenied(_("Este tipo de nodo no admite hijos."))
    initial = {"parent": parent, "node_type": ALLOWED_CHILD_TYPES[parent.node_type][0] if parent else "BOOK"}

    if request.method == "POST":
        form = ManuscriptNodeForm(request.POST, project=project, initial=initial)
        if form.is_valid():
            try:
                node = form.save()
            except ValidationError as error:
                form.add_error(None, " ".join(error.messages))
            else:
                messages.success(request, _("Nodo creado correctamente."))
                return redirect("manuscripts:detail", project_pk=project.pk, node_pk=node.pk)
    else:
        form = ManuscriptNodeForm(project=project, initial=initial)
        allowed = ALLOWED_CHILD_TYPES[parent.node_type] if parent else ("BOOK",)
        form.fields["node_type"].choices = [(value, label) for value, label in ManuscriptNode.NodeType.choices if value in allowed]

    return render(
        request,
        "manuscripts/node_form.html",
        {
            "form": form,
            "project": project,
            "title": _("Crear nodo"),
            "submit_label": _("Crear nodo"),
        },
    )


@login_required
@project_access()
def node_detail(request, project_pk, node_pk):
    project = request.project
    node = get_project_node(project, node_pk)
    node_mentions = node.character_mentions.filter(character__project=project).select_related("character").order_by("character__name", "mention_type")
    row = next(row for row in build_tree_rows(ManuscriptNode.objects.filter(project=project).visible().defer("content").order_by("position", "created_at", "pk")) if row["node"].pk == node.pk)
    draft = get_current_draft_version(node) if node.node_type == "SCENE" else None
    final = get_current_final_version(node) if node.node_type == "SCENE" else None
    working = draft or final
    return render(
        request,
        "manuscripts/node_detail.html",
        {
            "project": project,
            "node": node,
            "node_mentions": node_mentions,
            "can_manage_mentions": can_edit_project(request.user, project),
            "node_access": row,
            "draft": draft,
            "final": final,
            "working_version": working,
            "display_content": (working.content if working else "") if node.node_type == "SCENE" else node.content,
            "parent": ManuscriptNode.objects.filter(project=project, pk=node.parent_id).first(),
        },
    )


@login_required
@project_access(Action.EDIT)
def node_edit(request, project_pk, node_pk):
    project = request.project
    node = get_project_node(project, node_pk)
    require_editable_node(node)

    if request.method == "POST":
        form = ManuscriptNodeForm(request.POST, instance=node, project=project)
        if form.is_valid():
            try:
                node = form.save()
            except ValidationError as error:
                form.add_error(None, " ".join(error.messages))
            else:
                messages.success(request, _("Nodo actualizado correctamente."))
                return redirect("manuscripts:detail", project_pk=project.pk, node_pk=node.pk)
    else:
        form = ManuscriptNodeForm(instance=node, project=project)

    return render(
        request,
        "manuscripts/node_form.html",
        {
            "form": form,
            "project": project,
            "node": node,
            "title": _("Editar nodo"),
            "submit_label": _("Guardar nodo"),
        },
    )


@login_required
@project_access(Action.DELETE)
def node_delete(request, project_pk, node_pk):
    project = request.project
    node = get_project_node(project, node_pk)
    require_editable_node(node)
    if request.method == "POST":
        try:
            soft_delete_node(node, user=request.user)
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("manuscripts:detail", project_pk=project.pk, node_pk=node.pk)
        messages.success(request, _("Nodo enviado a la papelera. Sus versiones y vínculos se conservan."))
        return redirect("manuscripts:tree", project_pk=project.pk)

    return render(request, "manuscripts/node_confirm_delete.html", {"project": project, "node": node})


@login_required
@project_access(Action.EDIT)
def node_move(request, project_pk, node_pk):
    project = request.project
    node = get_project_node(project, node_pk)
    require_editable_node(node)

    if request.method == "POST":
        get_parent_from_request_or_404(project, request.POST.get("parent"))
        form = ManuscriptNodeMoveForm(request.POST, project=project, node=node)
        if form.is_valid():
            try:
                moved_node = move_node(
                    node,
                    form.cleaned_data["parent"],
                    form.cleaned_data["position"],
                    user=request.user,
                )
            except ValidationError as error:
                form.add_error(None, " ".join(error.messages))
            else:
                messages.success(request, _("Nodo movido correctamente."))
                return redirect(node_return_url(request, project, moved_node))
    else:
        form = ManuscriptNodeMoveForm(
            project=project,
            node=node,
            initial={
                "parent": node.parent_id,
                "position": node.position,
            },
        )

    return render(
        request,
        "manuscripts/node_move.html",
        {
            "form": form,
            "project": project,
            "node": node,
            "return_url": node_return_url(request, project, node),
        },
    )


@login_required
@require_POST
@project_access(Action.EDIT)
def node_move_up(request, project_pk, node_pk):
    project = request.project
    node = get_project_node(project, node_pk)
    require_editable_node(node)
    try:
        move_node_up(node, user=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, _("Nodo movido hacia arriba."))
    return redirect(node_return_url(request, project, node))


@login_required
@require_POST
@project_access(Action.EDIT)
def node_move_down(request, project_pk, node_pk):
    project = request.project
    node = get_project_node(project, node_pk)
    require_editable_node(node)
    try:
        move_node_down(node, user=request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        messages.success(request, _("Nodo movido hacia abajo."))
    return redirect(node_return_url(request, project, node))
