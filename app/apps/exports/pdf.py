from .services import build_export_html


def build_export_pdf_html(export_job):
    return build_export_html(export_job)


def reject_external_resource(url, *args, **kwargs):
    raise ValueError("External resources are not permitted in exports.")


def build_export_pdf(export_job):
    from weasyprint import HTML

    html_content = build_export_pdf_html(export_job)
    return HTML(string=html_content, url_fetcher=reject_external_resource).write_pdf()
