from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Barrier, Event
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.characters.models import Character, CharacterMention
from apps.exports.job_services import request_export
from apps.exports.snapshots import get_export_document
from apps.notes.models import Note
from apps.projects.models import Project
from apps.references.services import attach_reference, create_reference
from apps.styles.models import StyleTemplate

from .models import ManuscriptNode, SceneVersion
from .services import move_node
from .trash import restore_node, soft_delete_node
from .version_services import get_current_draft_version, update_scene_version


@skipUnlessDBFeature("has_select_for_update")
class TrashConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="trash-race@example.test")
        self.project = Project.objects.create(user=self.user, name="Trash race")
        self.book = ManuscriptNode.objects.create(project=self.project, title="Book")
        self.chapter = ManuscriptNode.objects.create(project=self.project, parent=self.book, node_type="CHAPTER", title="Chapter")
        self.target = ManuscriptNode.objects.create(project=self.project, parent=self.book, node_type="CHAPTER", title="Target")
        self.scene = ManuscriptNode.objects.create(project=self.project, parent=self.chapter, node_type="SCENE", content="Original")
        self.draft = get_current_draft_version(self.scene)
        self.versions = list(SceneVersion.objects.values())
        self.enterContext(patch("apps.exports.job_services.enqueue_export"))

    def connected(self, operation):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout TO '8s'")
            return operation()
        finally:
            connections.close_all()

    def ordered(self, first, second):
        started = Event()
        def waiting():
            started.set()
            return second()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Project.objects.select_for_update().get(pk=self.project.pk)
                future = pool.submit(self.connected, waiting)
                self.assertTrue(started.wait(5))
                with self.assertRaises(TimeoutError):
                    future.result(0.2)
                first_result = first()
            return first_result, future.result(15)

    def remove(self):
        return soft_delete_node(self.chapter, user=self.user)

    def test_waiting_editor_rechecks_visibility(self):
        with self.assertRaises(ValidationError):
            self.ordered(self.remove, lambda: update_scene_version(self.scene, self.draft, user=self.user,
                expected_revision=self.draft.revision, content="Lost edit"))
        self.assertEqual(list(SceneVersion.objects.values()), self.versions)

    def test_waiting_move_rechecks_visibility(self):
        with self.assertRaises(ValidationError):
            self.ordered(self.remove, lambda: move_node(self.scene, self.target, user=self.user))
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.parent_id, self.chapter.pk)

    def test_waiting_note_rechecks_visibility(self):
        with self.assertRaises(ValidationError):
            self.ordered(self.remove, lambda: Note.objects.create(project=self.project, node=self.scene, title="Note"))
        self.assertFalse(Note.objects.exists())

    def test_waiting_mention_rechecks_visibility(self):
        character = Character.objects.create(project=self.project, name="Name")
        with self.assertRaises(ValidationError):
            self.ordered(self.remove, lambda: CharacterMention.objects.create(character=character, node=self.scene, mention_type="APPEARS"))
        self.assertFalse(CharacterMention.objects.exists())

    def test_waiting_reference_rechecks_visibility(self):
        ref = create_reference(self.project, user=self.user, title="Source", material_type="BIBLIOGRAPHY")
        with self.assertRaises(ValidationError):
            self.ordered(self.remove, lambda: attach_reference(ref, self.scene, user=self.user))
        self.assertFalse(ref.associations.exists())

    def test_waiting_restore_rechecks_project_status(self):
        self.remove()
        with self.assertRaises(PermissionDenied):
            self.ordered(lambda: Project.objects.filter(pk=self.project.pk).update(status="FROZEN"),
                         lambda: restore_node(self.chapter, user=self.user))
        self.chapter.refresh_from_db()
        self.assertIsNotNone(self.chapter.deleted_at)

    def test_double_restore_is_idempotent(self):
        self.remove()
        barrier = Barrier(2)
        def restore():
            barrier.wait(5)
            return restore_node(self.chapter, user=self.user).pk
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.connected, restore) for _ in range(2)]
            self.assertEqual([future.result(15) for future in futures], [self.chapter.pk] * 2)
        self.assertEqual(list(SceneVersion.objects.values()), self.versions)
        self.assertEqual(ManuscriptNode.objects.filter(project=self.project).visible().count(), 4)

    def capture(self):
        style = StyleTemplate.objects.create(is_system=True, name="Trash style")
        return request_export(user=self.user, project=self.project, style_template=style, request_key=uuid4())

    def test_snapshot_before_deletion_keeps_original_text(self):
        job, _ = self.ordered(self.capture, self.remove)
        self.assertIn(self.scene.pk, {node.node_id for node in get_export_document(job).nodes})

    def test_snapshot_after_deletion_excludes_subtree(self):
        _, job = self.ordered(self.remove, self.capture)
        self.assertNotIn(self.scene.pk, {node.node_id for node in get_export_document(job).nodes})
