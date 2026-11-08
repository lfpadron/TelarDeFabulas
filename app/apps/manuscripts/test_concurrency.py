from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Barrier, Event

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.projects.models import Project

from .models import ManuscriptNode
from .services import move_node, move_node_down, move_node_up, normalize_positions
from .version_services import get_current_draft_version, update_scene_version


@skipUnlessDBFeature("has_select_for_update")
class ManuscriptConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="concurrency@example.test")
        self.project = Project.objects.create(user=self.user, name="Concurrent manuscript")
        self.book = ManuscriptNode.objects.create(project=self.project, title="Book")
        self.chapters = [ManuscriptNode.objects.create(project=self.project, parent=self.book, node_type="CHAPTER", title=f"Chapter {index}") for index in range(3)]
        self.scenes = [ManuscriptNode.objects.create(project=self.project, parent=self.chapters[0], node_type="SCENE", title=f"Scene {index}", content=f"Original {index}") for index in range(2)]

    def in_connection(self, operation, barrier=None):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout TO '5s'")
            if barrier:
                barrier.wait(timeout=10)
            return operation()
        finally:
            connections.close_all()

    def simultaneously(self, *operations):
        barrier = Barrier(len(operations))
        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            futures = [pool.submit(self.in_connection, operation, barrier) for operation in operations]
            return [future.result(timeout=20) for future in futures]

    def assert_positions(self):
        groups = {}
        for parent, position in ManuscriptNode.objects.filter(project=self.project).order_by("position").values_list("parent_id", "position"):
            groups.setdefault(parent, []).append(position)
        for positions in groups.values():
            self.assertEqual(positions, list(range(1, len(positions) + 1)))

    def create_scene(self):
        return ManuscriptNode.objects.create(project_id=self.project.pk, parent_id=self.chapters[1].pk, node_type="SCENE", position=1).pk

    def move(self, scene_index, chapter_index):
        node = ManuscriptNode.objects.get(pk=self.scenes[scene_index].pk)
        parent = ManuscriptNode.objects.get(pk=self.chapters[chapter_index].pk)
        return move_node(node, parent, 1).pk

    def test_concurrent_creates_do_not_duplicate_positions(self):
        pks = self.simultaneously(self.create_scene, self.create_scene)
        self.assertEqual(len(set(pks)), 2)
        self.assert_positions()

    def test_concurrent_moves_to_same_parent_preserve_both_nodes(self):
        before = set(ManuscriptNode.objects.values_list("pk", flat=True))
        self.simultaneously(lambda: self.move(0, 1), lambda: self.move(1, 1))
        self.assertEqual(set(ManuscriptNode.objects.values_list("pk", flat=True)), before)
        self.assertEqual(ManuscriptNode.objects.filter(parent=self.chapters[1]).count(), 2)
        self.assert_positions()

    def test_concurrent_create_and_move_are_serialized(self):
        self.simultaneously(self.create_scene, lambda: self.move(0, 1))
        self.assertEqual(ManuscriptNode.objects.filter(parent=self.chapters[1]).count(), 2)
        self.assert_positions()

    def test_concurrent_moves_of_same_scene_leave_one_location(self):
        pk = self.scenes[0].pk
        self.assertEqual(self.simultaneously(lambda: self.move(0, 1), lambda: self.move(0, 2)), [pk, pk])
        self.assertIn(ManuscriptNode.objects.get(pk=pk).parent_id, [self.chapters[1].pk, self.chapters[2].pk])
        self.assert_positions()

    def test_concurrent_up_and_down_do_not_lose_nodes(self):
        self.simultaneously(lambda: move_node_up(ManuscriptNode.objects.get(pk=self.scenes[1].pk)),
                            lambda: move_node_down(ManuscriptNode.objects.get(pk=self.scenes[0].pk)))
        self.assert_positions()
        self.assertEqual(ManuscriptNode.objects.filter(parent=self.chapters[0]).count(), 2)

    def test_text_save_during_move_preserves_new_text_and_location(self):
        stale = ManuscriptNode.objects.get(pk=self.scenes[0].pk)
        version = get_current_draft_version(stale)
        def edit():
            update_scene_version(stale, version, user=self.user, expected_revision=version.revision, content="Concurrent text")
        self.simultaneously(edit, lambda: self.move(0, 1))
        current = ManuscriptNode.objects.get(pk=stale.pk)
        version.refresh_from_db()
        self.assertEqual(version.content, "Concurrent text")
        self.assertEqual(version.word_count, 2)
        self.assertEqual(current.parent_id, self.chapters[1].pk)
        self.assert_positions()

    def test_normalize_and_move_share_project_lock(self):
        self.simultaneously(lambda: normalize_positions(self.project, self.chapters[0]), lambda: self.move(0, 1))
        self.assert_positions()

    def test_waiting_move_rechecks_status_after_project_lock(self):
        started = Event()
        def attempt():
            started.set()
            self.move(0, 1)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Project.objects.select_for_update().get(pk=self.project.pk)
                future = pool.submit(self.in_connection, attempt)
                self.assertTrue(started.wait(timeout=5))
                with self.assertRaises(TimeoutError):
                    future.result(timeout=0.2)
                Project.objects.filter(pk=self.project.pk).update(status="FROZEN")
            with self.assertRaises(ValidationError):
                future.result(timeout=10)
        self.assertEqual(ManuscriptNode.objects.get(pk=self.scenes[0].pk).parent_id, self.chapters[0].pk)
        self.assert_positions()
