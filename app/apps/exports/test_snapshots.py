import json
import shutil
import tempfile
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from docx import Document
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import DatabaseError, connection, transaction
from django.http import Http404
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.core.tests.helpers import SecurityTestCase
from apps.manuscripts.models import ManuscriptNode, SceneVersion
from apps.manuscripts.services import move_node
from apps.manuscripts.version_services import create_scene_version, finalize_scene_version, get_current_draft_version, update_scene_version
from apps.projects.models import Project
from apps.styles.models import StyleTemplate

from .docx import build_export_docx
from .epub import build_export_epub
from .job_services import enqueue_export, request_export, retry_export
from .models import ExportJob, ExportSnapshot
from .pdf import build_export_pdf, build_export_pdf_html
from .services import build_export_html
from .snapshots import build_manifest, get_export_document, manifest_digest
from .tasks import generate_export_job


class ExportSnapshotTests(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        self.enterContext(override_settings(MEDIA_ROOT=self.media_root))
        self.part = ManuscriptNode.objects.create(project=self.project, parent=self.book, node_type="PART", title="Part")
        move_node(self.chapter, self.part)
        self.chapter.refresh_from_db()
        first = get_current_draft_version(self.scene)
        finalize_scene_version(self.scene, first, user=self.user, expected_revision=first.revision)
        second = create_scene_version(self.scene, user=self.user, content="  FINAL_ALPHA\r\nExact text.\t")
        self.final = finalize_scene_version(self.scene, second, user=self.user, expected_revision=second.revision)
        self.draft = create_scene_version(self.scene, user=self.user, content="DRAFT_ALPHA")
        self.scene2 = ManuscriptNode.objects.create(project=self.project, parent=self.chapter, node_type="SCENE", title="Second", content="DRAFT_BETA")
        self.scene3 = ManuscriptNode.objects.create(project=self.project, parent=self.chapter, node_type="SCENE", title="Third", content="FINAL_GAMMA")
        third = get_current_draft_version(self.scene3)
        finalize_scene_version(self.scene3, third, user=self.user, expected_revision=third.revision)
        self.empty = ManuscriptNode.objects.create(project=self.project, parent=self.book, node_type="CHAPTER", title="Empty chapter")
        self.style.include_table_of_contents = True
        self.style.config_json = {"test": "original"}
        self.style.save()

    def request(self, **overrides):
        return request_export(**{"user": self.user, "project": self.project, "style_template": self.style,
                                 "request_key": uuid4(), **overrides})

    def test_work_prefers_active_draft_and_falls_back_to_final(self):
        document = get_export_document(self.request())
        texts = [node.content for node in document.nodes]
        self.assertIn("DRAFT_ALPHA", texts)
        self.assertIn("FINAL_GAMMA", texts)
        self.assertNotIn(self.final.content, texts)
        self.assertEqual((document.included_scene_count, document.excluded_scene_count), (3, 0))

    def test_work_includes_review_and_consistent_empty_scene(self):
        update_scene_version(self.scene, self.draft, user=self.user, expected_revision=self.draft.revision, editorial_stage="REVIEW")
        empty_scene = ManuscriptNode.objects.create(project=self.project, parent=self.chapter, node_type="SCENE", title="No version")
        SceneVersion.objects.filter(scene=empty_scene).delete()
        document = get_export_document(self.request())
        nodes = {node.node_id: node for node in document.nodes}
        self.assertEqual(nodes[self.scene.pk].editorial_stage, "REVIEW")
        self.assertEqual(nodes[empty_scene.pk].content, "")

    def test_final_prunes_drafts_and_empty_containers_preserving_ancestors(self):
        document = get_export_document(self.request(export_mode="FINAL"))
        self.assertEqual([node.node_id for node in document.nodes], [self.book.pk, self.part.pk, self.chapter.pk, self.scene.pk, self.scene3.pk])
        self.assertEqual([node.depth for node in document.nodes], [0, 1, 2, 3, 3])
        self.assertEqual((document.included_scene_count, document.excluded_scene_count), (2, 1))
        self.assertEqual(document.nodes[-2].content, self.final.content)
        self.assertTrue(all(node.editorial_stage in (None, "FINAL") for node in document.nodes))

    def test_final_scopes_to_root_and_rejects_selection_without_final(self):
        document = get_export_document(self.request(root_node=self.scene, export_mode="FINAL"))
        self.assertEqual([node.node_id for node in document.nodes], [self.scene.pk])
        before = ExportJob.objects.count()
        with self.assertRaisesMessage(ValidationError, "No hay escenas"):
            self.request(root_node=self.scene2, export_mode="FINAL")
        self.assertEqual(ExportJob.objects.count(), before)

    def test_snapshot_copies_exact_text_revision_metadata_and_all_style_settings(self):
        self.scene.short_description = "Synopsis"
        self.scene.save()
        job = self.request(export_mode="FINAL")
        snapshot = job.snapshot
        row = next(row for row in snapshot.manifest_json["ordered_nodes"] if row["node_id"] == self.scene.pk)
        self.assertEqual(row["content"], self.final.content)
        self.assertEqual(row["revision"], self.final.revision)
        self.assertEqual(row["selected_version_id"], self.final.pk)
        self.assertEqual(row["short_description"], "Synopsis")
        self.assertEqual(snapshot.manifest_json["style_configuration"]["config_json"], {"test": "original"})
        self.assertEqual(manifest_digest(snapshot.manifest_json), (snapshot.checksum, snapshot.size_bytes))
        roundtrip = json.loads(json.dumps(snapshot.manifest_json, ensure_ascii=False))
        self.assertEqual(manifest_digest(roundtrip), manifest_digest(snapshot.manifest_json))

    def test_later_edit_move_title_description_style_and_locale_do_not_change_snapshot(self):
        job = self.request()
        before = job.snapshot.manifest_json
        update_scene_version(self.scene, self.draft, user=self.user, expected_revision=self.draft.revision, content="LATER_EDIT")
        move_node(self.scene, self.empty)
        self.scene.refresh_from_db()
        self.scene.title, self.scene.short_description = "Later title", "Later synopsis"
        self.scene.save()
        self.style.body_size, self.style.name, self.style.config_json = 19, "Later style", {"test": "later"}
        self.style.save()
        Project.objects.filter(pk=self.project.pk).update(name="Later project", locale="en-us")
        job.refresh_from_db()
        self.assertEqual(job.snapshot.manifest_json, before)
        html = build_export_html(job)
        self.assertIn("DRAFT_ALPHA", html)
        self.assertNotIn("LATER_EDIT", html)
        self.assertNotIn("Later title", html)
        self.assertEqual(get_export_document(job).style.body_size, before["style_configuration"]["body_size"])

    def test_deleting_root_scene_does_not_expand_or_destroy_snapshot(self):
        job = self.request(root_node=self.scene)
        original_id = self.scene.pk
        self.scene.delete()
        job.refresh_from_db()
        self.assertIsNone(job.root_node_id)
        document = get_export_document(job)
        self.assertEqual([node.node_id for node in document.nodes], [original_id])
        self.assertEqual(document.nodes[0].content, "DRAFT_ALPHA")

    def test_snapshot_model_and_sql_updates_are_blocked(self):
        snapshot = self.request().snapshot
        with self.assertRaises(ValidationError):
            snapshot.save()
        with self.assertRaises(ValidationError):
            snapshot.delete()
        with self.assertRaises(DatabaseError), transaction.atomic():
            ExportSnapshot.objects.filter(pk=snapshot.pk).update(checksum="0" * 64)

    def test_integrity_checks_fail_closed(self):
        job = self.request()
        snapshot = job.snapshot
        snapshot.manifest_json["ordered_nodes"][-1]["title"] = "tampered"
        with patch.object(ExportSnapshot.objects, "get", return_value=snapshot):
            with self.assertRaisesMessage(ValidationError, "integridad"):
                get_export_document(job)

    def test_job_identity_tampering_fails_closed(self):
        job = self.request()
        job.export_mode = "FINAL"
        with self.assertRaises(ValidationError):
            get_export_document(job)

    def test_failure_to_build_snapshot_rolls_back_job_and_callback(self):
        before = ExportJob.objects.count()
        with self.captureOnCommitCallbacks(execute=True) as callbacks, patch("apps.exports.job_services.manifest_digest", side_effect=ValidationError("Too big")):
            with self.assertRaises(ValidationError):
                self.request()
        self.assertEqual(callbacks, [])
        self.assertEqual(ExportJob.objects.count(), before)
        self.assertFalse(ExportSnapshot.objects.exists())

    @override_settings(EXPORT_SNAPSHOT_MAX_BYTES=10)
    def test_snapshot_size_limit_does_not_leave_job(self):
        with self.assertRaises(ValidationError):
            self.request()
        self.assertFalse(ExportSnapshot.objects.exists())

    @override_settings(EXPORT_SNAPSHOT_MAX_NODES=2)
    def test_node_limit_does_not_leave_job(self):
        with self.assertRaises(ValidationError):
            self.request()
        self.assertFalse(ExportSnapshot.objects.exists())

    def test_identical_request_key_is_idempotent(self):
        key = uuid4()
        with patch("apps.exports.job_services.enqueue_export") as send, self.captureOnCommitCallbacks(execute=True):
            first = self.request(request_key=key)
            second = self.request(request_key=key)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ExportSnapshot.objects.count(), 1)
        send.assert_called_once_with(first.pk)
        with self.assertRaises(ValidationError):
            self.request(request_key=key, export_mode="FINAL")

    def test_enqueue_only_runs_after_commit(self):
        with patch("apps.exports.job_services.enqueue_export") as send:
            with self.captureOnCommitCallbacks(execute=True):
                job = self.request()
                send.assert_not_called()
                self.assertTrue(ExportSnapshot.objects.filter(export_job=job).exists())
            send.assert_called_once_with(job.pk)

    def test_broker_failure_and_controlled_retry_keep_original_snapshot(self):
        with patch("apps.exports.tasks.generate_export_job.apply_async", side_effect=ConnectionError("private host")), self.captureOnCommitCallbacks(execute=True):
            job = self.request()
        job.refresh_from_db()
        before = job.snapshot.checksum
        self.assertEqual(job.status, "REQUESTED")
        self.assertIsNone(job.enqueued_at)
        self.assertTrue(job.error_message)
        self.assertNotIn("private host", job.error_message)
        with patch("apps.exports.tasks.generate_export_job.apply_async") as send, self.captureOnCommitCallbacks(execute=True):
            retry_export(job, user=self.user)
        job.refresh_from_db()
        self.assertIsNotNone(job.enqueued_at)
        self.assertEqual(job.snapshot.checksum, before)
        send.assert_called_once()
        enqueue_export(job.pk)
        with self.assertRaises(ValidationError):
            retry_export(job, user=self.user)

    def test_failed_render_retry_and_duplicate_delivery_preserve_single_file(self):
        job = self.request()
        checksum = job.snapshot.checksum
        with patch("apps.exports.tasks.build_export_html", side_effect=OSError("private")):
            generate_export_job.run(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        retry_export(job, user=self.user)
        generate_export_job.run(job.pk)
        job.refresh_from_db()
        name, finished = job.file.name, job.finished_at
        generate_export_job.run(job.pk)
        job.refresh_from_db()
        self.assertEqual((job.status, job.file.name, job.finished_at, job.snapshot.checksum), ("READY", name, finished, checksum))

    def test_all_formats_use_snapshot_and_never_query_live_manuscript(self):
        for mode in ("WORK", "FINAL"):
            with self.subTest(mode=mode):
                job = self.request(export_mode=mode)
                with CaptureQueriesContext(connection) as queries:
                    html = build_export_html(job)
                    docx = build_export_docx(job)
                    epub = build_export_epub(job)
                    pdf_html = build_export_pdf_html(job)
                    pdf = build_export_pdf(job)
                self.assertEqual(len(queries), 5)
                self.assertTrue(all('exports_exportsnapshot' in q["sql"] for q in queries))
                self.assertTrue(pdf.startswith(b"%PDF"))
                docx_text = "\n".join(p.text for p in Document(BytesIO(docx)).paragraphs)
                with ZipFile(BytesIO(epub)) as archive:
                    epub_text = "\n".join(archive.read(name).decode() for name in archive.namelist() if name.endswith(".xhtml") and "node-" in name)
                expected = "DRAFT_ALPHA" if mode == "WORK" else "FINAL_ALPHA"
                absent = "FINAL_ALPHA" if mode == "WORK" else "DRAFT_ALPHA"
                for text in (html, docx_text, epub_text, pdf_html):
                    self.assertIn(expected, text)
                    self.assertIn("FINAL_GAMMA", text)
                    self.assertLess(text.index(expected), text.index("FINAL_GAMMA"))
                    self.assertNotIn(absent, text)
                    self.assertNotIn("Owner note", text)
                    self.assertNotIn("Owner character", text)
                    self.assertNotIn("selected_version_id", text)
                    self.assertEqual("DRAFT_BETA" in text, mode == "WORK")

    def test_query_count_does_not_grow_with_scene_count(self):
        with CaptureQueriesContext(connection) as small:
            build_manifest(self.project, self.style)
        for index in range(15):
            ManuscriptNode.objects.create(project=self.project, parent=self.chapter, node_type="SCENE", title=f"Extra {index}", content="Extra text")
        with CaptureQueriesContext(connection) as larger:
            build_manifest(self.project, self.style)
        self.assertEqual(len(larger), len(small))

    def test_final_confirmation_warns_before_creation(self):
        url = self.url("exports:create")
        payload = {"style_template": self.style.pk, "format": "MARKDOWN", "export_mode": "FINAL", "request_key": uuid4()}
        response = self.client.post(url, payload)
        self.assertContains(response, "Estas escenas no se incluir")
        self.assertEqual(response.context["counts"], {"included": 2, "excluded": 1})
        self.assertFalse(ExportSnapshot.objects.exists())
        payload["selection_confirmation"] = response.context["form"]["selection_confirmation"].value()
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        self.assertEqual(ExportSnapshot.objects.count(), 1)

    def test_final_confirmation_is_invalidated_when_counts_change(self):
        url = self.url("exports:create")
        payload = {"style_template": self.style.pk, "format": "MARKDOWN", "export_mode": "FINAL", "request_key": uuid4()}
        response = self.client.post(url, payload)
        payload["selection_confirmation"] = response.context["form"]["selection_confirmation"].value()
        version = get_current_draft_version(self.scene2)
        finalize_scene_version(self.scene2, version, user=self.user, expected_revision=version.revision)
        self.assertEqual(self.client.post(url, payload).status_code, 200)
        self.assertFalse(ExportSnapshot.objects.exists())

    def test_foreign_requests_and_snapshots_are_private(self):
        job = self.request()
        for overrides in ({"user": self.other_user}, {"root_node": self.other_node},
                          {"style_template": StyleTemplate.objects.create(user=self.other_user, name="Foreign")}):
            with self.subTest(overrides=overrides), self.assertRaises(Http404):
                self.request(**overrides)
        self.client.force_login(self.other_user)
        for name in ("detail", "download", "retry"):
            self.assertEqual(self.client.post(self.url(f"exports:{name}", export_pk=job.pk)).status_code, 404)
        self.assertEqual(self.client.get(f"/exports/snapshots/{job.snapshot.pk}/").status_code, 404)
        self.client.force_login(self.user)
        response = self.client.get(self.url("exports:detail", export_pk=job.pk))
        self.assertNotContains(response, "DRAFT_ALPHA")
        self.assertNotContains(response, "manifest_json")

    def test_readonly_project_states_allow_export_deleted_denies_it(self):
        for status in ("FROZEN", "PENDING_DELETION"):
            self.set_status(status)
            self.assertTrue(self.request().snapshot)
        self.set_status("DELETED")
        with self.assertRaises(Http404):
            self.request()

    def test_preview_modes_limits_and_no_persistent_side_effects(self):
        before = ExportJob.objects.count()
        with patch("apps.exports.tasks.generate_export_job.apply_async") as send:
            for mode in ("WORK", "FINAL"):
                response = self.client.get(self.url("exports:preview"), {"style_template": self.style.pk, "export_mode": mode})
                self.assertEqual(response.status_code, 200)
                result = response.context["preview_result"]
                self.assertEqual(result.excluded_scene_count, 1 if mode == "FINAL" else 0)
            with override_settings(EXPORT_PREVIEW_MAX_NODES=4, EXPORT_PREVIEW_MAX_WORDS=1):
                response = self.client.get(self.url("exports:preview"))
                result = response.context["preview_result"]
                self.assertTrue(result.truncated)
                self.assertLessEqual(result.node_count, 4)
                self.assertLessEqual(result.word_count, 1)
        send.assert_not_called()
        self.assertEqual(ExportJob.objects.count(), before)
        self.assertFalse(ExportSnapshot.objects.exists())

    def test_preview_final_without_final_is_clear_validation(self):
        response = self.client.get(self.url("exports:preview"), {"style_template": self.style.pk, "export_mode": "FINAL", "root_node": self.scene2.pk})
        self.assertContains(response, "No hay escenas")
        self.assertIsNone(response.context["preview_result"])

    def test_historical_download_survives_and_is_never_regenerated(self):
        self.job.file.save("legacy.html", ContentFile(b"Original historical file"), save=False)
        self.job.status = "READY"
        self.job.save()
        before = self.job.finished_at
        generate_export_job.run(self.job.pk)
        response = self.client.get(self.url("exports:download", export_pk=self.job.pk))
        self.assertEqual(b"".join(response.streaming_content), b"Original historical file")
        self.job.refresh_from_db()
        self.assertEqual(self.job.finished_at, before)
        self.assertFalse(ExportSnapshot.objects.exists())
        with self.assertRaises(ValidationError):
            retry_export(self.job, user=self.user)
        with self.assertRaises(ValidationError):
            build_export_html(self.job)

    def test_legacy_pending_job_fails_without_reading_live_content(self):
        with patch("apps.exports.tasks.build_export_html") as render:
            generate_export_job.run(self.job.pk)
        render.assert_not_called()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "FAILED")
        self.assertFalse(ExportSnapshot.objects.exists())

    def test_retry_requires_post_csrf_and_owner(self):
        from django.test import Client

        job = self.request()
        url = self.url("exports:retry", export_pk=job.pk)
        self.assertEqual(self.client.get(url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(url).status_code, 403)
