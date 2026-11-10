from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST, require_safe

from apps.core.decorators import project_access
from apps.core.files import open_private_file, private_file_response
from apps.core.permissions import Action, can_download_export, can_export_project, get_user_project, local_project_relations
from apps.manuscripts.models import ManuscriptNode
from apps.styles.models import StyleTemplate

from .forms import ExportJobForm, ExportPreviewForm
from .models import ExportJob
from .services import render_export_html
from .job_services import retry_export
from .lifecycle import delete_export, locked_job
from .files import DownloadFile, acquire_download_lock, private_path
from .snapshots import build_manifest, document_from_manifest, select_structure


def snapshot_summary(queryset):
    return queryset.defer("root_node__content", "root_node__short_description").annotate(
        captured_style=F("snapshot__style_name"), captured_title=F("snapshot__scope_title"),
        included_scenes=F("snapshot__included_scene_count"), excluded_scenes=F("snapshot__excluded_scene_count"),
        included_entities=F("snapshot__included_entity_count"),
    )


def get_project_export_job(user, project, export_pk):
    return get_object_or_404(
        snapshot_summary(local_project_relations(ExportJob.objects.select_related("project", "root_node", "style_template", "user"))),
        pk=export_pk,
        project=project,
        user=user,
    )


DOWNLOAD_CONTENT_TYPES = {
    ExportJob.ExportFormat.MARKDOWN: "text/markdown; charset=utf-8",
    ExportJob.ExportFormat.HTML: "text/html; charset=utf-8",
    ExportJob.ExportFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ExportJob.ExportFormat.PDF: "application/pdf",
    ExportJob.ExportFormat.EPUB: "application/epub+zip",
}

DOWNLOAD_EXTENSIONS = {
    ExportJob.ExportFormat.MARKDOWN: "md",
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
        snapshot_summary(local_project_relations(ExportJob.objects.filter(project=project, user=request.user)))
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
    counts = None
    final_review = False
    if request.method == "POST":
        form = ExportJobForm(request.POST, user=request.user, project=project)
        if form.is_valid():
            try:
                with transaction.atomic():
                    locked_project = get_user_project(request.user, project.pk, Action.EXPORT, for_update=True)
                    structure, versions, included, excluded = select_structure(locked_project, form.cleaned_data["root_node"], mode=form.cleaned_data["export_mode"])
                counts = {"included": included, "excluded": excluded}
                selection = [str(form.cleaned_data["request_key"]), project.pk,
                             form.cleaned_data["root_node"].pk if form.cleaned_data["root_node"] else None,
                             form.cleaned_data["style_template"].pk, form.cleaned_data["format"],
                             form.cleaned_data["export_mode"], included, excluded, form.cleaned_data["notify_by_email"]]
                confirmed = None
                try:
                    confirmed = signing.loads(form.cleaned_data["selection_confirmation"], salt="export-selection", max_age=3600)
                except signing.BadSignature:
                    pass
                final_review = form.cleaned_data["export_mode"] == "FINAL"
                if request.POST.get("review") or (final_review and confirmed != selection):
                    form.data = form.data.copy()
                    form.data["selection_confirmation"] = signing.dumps(selection, salt="export-selection")
                else:
                    form.expected_counts = (included, excluded)
                    export_job = form.save()
                    messages.success(request, _("Solicitud de exportación conservada."))
                    return redirect("exports:detail", project_pk=project.pk, export_pk=export_job.pk)
            except ValidationError as exc:
                form.add_error(None, exc)
    else:
        form = ExportJobForm(user=request.user, project=project)
        default_style = form.fields["style_template"].queryset.first()
        if default_style:
            form.initial["style_template"] = default_style.pk

    return render(
        request,
        "exports/export_form.html",
        {
            "form": form,
            "project": project,
            "counts": counts,
            "final_review": final_review,
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
            try:
                preview_result = preview_selection(request.user, project, form.cleaned_data["style_template"],
                                                   root=form.cleaned_data["root_node"], mode=form.cleaned_data["export_mode"])
            except ValidationError as exc:
                form.add_error(None, exc)
    else:
        form = ExportPreviewForm(user=request.user, project=project)
        default_style = form.fields["style_template"].queryset.first()
        if default_style:
            form.initial["style_template"] = default_style.pk
            try:
                preview_result = preview_selection(request.user, project, default_style)
            except ValidationError as exc:
                form = ExportPreviewForm({"style_template": default_style.pk}, user=request.user, project=project)
                form.is_valid()
                form.add_error(None, exc)

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


def preview_selection(user, project, style, *, root=None, mode="WORK"):
    with transaction.atomic():
        project = get_user_project(user, project.pk, Action.EXPORT, for_update=True)
        style = get_object_or_404(StyleTemplate.objects.select_for_update().filter(Q(is_system=True) | Q(user=user)), pk=style.pk)
        if root:
            root = get_object_or_404(ManuscriptNode, pk=root.pk, project=project)
        document = document_from_manifest(build_manifest(project, style, root_node=root, mode=mode,
                                                        max_nodes=settings.EXPORT_PREVIEW_MAX_NODES))
    return render_export_html(document=document, max_words=settings.EXPORT_PREVIEW_MAX_WORDS, preview_mode=True)


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
            "can_retry": can_export_project(request.user, project) and export_job.included_scenes is not None
                         and (export_job.can_retry or (export_job.status == "REQUESTED" and not export_job.enqueued_at and not export_job.deletion_requested_at)),
        },
    )


@login_required
@project_access(Action.EXPORT)
@require_POST
def export_retry(request, project_pk, export_pk):
    job = get_project_export_job(request.user, request.project, export_pk)
    try:
        retry_export(job, user=request.user)
        messages.success(request, _("Se solicitó el reenvío del snapshot original."))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("exports:detail", project_pk=project_pk, export_pk=export_pk)


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
    lease = acquire_download_lock(export_job.pk)
    try:
        with locked_job(export_job.pk) as current:
            if not current or not can_download_export(request.user, current):
                raise Http404
            try:
                private_path(current, current.file.name)
            except (OSError, ValueError, SuspiciousFileOperation):
                raise Http404 from None
            stream = open_private_file(current.file, f"exports/{request.user.pk}/{project.pk}/")
        return private_file_response(DownloadFile(stream, lease), as_attachment=True, filename=filename, content_type=content_type)
    except BaseException:
        lease.close()
        raise


@login_required
@project_access(Action.EXPORT)
@require_POST
def export_delete(request, project_pk, export_pk):
    job = get_project_export_job(request.user, request.project, export_pk)
    try:
        deleted = delete_export(job.pk, user=request.user)
        messages.success(request, _("Exportación borrada.") if deleted else _("Borrado pendiente. Las nuevas descargas ya están bloqueadas."))
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("exports:detail", project_pk=project_pk, export_pk=export_pk)
