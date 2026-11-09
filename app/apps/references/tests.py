from datetime import timedelta
import os
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.http import Http404
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.characters.models import Character
from apps.projects.models import Project
from .files import cleanup_file, reconcile_orphans, reference_path, retry_cleanup
from .forms import ReferenceForm
from .models import ReferenceAssociation as Association, ReferenceFileCleanup as Cleanup, ReferenceMaterial as Reference, TARGETS
from .services import (ReferenceConflict, attach_reference, create_reference, delete_reference, detach_reference,
                       get_references_for_entity, project_storage_bytes, update_reference)
from .test_support import ReferenceFixtures, docx_upload, image_upload, pdf_upload, upload


class ModelServiceTests(ReferenceFixtures, TestCase):
    def test_bibliography_needs_only_title(self):
        ref = self.reference()
        self.assertEqual((ref.material_type, ref.revision, ref.file_size), ("BIBLIOGRAPHY", 1, 0))

    def test_link_requires_valid_url(self):
        for url in ("", "javascript:alert(1)", "file:///etc/passwd", "data:text/plain,x", "ftp://example.test/file"):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                self.reference(material_type="LINK", source_url=url)
        self.assertEqual(self.reference(material_type="LINK", source_url="https://example.test/book").source_url, "https://example.test/book")

    def test_image_and_document_require_correct_file(self):
        for kind, file in (("IMAGE", None), ("DOCUMENT", None), ("IMAGE", upload()), ("DOCUMENT", image_upload())):
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                self.reference(material_type=kind, file=file)
        self.reference(material_type="IMAGE", file=image_upload())
        self.reference(material_type="DOCUMENT", file=pdf_upload())

    def test_title_type_and_project_required(self):
        for data in ({"title": ""}, {"title": " \r\n "}, {"material_type": "INVALID"}):
            with self.subTest(data=data), self.assertRaises(ValidationError):
                create_reference(self.project, **{"title": "Title", **data})
        with self.assertRaises(ValidationError):
            Reference(title="No project").save()

    def test_other_and_bibliography_allow_optional_files(self):
        for kind in ("OTHER", "BIBLIOGRAPHY"):
            self.assertTrue(self.reference(material_type=kind, file=docx_upload()).file)
            self.assertFalse(self.reference(material_type=kind).file)

    def test_metadata_real_size_uuid_and_private_url(self):
        file = image_upload()
        ref = self.reference(file=file)
        self.assertEqual(ref.file_size, len(file.read()))
        self.assertEqual(ref.mime_type, "image/png")
        self.assertEqual(ref.original_filename, "map.png")
        self.assertRegex(ref.file.name, rf"^references/{self.project.pk}/[a-f0-9]{{32}}\.png$")
        with self.assertRaises(ValueError):
            _ = ref.file.url

    def test_model_save_uses_validated_service(self):
        ref = Reference.objects.create(project=self.project, title="ORM", file=upload())
        self.assertEqual(ref.mime_type, "text/plain")
        ref.notes = "Line one\r\n\tLine two"
        ref.save()
        ref.refresh_from_db()
        self.assertEqual(ref.notes, "Line one\r\n\tLine two")
        self.assertEqual(ref.revision, 2)

    def test_untrusted_metadata_and_paths_rejected(self):
        with self.assertRaises(ValidationError):
            self.reference(file_size=999)
        with self.assertRaises(ValidationError):
            Reference.objects.create(project=self.project, title="Path", file="references/1/secret.txt")

    def test_project_identity_cannot_change(self):
        ref = self.reference()
        ref.project = self.same_owner
        with self.assertRaises(ValidationError):
            ref.save()

    def test_stale_edit_does_not_replace_text_or_file(self):
        old = self.reference(file=upload())
        updated = update_reference(old, expected_revision=1, notes="Winner")
        with self.assertRaises(ReferenceConflict):
            update_reference(old, expected_revision=1, notes="Loser", file=image_upload())
        self.assertEqual(Reference.objects.get(pk=old.pk).notes, "Winner")
        self.assertEqual(updated.file.name, old.file.name)
        self.assertEqual(len(list(Path(self.media.name).rglob("*.txt"))), 1)

    def test_successful_replacement_removes_old_after_commit(self):
        ref = self.reference(file=upload())
        old = Path(ref.file.path)
        with self.captureOnCommitCallbacks(execute=True):
            updated = update_reference(ref, expected_revision=1, file=image_upload())
            self.assertTrue(old.exists())
            self.assertNotEqual(updated.file.name, ref.file.name)
        self.assertFalse(old.exists())
        self.assertTrue(Path(updated.file.path).exists())
        self.assertFalse(Cleanup.objects.exists())

    def test_failed_update_retains_old_and_removes_new(self):
        ref = self.reference(file=upload())
        original = Path(ref.file.path).read_bytes()
        with patch("apps.references.services.models.Model.save", side_effect=RuntimeError("Injected DB failure")):
            with self.assertRaises(RuntimeError):
                update_reference(ref, expected_revision=1, file=image_upload())
        ref.refresh_from_db()
        self.assertEqual(Path(ref.file.path).read_bytes(), original)
        self.assertEqual(len([p for p in Path(self.media.name).rglob("*") if p.is_file()]), 1)

    def test_invalid_replacement_keeps_original(self):
        ref = self.reference(file=upload())
        with self.assertRaises(ValidationError):
            update_reference(ref, expected_revision=1, file=upload("bad.pdf"))
        self.assertTrue(Path(ref.file.path).exists())

    def test_file_write_failure_keeps_original(self):
        ref = self.reference(file=upload())
        with patch("apps.references.services.os.fsync", side_effect=OSError("disk")):
            with self.assertRaises(ValidationError):
                update_reference(ref, expected_revision=1, file=image_upload())
        self.assertTrue(Path(ref.file.path).exists())
        self.assertFalse(list(Path(self.media.name).rglob("*.png")))

    def test_clear_file_and_metadata_after_commit(self):
        ref = self.reference(file=upload())
        old = Path(ref.file.path)
        with self.captureOnCommitCallbacks(execute=True):
            current = update_reference(ref, expected_revision=1, clear_file=True)
        self.assertEqual((current.file.name, current.file_size, current.mime_type, current.original_filename), ("", 0, "", ""))
        self.assertFalse(old.exists())

    def test_delete_only_reference_and_associations(self):
        ref = self.reference(file=image_upload())
        path = Path(ref.file.path)
        attach_reference(ref, self.character)
        with self.captureOnCommitCallbacks(execute=True):
            delete_reference(ref, expected_revision=1)
        self.assertFalse(Reference.objects.exists())
        self.assertFalse(Association.objects.exists())
        self.assertFalse(path.exists())
        self.assertTrue(Character.objects.filter(pk=self.character.pk).exists())

    def test_failed_physical_deletion_retries(self):
        ref = self.reference(file=upload())
        path = Path(ref.file.path)
        with patch("apps.references.files.Path.unlink", side_effect=PermissionError("busy")):
            with self.captureOnCommitCallbacks(execute=True):
                delete_reference(ref)
        item = Cleanup.objects.get()
        self.assertEqual(item.last_error, "PermissionError")
        self.assertTrue(path.exists())
        self.assertTrue(cleanup_file(item.pk))
        self.assertFalse(path.exists())
        self.assertFalse(Cleanup.objects.exists())

    def test_cleanup_does_not_delete_live_file(self):
        ref = self.reference(file=upload())
        item = Cleanup.objects.create(project_id=self.project.pk, name=ref.file.name)
        self.assertFalse(cleanup_file(item.pk))
        self.assertTrue(Path(ref.file.path).exists())

    def test_rollback_preserves_reference_and_file(self):
        ref = self.reference(file=upload())
        pk, path = ref.pk, Path(ref.file.path)
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                delete_reference(ref)
                raise RuntimeError
        self.assertTrue(Reference.objects.filter(pk=pk).exists())
        self.assertTrue(path.exists())
        self.assertFalse(Cleanup.objects.exists())

    def test_orphan_reconciliation_age_and_live_exclusion(self):
        ref = self.reference(file=upload())
        orphan = reference_path(self.project.pk, f"references/{self.project.pk}/{'a' * 32}.txt")
        orphan.write_bytes(b"orphan")
        self.assertEqual(reconcile_orphans(), 0)
        old = (timezone.now() - timedelta(days=2)).timestamp()
        os.utime(orphan, (old, old))
        os.utime(ref.file.path, (old, old))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(reconcile_orphans(), 1)
        self.assertFalse(orphan.exists())
        self.assertTrue(Path(ref.file.path).exists())

    @override_settings(REFERENCE_PROJECT_STORAGE_MAX_MB=1)
    def test_project_quota(self):
        self.reference(file=upload(content=b"x" * 600000))
        with self.assertRaises(ValidationError):
            self.reference(file=upload(content=b"x" * 600000))
        self.assertEqual(Reference.objects.count(), 1)

    @override_settings(REFERENCE_PROJECT_STORAGE_MAX_MB=1)
    def test_replacement_reserves_headroom_and_pending_cleanup_counts(self):
        ref = self.reference(file=upload(content=b"x" * 600000))
        with self.assertRaises(ValidationError):
            update_reference(ref, expected_revision=1, file=upload(content=b"x" * 600000))
        with patch("apps.references.files.Path.unlink", side_effect=OSError):
            with self.captureOnCommitCallbacks(execute=True):
                delete_reference(ref)
        self.assertEqual(project_storage_bytes(self.project), 600000)
        with self.assertRaises(ValidationError):
            self.reference(file=upload(content=b"x" * 600000))

    def test_services_recheck_owner_and_state(self):
        ref = self.reference()
        with self.assertRaises(Http404):
            update_reference(ref, expected_revision=1, user=self.other, title="Bad")
        Project.objects.filter(pk=self.project.pk).update(status="FROZEN")
        for operation in (lambda: self.reference(), lambda: update_reference(ref, expected_revision=1, title="Bad"), lambda: delete_reference(ref), lambda: attach_reference(ref, self.character)):
            with self.assertRaises(ValidationError):
                operation()


