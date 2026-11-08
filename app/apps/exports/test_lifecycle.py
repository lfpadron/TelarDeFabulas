import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.core import mail
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import Client, override_settings
from django.utils import timezone

from apps.core.tests.helpers import SecurityTestCase
from apps.manuscripts.models import ManuscriptNode, SceneVersion
from apps.manuscripts.services import move_node
from apps.manuscripts.version_services import create_scene_version, finalize_scene_version, get_current_draft_version

from .files import acquire_download_lock, attempt_names, private_path
from .forms import ExportJobForm
from .job_services import enqueue_export, request_export, retry_export
from .lifecycle import (TRANSITIONS, backoff, claim_export, delete_export, fail_export,
                        heartbeat, locked_job, publish_export, recover_job, transition)
from .markdown import build_export_markdown, escape_prose
from .models import ExportJob, ExportNotification, ExportSnapshot
from .notifications import send_notification
from .tasks import cleanup_expired_exports, generate_export_job, recover_exports, send_pending_notifications


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ExportLifecycleTests(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.enterContext(override_settings(MEDIA_ROOT=self.media))

    def request(self, **kwargs):
        return request_export(**{"user": self.user, "project": self.project, "style_template": self.style,
                                 "export_format": "MARKDOWN", "request_key": uuid4(), **kwargs})

    def ready(self, **kwargs):
        job = self.request(**kwargs)
        generate_export_job.run(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "READY")
        return job

    def failed(self, *, retryable=False):
        job = self.request()
        claim = claim_export(job.pk)
        fail_export(job.pk, claim.execution_token, retryable=retryable, code="test_failure")
        job.refresh_from_db()
        return job

    def due(self, job):
        ExportJob.objects.filter(pk=job.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))

    def test_requested_defaults(self):
        job = self.request()
        self.assertEqual((job.status, job.attempt_count, job.max_attempts, job.notify_by_email), ("REQUESTED", 0, 3, True))

    def test_all_allowed_transitions_and_audit(self):
        for source, targets in TRANSITIONS.items():
            for target in targets:
                with self.subTest(source=source, target=target), transaction.atomic():
                    job = self.request()
                    job.status = source
                    transition(job, target, "test_transition")
                    self.assertEqual(job.status, target)
                    self.assertEqual(job.events.get().from_status, source)

    def test_all_invalid_transitions(self):
        for source, targets in TRANSITIONS.items():
            for target in TRANSITIONS.keys() - targets:
                with self.subTest(source=source, target=target), transaction.atomic():
                    self.job.status = source
                    with self.assertRaises(ValidationError):
                        transition(self.job, target, "invalid")

    def test_claim_is_unique_and_counted(self):
        job = self.request()
        claim = claim_export(job.pk)
        self.assertEqual(claim.attempt_count, 1)
        self.assertIsNotNone(claim.execution_token)
        self.assertIsNone(claim_export(job.pk))
        self.assertEqual(job.attempts.count(), 1)

    def test_duplicate_task_has_one_file(self):
        job = self.ready()
        before = list(Path(self.media).rglob("*.md"))
        generate_export_job.run(job.pk)
        self.assertEqual(list(Path(self.media).rglob("*.md")), before)
        self.assertEqual(job.attempts.count(), 1)

    def test_live_lease_not_recovered(self):
        job = claim_export(self.request().pk)
        recover_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "PROCESSING")

    def test_heartbeat_renews_only_current_token(self):
        job = claim_export(self.request().pk)
        before = job.lease_expires_at
        self.assertFalse(heartbeat(job.pk, uuid4()))
        self.assertTrue(heartbeat(job.pk, job.execution_token))
        job.refresh_from_db()
        self.assertGreater(job.lease_expires_at, before)

    def test_expired_heartbeat_cannot_resurrect_claim(self):
        job = claim_export(self.request().pk)
        ExportJob.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertFalse(heartbeat(job.pk, job.execution_token))

    def test_crash_recovery_fences_old_worker_and_preserves_snapshot(self):
        job = self.request()
        checksum = job.snapshot.checksum
        first = claim_export(job.pk)
        ExportJob.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        recover_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertFalse(job.notifications.exists())
        self.due(job)
        recover_job(job.pk)
        second = claim_export(job.pk)
        self.assertNotEqual(first.execution_token, second.execution_token)
        self.assertTrue(publish_export(job.pk, second.execution_token, b"NEW RESULT"))
        self.assertFalse(publish_export(job.pk, first.execution_token, b"OLD RESULT"))
        self.assertFalse(fail_export(job.pk, first.execution_token, retryable=False, code="old"))
        job.refresh_from_db()
        self.assertEqual(Path(job.file.path).read_bytes(), b"NEW RESULT")
        self.assertEqual(job.snapshot.checksum, checksum)

    def test_partial_file_removed_before_retry(self):
        job = claim_export(self.request().pk)
        part, final = [private_path(job, name) for name in attempt_names(job, job.execution_token)]
        part.parent.mkdir(parents=True)
        part.write_bytes(b"partial")
        final.write_bytes(b"uncommitted publication")
        ExportJob.objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        recover_job(job.pk)
        self.due(job)
        recover_job(job.pk)
        self.assertFalse(part.exists())
        self.assertFalse(final.exists())
        generate_export_job.run(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "READY")

    def test_failed_task_requires_controlled_retry(self):
        job = self.failed(retryable=True)
        generate_export_job.run(job.pk)
        self.assertEqual(job.attempts.count(), 1)
        retry_export(job, user=self.user)
        generate_export_job.run(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.attempt_count, 2)
        self.assertEqual(job.status, "READY")

    def test_max_attempts_becomes_terminal(self):
        job = self.request()
        ExportJob.objects.filter(pk=job.pk).update(max_attempts=1)
        with patch("apps.exports.tasks.build_export_markdown", side_effect=OSError("secret")):
            generate_export_job.run(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertIsNone(job.next_attempt_at)
        self.assertEqual(job.notifications.count(), 1)
        with self.assertRaises(ValidationError):
            retry_export(job, user=self.user)

    def test_permanent_error_not_retried_or_leaked(self):
        job = self.request()
        with patch("apps.exports.tasks.build_export_markdown", side_effect=ValueError("Private prose. /secret/password")):
            generate_export_job.run(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertFalse(job.retryable)
        self.assertNotIn("secret", job.error_message)
        self.assertEqual(job.notifications.count(), 1)

    def test_missing_snapshot_fails_without_recapture(self):
        generate_export_job.run(self.job.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "FAILED")
        self.assertFalse(ExportSnapshot.objects.filter(export_job=self.job).exists())

    def test_backoff_exponential_and_capped(self):
        self.assertEqual([backoff(n).total_seconds() for n in (1, 2, 3, 999999)], [60, 120, 240, 3600])

    def test_abandoned_requested_dispatched(self):
        job = self.request()
        with patch("apps.exports.tasks.generate_export_job.apply_async") as send, self.captureOnCommitCallbacks(execute=True):
            recover_job(job.pk)
        send.assert_called_once()
        job.refresh_from_db()
        self.assertIsNotNone(job.enqueued_at)
        self.assertIsNotNone(claim_export(job.pk))

    def test_lost_enqueued_message_redispatched(self):
        job = self.request()
        ExportJob.objects.filter(pk=job.pk).update(enqueued_at=timezone.now() - timedelta(days=1))
        with patch("apps.exports.tasks.generate_export_job.apply_async") as send, self.captureOnCommitCallbacks(execute=True):
            recover_job(job.pk)
        send.assert_called_once()

    def test_broker_failure_persists_request_and_backoff(self):
        job = self.request()
        with patch("apps.exports.tasks.generate_export_job.apply_async", side_effect=ConnectionError("secret")):
            enqueue_export(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "REQUESTED")
        self.assertGreater(job.next_attempt_at, timezone.now())
        self.assertEqual(job.attempt_count, 0)
        self.assertNotIn("secret", job.error_message)

    def test_ready_sends_generic_spanish_mail_once(self):
        job = self.ready()
        notice = job.notifications.get()
        self.assertTrue(send_notification(notice.pk))
        self.assertFalse(send_notification(notice.pk))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Tu exportación de Telar de Fábulas está lista")
        self.assertIn(self.url("exports:detail", export_pk=job.pk), mail.outbox[0].body)
        for private in (self.project.name, self.scene.content, self.scene.title, self.style.name, "manifest_json"):
            self.assertNotIn(private, mail.outbox[0].body)
        self.assertFalse(mail.outbox[0].attachments)
        self.client.logout()
        self.assertEqual(self.client.get(self.url("exports:detail", export_pk=job.pk)).status_code, 302)
        job.refresh_from_db()
        self.assertIsNotNone(job.notification_sent_at)

    def test_english_user_receives_english_mail(self):
        self.user.preferred_locale = "en-us"
        self.user.save(update_fields=["preferred_locale"])
        job = self.ready()
        send_notification(job.notifications.get().pk)
        self.assertEqual(mail.outbox[0].subject, "Your Telar de Fábulas export is ready")
        self.assertIn("available until:", mail.outbox[0].body)

    def test_final_failure_mail(self):
        job = self.failed()
        send_notification(job.notifications.get().pk)
        self.assertEqual(mail.outbox[0].subject, "No pudimos completar tu exportación")

    def test_transient_failure_has_no_mail(self):
        job = self.failed(retryable=True)
        self.assertFalse(job.notifications.exists())

    def test_opt_out_has_no_mail(self):
        job = self.ready(notify_by_email=False)
        self.assertFalse(job.notifications.exists())

    def test_smtp_failure_preserves_ready_and_retries(self):
        job = self.ready()
        notice = job.notifications.get()
        with patch("apps.exports.notifications.EmailMessage.send", side_effect=OSError("private smtp host")):
            self.assertFalse(send_notification(notice.pk))
        job.refresh_from_db()
        notice.refresh_from_db()
        self.assertEqual(job.status, "READY")
        self.assertEqual(notice.last_error, "delivery_failed")
        self.assertFalse(send_notification(notice.pk))
        ExportNotification.objects.filter(pk=notice.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(send_notification(notice.pk))

    def test_deleted_export_suppresses_unsent_mail(self):
        job = self.ready()
        notice = job.notifications.get()
        delete_export(job.pk, user=self.user)
        self.assertFalse(send_notification(notice.pk))

    def test_delete_ready_removes_file_snapshot_and_keeps_audit(self):
        job = self.ready()
        path = Path(job.file.path)
        self.assertTrue(delete_export(job.pk, user=self.user))
        job.refresh_from_db()
        self.assertEqual(job.status, "DELETED")
        self.assertIsNotNone(job.deleted_at)
        self.assertFalse(path.exists())
        self.assertFalse(ExportSnapshot.objects.filter(export_job=job).exists())
        self.assertEqual(job.events.last().to_status, "DELETED")
        self.assertEqual(self.client.get(self.url("exports:download", export_pk=job.pk)).status_code, 404)

    def test_delete_failed(self):
        job = self.failed()
        self.assertTrue(delete_export(job.pk, user=self.user))
        job.refresh_from_db()
        self.assertEqual(job.status, "DELETED")

    def test_foreign_user_cannot_delete(self):
        job = self.ready()
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.post(self.url("exports:delete", export_pk=job.pk)).status_code, 404)
        job.refresh_from_db()
        self.assertEqual(job.status, "READY")

    def test_processing_cannot_be_deleted(self):
        job = claim_export(self.request().pk)
        with self.assertRaises(ValidationError):
            delete_export(job.pk, user=self.user)
        job.refresh_from_db()
        self.assertIsNone(job.deletion_requested_at)

    def test_requested_cancel_blocks_late_worker_and_same_request_key(self):
        job = self.request()
        delete_export(job.pk, user=self.user)
        generate_export_job.run(job.pk)
        self.assertFalse(job.attempts.exists())
        with self.assertRaises(ValidationError):
            self.request(request_key=job.request_key)

    def test_delete_uses_post_and_csrf(self):
        job = self.ready()
        url = self.url("exports:delete", export_pk=job.pk)
        self.assertEqual(self.client.get(url).status_code, 405)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(url).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 302)

    def test_delete_waits_for_download(self):
        job = self.ready()
        response = self.client.get(self.url("exports:download", export_pk=job.pk))
        self.assertEqual(response.status_code, 200)
        try:
            self.assertFalse(delete_export(job.pk, user=self.user))
            job.refresh_from_db()
            self.assertEqual(job.status, "READY")
            self.assertTrue(Path(job.file.path).exists())
            self.assertEqual(self.client.get(self.url("exports:download", export_pk=job.pk)).status_code, 404)
            self.assertTrue(b"".join(response.streaming_content))
        finally:
            if not response.closed:
                response.close()
        self.assertTrue(delete_export(job.pk, user=self.user))

    def test_physical_delete_failure_remains_retryable(self):
        job = self.ready()
        with patch("apps.exports.lifecycle.remove_artifacts", side_effect=PermissionError("private path")):
            self.assertFalse(delete_export(job.pk, user=self.user))
        job.refresh_from_db()
        self.assertEqual(job.status, "READY")
        self.assertTrue(job.cleanup_error)
        self.assertFalse(job.downloadable)
        recover_exports.run()
        job.refresh_from_db()
        self.assertEqual(job.status, "DELETED")

    def test_cleanup_preserves_source_data_and_future_jobs(self):
        versions = list(SceneVersion.objects.values())
        before = {key: value for key, value in self.snapshot().items() if key != "exports.ExportJob"}
        expired, future, failed, pending = self.ready(), self.ready(), self.failed(), self.request()
        processing = claim_export(self.request().pk)
        for job in (expired, failed, pending, processing):
            ExportJob.objects.filter(pk=job.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        cleanup_expired_exports.run()
        cleanup_expired_exports.run()
        for job, state in ((expired, "DELETED"), (failed, "DELETED"), (future, "READY"), (pending, "REQUESTED"), (processing, "PROCESSING")):
            job.refresh_from_db()
            self.assertEqual(job.status, state)
        self.assertEqual(versions, list(SceneVersion.objects.values()))
        self.assertEqual(before, {key: value for key, value in self.snapshot().items() if key != "exports.ExportJob"})

    def test_expired_download_blocked_before_daily_cleanup(self):
        job = self.ready()
        ExportJob.objects.filter(pk=job.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get(self.url("exports:download", export_pk=job.pk)).status_code, 404)

    def test_foreign_file_reference_not_deleted(self):
        job = self.ready()
        original = Path(job.file.path)
        ExportJob.objects.filter(pk=job.pk).update(file=f"exports/{self.other_user.pk}/{self.other_project.pk}/private.md")
        self.assertFalse(delete_export(job.pk, user=self.user))
        self.assertTrue(original.exists())

    def test_markdown_hierarchy_plain_text_and_privacy(self):
        job = self.request()
        text = build_export_markdown(job)
        self.assertIn("# Book\n\n## Chapter\n\n### Scene", text)
        self.assertIn("Private prose\\.", text)
        self.assertNotIn("Owner character", text)
        self.assertNotIn("Owner note", text)
        self.assertNotIn("selected_version_id", text)
        self.assertEqual(escape_prose("# title\n\n*not bold* [link](https://x) <script>\\"),
                         "\\# title\n\n\\*not bold\\* \\[link\\]\\(https\\:\\/\\/x\\) \\<script\\>\\\\")

    def test_markdown_work_final_and_frozen_selection(self):
        final = get_current_draft_version(self.scene)
        finalize_scene_version(self.scene, final, user=self.user, expected_revision=final.revision)
        create_scene_version(self.scene, user=self.user, content="New draft")
        work = self.request()
        definitive = self.request(export_mode="FINAL")
        self.assertIn("New draft", build_export_markdown(work))
        self.assertNotIn("New draft", build_export_markdown(definitive))
        self.assertIn("Private prose\\.", build_export_markdown(definitive))
        self.scene.delete()
        self.assertIn("New draft", build_export_markdown(work))

    def test_markdown_download_is_private_attachment(self):
        job = self.ready()
        response = self.client.get(self.url("exports:download", export_pk=job.pk))
        try:
            self.assertEqual(response["Content-Type"], "text/markdown; charset=utf-8")
            self.assertIn("attachment;", response["Content-Disposition"])
            self.assertIn(".md", response["Content-Disposition"])
            self.assertIn("no-store", response["Cache-Control"])
        finally:
            b"".join(response.streaming_content)
        self.client.logout()
        self.assertEqual(self.client.get(self.url("exports:download", export_pk=job.pk)).status_code, 302)

    def test_commercial_formats_and_notify_default(self):
        form = ExportJobForm(user=self.user, project=self.project)
        self.assertEqual([value for value, label in form.fields["format"].choices], ["MARKDOWN", "DOCX", "PDF"])
        self.assertTrue(form["notify_by_email"].value())
        for export_format in ("HTML", "EPUB"):
            response = self.client.post(self.url("exports:create"), {"format": export_format, "style_template": self.style.pk, "request_key": uuid4()})
            self.assertEqual(response.status_code, 200)
            self.assertIn("format", response.context["form"].errors)

    def test_legacy_html_epub_downloads(self):
        for export_format in ("HTML", "EPUB"):
            job = self.ready(export_format=export_format)
            ExportSnapshot.objects.filter(export_job=job).delete()
            response = self.client.get(self.url("exports:download", export_pk=job.pk))
            self.assertEqual(response.status_code, 200)
            b"".join(response.streaming_content)

    def test_atomic_publication_failure_cleans_partial_file(self):
        job = self.request()
        with patch("apps.exports.files.os.replace", side_effect=OSError("storage")):
            generate_export_job.run(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "FAILED")
        self.assertTrue(job.retryable)
        self.assertEqual([p for p in Path(self.media).rglob("*") if p.is_file()], [])
        retry_export(job, user=self.user)
        generate_export_job.run(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, "READY")

    def test_file_referenced_by_another_job_is_not_removed(self):
        job = self.ready()
        another = self.request()
        ExportJob.objects.filter(pk=another.pk).update(file=job.file.name)
        self.assertFalse(delete_export(job.pk, user=self.user))
        self.assertTrue(Path(job.file.path).exists())

    def test_symlink_to_another_private_file_is_rejected(self):
        job = self.ready()
        source = Path(job.file.path)
        link = source.parent / "linked.md"
        link.symlink_to(source)
        ExportJob.objects.filter(pk=job.pk).update(file=str(link.relative_to(self.media)))
        self.assertEqual(self.client.get(self.url("exports:download", export_pk=job.pk)).status_code, 404)
        self.assertFalse(delete_export(job.pk, user=self.user))
        self.assertTrue(source.exists())

    def test_pending_notification_task_and_lost_mail_claim(self):
        job = self.ready()
        notice = job.notifications.get()
        ExportNotification.objects.filter(pk=notice.pk).update(claim_token=uuid4(), lease_expires_at=timezone.now() - timedelta(seconds=1))
        send_pending_notifications.run()
        send_pending_notifications.run()
        self.assertEqual(len(mail.outbox), 1)

    def test_configuration_rejects_invalid_limits(self):
        from config.settings.base import bounded_env_int
        from django.core.exceptions import ImproperlyConfigured
        for value in ("0", "-1", "abc", "11"):
            with patch.dict("os.environ", {"EXPORT_MAX_ATTEMPTS": value}), self.assertRaises(ImproperlyConfigured):
                bounded_env_int("EXPORT_MAX_ATTEMPTS", 3, 10)

    def test_markdown_preserves_work_legacy_container_text_and_indentation(self):
        self.book.content = "    Legacy prose\n\tIndented line"
        self.book.save()
        text = build_export_markdown(self.request())
        self.assertIn("&#32;&#32;&#32;&#32;Legacy prose\n&#9;Indented line", text)

    def test_markdown_part_hierarchy_and_snapshot_order(self):
        part = ManuscriptNode.objects.create(project=self.project, parent=self.book, title="Part", node_type="PART")
        move_node(self.chapter, part)
        second = ManuscriptNode.objects.create(project=self.project, parent=self.chapter, title="Second", node_type="SCENE", content="Second prose")
        job = self.request()
        text = build_export_markdown(job)
        self.assertIn("# Book\n\n## Part\n\n### Chapter\n\n#### Scene", text)
        self.assertLess(text.index("#### Scene"), text.index("#### Second"))
        move_node(second, self.chapter, new_position=1)
        self.assertEqual(build_export_markdown(job), text)
