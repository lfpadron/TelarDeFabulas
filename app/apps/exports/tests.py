import shutil
import tempfile
from io import BytesIO
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

    def create_url(self, project=None):
        project = project or self.project
        return reverse("exports:create", kwargs={"project_pk": project.pk})

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

    def test_free_user_can_use_system_style(self):
        self.client.force_login(self.free_user)

        with patch("apps.exports.views.generate_export_job.delay"):
            response = self.client.post(
                self.create_url(self.free_project),
                self.export_payload(root_node=self.free_node.pk, style_template=self.system_style.pk),
            )

        export_job = ExportJob.objects.get(project=self.free_project)
        self.assertRedirects(response, self.detail_url(export_job, self.free_project))

    def test_form_offers_html_docx_and_pdf_only(self):
        self.client.force_login(self.premium_user)

        response = self.client.get(self.create_url())

        choices = list(response.context["form"].fields["format"].choices)
        self.assertEqual(
            choices,
            [
                (ExportJob.ExportFormat.HTML, "HTML"),
                (ExportJob.ExportFormat.DOCX, "DOCX"),
                (ExportJob.ExportFormat.PDF, "PDF"),
            ],
        )
        self.assertNotIn(ExportJob.ExportFormat.EPUB, [value for value, label in choices])

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

    def test_task_marks_epub_failed_and_saves_clear_error(self):
        export_job = ExportJob.objects.create(
            user=self.premium_user,
            project=self.project,
            style_template=self.system_style,
            format=ExportJob.ExportFormat.EPUB,
        )

        generate_export_job.run(export_job.pk)

        export_job.refresh_from_db()
        self.assertEqual(export_job.status, ExportJob.ExportStatus.FAILED)
        self.assertIn("formato", export_job.error_message.lower())
        self.assertIsNotNone(export_job.finished_at)

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
