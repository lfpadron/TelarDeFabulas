from datetime import timedelta
from io import BytesIO
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from django.core import mail
from django.core.exceptions import ValidationError
from django.db import connection, DatabaseError, IntegrityError, transaction
from django.http import Http404
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from docx import Document
from pypdf import PdfReader

from apps.characters.models import Character, CharacterRelationship
from apps.geography.models import GeographicLocation
from apps.geography.services import move_location
from apps.organizations.models import CharacterOrganizationMembership
from apps.organizations.services import move_organization
from apps.projects.models import Project
from apps.references.models import ReferenceMaterial, ReferenceAssociation
from apps.worldbuilding.models import WorldbuildingEntry

from .docx import build_export_docx
from .forms import ExportJobForm, ExportPreviewForm
from .job_services import retry_export
from .lifecycle import claim_export, delete_export, recover_job
from .markdown import build_export_markdown
from .models import ExportJob, ExportSnapshot
from .notifications import send_notification
from .pdf import build_export_pdf
from .services import build_export_html
from .snapshots import get_export_document, manifest_digest
from .tasks import cleanup_expired_exports, generate_export_job
from .world_exports import build_world_manifest, normalize_selection, public_source_url
from .world_forms import WorldExportForm
from .world_test_helpers import WorldExportFixture