class AssociationTests(ReferenceFixtures, TestCase):
    def test_all_five_entity_types_share_one_file(self):
        ref = self.reference(file=image_upload())
        for entity in self.entities:
            self.assertEqual(attach_reference(ref, entity).entity.pk, entity.pk)
        self.assertEqual(Association.objects.count(), 5)
        self.assertEqual(len(list(Path(self.media.name).rglob("*.png"))), 1)

    def test_cross_project_same_author_rejected(self):
        foreign = Character.objects.create(project=self.same_owner, name="Foreign")
        with self.assertRaises(ValidationError):
            attach_reference(self.reference(), foreign)

    def test_cross_author_rejected(self):
        foreign = Character.objects.create(project=self.other_project, name="Foreign")
        with self.assertRaises(ValidationError):
            attach_reference(self.reference(), foreign)

    def test_duplicate_rejected_even_different_description(self):
        ref = self.reference()
        attach_reference(ref, self.character)
        with self.assertRaises(ValidationError):
            attach_reference(ref, self.character, description="Another description")

    def test_exactly_one_model_validation(self):
        ref = self.reference()
        for fields in ({}, {"character": self.character, "organization": self.organization}):
            with self.assertRaises(ValidationError):
                Association(reference=ref, **fields).save()

    def test_sql_constraints(self):
        ref = self.reference()
        for row in (Association(reference=ref), Association(reference=ref, character=self.character, organization=self.organization)):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Association.objects.bulk_create([row])
        attach_reference(ref, self.character)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Association.objects.bulk_create([Association(reference=ref, character=self.character)])

    def test_detach_preserves_reference_and_other_associations(self):
        ref = self.reference(file=upload())
        first = attach_reference(ref, self.character)
        attach_reference(ref, self.node)
        detach_reference(first)
        self.assertEqual(Association.objects.count(), 1)
        self.assertTrue(Reference.objects.filter(pk=ref.pk).exists())
        self.assertTrue(Path(ref.file.path).exists())

    def test_delete_entity_preserves_reference(self):
        ref = self.reference(file=upload())
        attach_reference(ref, self.character)
        self.character.delete()
        self.assertFalse(Association.objects.exists())
        self.assertTrue(Reference.objects.filter(pk=ref.pk).exists())
        self.assertTrue(Path(ref.file.path).exists())

    def test_association_identity_cannot_change(self):
        association = attach_reference(self.reference(), self.character)
        association.character = None
        association.organization = self.organization
        with self.assertRaises(ValidationError):
            association.save()

    def test_corrupt_cross_project_association_is_hidden(self):
        ref = self.reference()
        association = attach_reference(ref, self.character)
        foreign = Character.objects.create(project=self.other_project, name="Foreign")
        Association.objects.filter(pk=association.pk).update(character=foreign)
        self.assertFalse(get_references_for_entity(foreign).exists())
        self.client.force_login(self.user)
        response = self.client.get(reverse("references:detail", args=[self.project.pk, ref.pk]))
        self.assertNotContains(response, "Foreign")


