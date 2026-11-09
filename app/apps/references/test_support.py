from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from docx import Document
from PIL import Image
from pypdf import PdfWriter

from apps.characters.models import Character
from apps.geography.models import GeographicLocation
from apps.manuscripts.models import ManuscriptNode
from apps.organizations.models import Organization
from apps.projects.models import Project
from apps.worldbuilding.models import WorldbuildingEntry


def upload(name="note.txt", content=b"Plain text\r\nSecond line"):
    return SimpleUploadedFile(name, content, content_type="application/x-untrusted-client")


def image_upload(format="PNG", color="green"):
    output = BytesIO()
    Image.new("RGB", (32, 24), color).save(output, format=format)
    return upload("map." + {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}[format], output.getvalue())


def pdf_upload():
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(output)
    return upload("book.pdf", output.getvalue())


def docx_upload():
    output = BytesIO()
    doc = Document()
    doc.add_paragraph("Document text")
    doc.save(output)
    return upload("book.docx", output.getvalue())


class ReferenceFixtures:
    def setUp(self):
        super().setUp()
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        settings = override_settings(MEDIA_ROOT=self.media.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.user = get_user_model().objects.create_user(email="reference@example.test", user_type="PREMIUM")
        self.other = get_user_model().objects.create_user(email="other-reference@example.test")
        self.project = Project.objects.create(user=self.user, name="Reference project")
        self.other_project = Project.objects.create(user=self.other, name="Other project")
        self.same_owner = Project.objects.create(user=self.user, name="Second project")
        self.node = ManuscriptNode.objects.create(project=self.project, node_type="BOOK", title="Book")
        self.character = Character.objects.create(project=self.project, name="Character")
        self.location = GeographicLocation.objects.create(project=self.project, name="Place")
        self.organization = Organization.objects.create(project=self.project, name="Organization")
        self.world = WorldbuildingEntry.objects.create(project=self.project, category="HISTORY", title="History")
        self.entities = (self.node, self.character, self.location, self.organization, self.world)

    def reference(self, **data):
        from .services import create_reference
        return create_reference(self.project, **{"title": "Reference", **data})