class WorldSelectionTests(WorldExportFixture, TestCase):
    def test_character_sheet(self):
        job = self.request(scope_kind="CHARACTER", entity_id=self.ada.pk)
        self.assertEqual(self.ids(job, "CHARACTER"), [self.ada.pk])
        text = self.contents(job)
        for value in ("Archivist", "BIO ORIGINAL", "Kingdom / Harbor", "Year of rain", "RELATION ORIGINAL", "Atlas", "H\u00e9roe"):
            self.assertIn(value, text)
        self.assertNotIn("BEN ORIGINAL", text)

    def test_character_catalog_has_unique_stable_entries(self):
        job = self.request(scope_kind="CHARACTERS_ALL")
        self.assertEqual(self.ids(job, "CHARACTER"), [self.ada.pk, self.ben.pk, self.cora.pk])
        self.assertEqual(self.contents(job).count("\u2194"), 1)
        self.assertEqual(self.contents(job).count("Ada \u2192 Ben"), 1)
        self.assertNotIn("Ben \u2192 Ada", self.contents(job))

    def test_incoming_relationships(self):
        job = self.request(scope_kind="CHARACTER", entity_id=self.ben.pk)
        self.assertIn("Relaciones entrantes", self.contents(job))
        self.assertIn("Ada \u2192 Ben", self.contents(job))
        self.assertNotIn("Relaciones salientes", self.contents(job))

    def test_location_individual(self):
        job = self.request(scope_kind="GEOGRAPHIC_LOCATION", entity_id=self.country.pk)
        self.assertEqual(self.ids(job, "GEOGRAPHIC_LOCATION"), [self.country.pk])

    def test_location_descendants(self):
        job = self.request(scope_kind="GEOGRAPHIC_LOCATION", entity_id=self.country.pk, include_descendants=True)
        self.assertEqual(self.ids(job, "GEOGRAPHIC_LOCATION"), [self.country.pk, self.city.pk])
        self.assertEqual([n.depth for n in self.sections(job, "GEOGRAPHIC_LOCATION")], [2, 3])

    def test_geography_all_and_context(self):
        job = self.request(scope_kind="GEOGRAPHY_ALL")
        self.assertEqual(self.ids(job, "GEOGRAPHIC_LOCATION"), [self.country.pk, self.city.pk])
        self.assertIn("Ada", self.contents(job))
        self.assertIn("Council", self.contents(job))

    def test_organization_individual(self):
        job = self.request(scope_kind="ORGANIZATION", entity_id=self.guild.pk)
        self.assertEqual(self.ids(job, "ORGANIZATION"), [self.guild.pk])
        self.assertIn("Kingdom / Harbor", self.contents(job))

    def test_organization_descendants(self):
        job = self.request(scope_kind="ORGANIZATION", entity_id=self.guild.pk, include_descendants=True)
        self.assertEqual(self.ids(job, "ORGANIZATION"), [self.guild.pk, self.branch.pk])

    def test_all_organizations(self):
        job = self.request(scope_kind="ORGANIZATIONS_ALL")
        self.assertEqual(self.ids(job, "ORGANIZATION"), [self.guild.pk, self.branch.pk])
        self.assertEqual([n.depth for n in self.sections(job, "ORGANIZATION")], [2, 3])

    def test_multiple_memberships_group_one_person(self):
        CharacterOrganizationMembership.objects.create(character=self.ada, organization=self.guild, position_title="Guide", membership_status="FORMER")
        job = self.request(scope_kind="ORGANIZATION", entity_id=self.guild.pk)
        members = next(n.content for n in self.sections(job) if n.title == "Integrantes")
        self.assertEqual(members.count("Ada"), 1)
        self.assertIn("Guide", members)
        self.assertIn("Archivist", members)

    def test_single_worldbuilding_entry(self):
        job = self.request(scope_kind="WORLDBUILDING_ENTRY", entity_id=self.politics.pk)
        self.assertEqual(self.ids(job, "WORLDBUILDING_ENTRY"), [self.politics.pk])
        self.assertIn("FIRST PARAGRAPH\n\nSECOND PARAGRAPH", self.contents(job))

    def test_worldbuilding_category(self):
        job = self.request(scope_kind="WORLDBUILDING_CATEGORY", category="POLITICS")
        self.assertEqual(self.ids(job, "WORLDBUILDING_ENTRY"), [self.politics.pk])

    def test_worldbuilding_all_fixed_category_then_authored_order(self):
        history = WorldbuildingEntry.objects.create(project=self.project, category="HISTORY", title="Older")
        second = WorldbuildingEntry.objects.create(project=self.project, category="POLITICS", title="A later entry")
        job = self.request(scope_kind="WORLDBUILDING_ALL")
        self.assertEqual(self.ids(job, "WORLDBUILDING_ENTRY"), [self.politics.pk, second.pk, self.religion.pk, history.pk])

    def test_individual_reference(self):
        job = self.request(scope_kind="REFERENCE_MATERIAL", entity_id=self.reference.pk)
        self.assertEqual(self.ids(job, "REFERENCE_MATERIAL"), [self.reference.pk])
        for text in ("Writer", "Era of rain", "Press", "REFERENCE ORIGINAL", "Ada", "ASSOCIATION ORIGINAL"):
            self.assertIn(text, self.contents(job))

    def test_references_catalog(self):
        job = self.request(scope_kind="REFERENCES_ALL")
        self.assertEqual(self.ids(job, "REFERENCE_MATERIAL"), [self.reference.pk, self.link.pk])
        self.assertIn("https://example.com/history", self.contents(job))

    def test_compendium_order_no_manuscripts_and_unique_references(self):
        ReferenceAssociation.objects.create(reference=self.reference, organization=self.guild)
        job = self.request()
        headers = [n.title for n in self.sections(job) if n.depth == 1]
        self.assertEqual(headers, ["Personajes", "Geograf\u00eda", "Organizaciones", "Pol\u00edtica", "Religi\u00f3n", "Referencias y materiales"])
        self.assertEqual(job.snapshot.included_entity_count, 11)
        self.assertEqual(self.ids(job, "REFERENCE_MATERIAL"), [self.reference.pk, self.link.pk])
        for secret in ("MANUSCRIPT SECRET", "DO NOT EXPORT", "FOREIGN"):
            self.assertNotIn(secret, self.contents(job))

    def test_empty_sections_omitted(self):
        job = self.request(scope_kind="CHARACTER", entity_id=self.cora.pk)
        self.assertEqual([n.title for n in self.sections(job) if n.depth == 1], ["Personajes"])
        self.assertNotIn("Biograf\u00eda:", self.contents(job))

    def test_empty_scope_rejected_without_job(self):
        with self.assertRaises(ValidationError):
            self.request(scope_kind="WORLDBUILDING_CATEGORY", category="HISTORY")
        self.assertFalse(ExportJob.objects.exists())

    def test_invalid_selections(self):
        for kwargs in ({"scope_kind": "MANUSCRIPT"}, {"scope_kind": "BAD"}, {"scope_kind": "CHARACTER"},
                {"scope_kind": "CHARACTER", "entity_id": -1}, {"scope_kind": "CHARACTER", "entity_id": True},
                {"scope_kind": "CHARACTER", "entity_id": 10**30}, {"scope_kind": "CHARACTERS_ALL", "entity_id": self.ada.pk},
                {"scope_kind": "CHARACTER", "entity_id": "9" * 5000},
                {"scope_kind": "WORLDBUILDING_CATEGORY", "category": "INVALID"},
                {"scope_kind": "WORLD_COMPENDIUM", "include_descendants": True},
                {"scope_kind": "WORLD_COMPENDIUM", "category": "POLITICS"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                normalize_selection(**kwargs)


class WorldSnapshotTests(WorldExportFixture, TestCase):
    def unchanged_after(self, write):
        job = self.request()
        manifest, text = job.snapshot.manifest_json, self.contents(job)
        digest = job.snapshot.checksum
        write()
        job.refresh_from_db()
        self.assertEqual(job.snapshot.manifest_json, manifest)
        self.assertEqual(job.snapshot.checksum, digest)
        self.assertEqual(self.contents(job), text)

    def test_biography_frozen(self):
        self.unchanged_after(lambda: Character.objects.filter(pk=self.ada.pk).update(biography="CHANGED"))

    def test_residence_frozen(self):
        self.unchanged_after(lambda: Character.objects.filter(pk=self.ada.pk).update(residence=self.country))

    def test_membership_frozen(self):
        self.unchanged_after(lambda: CharacterOrganizationMembership.objects.filter(pk=self.membership.pk).update(position_title="CHANGED"))

    def test_relationship_frozen(self):
        self.unchanged_after(lambda: CharacterRelationship.objects.filter(pk=self.relation.pk).update(description="CHANGED", relationship_type="FRIEND"))

    def test_geographic_movement_frozen(self):
        self.unchanged_after(lambda: move_location(self.city, None))

    def test_organization_movement_frozen(self):
        self.unchanged_after(lambda: move_organization(self.branch, None))

    def test_style_frozen(self):
        def change():
            self.style.name, self.style.body_size = "CHANGED", 22
            self.style.save()
        self.unchanged_after(change)

    def test_reference_frozen(self):
        self.unchanged_after(lambda: ReferenceMaterial.objects.filter(pk=self.reference.pk).update(notes="CHANGED"))

    def test_worldbuilding_frozen(self):
        self.unchanged_after(lambda: WorldbuildingEntry.objects.filter(pk=self.politics.pk).update(content="CHANGED"))

    def test_deletion_does_not_change_individual_snapshot(self):
        job = self.request(scope_kind="CHARACTER", entity_id=self.ben.pk)
        text = self.contents(job)
        self.ben.delete()
        self.assertEqual(self.contents(job), text)
        self.assertIn("BEN ORIGINAL", text)

    def test_all_primary_domain_deletions_preserve_compendium(self):
        def remove():
            self.politics.delete()
            self.reference.delete()
            self.ben.delete()
            self.branch.delete()
        self.unchanged_after(remove)

    def test_checksum_reproducible(self):
        a, b = self.request(), self.request()
        self.assertEqual(a.snapshot.checksum, b.snapshot.checksum)
        self.assertEqual(manifest_digest(a.snapshot.manifest_json), (a.snapshot.checksum, a.snapshot.size_bytes))

    def test_model_and_database_immutability(self):
        job = self.request()
        with self.assertRaises(ValidationError):
            job.snapshot.save()
        with self.assertRaises(DatabaseError), transaction.atomic():
            ExportSnapshot.objects.filter(export_job=job).update(manifest_json={})

    def test_idempotency_reuses_original_capture_after_source_deletion(self):
        key = uuid4()
        kwargs = {"scope_kind": "CHARACTER", "entity_id": self.ben.pk, "request_key": key}
        job = self.request(**kwargs)
        self.ben.delete()
        self.assertEqual(self.request(**kwargs).pk, job.pk)
        self.assertEqual(ExportSnapshot.objects.count(), 1)

    def test_idempotency_rejects_changed_scope(self):
        key = uuid4()
        self.request(request_key=key)
        with self.assertRaises(ValidationError):
            self.request(request_key=key, scope_kind="CHARACTERS_ALL")

    def test_render_uses_snapshot_without_live_content_queries(self):
        job = self.request()
        with CaptureQueriesContext(connection) as queries:
            document = get_export_document(job)
            build_export_markdown(job, document=document)
            build_export_html(job, document=document)
            build_export_docx(job, document=document)
        self.assertEqual(len(queries), 1)
        self.assertIn("exports_exportsnapshot", queries[0]["sql"])

    def test_scope_tampering_detected(self):
        job = self.request()
        job.scope_kind = "CHARACTERS_ALL"
        with self.assertRaises(ValidationError):
            get_export_document(job)


class WorldRenderingTests(WorldExportFixture, TestCase):
    def test_markdown_plaintext_toc_and_headings(self):
        text = build_export_markdown(self.request())
        self.assertIn("# \u00cdndice", text)
        self.assertIn("## Geograf\u00eda\n\n### Kingdom", text)
        self.assertIn("#### Harbor", text)
        self.assertIn("FIRST PARAGRAPH\n\nSECOND PARAGRAPH", text)
        self.assertNotIn("<script>", text)
        self.assertIn("\\<script\\>", text)

    def test_docx_real_content_and_hierarchy(self):
        data = build_export_docx(self.request(export_format="DOCX"))
        document = Document(BytesIO(data))
        self.assertIn("BIO ORIGINAL", "\n".join(p.text for p in document.paragraphs))
        self.assertTrue(any(p.text == "Harbor" and p.style.name == "Heading 4" for p in document.paragraphs))
        with ZipFile(BytesIO(data)) as archive:
            self.assertFalse(any(name.startswith("word/media/") for name in archive.namelist()))

    def test_pdf_real_searchable_content_and_toc(self):
        data = build_export_pdf(self.request(export_format="PDF"))
        self.assertTrue(data.startswith(b"%PDF-"))
        reader = PdfReader(BytesIO(data))
        text = "\n".join(page.extract_text() for page in reader.pages)
        self.assertIn("BIO ORIGINAL", text)
        self.assertIn("Kingdom", text)
        self.assertIn("FIRST PARAGRAPH", text)

    def test_html_escapes_worldbuilding_and_has_no_external_assets(self):
        html = build_export_html(self.request())
        self.assertNotIn('<script>alert', html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn('<img', html)
        self.assertNotIn('<link', html)

    def test_metadata_only_never_opens_private_files(self):
        ReferenceMaterial.objects.filter(pk=self.reference.pk).update(file="references/private-secret.bin", original_filename="source.pdf", mime_type="application/pdf")
        Character.objects.filter(pk=self.ada.pk).update(image="characters/secret.jpg")
        with patch("django.core.files.storage.FileSystemStorage.open", side_effect=AssertionError("Binary read")):
            job = self.request()
            text = json.dumps(job.snapshot.manifest_json, ensure_ascii=False)
            build_export_docx(job)
            build_export_pdf(job)
        self.assertIn("source.pdf", text)
        self.assertIn("application/pdf", text)
        for secret in ("private-secret", "secret.jpg", "private_media", "file_size", '"file"'):
            self.assertNotIn(secret, text)

    def test_source_urls_strip_private_tokens_and_paths(self):
        for url in ("https://example.com/x?token=SECRET", "http://localhost:8000/projects/1/references/2/download/",
                "https://example.com/x#access_token=SECRET", "https://example.com/x?X-Goog-Credential=SECRET",
                "https://example.com/x?sig=SECRET", "https://example.com/x?authorization=SECRET",
                "https://127.0.0.1/x", "https://example.com/private_media/foo", "https://u:p@example.com/x", "file:///secret", "javascript:alert(1)"):
            with self.subTest(url=url):
                self.assertEqual(public_source_url(url), "")
        self.assertEqual(public_source_url("https://example.com/history?q=era"), "https://example.com/history?q=era")

    def test_private_url_absent_from_snapshot(self):
        ReferenceMaterial.objects.filter(pk=self.link.pk).update(source_url="https://example.com/x?token=SECRET")
        self.assertNotIn("SECRET", json.dumps(self.request().snapshot.manifest_json))

    def test_unsafe_filename_absent(self):
        ReferenceMaterial.objects.filter(pk=self.reference.pk).update(original_filename="C:\\private\\secret.pdf")
        self.assertNotIn("secret.pdf", json.dumps(self.request().snapshot.manifest_json))

    def test_no_toc_when_disabled(self):
        self.style.include_table_of_contents = False
        self.style.save()
        self.assertNotIn("# \u00cdndice", build_export_markdown(self.request()))


class WorldSecurityAndFormTests(WorldExportFixture, TestCase):
    def test_foreign_project_request_and_page_are_404(self):
        with self.assertRaises(Http404):
            self.request(user=self.other_user)
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.client.post(self.url(), self.post_data()).status_code, 404)

    def test_foreign_entity_rejected(self):
        with self.assertRaises(Http404):
            self.request(scope_kind="CHARACTER", entity_id=self.foreign.pk)
        form = WorldExportForm(self.post_data(scope_kind="CHARACTER", character=self.foreign.pk), user=self.user, project=self.project)
        self.assertFalse(form.is_valid())

    def test_foreign_style_rejected(self):
        self.style.user = self.other_user
        self.style.save()
        with self.assertRaises(Http404):
            self.request()

    def test_foreign_download_and_history_detail_are_404(self):
        job = self.request()
        generate_export_job.run(job.pk)
        self.client.force_login(self.other_user)
        for name in ("download", "detail"):
            self.assertEqual(self.client.get(self.url(name, job)).status_code, 404)

    def test_frozen_project_can_export(self):
        Project.objects.filter(pk=self.project.pk).update(status="FROZEN")
        job = self.request()
        generate_export_job.run(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "READY")

    def test_pending_project_can_export(self):
        Project.objects.filter(pk=self.project.pk).update(status="PENDING_DELETION")
        self.assertEqual(self.request().status, "REQUESTED")

    def test_deleted_project_cannot_export(self):
        Project.objects.filter(pk=self.project.pk).update(status="DELETED")
        with self.assertRaises(Http404):
            self.request()
        self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_cross_project_reference_association_rejected(self):
        ReferenceAssociation.objects.filter(pk=self.association.pk).update(reference=self.foreign_reference)
        with self.assertRaises(ValidationError):
            self.request()
        self.assertFalse(ExportJob.objects.exists())

    def test_cross_project_relationship_rejected(self):
        CharacterRelationship.objects.filter(pk=self.relation.pk).update(target_character=self.foreign)
        with self.assertRaises(ValidationError):
            self.request()

    def test_cross_project_membership_rejected(self):
        CharacterOrganizationMembership.objects.filter(pk=self.membership.pk).update(character=self.foreign)
        with self.assertRaises(ValidationError):
            self.request()

    def test_cross_project_residence_rejected(self):
        place = GeographicLocation.objects.create(project=self.other_project, name="FOREIGN LOCATION")
        Character.objects.filter(pk=self.ada.pk).update(residence=place)
        with self.assertRaises(ValidationError):
            self.request()

    def test_form_modes_formats_and_entity_queries(self):
        response = self.client.get(self.url())
        self.assertContains(response, 'data-scopes="CHARACTER"')
        self.assertNotContains(response, "FOREIGN")
        form = response.context["form"]
        self.assertNotIn("export_mode", form.fields)
        self.assertEqual([v for v, _ in form.fields["format"].choices], ["MARKDOWN", "DOCX", "PDF"])
        self.assertEqual(len(form.fields["scope_kind"].choices), 6)
        self.assertEqual(len(form.fields["character"].queryset), 3)

    def test_successful_post_shared_history_and_count(self):
        response = self.client.post(self.url(), self.post_data())
        job = ExportJob.objects.get()
        self.assertRedirects(response, self.url("detail", job))
        self.assertEqual((job.export_mode, job.scope_kind, job.status), ("REFERENCE", "WORLD_COMPENDIUM", "REQUESTED"))
        self.assertContains(self.client.get(self.url("detail", job)), "11")
        self.assertContains(self.client.get(self.url("list")), "Documento de consulta")

    def test_form_rejects_inconsistent_entity_and_descendants(self):
        for values in ({"scope_kind": "CHARACTERS_ALL", "character": self.ada.pk},
                {"include_descendants": True}, {"format": "EPUB"}, {"format": "HTML"}, {"category": "POLITICS"}):
            form = WorldExportForm(self.post_data(**values), user=self.user, project=self.project)
            self.assertFalse(form.is_valid(), values)

    def test_form_requires_entity_and_category(self):
        for scope in ("CHARACTER", "GEOGRAPHIC_LOCATION", "ORGANIZATION", "WORLDBUILDING_ENTRY", "REFERENCE_MATERIAL", "WORLDBUILDING_CATEGORY"):
            form = WorldExportForm(self.post_data(scope_kind=scope), user=self.user, project=self.project)
            self.assertFalse(form.is_valid(), scope)

    def test_post_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url(), self.post_data()).status_code, 403)

    def test_literary_forms_do_not_show_reference_mode(self):
        for cls in (ExportJobForm, ExportPreviewForm):
            form = cls(user=self.user, project=self.project)
            self.assertEqual([v for v, _ in form.fields["export_mode"].choices], ["WORK", "FINAL"])

    def test_database_rejects_mode_scope_mismatch(self):
        job = self.request()
        for changes in ({"export_mode": "WORK"}, {"scope_kind": "MANUSCRIPT"}, {"format": "HTML"}, {"root_node": self.book}):
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                ExportJob.objects.filter(pk=job.pk).update(**changes)

    def test_reference_cannot_accept_literary_selection(self):
        with self.assertRaises(ValidationError):
            self.request(root_node=self.book)
        with self.assertRaises(ValidationError):
            self.request(export_mode="WORK")


