from pathlib import PurePosixPath
import warnings

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from PIL import Image


IMAGE_FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
IMAGE_CONTENT_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}


def verified_image_format(file, *, allow_legacy_gif=False):
    formats = ["JPEG", "PNG", "WEBP"] + (["GIF"] if allow_legacy_gif else [])
    position = file.tell()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            file.seek(0)
            with Image.open(file, formats=formats) as image:
                image_format = image.format
                image.verify()
            file.seek(0)
            with Image.open(file, formats=formats) as image:
                image.load()
        return image_format
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError(_("El archivo no es una imagen valida o esta corrupto.")) from None
    finally:
        file.seek(position)


def validate_character_image(value):
    # Existing references remain readable; validate uploads, not old files on every text edit.
    if not value or getattr(value, "_committed", False):
        return
    name = value.name
    if any(char in name for char in ("/", "\\", ":", "\x00")) or name.startswith("."):
        raise ValidationError(_("Nombre de archivo no permitido."))
    expected_format = IMAGE_FORMATS.get(PurePosixPath(name).suffix.lower())
    if expected_format is None:
        raise ValidationError(_("Sube una imagen JPEG, PNG o WebP. No se permite SVG ni GIF."))
    if value.size > settings.CHARACTER_IMAGE_MAX_MB * 1024 * 1024:
        raise ValidationError(_("La imagen supera el limite de %(limit)s MB."), params={"limit": settings.CHARACTER_IMAGE_MAX_MB})
    if verified_image_format(value) != expected_format:
        raise ValidationError(_("La extension no coincide con el contenido real de la imagen."))
