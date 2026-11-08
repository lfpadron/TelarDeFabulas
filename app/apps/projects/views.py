from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from apps.core.decorators import project_access
from apps.core.permissions import Action, visible_projects

from .forms import ProjectForm
from .models import Project


@login_required
def project_list(request):
    projects = visible_projects(request.user)
    return render(request, "projects/project_list.html", {"projects": projects})


@login_required
def project_create(request):
    if request.method == "POST":
        form = ProjectForm(request.POST, user=request.user)
        if form.is_valid():
            project = form.save()
            messages.success(request, _("Proyecto creado correctamente."))
            return redirect("projects:detail", pk=project.pk)
    else:
        form = ProjectForm(user=request.user)

    return render(
        request,
        "projects/project_form.html",
        {
            "form": form,
            "title": _("Crear proyecto"),
            "submit_label": _("Crear proyecto"),
        },
    )


@login_required
@project_access(key="pk")
def project_detail(request, pk):
    project = request.project
    return render(request, "projects/project_detail.html", {"project": project})


@login_required
@project_access(Action.EDIT, key="pk")
def project_edit(request, pk):
    project = request.project

    if request.method == "POST":
        form = ProjectForm(request.POST, instance=project, user=request.user)
        if form.is_valid():
            project = form.save()
            messages.success(request, _("Proyecto actualizado correctamente."))
            return redirect("projects:detail", pk=project.pk)
    else:
        form = ProjectForm(instance=project, user=request.user)

    return render(
        request,
        "projects/project_form.html",
        {
            "form": form,
            "project": project,
            "title": _("Editar proyecto"),
            "submit_label": _("Guardar proyecto"),
        },
    )


@login_required
@project_access(Action.DELETE, key="pk")
def project_delete(request, pk):
    project = request.project

    if request.method == "POST":
        try:
            project.mark_for_deletion()
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.warning(
                request,
                _("Proyecto marcado para borrado. Se conservará durante 90 días antes del borrado real."),
            )
        return redirect("projects:detail", pk=project.pk)

    return render(request, "projects/project_confirm_delete.html", {"project": project})


@login_required
@require_POST
@project_access(Action.RESTORE, key="pk")
def project_restore(request, pk):
    project = request.project

    project.restore()
    messages.success(request, _("Proyecto restaurado correctamente."))
    return redirect("projects:detail", pk=project.pk)
