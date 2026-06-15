from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _

from apps.projects.models import Project

from .forms import ManuscriptNodeForm
from .models import ManuscriptNode


def get_user_project(user, project_pk):
    return get_object_or_404(Project, pk=project_pk, user=user)


def get_project_node(project, node_pk):
    return get_object_or_404(ManuscriptNode, pk=node_pk, project=project)


def project_allows_manuscript_changes(project):
    return project.status not in (Project.ProjectStatus.DELETED, Project.ProjectStatus.PENDING_DELETION)


def build_tree_rows(nodes):
    children_by_parent = {}
    for node in nodes:
        children_by_parent.setdefault(node.parent_id, []).append(node)

    rows = []

    def visit(parent_id, level):
        for node in children_by_parent.get(parent_id, []):
            rows.append({"node": node, "level": level, "indent": level * 24})
            visit(node.id, level + 1)

    visit(None, 0)
    return rows


@login_required
def manuscript_tree(request, project_pk):
    project = get_user_project(request.user, project_pk)
    nodes = ManuscriptNode.objects.filter(project=project).select_related("parent").order_by("parent_id", "position", "created_at")
    return render(
        request,
        "manuscripts/manuscript_tree.html",
        {
            "project": project,
            "tree_rows": build_tree_rows(nodes),
        },
    )


@login_required
def node_create(request, project_pk):
    project = get_user_project(request.user, project_pk)
    if not project_allows_manuscript_changes(project):
        messages.error(request, _("No se pueden crear nodos en proyectos eliminados o pendientes de borrado."))
        return redirect("projects:detail", pk=project.pk)

    if request.method == "POST":
        form = ManuscriptNodeForm(request.POST, project=project)
        if form.is_valid():
            node = form.save()
            messages.success(request, _("Nodo creado correctamente."))
            return redirect("manuscripts:detail", project_pk=project.pk, node_pk=node.pk)
    else:
        form = ManuscriptNodeForm(project=project)

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
def node_detail(request, project_pk, node_pk):
    project = get_user_project(request.user, project_pk)
    node = get_project_node(project, node_pk)
    return render(request, "manuscripts/node_detail.html", {"project": project, "node": node})


@login_required
def node_edit(request, project_pk, node_pk):
    project = get_user_project(request.user, project_pk)
    node = get_project_node(project, node_pk)
    if not project_allows_manuscript_changes(project):
        raise Http404(_("No se pueden editar nodos en proyectos eliminados o pendientes de borrado."))

    if request.method == "POST":
        form = ManuscriptNodeForm(request.POST, instance=node, project=project)
        if form.is_valid():
            node = form.save()
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
def node_delete(request, project_pk, node_pk):
    project = get_user_project(request.user, project_pk)
    node = get_project_node(project, node_pk)
    if node.children.exists():
        messages.error(request, _("No puedes borrar un nodo que tiene hijos. Borra o mueve primero sus hijos."))
        return redirect("manuscripts:detail", project_pk=project.pk, node_pk=node.pk)

    if request.method == "POST":
        node.delete()
        messages.success(request, _("Nodo borrado correctamente."))
        return redirect("manuscripts:tree", project_pk=project.pk)

    return render(request, "manuscripts/node_confirm_delete.html", {"project": project, "node": node})
