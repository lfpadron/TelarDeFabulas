from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
import re
import unicodedata
from zlib import error as ZlibError
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile
from xml.etree import ElementTree

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.translation import gettext_lazy as _
from pypdf import PdfReader

from apps.characters.validators import IMAGE_CONTENT_TYPES, IMAGE_FORMATS, verified_image_format


DOCUMENT_TYPES = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown",
                  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
validate_source_url = URLValidator(schemes=["http", "https"])


@dataclass(frozen=True)
class ValidatedUpload:
    content: bytes
    original_filename: str
    extension: str
    mime_type: str

    @property
    def size(self):
        return len(self.content)


def safe_original_filename(name):
    name = unicodedata.normalize("NFC", str(name))
    if (not name or len(name) > 240 or name.startswith(".") or name.endswith((".", " "))
            or any(c in name for c in '/\\:<>"|?*')
            or any(unicodedata.category(c).startswith("C") for c in name)
            or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}):
        raise ValidationError(_("Nombre de archivo no permitido."))
    return name


def _xml(data):
    text = data.decode("utf-8-sig")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("XML declarations not permitted")
    return ElementTree.fromstring(text)


def _validate_docx(data):
    with ZipFile(BytesIO(data)) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(infos) > 2048 or len(names) != len(set(names)) or sum(i.file_size for i in infos) > 50 * 1024 * 1024:
            raise ValueError("Container limits")
        required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
        if not required <= set(names):
            raise ValueError("Missing OOXML structure")
        documents = {}
        for item in infos:
            path = PurePosixPath(item.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in item.filename or ":" in item.filename
                    or item.flag_bits & 1 or item.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
                    or (item.external_attr >> 16) & 0o170000 == 0o120000
                    or item.file_size > 20 * 1024 * 1024 or item.file_size > max(item.compress_size, 1) * 200
                    or "vbaproject" in item.filename.lower() or item.filename.lower().endswith((".exe", ".bin"))):
                raise ValueError("Unsafe ZIP member")
            with archive.open(item) as source:
                content = source.read(20 * 1024 * 1024 + 1)
            if len(content) != item.file_size:
                raise ValueError("Invalid ZIP member")
            if item.filename.endswith((".xml", ".rels")):
                root = _xml(content)
                if item.filename in required:
                    documents[item.filename] = root
        types = documents["[Content_Types].xml"]
        ns = "{http://schemas.openxmlformats.org/package/2006/content-types}"
        main_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
        if types.tag != ns + "Types" or not any(el.get("PartName") == "/word/document.xml" and el.get("ContentType") == main_type for el in types):
            raise ValueError("Not a DOCX document")
        if any("macroenabled" in el.get("ContentType", "").lower() or "vba" in el.get("ContentType", "").lower() for el in types):
            raise ValueError("Macros not permitted")
        rels = documents["_rels/.rels"]
        if not any(el.get("Type", "").endswith("/officeDocument") and el.get("Target") in ("word/document.xml", "/word/document.xml")
                   and el.get("TargetMode", "Internal") == "Internal" for el in rels):
            raise ValueError("Missing document relationship")
        root = documents["word/document.xml"]
        word_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        if root.tag != word_ns + "document" or root.find(word_ns + "body") is None:
            raise ValueError("Missing document body")


def _validate_pdf(data):
    if not re.match(rb"%PDF-(1\.[0-7]|2\.0)[\r\n]", data) or not data.rstrip().endswith(b"%%EOF"):
        raise ValueError("Invalid PDF signature")
    reader = PdfReader(BytesIO(data), strict=True, root_object_recovery_limit=0)
    if reader.is_encrypted:
        raise ValueError("Encrypted documents cannot be validated")
    root = reader.trailer["/Root"]
    pages = root["/Pages"]
    if root.get("/Type") != "/Catalog" or pages.get("/Type") != "/Pages" or not pages.get("/Kids") or pages.get("/Count", 0) < 1:
        raise ValueError("Invalid PDF structure")


def validate_reference_upload(upload):
    name = safe_original_filename(upload.name)
    extension = PurePosixPath(name).suffix.lower()
    is_image = extension in IMAGE_FORMATS
    if not is_image and extension not in DOCUMENT_TYPES:
        raise ValidationError(_("Sube JPEG, PNG, WebP, PDF, TXT, MD o DOCX."))
    limit_mb = settings.REFERENCE_IMAGE_MAX_MB if is_image else settings.REFERENCE_DOCUMENT_MAX_MB
    upload.seek(0)
    data = upload.read(limit_mb * 1024 * 1024 + 1)
    upload.seek(0)
    if not data:
        raise ValidationError(_("El archivo está vacío."))
    if len(data) > limit_mb * 1024 * 1024:
        raise ValidationError(_("El archivo supera el límite de %(limit)s MB."), params={"limit": limit_mb})
    try:
        if is_image:
            actual = verified_image_format(BytesIO(data))
            if actual != IMAGE_FORMATS[extension]:
                raise ValueError("Image extension mismatch")
            mime = IMAGE_CONTENT_TYPES[actual]
        else:
            mime = DOCUMENT_TYPES[extension]
            if extension == ".pdf":
                _validate_pdf(data)
            elif extension == ".docx":
                _validate_docx(data)
            else:
                text = data.decode("utf-8-sig")
                if any(ord(c) < 32 and c not in "\t\r\n" for c in text) or "\x7f" in text:
                    raise ValueError("Binary text")
                if text.lstrip().lower().startswith(("<!doctype html", "<html", "<svg", "<script")):
                    raise ValueError("Active markup")
    except (ValidationError, ValueError, OSError, KeyError, TypeError, IndexError, RecursionError, BadZipFile, ZlibError, ElementTree.ParseError):
        raise ValidationError(_("El archivo está corrupto, no es compatible o no coincide con su extensión.")) from None
    except Exception as exc:
        # PDF parsers expose several format-specific exceptions; none should leak file details.
        if extension != ".pdf":
            raise
        raise ValidationError(_("No se pudo validar la estructura del PDF.")) from exc
    return ValidatedUpload(data, name, ".jpg" if extension == ".jpeg" else extension, mime)
