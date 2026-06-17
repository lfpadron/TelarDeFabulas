import shutil
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from docx import Document
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.manuscripts.models import ManuscriptNode
from apps.notes.models import Note
from apps.projects.models import Project
from apps.styles.models import StyleTemplate

from .models import ExportJob
from .pdf import build_export_pdf_html
from .tasks import generate_export_job


class ExportJobTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)

        User = get_user_model()
        self.password = "safe-test-password"
        self.free_user = User.objects.create_user(
            email="free@example.com",
            password=self.password,
            user_type=User.UserType.FREE,
        )
        self.premium_user = User.objects.create_user(
            email="premium@example.com",
            password=self.password,
            user_type=User.UserType.PREMIUM,
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password=self.password,
            user_type=User.UserType.PREMIUM,
        )
        self.project = Project.objects.create(user=self.premium_user, name="Proyecto exportable")
        self.free_project = Project.objects.create(user=self.free_user, name="Proyecto gratuito")
        self.other_project = Project.objects.create(user=self.other_user, name="Proyecto ajeno")
        self.book = ManuscriptNode.objects.create(
            project=self.project,
            node_type=ManuscriptNode.NodeType.BOOK,
            title="Libro raíz",
            content="Texto del libro.",
        )
        self.chapter = ManuscriptNode.objects.create(
            project=self.project,
            parent=self.book,
            node_type=ManuscriptNode.NodeType.CHAPTER,
            title="Capítulo uno",
            content="Texto del capítulo.",
        )
        self.scene = ManuscriptNode.objects.create(
            project=self.project,
            parent=self.chapter,
            node_type=ManuscriptNode.NodeType.SCENE,
            title="Escena secreta",
            content="Texto de la escena.",
        )
        self.other_scene = ManuscriptNode.objects.create(
            project=self.project,
            parent=self.book,
            node_type=ManuscriptNode.NodeType.SCENE,
            title="Escena fuera del capítulo",
            content="Texto fuera.",
        )
        self.other_node = ManuscriptNode.objects.create(
            project=self.other_project,
            node_type=ManuscriptNode.NodeType.BOOK,
            title="Nodo ajeno",
        )
        self.free_node = ManuscriptNode.objects.create(
            project=self.free_project,
            node_type=ManuscriptNode.NodeType.BOOK,
            title="Libro gratuito",
        )
        self.system_style = StyleTemplate.objects.create(name="Sistema HTML", is_system=True)
        self.own_style = StyleTemplate.objects.create(user=self.premium_user, name="Estilo propio")
        self.other_style = StyleTemplate.objects.create(user=self.other_user, name="Estilo ajeno")

    def export_payload(self, **overrides):
        payload = {
            "root_node": "",
            "style_template": self.system_style.pk,
            "format": ExportJob.ExportFormat.HTML,
        }
        payload.update(overrides)
        return payload

    def preview_payload(self, **overrides):
        payload = {
            "root_node": "",
            "style_template": self.system_style.pk,
        }
        payload.update(overrides)
        return payload

    def create_url(self, project=None):
        project = project or self.project
        return reverse("exports:create", kwargs={"project_pk": project.pk})

    def preview_url(self, project=None):
        project = project or self.project
        return reverse("exports:preview", kwargs={"project_pk": project.pk})

    def list_url(self, project=None):
        project = project or self.project
        return reverse("exports:list", kwargs={"project_pk": project.pk})

    def detail_url(self, export_job, project=None):
        project = project or export_job.project
        return reverse("exports:detail", kwargs={"project_pk": project.pk, "export_pk": export_job.pk})

    def download_url(self, export_job, project=None):
        project = project or export_job.project
        return reverse("exports:download", kwargs={"project_pk": project.pk, "export_pk": export_job.pk})

    def export_html_for_job(self, export_job):
        export_job.refresh_from_db()
        with export_job.file.open("rb") as exported_file:
            return exported_file.read().decode("utf-8")

    def export_docx_text_for_job(self, export_job):
        export_job.refresh_from_db()
        with export_job.file.open("rb") as exported_file:
            document = Document(BytesIO(exported_file.read()))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)

    def export_pdf_bytes_for_job(self, export_job):
        export_job.refresh_from_db()
        with export_job.file.open("rb") as exported_file:
            return exported_file.read()

    def export_epub_bytes_for_job(self, export_job):
        export_job.refresh_from_db()
        with export_job.file.open("rb") as exported_file:
            return exported_file.read()

    def export_epub_text_for_job(self, export_job):
        epub_content = self.export_epub_bytes_for_job(export_job)
        with zipfile.ZipFile(BytesIO(epub_content)) as epub_zip:
            xhtml_names = [name for name in epub_zip.namelist() if name.endswith(".xhtml")]
            return "\n".join(epub_zip.read(name).decode("utf-8") for name in xhtml_names)

    def test_authenticated_user_can_create_html_export_for_own_project(self):
        self.client.force_login(self.premium_user)

        with patch("apps.exports.views.generate_export_job.delay") as delay:
            response = self.client.post(self.create_url(), self.export_payload())

        export_job = ExportJob.objects.get(project=self.project)
        self.assertRedirects(response, self.detail_url(export_job))
        delay.assert_called_once_with(export_job.pk)

    def test_unauthenticated_user_is_redirected(self):
        response = self.client.get(self.list_url())

        self.assertRedirects(response, f"{reverse('login')}?next={self.list_url()}")

    def test_user_cannot_export_project_from_another_user(self):
        self.client.force_login(self.premium_user)

        response = self.client.post(self.create_url(self.other_project), self.export_payload())

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ExportJob.objects.filter(project=self.other_project).exists())

    def test_user_cannot_create_docx_export_for_project_from_another_user(self):
        self.client.force_login(self.premium_user)

        response = self.client.post(
            self.create_url(self.other_project),
            self.export_payload(format=ExportJob.ExportFormat.DOCX),
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ExportJob.objects.filter(project=self.other_project).exists())

    def test_user_cannot_create_pdf_export_for_project_from_another_user(self):
        self.client.force_login(self.premium_user)

        response = self.client.post(
            self.create_url(self.other_project),
            self.export_payload(format=ExportJob.ExportFormat.PDF),
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ExportJob.objects.filter(project=self.other_project).exists())

    def test_user_cannot_create_epub_export_for_project_from_another_user(self):
        self.client.force_login(self.premium_user)

        response = self.client.post(
            self.create_url(self.other_project),
            self.export_payload(format=ExportJob.ExportFormat.EPUB),
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ExportJob.objects.filter(project=self.other_project).exists())

    def test_user_cannot_use_root_node_from_another_project(self):
        self.client.force_login(self.premium_user)

        response = self.client.post(
            self.create_url(),
            self.export_payload(root_node=self.other_node.pk, format=ExportJob.ExportFormat.DOCX),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExportJob.objects.exists())

    def test_user_cannot_use_pdf_root_node_from_another_project(self):
        self.client.force_login(self.premium_user)

        response = self.client.post(
            self.create_url(),
            self.export_payload(root_node=self.other_node.pk, format=ExportJob.ExportFormat.PDF),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExportJob.objects.exists())

    def test_user_cannot_use_epub_root_node_from_another_project(self):
        self.client.force_login(self.premium_user)

        response = self.client.post(
            self.create_url(),
            self.export_payload(root_node=self.other_node.pk, format=ExportJob.ExportFormat.EPUB),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExportJob.objects.exists())

    def test_user_can_use_system_style(self):
        self.client.force_login(self.premium_user)

        with patch("apps.exports.views.generate_export_job.delay"):
            response = self.client.post(self.create_url(), self.export_payload(style_template=self.system_style.pk))

        export_job = ExportJob.objects.get(project=self.project)
        self.assertRedirects(response, self.detail_url(export_job))
        self.assertEqual(export_job.style_template, self.system_style)

    def test_user_can_use_own_style(self):
        self.client.force_login(self.premium_user)

        with patch("apps.exports.views.generate_export_job.delay"):
            response = self.client.post(self.create_url(), self.export_payload(style_template=self.own_style.pk))

        export_job = ExportJob.objects.get(project=self.project)
        self.assertRedirects(response, self.detail_url(export_job))
        self.assertEqual(export_job.style_template, self.own_style)

    def test_user_cannot_use_style_from_another_user(self):
        self.client.force_login(self.premium_user)

        response = self.client.post(
            self.create_url(),
            self.export_payload(style_template=self.other_style.pk, format=ExportJob.ExportFormat.DOCX),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExportJob.objects.exists())

    def test_user_cannot_use_pdf_style_from_another_user(self):
        self.client.force_login(self.premium_user)

        response = self.client.post(
            self.create_url(),
            self.export_payload(style_template=self.other_style.pk, format=ExportJob.ExportFormat.PDF),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExportJob.objects.exists())

    def test_user_cannot_use_epub_style_from_another_user(self):
        self.client.force_login(self.premium_user)

        response = self.client.post(
            self.create_url(),
            self.export_payload(style_template=self.other_style.pk, format=ExportJob.ExportFormat.EPUB),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExportJob.objects.exists())

    def test_free_user_can_use_system_style(self):
        self.client.force_login(self.free_user)

        with patch("apps.exports.views.generate_export_job.delay"):
            response = self.client.post(
                self.create_url(self.free_project),
                self.export_payload(root_node=self.free_node.pk, style_template=self.system_style.pk),
            )

        export_job = ExportJob.objects.get(project=self.free_project)
        self.assertRedirects(response, self.detail_url(export_job, self.free_project))

    def test_form_offers_html_docx_pdf_and_epub(self):
        self.client.force_login(self.premium_user)

        response = self.client.get(self.create_url())

        choices = list(response.context["form"].fields["format"].choices)
        self.assertEqual(
            choices,
            [
                (ExportJob.ExportFormat.HTML, "HTML"),
                (ExportJob.ExportFormat.DOCX, "DOCX"),
                (ExportJob.ExportFormat.PDF, "PDF"),
                (ExportJob.ExportFormat.EPUB, "EPUB"),
            ],
        )

    def test_unauthenticated_user_is_redirected_from_preview(self):
        response = self.client.get(self.preview_url())

        self.assertRedirects(response, f"{reverse('login')}?next={self.preview_url()}")

    def test_authenticated_user_can_preview_own_project(self):
        self.client.force_login(self.premium_user)

        response = self.client.get(self.preview_url(), self.preview_payload())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Telar de Fábulas")
        self.assertContains(response, "Libro raíz")
        self.assertContains(response, "Texto del libro.")

    def test_user_cannot_preview_project_from_another_user(self):
        self.client.force_login(self.premium_user)

        response = self.client.get(self.preview_url(self.other_project), self.preview_payload())

        self.assertEqual(response.status_code, 404)

    def test_user_cannot_preview_with_root_node_from_another_project(self):
        self.client.force_login(self.premium_user)

        response = self.client.get(self.preview_url(), self.preview_payload(root_node=self.other_node.pk))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["preview_result"])
        self.assertNotContains(response, "Nodo ajeno")

    def test_user_can_preview_with_system_style(self):
        self.client.force_login(self.premium_user)

        response = self.client.get(self.preview_url(), self.preview_payload(style_template=self.system_style.pk))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Libro raíz")

    def test_user_can_preview_with_own_style(self):
        self.client.force_login(self.premium_user)

        response = self.client.get(self.preview_url(), self.preview_payload(style_template=self.own_style.pk))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Libro raíz")

    def test_user_cannot_preview_with_style_from_another_user(self):
        self.client.force_login(self.premium_user)

        response = self.client.get(self.preview_url(), self.preview_payload(style_template=self.other_style.pk))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["preview_result"])

    def test_preview_does_not_create_export_job(self):
        self.client.force_login(self.premium_user)

        response = self.client.get(self.preview_url(), self.preview_payload())

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExportJob.objects.exists())

    def test_preview_does_not_write_media_files(self):
        self.client.force_login(self.premium_user)

        response = self.client.get(self.preview_url(), self.preview_payload())

        self.assertEqual(response.status_code, 200)
        self.assertEqual([path for path in Path(self.media_root).rglob("*") if path.is_file()], [])

    def test_preview_does_not_include_notes(self):
        Note.objects.create(project=self.project, title="Nota secreta", content="Contenido interno de nota")
        self.client.force_login(self.premium_user)

        response = self.client.get(self.preview_url(), self.preview_payload())

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Nota secreta")
        self.assertNotContains(response, "Contenido interno de nota")

    def test_preview_with_root_node_includes_descendants_only(self):
        self.client.force_login(self.premium_user)

        response = self.client.get(self.preview_url(), self.preview_payload(root_node=self.chapter.pk))
        html = response.context["preview_result"].html

        self.assertIn("Capítulo uno", html)
        self.assertIn("Escena secreta", html)
        self.assertNotIn("Libro raíz", html)
        self.assertNotIn("Escena fuera del capítulo", html)

    def test_preview_without_root_node_includes_full_manuscript(self):
        self.client.force_login(self.premium_user)

        response = self.client.get(self.preview_url(), self.preview_payload(root_node=""))

        self.assertContains(response, "Libro raíz")
        self.assertContains(response, "Capítulo uno")
        self.assertContains(response, "Escena secreta")

    @override_settings(EXPORT_PREVIEW_MAX_NODES=1, EXPORT_PREVIEW_MAX_WORDS=2500)
    def test_preview_truncates_by_node_limit(self):
        self.client.force_login(self.premium_user)

        response = self.client.get(self.preview_url(), self.preview_payload())

        self.assertTrue(response.context["preview_result"].truncated)
        self.assertEqual(response.context["preview_result"].node_count, 1)
        self.assertContains(
            response,
            "Vista previa limitada. Exporta el archivo completo para ver todo el manuscrito.",
        )
        self.assertNotIn("Capítulo uno", response.context["preview_result"].html)

    @override_settings(EXPORT_PREVIEW_MAX_NODES=12, EXPORT_PREVIEW_MAX_WORDS=3)
    def test_preview_truncates_by_word_limit(self):
        self.book.content = "uno dos tres cuatro cinco"
        self.book.save()
        self.client.force_login(self.premium_user)

        response = self.client.get(self.preview_url(), self.preview_payload())

        self.assertTrue(response.context["preview_result"].truncated)
        self.assertEqual(response.context["preview_result"].word_count, 3)
        self.assertContains(response, "uno dos tres...")
        self.assertNotContains(response, "cuatro")

    def test_preview_redirects_for_pending_deletion_project(self):
        pending_project = Project.objects.create(
            user=self.premium_user,
            name="Proyecto pendiente preview",
            status=Project.ProjectStatus.PENDING_DELETION,
            deletion_requested_at=timezone.now(),
        )
        self.client.force_login(self.premium_user)

        response = self.client.get(self.preview_url(pending_project), self.preview_payload())

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": pending_project.pk}))

    def test_create_export_starts_as_pending(self):
        self.client.force_login(self.premium_user)

        with patch("apps.exports.views.generate_export_job.delay"):
            self.client.post(self.create_url(), self.export_payload())

        export_job = ExportJob.objects.get(project=self.project)
        self.assertEqual(export_job.status, ExportJob.ExportStatus.PENDING)

    def test_authenticated_user_can_create_docx_export_for_own_project(self):
        self.client.force_login(self.premium_user)

        with patch("apps.exports.views.generate_export_job.delay") as delay:
            response = self.client.post(self.create_url(), self.export_payload(format=ExportJob.ExportFormat.DOCX))

        export_job = ExportJob.objects.get(project=self.project)
        self.assertRedirects(response, self.detail_url(export_job))
        self.assertEqual(export_job.format, ExportJob.ExportFormat.DOCX)
        delay.assert_called_once_with(export_job.pk)

    def test_authenticated_user_can_create_pdf_export_for_own_project(self):
        self.client.force_login(self.premium_user)

        with patch("apps.exports.views.generate_export_job.delay") as delay:
            response = self.client.post(self.create_url(), self.export_payload(format=ExportJob.ExportFormat.PDF))

        export_job = ExportJob.objects.get(project=self.project)
        self.assertRedirects(response, self.detail_url(export_job))
        self.assertEqual(export_job.format, ExportJob.ExportFormat.PDF)
        delay.assert_called_once_with(export_job.pk)

    def test_authenticated_user_can_create_epub_export_for_own_project(self):
        self.client.force_login(self.premium_user)

        with patch("apps.exports.views.generate_export_job.delay") as delay:
            response = self.client.post(self.create_url(), self.export_payload(format=ExportJob.ExportFormat.EPUB))

        export_job = ExportJob.objects.get(project=self.project)
        self.assertRedirects(response, self.detail_url(export_job))
        self.assertEqual(export_job.format, ExportJob.ExportFormat.EPUB)
        delay.assert_called_once_with(export_job.pk)

    def test_task_generates_html_file_and_marks_done(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.book,
            style_template=self.system_style,
        )

        generate_export_job.run(export_job.pk)

        export_job.refresh_from_db()
        self.assertEqual(export_job.status, ExportJob.ExportStatus.DONE)
        self.assertTrue(export_job.file.name.endswith(f"exports/{self.premium_user.pk}/{self.project.pk}/{export_job.pk}.html"))
        self.assertIn("<!doctype html>", self.export_html_for_job(export_job))

    def test_download_forces_html_attachment_with_embedded_css(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.book,
            style_template=self.system_style,
        )
        generate_export_job.run(export_job.pk)
        self.client.force_login(self.premium_user)

        response = self.client.get(self.download_url(export_job))

        content = b"".join(response.streaming_content).decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn(".html", response["Content-Disposition"])
        self.assertIn("<style>", content)
        self.assertIn("Libro raíz", content)

    def test_task_generates_docx_file_and_marks_done(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.book,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.DOCX,
        )

        generate_export_job.run(export_job.pk)

        export_job.refresh_from_db()
        self.assertEqual(export_job.status, ExportJob.ExportStatus.DONE)
        self.assertTrue(export_job.file.name.endswith(f"exports/{self.premium_user.pk}/{self.project.pk}/{export_job.pk}.docx"))
        self.assertGreater(export_job.file.size, 0)
        self.assertIn("Libro raíz", self.export_docx_text_for_job(export_job))

    def test_download_forces_docx_attachment(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.book,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.DOCX,
        )
        generate_export_job.run(export_job.pk)
        self.client.force_login(self.premium_user)

        response = self.client.get(self.download_url(export_job))

        content = b"".join(response.streaming_content)
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn(".docx", response["Content-Disposition"])
        self.assertGreater(len(content), 0)

    def test_task_generates_pdf_file_and_marks_done(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.book,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.PDF,
        )

        generate_export_job.run(export_job.pk)

        export_job.refresh_from_db()
        pdf_content = self.export_pdf_bytes_for_job(export_job)
        self.assertEqual(export_job.status, ExportJob.ExportStatus.DONE)
        self.assertTrue(export_job.file.name.endswith(f"exports/{self.premium_user.pk}/{self.project.pk}/{export_job.pk}.pdf"))
        self.assertGreater(len(pdf_content), 0)
        self.assertTrue(pdf_content.startswith(b"%PDF"))

    def test_download_forces_pdf_attachment(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.book,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.PDF,
        )
        generate_export_job.run(export_job.pk)
        self.client.force_login(self.premium_user)

        response = self.client.get(self.download_url(export_job))

        content = b"".join(response.streaming_content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn(".pdf", response["Content-Disposition"])
        self.assertTrue(content.startswith(b"%PDF"))

    def test_task_generates_epub_file_and_marks_done(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.book,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.EPUB,
        )

        generate_export_job.run(export_job.pk)

        export_job.refresh_from_db()
        epub_content = self.export_epub_bytes_for_job(export_job)
        self.assertEqual(export_job.status, ExportJob.ExportStatus.DONE)
        self.assertTrue(export_job.file.name.endswith(f"exports/{self.premium_user.pk}/{self.project.pk}/{export_job.pk}.epub"))
        self.assertGreater(len(epub_content), 0)
        self.assertTrue(zipfile.is_zipfile(BytesIO(epub_content)))
        with zipfile.ZipFile(BytesIO(epub_content)) as epub_zip:
            names = epub_zip.namelist()
            self.assertIn("mimetype", names)
            self.assertEqual(epub_zip.read("mimetype"), b"application/epub+zip")
            self.assertIn("META-INF/container.xml", names)
            self.assertTrue(any(name.endswith(".xhtml") for name in names))

    def test_download_forces_epub_attachment(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.book,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.EPUB,
        )
        generate_export_job.run(export_job.pk)
        self.client.force_login(self.premium_user)

        response = self.client.get(self.download_url(export_job))

        content = b"".join(response.streaming_content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/epub+zip")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn(".epub", response["Content-Disposition"])
        self.assertTrue(zipfile.is_zipfile(BytesIO(content)))

    def test_exporting_chapter_includes_its_scenes(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.chapter,
            style_template=self.system_style,
        )

        generate_export_job.run(export_job.pk)
        html = self.export_html_for_job(export_job)

        self.assertIn("Capítulo uno", html)
        self.assertIn("Escena secreta", html)
        self.assertNotIn("Escena fuera del capítulo", html)

    def test_exporting_scene_only_includes_that_scene(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.scene,
            style_template=self.system_style,
        )

        generate_export_job.run(export_job.pk)
        html = self.export_html_for_job(export_job)

        self.assertIn("Escena secreta", html)
        self.assertNotIn("Capítulo uno", html)
        self.assertNotIn("Escena fuera del capítulo", html)

    def test_docx_exporting_chapter_includes_its_scenes(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.chapter,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.DOCX,
        )

        generate_export_job.run(export_job.pk)
        text = self.export_docx_text_for_job(export_job)

        self.assertIn("Capítulo uno", text)
        self.assertIn("Escena secreta", text)
        self.assertNotIn("Escena fuera del capítulo", text)

    def test_docx_exporting_scene_only_includes_that_scene(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.scene,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.DOCX,
        )

        generate_export_job.run(export_job.pk)
        text = self.export_docx_text_for_job(export_job)

        self.assertIn("Escena secreta", text)
        self.assertNotIn("Capítulo uno", text)
        self.assertNotIn("Escena fuera del capítulo", text)

    def test_pdf_exporting_chapter_includes_its_scenes(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.chapter,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.PDF,
        )

        html = build_export_pdf_html(export_job)

        self.assertIn("Capítulo uno", html)
        self.assertIn("Escena secreta", html)
        self.assertNotIn("Escena fuera del capítulo", html)

    def test_pdf_exporting_scene_only_includes_that_scene(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.scene,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.PDF,
        )

        html = build_export_pdf_html(export_job)

        self.assertIn("Escena secreta", html)
        self.assertNotIn("Capítulo uno", html)
        self.assertNotIn("Escena fuera del capítulo", html)

    def test_epub_exporting_chapter_includes_its_scenes(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.chapter,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.EPUB,
        )

        generate_export_job.run(export_job.pk)
        text = self.export_epub_text_for_job(export_job)

        self.assertIn("Capítulo uno", text)
        self.assertIn("Escena secreta", text)
        self.assertNotIn("Escena fuera del capítulo", text)

    def test_epub_exporting_scene_only_includes_that_scene(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.scene,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.EPUB,
        )

        generate_export_job.run(export_job.pk)
        text = self.export_epub_text_for_job(export_job)

        self.assertIn("Escena secreta", text)
        self.assertNotIn("Capítulo uno", text)
        self.assertNotIn("Escena fuera del capítulo", text)

    def test_generated_html_does_not_include_notes(self):
        Note.objects.create(project=self.project, title="Nota secreta", content="Contenido interno de nota")
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            style_template=self.system_style,
        )

        generate_export_job.run(export_job.pk)
        html = self.export_html_for_job(export_job)

        self.assertNotIn("Nota secreta", html)
        self.assertNotIn("Contenido interno de nota", html)

    def test_generated_docx_does_not_include_notes(self):
        Note.objects.create(project=self.project, title="Nota secreta", content="Contenido interno de nota")
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.DOCX,
        )

        generate_export_job.run(export_job.pk)
        text = self.export_docx_text_for_job(export_job)

        self.assertNotIn("Nota secreta", text)
        self.assertNotIn("Contenido interno de nota", text)

    def test_generated_pdf_does_not_include_notes(self):
        Note.objects.create(project=self.project, title="Nota secreta", content="Contenido interno de nota")
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.PDF,
        )

        html = build_export_pdf_html(export_job)

        self.assertNotIn("Nota secreta", html)
        self.assertNotIn("Contenido interno de nota", html)

    def test_generated_epub_does_not_include_notes(self):
        Note.objects.create(project=self.project, title="Nota secreta", content="Contenido interno de nota")
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.EPUB,
        )

        generate_export_job.run(export_job.pk)
        text = self.export_epub_text_for_job(export_job)

        self.assertNotIn("Nota secreta", text)
        self.assertNotIn("Contenido interno de nota", text)

    def test_list_only_shows_exports_for_current_project(self):
        second_project = Project.objects.create(user=self.premium_user, name="Segundo proyecto")
        second_node = ManuscriptNode.objects.create(project=second_project, title="Nodo de segundo proyecto")
        own_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            root_node=self.book,
            style_template=self.system_style,
        )
        ExportJob.objects.create(
            user=self.premium_user,
            project=second_project,
            root_node=second_node,
            style_template=self.system_style,
        )
        self.client.force_login(self.premium_user)

        response = self.client.get(self.list_url())

        self.assertContains(response, own_job.root_node.title)
        self.assertNotContains(response, "Nodo de segundo proyecto")

    def test_deleted_project_cannot_be_exported(self):
        deleted_project = Project.objects.create(
            user=self.premium_user,
            name="Proyecto eliminado",
            status=Project.ProjectStatus.DELETED,
            deleted_at=timezone.now(),
        )
        self.client.force_login(self.premium_user)

        response = self.client.post(self.create_url(deleted_project), self.export_payload())

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": deleted_project.pk}))
        self.assertFalse(ExportJob.objects.filter(project=deleted_project).exists())

    def test_pending_deletion_project_cannot_be_exported(self):
        pending_project = Project.objects.create(
            user=self.premium_user,
            name="Proyecto pendiente",
            status=Project.ProjectStatus.PENDING_DELETION,
            deletion_requested_at=timezone.now(),
        )
        self.client.force_login(self.premium_user)

        response = self.client.post(self.create_url(pending_project), self.export_payload())

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": pending_project.pk}))
        self.assertFalse(ExportJob.objects.filter(project=pending_project).exists())
