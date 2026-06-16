from django.conf import settings

from .services import build_export_html


def build_export_pdf_html(export_job):
    return build_export_html(export_job)


def build_export_pdf(export_job):
    from weasyprint import HTML

    html_content = build_export_pdf_html(export_job)
    return HTML(string=html_content, base_url=str(settings.BASE_DIR)).write_pdf()
