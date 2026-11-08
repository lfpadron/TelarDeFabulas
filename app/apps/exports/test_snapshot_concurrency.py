import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections, transaction
from django.http import Http404
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature

from apps.manuscripts.models import ManuscriptNode
from apps.manuscripts.services import move_node
from apps.manuscripts.version_services import get_current_draft_version, update_scene_version
from apps.projects.models import Project
from apps.styles.models import StyleTemplate

from .job_services import request_export
from .models import ExportJob, ExportSnapshot
from .snapshots import build_manifest, get_export_document
from .tasks import generate_export_job


@skipUnlessDBFeature("has_select_for_update")
class ExportSnapshotConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="snapshot-concurrency@example.test")
        self.project = Project.objects.create(user=self.user, name="Concurrent export")
        self.book = ManuscriptNode.objects.create(project=self.project, title="Book")
        self.chapter = ManuscriptNode.objects.create(project=self.project, parent=self.book, node_type="CHAPTER", title="First chapter")
        self.other_chapter = ManuscriptNode.objects.create(project=self.project, parent=self.book, node_type="CHAPTER", title="Other chapter")
        self.scene = ManuscriptNode.objects.create(project=self.project, parent=self.chapter, node_type="SCENE", title="Scene", content="Original text")
        self.style = StyleTemplate.objects.create(is_system=True, name="Original style")
        self.enterContext(patch("apps.exports.job_services.enqueue_export"))
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        self.enterContext(override_settings(MEDIA_ROOT=media))

    def request(self, **overrides):
        return request_export(**{"user": self.user, "project": self.project, "style_template": self.style,
                                 "request_key": uuid4(), **overrides})

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

    def simultaneous(self, first, second):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.connected, op, barrier) for op in (first, second)]
            return [future.result(timeout=20) for future in futures]

    def snapshot_before_writer(self, writer):
        captured, release, writer_started = Event(), Event(), Event()

        def paused_capture(*args, **kwargs):
            captured.set()
            if not release.wait(timeout=10):
                raise RuntimeError("Test synchronization timed out")
            return build_manifest(*args, **kwargs)

        def write():
            writer_started.set()
            return writer()

        with patch("apps.exports.job_services.build_manifest", side_effect=paused_capture), ThreadPoolExecutor(max_workers=2) as pool:
            snapshot = pool.submit(self.connected, self.request)
            self.assertTrue(captured.wait(timeout=10))
            future = pool.submit(self.connected, write)
            try:
                self.assertTrue(writer_started.wait(timeout=5))
                with self.assertRaises(TimeoutError):
                    future.result(timeout=0.25)
            finally:
                release.set()
            job = snapshot.result(timeout=15)
            future.result(timeout=15)
        return get_export_document(job)

    def test_edit_waits_for_snapshot_and_snapshot_has_original_text(self):
        version = get_current_draft_version(self.scene)
        document = self.snapshot_before_writer(lambda: update_scene_version(
            self.scene, version, user=self.user, expected_revision=version.revision, content="Later edit"))
        self.assertEqual(next(n for n in document.nodes if n.node_id == self.scene.pk).content, "Original text")
        version.refresh_from_db()
        self.assertEqual(version.content, "Later edit")

    def test_move_waits_for_snapshot_and_snapshot_has_original_parent_and_order(self):
        document = self.snapshot_before_writer(lambda: move_node(self.scene, self.other_chapter))
        self.assertEqual(next(n for n in document.nodes if n.node_id == self.scene.pk).parent_id, self.chapter.pk)
        self.assertLess([n.node_id for n in document.nodes].index(self.scene.pk), [n.node_id for n in document.nodes].index(self.other_chapter.pk))
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.parent_id, self.other_chapter.pk)

    def test_style_update_waits_for_snapshot_and_copies_original_settings(self):
        def update_style():
            style = StyleTemplate.objects.get(pk=self.style.pk)
            style.name, style.body_size = "Changed style", 19
            style.save()
        document = self.snapshot_before_writer(update_style)
        self.assertEqual(document.style.name, "Original style")
        self.assertEqual(document.style.body_size, str(self.style.body_size))

    def test_snapshot_waits_for_in_progress_style_change(self):
        started = Event()
        def request():
            started.set()
            return self.request()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                style = StyleTemplate.objects.select_for_update().get(pk=self.style.pk)
                future = pool.submit(self.connected, request)
                self.assertTrue(started.wait(timeout=5))
                with self.assertRaises(TimeoutError):
                    future.result(timeout=0.25)
                style.name, style.body_size = "Committed style", 18
                style.save()
            document = get_export_document(future.result(timeout=10))
        self.assertEqual((document.style.name, document.style.body_size), ("Committed style", "18.00"))

    def test_simultaneous_requests_create_independent_complete_snapshots(self):
        jobs = self.simultaneous(self.request, self.request)
        self.assertNotEqual(jobs[0].pk, jobs[1].pk)
        self.assertEqual(ExportSnapshot.objects.count(), 2)
        self.assertEqual(jobs[0].snapshot.checksum, jobs[1].snapshot.checksum)

    def test_repeated_request_key_concurrently_creates_one_job(self):
        key = uuid4()
        jobs = self.simultaneous(lambda: self.request(request_key=key), lambda: self.request(request_key=key))
        self.assertEqual(jobs[0].pk, jobs[1].pk)
        self.assertEqual(ExportJob.objects.count(), 1)
        self.assertEqual(ExportSnapshot.objects.count(), 1)

    def test_duplicate_task_does_not_render_or_write_twice(self):
        job = self.request()
        started, release = Event(), Event()
        def render(*args, **kwargs):
            started.set()
            if not release.wait(timeout=10):
                raise RuntimeError("Test synchronization timed out")
            return "<html>Original</html>"
        with patch("apps.exports.tasks.build_export_html", side_effect=render) as builder, ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.connected, lambda: generate_export_job.run(job.pk))
            self.assertTrue(started.wait(timeout=5))
            second = pool.submit(self.connected, lambda: generate_export_job.run(job.pk))
            try:
                second.result(timeout=5)
            finally:
                release.set()
            first.result(timeout=10)
        builder.assert_called_once()
        job.refresh_from_db()
        self.assertEqual(job.status, "READY")
        self.assertTrue(job.file)

    def test_waiting_snapshot_rechecks_deleted_project_after_lock(self):
        started = Event()
        def request():
            started.set()
            return self.request()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Project.objects.select_for_update().get(pk=self.project.pk)
                future = pool.submit(self.connected, request)
                self.assertTrue(started.wait(timeout=5))
                with self.assertRaises(TimeoutError):
                    future.result(timeout=0.25)
                Project.objects.filter(pk=self.project.pk).update(status="DELETED")
            with self.assertRaises(Http404):
                future.result(timeout=10)
        self.assertFalse(ExportJob.objects.exists())
