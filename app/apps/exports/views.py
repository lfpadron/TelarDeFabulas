from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_safe

from apps.core.decorators import project_access
from apps.core.files import open_private_file, private_file_response
from apps.core.permissions import Action, can_download_export, can_export_project, local_project_relations

from .forms import ExportJobForm, ExportPreviewForm
from .models import ExportJob
from .services import render_export_html
from .tasks import generate_export_job


def get_project_export_job(user, project, export_pk):
    return get_object_or_404(
        local_project_relations(ExportJob.objects.select_related("project", "root_node", "style_template", "user")),
        pk=export_pk,
        project=project,
        user=user,
    )


DOWNLOAD_CONTENT_TYPES = {
    ExportJob.ExportFormat.HTML: "text/html; charset=utf-8",
    ExportJob.ExportFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ExportJob.ExportFormat.PDF: "application/pdf",
    ExportJob.ExportFormat.EPUB: "application/epub+zip",
}

DOWNLOAD_EXTENSIONS = {
    ExportJob.ExportFormat.HTML: "html",
    ExportJob.ExportFormat.DOCX: "docx",
    ExportJob.ExportFormat.PDF: "pdf",
    ExportJob.ExportFormat.EPUB: "epub",
}


@login_required
@project_access()
def export_list(request, project_pk):
    project = request.project
    export_jobs = (
        local_project_relations(ExportJob.objects.filter(project=project, user=request.user))
        .select_related("root_node", "style_template")
        .order_by("-created_at")
    )
    return render(
        request,
        "exports/export_list.html",
        {
            "project": project,
            "export_jobs": export_jobs,
            "can_create_export": can_export_project(request.user, project),
        },
    )


@login_required
@project_access(Action.EXPORT)
def export_create(request, project_pk):
    project = request.project

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
@project_access(Action.EXPORT)
def export_preview(request, project_pk):
    project = request.project

    preview_result = None
    if request.GET:
        form = ExportPreviewForm(request.GET, user=request.user, project=project)
        if form.is_valid():
            preview_result = render_export_html(
                project=project,
                root_node=form.cleaned_data["root_node"],
                style_template=form.cleaned_data["style_template"],
                max_nodes=settings.EXPORT_PREVIEW_MAX_NODES,
                max_words=settings.EXPORT_PREVIEW_MAX_WORDS,
                preview_mode=True,
            )
    else:
        form = ExportPreviewForm(user=request.user, project=project)
        default_style = form.fields["style_template"].queryset.first()
        if default_style:
            form.initial["style_template"] = default_style.pk
            preview_result = render_export_html(
                project=project,
                style_template=default_style,
                max_nodes=settings.EXPORT_PREVIEW_MAX_NODES,
                max_words=settings.EXPORT_PREVIEW_MAX_WORDS,
                preview_mode=True,
            )

    return render(
        request,
        "exports/export_preview.html",
        {
            "form": form,
            "project": project,
            "preview_result": preview_result,
            "max_nodes": settings.EXPORT_PREVIEW_MAX_NODES,
            "max_words": settings.EXPORT_PREVIEW_MAX_WORDS,
        },
    )


@login_required
@project_access()
def export_detail(request, project_pk, export_pk):
    project = request.project
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
@project_access(Action.DOWNLOAD)
@require_safe
def export_download(request, project_pk, export_pk):
    project = request.project
    export_job = get_project_export_job(request.user, project, export_pk)
    if not can_download_export(request.user, export_job):
        raise Http404(_("La exportación todavía no está disponible para descarga."))

    project_slug = slugify(project.name) or "exportacion"
    extension = DOWNLOAD_EXTENSIONS.get(export_job.format, "bin")
    content_type = DOWNLOAD_CONTENT_TYPES.get(export_job.format, "application/octet-stream")
    filename = f"{project_slug}-{export_job.pk}.{extension}"
    return private_file_response(
        open_private_file(export_job.file, f"exports/{request.user.pk}/{project.pk}/"),
        as_attachment=True,
        filename=filename,
        content_type=content_type,
    )