class ReferenceWebCase(ReferenceFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.ref = self.reference(file=image_upload(), author="Author")

    def url(self, name, pk=None):
        return reverse("references:" + name, args=[self.project.pk, *([pk or self.ref.pk] if name not in ("list", "create", "associate") else [])])

    def data(self, **changes):
        return {"title": "Updated", "material_type": "BIBLIOGRAPHY", "notes": "Notes\r\nText", "expected_revision": self.ref.revision, **changes}


class WebTests(ReferenceWebCase):
    def test_list_and_project_navigation(self):
        self.assertContains(self.client.get(reverse("projects:detail", args=[self.project.pk])), self.url("list"))
        response = self.client.get(self.url("list"))
        self.assertContains(response, "Reference")
        self.assertContains(response, "Author")

    def test_search_and_type_filter(self):
        self.reference(title="Other title")
        response = self.client.get(self.url("list"), {"q": "Author", "material_type": "BIBLIOGRAPHY"})
        self.assertEqual(list(response.context["page"]), [self.ref])
        self.assertFalse(self.client.get(self.url("list"), {"material_type": "DOCUMENT"}).context["page"])

    def test_invalid_filter_400(self):
        self.assertEqual(self.client.get(self.url("list"), {"material_type": "INVALID"}).status_code, 400)

    def test_detail_external_url_and_escaped_notes(self):
        update_reference(self.ref, expected_revision=1, source_url="https://example.test", notes="<script>x</script>\r\nSecond")
        response = self.client.get(self.url("detail"))
        self.assertContains(response, 'rel="noopener noreferrer"')
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, self.ref.file.name)

    def test_upload_form_and_create(self):
        self.assertContains(self.client.get(self.url("create")), 'enctype="multipart/form-data"')
        response = self.client.post(self.url("create"), {"title": "New", "material_type": "DOCUMENT", "file": upload()})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Reference.objects.get(title="New").mime_type, "text/plain")

    def test_preselection_creates_and_associates(self):
        for key, entity in zip(TARGETS, self.entities):
            param = TARGETS[key][1]
            response = self.client.post(self.url("create") + f"?{param}={entity.pk}", {"title": key, "material_type": "BIBLIOGRAPHY"})
            self.assertEqual(response.status_code, 302)
            self.assertTrue(Association.objects.filter(reference__title=key, **{key: entity}).exists())

    def test_bad_preselection_rejected(self):
        foreign = Character.objects.create(project=self.same_owner, name="Foreign")
        for query in (f"?character={foreign.pk}", "?character=x", "?character=0", f"?character={self.character.pk}&node={self.node.pk}"):
            self.assertEqual(self.client.get(self.url("create") + query).status_code, 404)

    def test_all_entity_details_show_links(self):
        for key, entity in zip(TARGETS, self.entities):
            attach_reference(self.ref, entity)
            response = self.client.get(reverse(TARGETS[key][2], args=[self.project.pk, entity.pk]))
            self.assertContains(response, "Ver referencia")
            self.assertContains(response, self.url("detail"))

    def test_attach_from_reference(self):
        response = self.client.post(self.url("attach"), {"reference": self.ref.pk, "character": self.character.pk, "description": "Source"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Association.objects.get().description, "Source")

    def test_attach_existing_from_entity(self):
        response = self.client.post(self.url("associate") + f"?location={self.location.pk}", {"reference": self.ref.pk})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Association.objects.get().geographic_location_id, self.location.pk)

    def test_download_content_headers_and_real_bytes(self):
        response = self.client.get(self.url("download"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(b"".join(response.streaming_content), Path(self.ref.file.path).read_bytes())

    def test_edit_replaces_and_clears(self):
        old = Path(self.ref.file.path)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url("edit"), self.data(file=upload()))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(old.exists())
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.notes, "Notes\r\nText")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url("edit"), self.data(**{"file-clear": "on"}))
        self.ref.refresh_from_db()
        self.assertFalse(self.ref.file)

    def test_stale_form_preserves_text_and_original_file(self):
        update_reference(self.ref, expected_revision=1, title="Winner")
        response = self.client.post(self.url("edit"), self.data(title="Rejected title", notes="Recover me", file=upload()))
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Recover me", status_code=409)
        self.assertEqual(Reference.objects.get(pk=self.ref.pk).file.name, self.ref.file.name)

    def test_invalid_upload_errors_no_file_written(self):
        response = self.client.post(self.url("create"), {"title": "Invalid", "material_type": "IMAGE", "file": upload("bad.png")})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertEqual(Reference.objects.count(), 1)

    def test_delete_confirmation_revision_and_post(self):
        self.assertEqual(self.client.get(self.url("delete")).status_code, 200)
        self.assertEqual(Reference.objects.count(), 1)
        self.client.post(self.url("delete"), {})
        self.assertEqual(Reference.objects.count(), 1)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url("delete"), {"expected_revision": 1})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Reference.objects.exists())

    def test_detach_confirmation_preserves_file(self):
        association = attach_reference(self.ref, self.character)
        url = self.url("detach", association.pk)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertTrue(Association.objects.exists())
        self.assertEqual(self.client.post(url, {}).status_code, 302)
        self.assertFalse(Association.objects.exists())
        self.assertTrue(Path(self.ref.file.path).exists())

    def test_public_paths_missing_files_and_traversal_404(self):
        for prefix in ("/media/", "/private_media/"):
            self.assertEqual(self.client.get(prefix + self.ref.file.name).status_code, 404)
        for path in ("../secret.txt", f"references/{self.other_project.pk}/{'a' * 32}.txt", f"references/{self.project.pk}/{'a' * 32}.txt"):
            Reference.objects.filter(pk=self.ref.pk).update(file=path)
            self.assertEqual(self.client.get(self.url("download")).status_code, 404)

    def test_symlink_to_other_file_rejected(self):
        actual = Path(self.ref.file.path)
        link = reference_path(self.project.pk, f"references/{self.project.pk}/{'b' * 32}.png")
        link.symlink_to(actual)
        Reference.objects.filter(pk=self.ref.pk).update(file=link.relative_to(self.media.name).as_posix())
        self.assertEqual(self.client.get(self.url("download")).status_code, 404)

    def test_no_file_download_404(self):
        ref = self.reference()
        self.assertEqual(self.client.get(self.url("download", ref.pk)).status_code, 404)


