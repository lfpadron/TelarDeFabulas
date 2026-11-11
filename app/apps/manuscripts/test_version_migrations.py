import hashlib
from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace

from django.db import connection, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class SceneVersionMigrationTests(TransactionTestCase):
    def setUp(self):
        self.assertTrue(connection.settings_dict["NAME"].startswith("test_"))
        self.latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        self.other_targets = [target for target in self.latest if target[0] not in ("manuscripts", "exports", "references")] + [
            ("exports", "0002_exportjob_enqueued_at_exportjob_export_mode_and_more")]
        old = [*self.other_targets, ("manuscripts", "0002_literary_hierarchy")]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(self.latest))
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        self.old_apps = executor.loader.project_state(old).apps
        User = self.old_apps.get_model("accounts", "User")
        Project = self.old_apps.get_model("projects", "Project")
        Node = self.old_apps.get_model("manuscripts", "ManuscriptNode")
        user = User.objects.create(email="legacy-version@example.test", password="!")
        project = Project.objects.create(user=user, name="Migration fixture", status="FROZEN")
        self.book = Node.objects.create(project=project, title="Book", content="Container text", node_type="BOOK")
        chapter = Node.objects.create(project=project, parent=self.book, title="Chapter", node_type="CHAPTER", content="Chapter text")
        self.scenes = []
        for status in ("PENDING", "IN_PROGRESS", "DRAFT", "REVIEW", "FINISHED", "PUBLISHABLE", "PUBLISHED"):
            self.scenes.append(Node.objects.create(project=project, parent=chapter, node_type="SCENE", title=status,
                                                  content="  Ni\u00f1a, cafe\u0301.\r\n\t", status=status, word_count=777))
        self.empty = Node.objects.create(project=project, parent=chapter, node_type="SCENE", title="", content="")
        self.spaces = Node.objects.create(project=project, parent=chapter, node_type="SCENE", content=" \r\n\t ", status="PUBLISHED")
        self.fragment = Node.objects.create(project=project, parent=chapter, node_type="FRAGMENT", content="Legacy fragment", title="Fragment")
        Node.objects.create(project=project, parent=self.book, node_type="PART", content="Part text", title="Part")
        historical_date = timezone.now() - timedelta(days=30)
        Node.objects.update(created_at=historical_date, updated_at=historical_date)
        self.note = self.old_apps.get_model("notes", "Note").objects.create(project=project, node=self.scenes[0], title="Note")
        character = self.old_apps.get_model("characters", "Character").objects.create(project=project, name="Character")
        self.mention = self.old_apps.get_model("characters", "CharacterMention").objects.create(character=character, node=self.scenes[0], mention_type="APPEARS")
        style = self.old_apps.get_model("styles", "StyleTemplate").objects.create(is_system=True, name="Style")
        self.job = self.old_apps.get_model("exports", "ExportJob").objects.create(project=project, user=user, root_node=self.scenes[0], style_template=style, status="DONE", file="historical.html")
        self.before = {row["id"]: row for row in Node.objects.values()}
        self.migration = import_module("apps.manuscripts.migrations.0004_import_scene_versions")

    def migrate(self):
        MigrationExecutor(connection).migrate(self.latest)
        self.apps = MigrationExecutor(connection).loader.project_state(self.latest).apps
        self.Node = self.apps.get_model("manuscripts", "ManuscriptNode")
        self.Version = self.apps.get_model("manuscripts", "SceneVersion")

    def replay(self):
        with transaction.atomic():
            self.migration.import_scene_versions(self.apps, SimpleNamespace(connection=connection))

    def test_every_scene_gets_exact_content_and_hash(self):
        self.migrate()
        for scene in [*self.scenes, self.empty, self.spaces]:
            version = self.Version.objects.get(scene_id=scene.pk)
            self.assertEqual(version.content, scene.content)
            self.assertEqual(version.legacy_source_hash, hashlib.sha256(scene.content.encode()).hexdigest())
            self.assertEqual(version.version_number, 1)
            self.assertEqual(version.revision, 1)

    def test_all_seven_status_mappings_and_current_pointers(self):
        self.migrate()
        expected = ["DRAFT", "DRAFT", "DRAFT", "REVIEW", "REVIEW", "FINAL", "FINAL"]
        for scene, stage in zip(self.scenes, expected):
            with self.subTest(status=scene.status):
                version = self.Version.objects.get(scene_id=scene.pk)
                current = self.Node.objects.get(pk=scene.pk)
                self.assertEqual(version.editorial_stage, stage)
                self.assertEqual(version.is_current_final, stage == "FINAL")
                self.assertEqual(current.current_draft_version_id, None if stage == "FINAL" else version.pk)

    def test_empty_and_whitespace_scenes_are_not_dropped(self):
        self.migrate()
        self.assertEqual(self.Version.objects.get(scene_id=self.empty.pk).word_count, 0)
        whitespace = self.Version.objects.get(scene_id=self.spaces.pk)
        self.assertEqual(whitespace.content, " \r\n\t ")
        self.assertEqual(whitespace.editorial_stage, "FINAL")

    def test_node_fields_and_non_scene_content_are_unchanged(self):
        self.migrate()
        after = {}
        for row in self.Node.objects.values():
            row.pop("current_draft_version_id")
            self.assertIsNone(row.pop("deleted_at"))
            self.assertIsNone(row.pop("deleted_by_id"))
            after[row["id"]] = row
        self.assertEqual(after, self.before)
        self.assertFalse(self.Version.objects.exclude(scene__node_type="SCENE").exists())

    def test_notes_mentions_and_historical_export_are_unchanged(self):
        self.migrate()
        self.assertEqual(self.apps.get_model("notes", "Note").objects.get(pk=self.note.pk).node_id, self.scenes[0].pk)
        self.assertEqual(self.apps.get_model("characters", "CharacterMention").objects.get(pk=self.mention.pk).node_id, self.scenes[0].pk)
        job = self.apps.get_model("exports", "ExportJob").objects.get(pk=self.job.pk)
        self.assertEqual((job.root_node_id, job.file.name, job.status), (self.scenes[0].pk, "historical.html", "READY"))

    def test_original_timestamps_preserved_and_finalization_is_import_time(self):
        started = timezone.now()
        self.migrate()
        for version in self.Version.objects.all():
            source = self.before[version.scene_id]
            self.assertEqual(version.created_at, source["created_at"])
            self.assertEqual(version.updated_at, source["updated_at"])
            if version.editorial_stage == "FINAL":
                self.assertGreaterEqual(version.finalized_at, started)
        self.assertEqual(self.Node.objects.get(pk=self.scenes[0].pk).word_count, 777)
        self.assertEqual(self.Version.objects.get(scene_id=self.scenes[0].pk).word_count, 2)

    def test_replaying_import_does_not_duplicate_or_overwrite_edits(self):
        self.migrate()
        version = self.Version.objects.get(scene_id=self.scenes[0].pk)
        self.Version.objects.filter(pk=version.pk).update(content="Post-import edition", revision=2)
        before = list(self.Version.objects.order_by("pk").values())
        self.replay()
        self.replay()
        self.assertEqual(list(self.Version.objects.order_by("pk").values()), before)

    def test_existing_non_imported_versions_are_never_replaced(self):
        target = [*self.other_targets, ("manuscripts", "0003_scene_versions")]
        MigrationExecutor(connection).migrate(target)
        apps = MigrationExecutor(connection).loader.project_state(target).apps
        Version = apps.get_model("manuscripts", "SceneVersion")
        existing = Version.objects.create(scene_id=self.scenes[0].pk, version_number=1, content="Independent version")
        apps.get_model("manuscripts", "ManuscriptNode").objects.filter(pk=self.scenes[0].pk).update(current_draft_version_id=existing.pk)
        self.migrate()
        self.assertEqual(self.Version.objects.filter(scene_id=self.scenes[0].pk).count(), 1)
        self.assertEqual(self.Version.objects.get(pk=existing.pk).content, "Independent version")

    def test_unknown_status_aborts_without_partial_copy(self):
        Node = self.old_apps.get_model("manuscripts", "ManuscriptNode")
        Node.objects.filter(pk=self.scenes[-1].pk).update(status="UNKNOWN")
        try:
            with self.assertRaises(RuntimeError):
                self.migrate()
            apps = MigrationExecutor(connection).loader.project_state([*self.other_targets, ("manuscripts", "0003_scene_versions")]).apps
            self.assertEqual(apps.get_model("manuscripts", "SceneVersion").objects.count(), 0)
        finally:
            Node.objects.filter(pk=self.scenes[-1].pk).update(status="PUBLISHED")
            self.migrate()

    def test_changed_legacy_hash_aborts_replay(self):
        self.migrate()
        self.Node.objects.filter(pk=self.scenes[0].pk).update(content="Unexpected legacy edit")
        before = list(self.Version.objects.values())
        with self.assertRaises(RuntimeError):
            self.replay()
        self.assertEqual(list(self.Version.objects.values()), before)

    def test_reverse_refuses_to_discard_history(self):
        self.migrate()
        before = list(self.Version.objects.values())
        with self.assertRaises(IrreversibleError):
            self.migration.reverse_import(self.apps, SimpleNamespace(connection=connection))
        self.assertEqual(list(self.Version.objects.values()), before)
