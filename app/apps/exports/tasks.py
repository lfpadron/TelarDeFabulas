from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.translation import gettext as _

from config.celery import app

from apps.core.permissions import can_export_project

from .docx import build_export_docx
from .epub import build_export_epub
from .models import ExportJob
from .pdf import build_export_pdf
from .services import build_export_html


@app.task(name="apps.exports.generate_export_job")
def generate_export_job(export_job_id):
    export_job = ExportJob.objects.select_related("project", "root_node", "style_template", "user").get(pk=export_job_id)
    export_job.status = ExportJob.ExportStatus.PROCESSING
    export_job.started_at = timezone.now()
    export_job.error_message = ""
    export_job.save(update_fields=["status", "started_at", "error_message"])

    try:
        if not can_export_project(export_job.user, export_job.project):
            raise PermissionError("Export no longer authorized.")
        export_job.full_clean(exclude=["file"])
        if export_job.format == ExportJob.ExportFormat.HTML:
            html_content = build_export_html(export_job)
            export_job.file.save(f"{export_job.pk}.html", ContentFile(html_content.encode("utf-8")), save=False)
        elif export_job.format == ExportJob.ExportFormat.DOCX:
            docx_content = build_export_docx(export_job)
            export_job.file.save(f"{export_job.pk}.docx", ContentFile(docx_content), save=False)
        elif export_job.format == ExportJob.ExportFormat.PDF:
            pdf_content = build_export_pdf(export_job)
            export_job.file.save(f"{export_job.pk}.pdf", ContentFile(pdf_content), save=False)
        elif export_job.format == ExportJob.ExportFormat.EPUB:
            epub_content = build_export_epub(export_job)
            export_job.file.save(f"{export_job.pk}.epub", ContentFile(epub_content), save=False)
        else:
            raise NotImplementedError(_("Formato todavía no implementado."))

        export_job.status = ExportJob.ExportStatus.DONE
        export_job.finished_at = timezone.now()
        export_job.error_message = ""
        export_job.save(update_fields=["file", "status", "finished_at", "error_message"])
    except Exception:
        export_job.status = ExportJob.ExportStatus.FAILED
        export_job.error_message = _("No se pudo generar la exportación. Revisa sus permisos y vuelve a intentarlo.")
        export_job.finished_at = timezone.now()
        export_job.save(update_fields=["status", "error_message", "finished_at"])