class PermissionTests(ReferenceWebCase):
    def test_anonymous_download(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url("download")).status_code, 302)

    def test_foreign_owner_and_admin_404(self):
        for kind in ("FREE", "BUSINESS_ADMIN", "TECH_ADMIN"):
            self.other.user_type = kind
            self.other.is_staff = self.other.is_superuser = True
            self.other.save()
            self.client.force_login(self.other)
            for name in ("list", "detail", "download", "edit", "delete", "attach"):
                self.assertEqual(self.client.get(self.url(name)).status_code, 404)
                if name not in ("list", "detail", "download"):
                    self.assertEqual(self.client.post(self.url(name), {}).status_code, 404)

    def test_same_owner_other_project_404(self):
        self.assertEqual(self.client.get(reverse("references:detail", args=[self.same_owner.pk, self.ref.pk])).status_code, 404)

    def test_read_only_states(self):
        for status in ("FROZEN", "PENDING_DELETION"):
            Project.objects.filter(pk=self.project.pk).update(status=status)
            for name in ("list", "detail", "download"):
                response = self.client.get(self.url(name))
                self.assertEqual(response.status_code, 200)
                if response.streaming:
                    b"".join(response.streaming_content)
            for name in ("create", "edit", "delete", "attach", "associate"):
                self.assertEqual(self.client.post(self.url(name), {}).status_code, 403)

    def test_deleted_inaccessible(self):
        Project.objects.filter(pk=self.project.pk).update(status="DELETED")
        for name in ("list", "detail", "download", "create", "edit", "delete", "attach"):
            self.assertEqual(self.client.get(self.url(name)).status_code, 404)

    def test_csrf_for_all_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for name in ("create", "edit", "delete", "attach", "associate"):
            self.assertEqual(client.post(self.url(name), {}).status_code, 403)


