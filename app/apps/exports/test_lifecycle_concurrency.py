import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from apps.manuscripts.models import ManuscriptNode
from apps.projects.models import Project
from apps.styles.models import StyleTemplate

from .files import acquire_download_lock, remove_artifacts
from .job_services import request_export, retry_export
from .lifecycle import claim_export, delete_export, heartbeat, publish_export, recover_job
from .models import ExportJob
from .notifications import send_notification
from .tasks import Heartbeat, generate_export_job, recover_exports


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ExportLifecycleConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="lifecycle-concurrency@example.test")
        self.project = Project.objects.create(user=self.user, name="Concurrent")
        book = ManuscriptNode.objects.create(project=self.project, title="Book")
        chapter = ManuscriptNode.objects.create(project=self.project, parent=book, title="Chapter", node_type="CHAPTER")
        ManuscriptNode.objects.create(project=self.project, parent=chapter, title="Scene", node_type="SCENE", content="Private story")
        self.style = StyleTemplate.objects.create(name="Style", is_system=True)
        self.enterContext(patch("apps.exports.job_services.enqueue_export"))
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.enterContext(override_settings(MEDIA_ROOT=self.media))
        self.job = request_export(user=self.user, project=self.project, style_template=self.style,
                                  export_format="MARKDOWN", request_key=uuid4())

    def connected(self, operation, barrier=None):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout TO '8s'")
            if barrier:
                barrier.wait(timeout=10)
            return operation()
        finally:
            connections.close_all()

    def simultaneous(self, *operations):
        barrier = Barrier(len(operations))
        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            futures = [pool.submit(self.connected, op, barrier) for op in operations]
            return [future.result(timeout=20) for future in futures]

    def test_atomic_claim_two_connections(self):
        results = self.simultaneous(lambda: claim_export(self.job.pk), lambda: claim_export(self.job.pk))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.job.attempts.count(), 1)

    def test_duplicate_workers_render_once(self):
        entered, release = Event(), Event()
        def render(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Test timeout")
            return "result"
        with patch("apps.exports.tasks.build_export_markdown", side_effect=render) as builder, ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.connected, lambda: generate_export_job.run(self.job.pk))
            self.assertTrue(entered.wait(5))
            try:
                pool.submit(self.connected, lambda: generate_export_job.run(self.job.pk)).result(5)
            finally:
                release.set()
            first.result(10)
        builder.assert_called_once()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "READY")

    def test_two_recoverers_schedule_single_retry(self):
        claim_export(self.job.pk)
        ExportJob.objects.filter(pk=self.job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        self.simultaneous(lambda: recover_job(self.job.pk), lambda: recover_job(self.job.pk))
        self.assertEqual(self.job.events.filter(code="lease_expired").count(), 1)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "FAILED")
        ExportJob.objects.filter(pk=self.job.pk).update(next_attempt_at=timezone.now() - timedelta(seconds=1))
        self.simultaneous(lambda: recover_job(self.job.pk), lambda: recover_job(self.job.pk))
        self.assertEqual(self.job.events.filter(code="retry_requested").count(), 1)

    def test_cancellation_races_claim_safely(self):
        def cancel():
            try:
                return delete_export(self.job.pk, user=self.user)
            except ValidationError:
                return False
        results = self.simultaneous(lambda: claim_export(self.job.pk), cancel)
        self.job.refresh_from_db()
        self.assertIn(self.job.status, ("PROCESSING", "DELETED"))
        if self.job.status == "DELETED":
            self.assertIsNone(results[0])
            self.assertFalse(self.job.attempts.exists())
        else:
            self.assertFalse(results[1])

    def test_heartbeat_thread_really_renews(self):
        job = claim_export(self.job.pk)
        signaled = Event()
        def pulse(*args):
            result = heartbeat(*args)
            signaled.set()
            return result
        with override_settings(EXPORT_STALE_MINUTES=0.03), patch("apps.exports.tasks.heartbeat", side_effect=pulse):
            with Heartbeat(job):
                self.assertTrue(signaled.wait(5))
        job.refresh_from_db()
        self.assertGreater(job.last_heartbeat_at, job.started_at)

    def test_notification_parallel_delivery_is_deduplicated(self):
        generate_export_job.run(self.job.pk)
        notice = self.job.notifications.get()
        with patch("apps.exports.notifications.EmailMessage.send", return_value=1) as send:
            result = self.simultaneous(lambda: send_notification(notice.pk), lambda: send_notification(notice.pk))
        self.assertEqual(sorted(result), [False, True])
        send.assert_called_once()

    def test_cleaner_waits_for_other_connection_download(self):
        generate_export_job.run(self.job.pk)
        lease = acquire_download_lock(self.job.pk)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertFalse(pool.submit(self.connected, lambda: delete_export(self.job.pk, user=self.user)).result(10))
            self.job.refresh_from_db()
            self.assertEqual(self.job.status, "READY")
            self.assertFalse(self.job.downloadable)
        finally:
            lease.close()
        self.assertTrue(delete_export(self.job.pk, user=self.user))

    def test_old_worker_cannot_publish_after_new_attempt(self):
        first = claim_export(self.job.pk)
        ExportJob.objects.filter(pk=self.job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        recover_job(self.job.pk)
        retry_export(self.job, user=self.user)
        second = claim_export(self.job.pk)
        results = self.simultaneous(lambda: publish_export(self.job.pk, first.execution_token, b"old"),
                                    lambda: publish_export(self.job.pk, second.execution_token, b"new"))
        self.assertEqual(results, [False, True])
        self.job.refresh_from_db()
        with self.job.file.open("rb") as output:
            self.assertEqual(output.read(), b"new")

    def test_cleanup_crash_keeps_committed_tombstone(self):
        generate_export_job.run(self.job.pk)
        def crash_after_unlink(job):
            remove_artifacts(job)
            raise SystemExit("Simulated cleanup process loss")
        with patch("apps.exports.lifecycle.remove_artifacts", side_effect=crash_after_unlink):
            with self.assertRaises(SystemExit):
                delete_export(self.job.pk, user=self.user)
        self.job.refresh_from_db()
        self.assertIsNotNone(self.job.deletion_requested_at)
        self.assertEqual(self.job.status, "READY")
        self.assertFalse(self.job.downloadable)
        recover_exports.run()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "DELETED")
