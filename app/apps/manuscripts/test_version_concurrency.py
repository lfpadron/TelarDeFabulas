from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Barrier, Event

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.projects.models import Project

from .models import ManuscriptNode
from .services import move_node
from .version_services import RevisionConflict, create_scene_version, finalize_scene_version, get_current_draft_version, restore_scene_version, update_scene_version


@skipUnlessDBFeature("has_select_for_update")
class SceneVersionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="version-race@example.test")
        self.project = Project.objects.create(user=self.user, name="Version races")
        self.book = ManuscriptNode.objects.create(project=self.project, title="Book")
        self.chapter = ManuscriptNode.objects.create(project=self.project, parent=self.book, node_type="CHAPTER", title="Chapter")
        self.scene = ManuscriptNode.objects.create(project=self.project, parent=self.chapter, node_type="SCENE", content="Original text")
        self.v1 = get_current_draft_version(self.scene)

    def connection_call(self, operation, barrier=None):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout TO '5s'")
            if barrier:
                barrier.wait(timeout=10)
            try:
                return operation()
            except RevisionConflict:
                return "conflict"
        finally:
            connections.close_all()

    def race(self, *operations):
        barrier = Barrier(len(operations))
        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            futures = [pool.submit(self.connection_call, operation, barrier) for operation in operations]
            return [future.result(timeout=20) for future in futures]

    def create(self):
        return create_scene_version(self.scene, user=self.user).version_number

    def edit(self, text):
        update_scene_version(self.scene, self.v1, user=self.user, expected_revision=1, content=text)
        return "saved"

    def finalize(self, version=None):
        finalize_scene_version(self.scene, version or self.v1, user=self.user, expected_revision=1)
        return "finalized"

    def test_concurrent_number_allocation_is_unique(self):
        self.assertEqual(sorted(self.race(self.create, self.create)), [2, 3])
        self.assertEqual(get_current_draft_version(self.scene).version_number, 3)

    def test_two_editors_with_same_revision_have_one_winner(self):
        self.assertCountEqual(self.race(lambda: self.edit("First"), lambda: self.edit("Second")), ["saved", "conflict"])
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.revision, 2)
        self.assertIn(self.v1.content, ("First", "Second"))

    def test_two_finalizations_preserve_both_historical_finals(self):
        second = create_scene_version(self.scene, user=self.user, content="Second final")
        self.race(self.finalize, lambda: self.finalize(second))
        self.assertEqual(self.scene.versions.filter(is_current_final=True).count(), 1)
        self.assertEqual(self.scene.versions.filter(editorial_stage="FINAL").count(), 2)
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.content, "Original text")

    def test_edit_vs_finalize_never_overwrites_final(self):
        outcomes = self.race(lambda: self.edit("New draft"), self.finalize)
        self.assertIn("conflict", outcomes)
        self.v1.refresh_from_db()
        if "finalized" in outcomes:
            self.assertEqual((self.v1.editorial_stage, self.v1.content), ("FINAL", "Original text"))
        else:
            self.assertEqual((self.v1.editorial_stage, self.v1.content), ("DRAFT", "New draft"))

    def test_concurrent_restores_create_distinct_copies(self):
        final = finalize_scene_version(self.scene, self.v1, user=self.user, expected_revision=1)
        def restore():
            return restore_scene_version(self.scene, final, user=self.user, expected_revision=final.revision).version_number
        self.assertEqual(sorted(self.race(restore, restore)), [2, 3])
        self.assertEqual(self.scene.versions.filter(content="Original text").count(), 3)
        self.assertEqual(self.scene.versions.filter(is_current_final=True).count(), 1)

    def test_create_draft_vs_finalize_preserves_independent_pointers(self):
        self.race(self.create, self.finalize)
        self.assertEqual(get_current_draft_version(self.scene).version_number, 2)
        self.assertEqual(self.scene.versions.get(is_current_final=True).pk, self.v1.pk)

    def test_move_vs_edit_preserves_version_identity(self):
        chapter = ManuscriptNode.objects.create(project=self.project, parent=self.book, node_type="CHAPTER", title="Destination")
        self.race(lambda: move_node(self.scene, chapter, user=self.user), lambda: self.edit("Concurrent draft"))
        self.scene.refresh_from_db()
        self.v1.refresh_from_db()
        self.assertEqual(self.scene.parent_id, chapter.pk)
        self.assertEqual(self.v1.scene_id, self.scene.pk)
        self.assertEqual(self.v1.content, "Concurrent draft")

    def test_waiting_editor_rechecks_frozen_project(self):
        started = Event()
        def edit():
            started.set()
            return self.edit("Blocked draft")
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Project.objects.select_for_update().get(pk=self.project.pk)
                future = pool.submit(self.connection_call, edit)
                self.assertTrue(started.wait(timeout=5))
                with self.assertRaises(TimeoutError):
                    future.result(timeout=0.2)
                Project.objects.filter(pk=self.project.pk).update(status="FROZEN")
            with self.assertRaises(PermissionDenied):
                future.result(timeout=10)
        self.v1.refresh_from_db()
        self.assertEqual((self.v1.content, self.v1.revision), ("Original text", 1))
