from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED
from zlib import error as ZlibError

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, override_settings
from pypdf import PdfReader, PdfWriter

from .test_support import docx_upload, image_upload, pdf_upload, upload
from .validators import safe_original_filename, validate_reference_upload


class UploadTests(SimpleTestCase):
    def test_jpeg(self):
        self.assertEqual(validate_reference_upload(image_upload("JPEG")).mime_type, "image/jpeg")

    def test_png(self):
        self.assertEqual(validate_reference_upload(image_upload()).mime_type, "image/png")

    def test_webp(self):
        self.assertEqual(validate_reference_upload(image_upload("WEBP")).mime_type, "image/webp")

    def test_pdf(self):
        self.assertEqual(validate_reference_upload(pdf_upload()).mime_type, "application/pdf")

    def test_docx(self):
        self.assertIn("wordprocessingml", validate_reference_upload(docx_upload()).mime_type)

    def test_txt_and_exact_bytes(self):
        file = upload(content="Niña\r\n\tTexto".encode())
        checked = validate_reference_upload(file)
        self.assertEqual(checked.content, file.read())
        self.assertEqual(checked.mime_type, "text/plain")

    def test_markdown(self):
        self.assertEqual(validate_reference_upload(upload("note.md", b"# Heading\nText")).mime_type, "text/markdown")

    def test_client_mime_not_trusted(self):
        self.assertEqual(validate_reference_upload(image_upload()).mime_type, "image/png")

    def test_false_extensions(self):
        for name, content in (("fake.png", b"not an image"), ("fake.jpg", image_upload().read()), ("fake.pdf", b"text"), ("fake.docx", b"text")):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                validate_reference_upload(upload(name, content))

    def test_forbidden_extensions(self):
        for extension in ("exe", "bat", "cmd", "ps1", "js", "html", "svg", "zip", "rar", "gif", "docm"):
            with self.subTest(extension=extension), self.assertRaises(ValidationError):
                validate_reference_upload(upload("file." + extension))

    def test_dangerous_names(self):
        for name in ("../map.png", "folder/map.png", "a\\b.png", "C:map.png", "bad\r\n.txt", "NUL.txt", ".hidden.txt", "name.txt ", "name\u202e.txt"):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                safe_original_filename(name)

    def test_empty_upload(self):
        with self.assertRaises(ValidationError):
            validate_reference_upload(upload(content=b""))

    @override_settings(REFERENCE_DOCUMENT_MAX_MB=1, REFERENCE_IMAGE_MAX_MB=1)
    def test_real_size_limit_not_declared_size(self):
        file = upload(content=b"x" * (1024 * 1024 + 1))
        file.size = 1
        with self.assertRaises(ValidationError):
            validate_reference_upload(file)
        self.assertEqual(file.tell(), 0)

    def test_invalid_text_encoding_and_binary(self):
        for data in (b"\xff\xfe\x00", b"hello\x00world", b"MZ\x01\x02", b"<html>Not text</html>"):
            with self.subTest(data=data), self.assertRaises(ValidationError):
                validate_reference_upload(upload(content=data))

    def test_corrupt_image(self):
        with self.assertRaises(ValidationError):
            validate_reference_upload(upload("bad.png", image_upload().read()[:45]))

    def test_corrupt_pdf_even_with_signature(self):
        for data in (b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF", pdf_upload().read()[:-20]):
            with self.assertRaises(ValidationError):
                validate_reference_upload(upload("bad.pdf", data))

    def test_encrypted_pdf_rejected(self):
        writer = PdfWriter(clone_from=PdfReader(pdf_upload()))
        writer.encrypt("password")
        output = BytesIO()
        writer.write(output)
        with self.assertRaises(ValidationError):
            validate_reference_upload(upload("secret.pdf", output.getvalue()))

    def test_docx_missing_structure(self):
        output = BytesIO()
        with ZipFile(output, "w") as archive:
            archive.writestr("word/document.xml", "<document/>")
        with self.assertRaises(ValidationError):
            validate_reference_upload(upload("bad.docx", output.getvalue()))

    def test_docx_forbids_macros_traversal_dtd_and_bomb(self):
        for name, payload in (("word/vbaProject.bin", b"macro"), ("../escape", b"x"),
                              ("custom.xml", b'<!DOCTYPE x [<!ENTITY e "test">]><x>&e;</x>'), ("huge.txt", b"x" * 1000000)):
            output = BytesIO(docx_upload().read())
            with ZipFile(output, "a", compression=ZIP_DEFLATED) as archive:
                archive.writestr(name, payload)
            with self.subTest(name=name), self.assertRaises(ValidationError):
                validate_reference_upload(upload("bad.docx", output.getvalue()))

    def test_docx_corrupt_zip(self):
        with self.assertRaises(ValidationError):
            validate_reference_upload(upload("bad.docx", docx_upload().read()[:100]))

    def test_docx_invalid_compressed_stream_is_controlled(self):
        with patch("apps.references.validators._validate_docx", side_effect=ZlibError("Invalid compressed stream")):
            with self.assertRaises(ValidationError):
                validate_reference_upload(docx_upload())
