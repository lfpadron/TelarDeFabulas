from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import Client, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.urls import reverse

from .models import ReferenceAssociation, ReferenceMaterial
from .services import attach_reference, create_reference, delete_reference, update_reference
from .test_support import ReferenceFixtures, upload


@skipUnlessDBFeature("has_select_for_update")
class ReferenceConcurrencyTests(ReferenceFixtures, TransactionTestCase):
    def race(self, *operations):
        barrier = Barrier(len(operations))

        def run(operation):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout TO '10s'")
                barrier.wait(timeout=15)
                try:
                    return operation()
                except ValidationError:
                    return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            futures = [pool.submit(run, operation) for operation in operations]
            return [future.result(timeout=30) for future in futures]

    @override_settings(REFERENCE_PROJECT_STORAGE_MAX_MB=1)
    def test_two_uploads_respect_project_quota(self):
        def create():
            return create_reference(self.project, title="Upload", file=upload(content=b"x" * 600000)).pk
        results = self.race(create, create)
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(ReferenceMaterial.objects.count(), 1)
        self.assertEqual(len(list(Path(self.media.name).rglob("*.txt"))), 1)

    def test_two_replacements_one_winner_and_no_orphan(self):
        ref = self.reference(file=upload())
        old = Path(ref.file.path)

        def replace(text):
            return update_reference(ref, expected_revision=1, notes=text, file=upload(content=text.encode())).notes
        results = self.race(lambda: replace("First"), lambda: replace("Second"))
        self.assertEqual(results.count("rejected"), 1)
        winner = next(value for value in results if value != "rejected")
        ref.refresh_from_db()
        self.assertEqual(ref.notes, winner)
        self.assertEqual(Path(ref.file.path).read_text(), winner)
        self.assertFalse(old.exists())
        self.assertEqual(len(list(Path(self.media.name).rglob("*.txt"))), 1)

    def test_duplicate_association_race(self):
        ref = self.reference()
        results = self.race(lambda: attach_reference(ref, self.character).pk, lambda: attach_reference(ref, self.character).pk)
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(ReferenceAssociation.objects.count(), 1)

    def test_delete_vs_replace_no_resurrection(self):
        ref = self.reference(file=upload())
        pk = ref.pk

        def delete():
            delete_reference(ReferenceMaterial.objects.get(pk=pk), expected_revision=1)
            return "deleted"
        results = self.race(delete, lambda: update_reference(ref, expected_revision=1, file=upload(content=b"new")).pk)
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(ReferenceMaterial.objects.filter(pk=pk).exists(), "deleted" not in results)
        self.assertEqual(len(list(Path(self.media.name).rglob("*.txt"))), 0 if "deleted" in results else 1)

    def test_attach_vs_reference_delete(self):
        ref = self.reference(file=upload())

        def delete():
            delete_reference(ReferenceMaterial.objects.get(pk=ref.pk), expected_revision=1)
            return "deleted"
        results = self.race(delete, lambda: attach_reference(ref, self.character).pk)
        self.assertIn("deleted", results)
        self.assertFalse(ReferenceMaterial.objects.exists())
        self.assertFalse(ReferenceAssociation.objects.exists())

    def test_download_vs_delete_returns_file_or_404(self):
        ref = self.reference(file=upload())
        client = Client()
        client.force_login(self.user)
        url = reverse("references:download", args=[self.project.pk, ref.pk])

        def download():
            response = client.get(url)
            if response.status_code == 200:
                self.assertEqual(b"".join(response.streaming_content), b"Plain text\r\nSecond line")
            return response.status_code

        def delete():
            delete_reference(ReferenceMaterial.objects.get(pk=ref.pk), expected_revision=1)
            return "deleted"
        results = self.race(download, delete)
        self.assertIn(results[0], (200, 404))
        self.assertEqual(results[1], "deleted")

    def test_admin_vs_service_conflict(self):
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        ref = self.reference(file=upload())
        client = Client()
        client.force_login(self.user)

        def admin_edit():
            return client.post(reverse("admin:references_referencematerial_change", args=[ref.pk]),
                {"title": "Admin", "material_type": "BIBLIOGRAPHY", "notes": "Admin", "expected_revision": 1, "_save": "Save"}).status_code

        def service_edit():
            update_reference(ref, expected_revision=1, notes="Service")
            return "saved"
        results = self.race(admin_edit, service_edit)
        self.assertIn(results, ([302, "rejected"], [409, "saved"]))

    def test_attach_vs_entity_delete_preserves_reference(self):
        ref = self.reference(file=upload())

        def delete():
            self.character.delete()
            return "deleted"
        results = self.race(delete, lambda: attach_reference(ref, self.character).pk)
        self.assertIn("deleted", results)
        self.assertFalse(ReferenceAssociation.objects.exists())
        self.assertTrue(ReferenceMaterial.objects.filter(pk=ref.pk).exists())

    def test_other_entity_deletions_serialize_with_associations(self):
        for entity in (self.node, self.location, self.organization, self.world):
            with self.subTest(model=entity._meta.label):
                ref = self.reference(file=upload())

                def delete():
                    entity.delete()
                    return "deleted"
                results = self.race(delete, lambda: attach_reference(ref, entity).pk)
                self.assertIn("deleted", results)
                self.assertFalse(ReferenceAssociation.objects.filter(reference=ref).exists())
                self.assertTrue(Path(ref.file.path).exists())

    def test_admin_association_vs_entity_delete(self):
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        client = Client()
        client.force_login(self.user)
        ref = self.reference()
        character_pk = self.character.pk

        def attach():
            return client.post(reverse("admin:references_referenceassociation_add"),
                {"reference": ref.pk, "character": character_pk, "_save": "Save"}).status_code

        def delete():
            self.character.delete()
            return "deleted"
        results = self.race(attach, delete)
        self.assertIn(results[0], (200, 302))
        self.assertEqual(results[1], "deleted")
        self.assertFalse(ReferenceAssociation.objects.exists())