class WorldLifecycleTests(WorldExportFixture, TestCase):
    def test_requested_processing_and_lease(self):
        job = self.request()
        self.assertEqual(job.status, "REQUESTED")
        claim = claim_export(job.pk)
        self.assertEqual(claim.status, "PROCESSING")
        self.assertIsNotNone(claim.lease_expires_at)
        self.assertIsNone(claim_export(job.pk))

    def test_three_formats_ready_private_attachment(self):
        for format_, extension in (("MARKDOWN", ".md"), ("DOCX", ".docx"), ("PDF", ".pdf")):
            job = self.request(export_format=format_)
            generate_export_job.run(job.pk)
            job.refresh_from_db()
            self.assertEqual(job.status, "READY", job.error_message)
            response = self.client.get(self.url("download", job))
            self.assertEqual(response.status_code, 200)
            try:
                self.assertIn("attachment;", response["Content-Disposition"])
                self.assertIn(extension, response["Content-Disposition"])
                self.assertIn("no-store", response["Cache-Control"])
                self.assertTrue(b"".join(response.streaming_content))
            finally:
                if not response.closed:
                    response.close()

    def test_failure_retry_keeps_original_snapshot(self):
        job = self.request()
        checksum = job.snapshot.checksum
        with patch("apps.exports.tasks.build_export_markdown", side_effect=OSError("PRIVATE ERROR")):
            generate_export_job.run(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertNotIn("PRIVATE ERROR", job.error_message)
        Character.objects.filter(pk=self.ada.pk).update(biography="CHANGED")
        retry_export(job, user=self.user)
        generate_export_job.run(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "READY")
        self.assertEqual(job.snapshot.checksum, checksum)
        self.assertIn("BIO ORIGINAL", Path(job.file.path).read_text())

    def test_interruption_recovery(self):
        job = self.request()
        checksum = job.snapshot.checksum
        claim_export(job.pk)
        ExportJob.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        recover_job(job.pk)
        ExportJob.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        recover_job(job.pk)
        generate_export_job.run(job.pk)
        job.refresh_from_db()
        self.assertEqual((job.status, job.attempt_count, job.snapshot.checksum), ("READY", 2, checksum))

    def test_optional_notification_has_no_private_prose(self):
        for notify in (False, True):
            job = self.request(notify_by_email=notify)
            generate_export_job.run(job.pk)
            self.assertEqual(job.notifications.count(), int(notify))
            if notify:
                self.assertTrue(send_notification(job.notifications.get().pk))
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("BIO ORIGINAL", mail.outbox[0].body)

    def test_manual_deletion_removes_snapshot_and_file_only(self):
        job = self.request()
        generate_export_job.run(job.pk)
        job.refresh_from_db()
        path = Path(job.file.path)
        self.assertTrue(delete_export(job.pk, user=self.user))
        job.refresh_from_db()
        self.assertEqual(job.status, "DELETED")
        self.assertFalse(path.exists())
        self.assertFalse(ExportSnapshot.objects.filter(export_job=job).exists())
        self.assertTrue(Character.objects.filter(pk=self.ada.pk).exists())

    def test_expiry_blocks_download_then_cleans(self):
        job = self.request()
        generate_export_job.run(job.pk)
        ExportJob.objects.filter(pk=job.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get(self.url("download", job)).status_code, 404)
        cleanup_expired_exports.run()
        job.refresh_from_db()
        self.assertEqual(job.status, "DELETED")


class WorldPerformanceTests(WorldExportFixture, TestCase):
    def capture(self, scope="WORLD_COMPENDIUM"):
        return build_world_manifest(self.project, self.style, selection=normalize_selection(scope))

    def test_batched_queries_do_not_grow_with_characters(self):
        with CaptureQueriesContext(connection) as first:
            self.capture()
        Character.objects.bulk_create([Character(project=self.project, name=f"Extra {n}", biography="B" * 400) for n in range(60)])
        with CaptureQueriesContext(connection) as second:
            self.capture()
        self.assertEqual(len(first), len(second))
        self.assertLess(len(second), 65)

    @override_settings(EXPORT_SNAPSHOT_MAX_NODES=3)
    def test_source_row_limit(self):
        with self.assertRaises(ValidationError):
            self.request()
        self.assertFalse(ExportJob.objects.exists())

    @override_settings(EXPORT_SNAPSHOT_MAX_BYTES=1000)
    def test_oversize_text_preflight(self):
        Character.objects.filter(pk=self.ada.pk).update(biography="X" * 2000)
        with self.assertRaises(ValidationError):
            self.request(scope_kind="CHARACTER", entity_id=self.ada.pk)

    def test_deep_tree_is_iterative(self):
        # Bulk data deliberately bypasses web services to exercise a depth beyond Python's recursion limit.
        base = 100000
        GeographicLocation.objects.bulk_create([GeographicLocation(id=base+n, project=self.project, name="N",
            parent_id=base+n-1 if n else None, position=100 if n == 0 else 1) for n in range(1050)])
        result = self.capture("GEOGRAPHY_ALL")
        nodes = [n for n in result["ordered_sections"] if n["source_kind"] == "GEOGRAPHIC_LOCATION"]
        self.assertEqual(len(nodes), 1052)
        self.assertEqual(nodes[-1]["depth"], 1051)

    def test_corrupt_cycle_fails_without_recursion(self):
        GeographicLocation.objects.filter(pk=self.country.pk).update(parent=self.city)
        with self.assertRaises(ValidationError):
            self.request(scope_kind="GEOGRAPHY_ALL")