class AdminTests(ReferenceFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)

    def test_admin_creation_and_download_link_without_path(self):
        url = reverse("admin:references_referencematerial_add")
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {"project": self.project.pk, "title": "Admin", "material_type": "DOCUMENT", "file": upload(), "_save": "Save"})
        self.assertEqual(response.status_code, 302)
        ref = Reference.objects.get()
        response = self.client.get(reverse("admin:references_referencematerial_change", args=[ref.pk]))
        self.assertContains(response, reverse("references:download", args=[self.project.pk, ref.pk]))
        self.assertNotContains(response, ref.file.name)

    def test_admin_edit_and_stale_conflict(self):
        ref = self.reference(file=upload())
        url = reverse("admin:references_referencematerial_change", args=[ref.pk])
        data = {"title": "Winner", "material_type": "BIBLIOGRAPHY", "expected_revision": 1, "_save": "Save"}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        response = self.client.post(url, {**data, "notes": "Recover admin text"})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "Recover admin text", status_code=409)

    def test_admin_failed_upload_preserves_original_and_form(self):
        ref = self.reference(file=upload())
        old = Path(ref.file.path)
        url = reverse("admin:references_referencematerial_change", args=[ref.pk])
        with patch("apps.references.services.os.fsync", side_effect=OSError("Disk failure")):
            response = self.client.post(url, {"title": "Recover title", "notes": "Recover notes", "material_type": "DOCUMENT",
                "expected_revision": 1, "file": upload(content=b"replacement"), "_save": "Save"})
        self.assertContains(response, "Recover notes")
        self.assertContains(response, "No se pudo guardar el archivo")
        ref.refresh_from_db()
        self.assertEqual(ref.revision, 1)
        self.assertTrue(old.exists())
        self.assertEqual(len(list(Path(self.media.name).rglob("*.txt"))), 1)

    def test_admin_directory_failure_is_controlled(self):
        with patch("pathlib.Path.mkdir", side_effect=PermissionError()):
            response = self.client.post(reverse("admin:references_referencematerial_add"), {
                "project": self.project.pk, "title": "Upload", "material_type": "DOCUMENT", "file": upload(), "_save": "Save"})
        self.assertContains(response, "No se pudo guardar el archivo")
        self.assertFalse(Reference.objects.exists())

    def test_admin_foreign_content_and_files_hidden(self):
        ref = create_reference(self.other_project, title="Foreign secret", file=upload())
        self.assertNotContains(self.client.get(reverse("admin:references_referencematerial_changelist")), "Foreign secret")
        self.assertEqual(self.client.get(reverse("admin:references_referencematerial_change", args=[ref.pk])).status_code, 404)

    def test_admin_invalid_associations_rejected(self):
        ref = self.reference()
        foreign = Character.objects.create(project=self.same_owner, name="Foreign")
        url = reverse("admin:references_referenceassociation_add")
        for data in ({"character": foreign.pk}, {}, {"character": self.character.pk, "organization": self.organization.pk}):
            response = self.client.post(url, {"reference": ref.pk, "_save": "Save", **data})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(Association.objects.exists())

    def test_admin_valid_association(self):
        ref = self.reference()
        response = self.client.post(reverse("admin:references_referenceassociation_add"), {"reference": ref.pk, "character": self.character.pk, "_save": "Save"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Association.objects.count(), 1)

    def test_admin_frozen_reference_read_only(self):
        ref = self.reference()
        Project.objects.filter(pk=self.project.pk).update(status="FROZEN")
        url = reverse("admin:references_referencematerial_change", args=[ref.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {"title": "Bad"}).status_code, 403)

    def test_admin_no_bulk_or_reference_delete(self):
        ref = self.reference()
        self.assertEqual(self.client.post(reverse("admin:references_referencematerial_delete", args=[ref.pk]), {"post": "yes"}).status_code, 403)


class PerformanceTests(ReferenceFixtures, TestCase):
    def test_entity_references_have_no_n_plus_one(self):
        for index in range(12):
            attach_reference(self.reference(title=f"Reference {index}"), self.character)
        with self.assertNumQueries(1):
            rows = list(get_references_for_entity(self.character))
            for row in rows:
                str(row.reference)
                str(row.entity)
                _ = row.entity_url

    def test_list_paginates_without_opening_files_or_loading_notes(self):
        Reference.objects.bulk_create([Reference(project=self.project, title=f"Entry {i}", notes="Large text") for i in range(65)])
        self.client.force_login(self.user)
        with patch("apps.references.files.reference_path", side_effect=AssertionError("No file reads")):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse("references:list", args=[self.project.pk]))
        self.assertEqual(len(response.context["page"]), 50)
        self.assertLessEqual(len(queries), 10)
        selects = [q["sql"] for q in queries if 'FROM "references_referencematerial"' in q["sql"]]
        self.assertTrue(selects)
        self.assertTrue(all('"notes"' not in sql for sql in selects))

    def test_entity_reference_section_paginates(self):
        refs = Reference.objects.bulk_create([Reference(project=self.project, title=f"Entry {i}") for i in range(55)])
        Association.objects.bulk_create([Association(reference=ref, character=self.character) for ref in refs])
        self.client.force_login(self.user)
        response = self.client.get(reverse("characters:detail", args=[self.project.pk, self.character.pk]), {"references_page": 2})
        self.assertContains(response, "Ver referencia", count=5)
