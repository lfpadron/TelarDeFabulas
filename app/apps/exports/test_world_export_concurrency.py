from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

from django.db import close_old_connections, connection, connections, transaction
from django.http import Http404
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.geography.services import move_location
from apps.organizations.services import move_organization
from apps.projects.models import Project

from .models import ExportJob, ExportSnapshot
from .world_exports import build_world_manifest
from .world_test_helpers import WorldExportFixture


@skipUnlessDBFeature("has_select_for_update")
class WorldExportConcurrencyTests(WorldExportFixture, TransactionTestCase):
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

    def capture_before_writer(self, writer):
        captured, release, writer_started = Event(), Event(), Event()

        def paused_capture(*args, **kwargs):
            captured.set()
            if not release.wait(timeout=10):
                raise RuntimeError("Test synchronization timed out")
            return build_world_manifest(*args, **kwargs)

        def write():
            writer_started.set()
            return writer()

        with patch("apps.exports.job_services.build_world_manifest", side_effect=paused_capture), ThreadPoolExecutor(max_workers=2) as pool:
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
        return job

    def change(self, obj, field, value):
        setattr(obj, field, value)
        obj.save()

    def test_character_edit_serializes_with_capture(self):
        job = self.capture_before_writer(lambda: self.change(self.ada, "biography", "AFTER"))
        self.assertIn("BIO ORIGINAL", self.contents(job))
        self.assertNotIn("AFTER", self.contents(job))

    def test_relationship_edit_serializes_with_capture(self):
        job = self.capture_before_writer(lambda: self.change(self.relation, "description", "AFTER"))
        self.assertIn("RELATION ORIGINAL", self.contents(job))

    def test_membership_edit_serializes_with_capture(self):
        job = self.capture_before_writer(lambda: self.change(self.membership, "description", "AFTER"))
        self.assertIn("MEMBERSHIP ORIGINAL", self.contents(job))

    def test_geography_move_serializes_with_capture(self):
        job = self.capture_before_writer(lambda: move_location(self.city, None))
        self.assertEqual(self.sections(job, "GEOGRAPHIC_LOCATION")[1].parent_id, self.country.pk)

    def test_organization_move_serializes_with_capture(self):
        job = self.capture_before_writer(lambda: move_organization(self.branch, None))
        self.assertEqual(self.sections(job, "ORGANIZATION")[1].parent_id, self.guild.pk)

    def test_reference_edit_serializes_with_capture(self):
        job = self.capture_before_writer(lambda: self.change(self.reference, "notes", "AFTER"))
        self.assertIn("REFERENCE ORIGINAL", self.contents(job))

    def test_worldbuilding_edit_serializes_with_capture(self):
        job = self.capture_before_writer(lambda: self.change(self.politics, "content", "AFTER"))
        self.assertIn("FIRST PARAGRAPH", self.contents(job))

    def test_style_edit_serializes_with_capture(self):
        job = self.capture_before_writer(lambda: self.change(self.style, "name", "AFTER"))
        self.assertEqual(job.snapshot.style_name, "Original style")

    def test_entity_deletion_serializes_with_capture(self):
        job = self.capture_before_writer(self.ben.delete)
        self.assertIn("BEN ORIGINAL", self.contents(job))

    def test_repeated_key_creates_one_complete_snapshot(self):
        barrier, key = Barrier(2), uuid4()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.connected, lambda: self.request(request_key=key), barrier) for _ in range(2)]
            jobs = [future.result(timeout=20) for future in futures]
        self.assertEqual(jobs[0].pk, jobs[1].pk)
        self.assertEqual(ExportSnapshot.objects.count(), 1)

    def test_waiting_export_rechecks_project_after_lock(self):
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
