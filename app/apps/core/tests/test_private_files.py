from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.characters.forms import CharacterForm
from apps.characters.models import Character
from apps.characters.validators import validate_character_image
from apps.core.storage import PrivateMediaStorage
from apps.exports.models import ExportJob
from apps.exports.views import DOWNLOAD_CONTENT_TYPES, DOWNLOAD_EXTENSIONS
from apps.manuscripts.audit import has_public_media_route

from .helpers import SecurityTestCase, image_upload


class PrivateFileTests(SecurityTestCase):
    def setUp(self):
        super().setUp()
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.media_root = Path(directory.name)
        settings = override_settings(MEDIA_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)
        self.image_bytes = image_upload().read()
        self.character.image.save("portrait.png", ContentFile(self.image_bytes), save=True)
        self.job.file.save("book.html", ContentFile(b"<html>Private manuscript</html>"), save=False)
        self.job.status = "READY"
        self.job.save()
        self.image_url = self.url("characters:image", character_pk=self.character.pk)
        self.download_url = self.url("exports:download", export_pk=self.job.pk)

    def read_response(self, response):
        # The test client's streaming iterator closes the response after consumption.
        return b"".join(response.streaming_content)

    def assert_private_headers(self, response):
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("Cookie", response["Vary"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_image_requires_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.image_url), f"/login/?next={self.image_url}", fetch_redirect_response=False)

    def test_export_requires_login(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.download_url), f"/login/?next={self.download_url}", fetch_redirect_response=False)

    def test_other_user_cannot_access_known_private_urls(self):
        self.client.force_login(self.other_user)
        for url in (self.image_url, self.download_url):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_own_image_is_served_with_real_type_and_private_headers(self):
        response = self.client.get(self.image_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assert_private_headers(response)
        self.assertEqual(self.read_response(response), self.image_bytes)

    def test_export_downloads_are_attachments_with_correct_mime_types(self):
        for export_format, mime in DOWNLOAD_CONTENT_TYPES.items():
            ExportJob.objects.filter(pk=self.job.pk).update(format=export_format)
            with self.subTest(format=export_format):
                response = self.client.get(self.download_url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], mime)
                self.assertIn("attachment;", response["Content-Disposition"])
                self.assertIn(f'.{DOWNLOAD_EXTENSIONS[export_format]}"', response["Content-Disposition"])
                self.assert_private_headers(response)
                self.assertIn(b"Private manuscript", self.read_response(response))

    def test_readonly_projects_still_allow_images_and_downloads(self):
        for status in ("FROZEN", "PENDING_DELETION"):
            self.set_status(status)
            for url in (self.image_url, self.download_url):
                with self.subTest(status=status, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.read_response(response)

    def test_deleted_projects_block_private_files(self):
        self.set_status("DELETED")
        for url in (self.image_url, self.download_url):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_export_job_owner_is_checked_separately(self):
        ExportJob.objects.filter(pk=self.job.pk).update(user=self.other_user)
        self.assertEqual(self.client.get(self.download_url).status_code, 404)

    def test_unfinished_export_is_not_downloadable(self):
        ExportJob.objects.filter(pk=self.job.pk).update(status="PROCESSING")
        self.assertEqual(self.client.get(self.download_url).status_code, 404)

    @override_settings(DEBUG=True)
    def test_public_media_paths_do_not_serve_known_files_even_in_debug(self):
        self.client.logout()
        for name in (self.character.image.name, self.job.file.name):
            for prefix in ("/media/", "/private_media/"):
                with self.subTest(prefix=prefix, name=name):
                    self.assertEqual(self.client.get(prefix + name).status_code, 404)
        self.assertFalse(has_public_media_route())

    def test_storage_does_not_generate_public_urls(self):
        for field in (self.character.image, self.job.file):
            with self.assertRaises(ValueError):
                _ = field.url

    def test_private_file_views_only_allow_safe_methods(self):
        for url in (self.image_url, self.download_url):
            self.assertEqual(self.client.post(url).status_code, 405)

    def test_templates_use_authorized_route_and_private_widget(self):
        response = self.client.get(self.url("characters:detail", character_pk=self.character.pk))
        self.assertContains(response, self.image_url)
        self.assertNotContains(response, self.character.image.name)
        response = self.client.get(self.url("characters:edit", character_pk=self.character.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="image-clear"')
        self.assertNotContains(response, self.character.image.name)

    def test_missing_files_produce_controlled_404(self):
        for field, url in ((self.character.image, self.image_url), (self.job.file, self.download_url)):
            field.storage.delete(field.name)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)
            self.assertNotContains(response, str(self.media_root), status_code=404)

    def test_traversal_and_foreign_prefix_references_are_rejected(self):
        names = ("../secret", "/etc/passwd", "characters/../secret", "characters//secret", "C:\\secret",
                 f"characters/{self.other_project.pk}/portrait.png", f"exports/{self.other_user.pk}/{self.project.pk}/book.html")
        for name in names:
            Character.objects.filter(pk=self.character.pk).update(image=name)
            ExportJob.objects.filter(pk=self.job.pk).update(file=name)
            for url in (self.image_url, self.download_url):
                with self.subTest(name=name, url=url):
                    self.assertEqual(self.client.get(url).status_code, 404)

    def test_client_cannot_choose_a_file_path(self):
        for url in (self.image_url, self.download_url):
            response = self.client.get(url, {"path": "/etc/passwd", "file": "../../secret"})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(b"root:x:", self.read_response(response))

    def test_storage_rejects_symlink_outside_private_root(self):
        with TemporaryDirectory() as outside:
            target = Path(outside) / "secret.txt"
            target.write_bytes(b"secret")
            link = self.media_root / "outside"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("Creating symlinks requires OS support; exercised in the Linux container.")
            with self.assertRaises(SuspiciousFileOperation):
                PrivateMediaStorage().open("outside")

    def test_invalid_legacy_file_is_not_served_as_an_image(self):
        Path(self.character.image.path).write_bytes(b"<script>alert(1)</script>")
        self.assertEqual(self.client.get(self.image_url).status_code, 404)

    def test_legacy_gif_remains_readable_and_can_be_replaced(self):
        name = f"characters/{self.project.pk}/legacy.gif"
        self.character.image.storage.save(name, image_upload("GIF"))
        Character.objects.filter(pk=self.character.pk).update(image=name)
        response = self.client.get(self.image_url)
        self.assertEqual(response["Content-Type"], "image/gif")
        self.assertTrue(self.read_response(response).startswith(b"GIF"))
        self.character.refresh_from_db()
        form = CharacterForm(self.character_payload(), instance=self.character, project=self.project)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.assertTrue(self.character.image.storage.exists(name))

    def test_readonly_upload_is_rejected_before_file_write(self):
        for status in ("FROZEN", "PENDING_DELETION"):
            self.set_status(status)
            before = sorted(str(path) for path in self.media_root.rglob("*"))
            response = self.client.post(self.url("characters:edit", character_pk=self.character.pk),
                                        self.character_payload(image=image_upload()))
            self.assertEqual(response.status_code, 403)
            self.assertEqual(sorted(str(path) for path in self.media_root.rglob("*")), before)

    def test_upload_uses_uuid_filename(self):
        relative = Path(self.character.image.name)
        UUID(relative.stem)
        self.assertEqual(relative.parent.as_posix(), f"characters/{self.project.pk}")
        self.assertEqual(relative.suffix, ".png")


class ImageUploadTests(SecurityTestCase):
    def form(self, upload):
        return CharacterForm(self.character_payload(), {"image": upload}, project=self.project)

    def test_valid_jpeg_is_accepted(self):
        form = self.form(image_upload("JPEG"))
        self.assertTrue(form.is_valid(), form.errors)

    def test_valid_png_is_accepted(self):
        form = self.form(image_upload("PNG"))
        self.assertTrue(form.is_valid(), form.errors)

    def test_valid_webp_is_accepted(self):
        form = self.form(image_upload("WEBP"))
        self.assertTrue(form.is_valid(), form.errors)

    def test_corrupt_file_is_rejected(self):
        form = self.form(SimpleUploadedFile("bad.png", b"not an image", content_type="image/png"))
        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_truncated_file_is_rejected(self):
        form = self.form(SimpleUploadedFile("broken.png", image_upload().read()[:35]))
        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_misleading_extension_is_rejected(self):
        form = self.form(image_upload("PNG", "portrait.jpg"))
        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    @override_settings(CHARACTER_IMAGE_MAX_MB=1)
    def test_oversized_file_is_rejected_before_decoding(self):
        upload = SimpleUploadedFile("large.png", image_upload().read() + b"x" * (1024 * 1024))
        with patch("apps.characters.validators.verified_image_format") as decode:
            form = self.form(upload)
            self.assertFalse(form.is_valid())
        decode.assert_not_called()

    def test_svg_and_new_gif_uploads_are_rejected(self):
        for upload in (SimpleUploadedFile("script.svg", b'<svg onload="alert(1)"/>'), image_upload("GIF")):
            with self.subTest(filename=upload.name):
                form = self.form(upload)
                self.assertFalse(form.is_valid())
                self.assertIn("image", form.errors)

    def test_unsafe_original_names_are_rejected(self):
        for name in ("../portrait.png", "C:\\portrait.png", ".portrait.png", "portrait.png:script"):
            # Raw streams exercise validation before Django's UploadedFile basename normalization.
            upload = BytesIO(image_upload().read())
            upload.name = name
            upload.size = len(upload.getvalue())
            with self.subTest(name=name), self.assertRaises(ValidationError):
                validate_character_image(upload)

    def test_decompression_bomb_warning_is_rejected(self):
        with patch("PIL.Image.MAX_IMAGE_PIXELS", 5):
            form = self.form(image_upload())
            self.assertFalse(form.is_valid())
            self.assertIn("image", form.errors)
