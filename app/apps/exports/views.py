from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.projects.models import Project

from .forms import ExportJobForm
from .models import ExportJob
from .tasks import generate_export_job


def get_user_project(user, project_pk):
    return get_object_or_404(Project, pk=project_pk, user=user)


def get_project_export_job(user, project, export_pk):
    return get_object_or_404(
        ExportJob.objects.select_related("project", "root_node", "style_template", "user"),
        pk=export_pk,
        project=project,
        user=user,
    )


def project_allows_exports(project):
    return project.status not in (Project.ProjectStatus.DELETED, Project.ProjectStatus.PENDING_DELETION)


DOWNLOAD_CONTENT_TYPES = {
    ExportJob.ExportFormat.HTML: "text/html; charset=utf-8",
    ExportJob.ExportFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ExportJob.ExportFormat.PDF: "application/pdf",
}

DOWNLOAD_EXTENSIONS = {
    ExportJob.ExportFormat.HTML: "html",
    ExportJob.ExportFormat.DOCX: "docx",
    ExportJob.ExportFormat.PDF: "pdf",
}


@login_required
def export_list(request, project_pk):
    project = get_user_project(request.user, project_pk)
    export_jobs = (
        ExportJob.objects.filter(project=project, user=request.user)
        .select_related("root_node", "style_template")
        .order_by("-created_at")
    )
    return render(
        request,
        "exports/export_list.html",
        {
            "project": project,
            "export_jobs": export_jobs,
            "can_create_export": project_allows_exports(project),
        },
    )


@login_required
def export_create(request, project_pk):
    project = get_user_project(request.user, project_pk)
    if not project_allows_exports(project):
        messages.error(request, _("No se puede exportar un proyecto eliminado o pendiente de borrado."))
        return redirect("projects:detail", pk=project.pk)

    if request.method == "POST":
        form = ExportJobForm(request.POST, user=request.user, project=project)
        if form.is_valid():
            export_job = form.save()
            generate_export_job.delay(export_job.pk)
            messages.success(request, _("Exportación en proceso."))
            return redirect("exports:detail", project_pk=project.pk, export_pk=export_job.pk)
    else:
        form = ExportJobForm(user=request.user, project=project)

    return render(
        request,
        "exports/export_form.html",
        {
            "form": form,
            "project": project,
        },
    )


@login_required
def export_detail(request, project_pk, export_pk):
    project = get_user_project(request.user, project_pk)
    if project.user_id != request.user.id:
        raise Http404(_("No puedes ver exportaciones ajenas."))
    export_job = get_project_export_job(request.user, project, export_pk)
    return render(
        request,
        "exports/export_detail.html",
        {
            "project": project,
            "export_job": export_job,
        },
    )


@login_required
def export_download(request, project_pk, export_pk):
    project = get_user_project(request.user, project_pk)
    export_job = get_project_export_job(request.user, project, export_pk)
    if export_job.status != ExportJob.ExportStatus.DONE or not export_job.file:
        raise Http404(_("La exportación todavía no está disponible para descarga."))

    project_slug = slugify(project.name) or "exportacion"
    extension = DOWNLOAD_EXTENSIONS.get(export_job.format, "bin")
    content_type = DOWNLOAD_CONTENT_TYPES.get(export_job.format, "application/octet-stream")
    filename = f"{project_slug}-{export_job.pk}.{extension}"
    return FileResponse(
        export_job.file.open("rb"),
        as_attachment=True,
        filename=filename,
        content_type=content_type,
    )
