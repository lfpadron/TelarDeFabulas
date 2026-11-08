from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, Http404
from django.utils.cache import patch_cache_control, patch_vary_headers
from django.utils.translation import gettext_lazy as _

from .storage import validate_private_name


def open_private_file(field, expected_prefix):
    try:
        validate_private_name(field.name)
        if not field.name.startswith(expected_prefix):
            raise SuspiciousFileOperation("Invalid private file reference.")
        return field.storage.open(field.name, "rb")
    except (OSError, ValueError, SuspiciousFileOperation):
        raise Http404(_("Archivo no disponible.")) from None


def private_file_response(file, *, content_type, filename, as_attachment=False):
    response = FileResponse(file, content_type=content_type, filename=filename, as_attachment=as_attachment)
    patch_cache_control(response, private=True, no_store=True, no_cache=True, max_age=0)
    patch_vary_headers(response, ("Cookie",))
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
    return response
