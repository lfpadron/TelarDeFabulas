from django.db import connection
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class TrashMigrationTests(TransactionTestCase):
    def test_additive_migration_preserves_nodes_versions_and_links_and_protects_reverse(self):
        self.assertTrue(connection.settings_dict["NAME"].startswith("test_"))
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old = [target for target in latest if target[0] != "manuscripts"] + [("manuscripts", "0004_import_scene_versions")]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor.migrate(old)
        apps = executor.loader.project_state(old).apps
        User = apps.get_model("accounts", "User")
        Project = apps.get_model("projects", "Project")
        Node = apps.get_model("manuscripts", "ManuscriptNode")
        Version = apps.get_model("manuscripts", "SceneVersion")
        user = User.objects.create(email="trash-migration@example.test", password="!")
        project = Project.objects.create(user=user, name="Original")
        book = Node.objects.create(project=project, title="Book", node_type="BOOK", position=1)
        chapter = Node.objects.create(project=project, parent=book, title="Chapter", node_type="CHAPTER", position=1)
        scene = Node.objects.create(project=project, parent=chapter, node_type="SCENE", content="Legacy\r\n", position=1)
        version = Version.objects.create(scene=scene, version_number=9, content="  exact\r\n\t", editorial_stage="DRAFT", revision=7)
        Node.objects.filter(pk=scene.pk).update(current_draft_version=version)
        character = apps.get_model("characters", "Character").objects.create(project=project, name="Character")
        apps.get_model("notes", "Note").objects.create(project=project, node=scene, title="Note")
        apps.get_model("characters", "CharacterMention").objects.create(character=character, node=scene, mention_type="APPEARS")
        labels = ["manuscripts.ManuscriptNode", "manuscripts.SceneVersion", "notes.Note", "characters.CharacterMention"]
        before = {label: list(apps.get_model(label).objects.order_by("pk").values()) for label in labels}
        MigrationExecutor(connection).migrate(latest)
        current_apps = MigrationExecutor(connection).loader.project_state(latest).apps
        for label in labels:
            after = list(current_apps.get_model(label).objects.order_by("pk").values())
            if label == "manuscripts.ManuscriptNode":
                for row in after:
                    self.assertIsNone(row.pop("deleted_at"))
                    self.assertIsNone(row.pop("deleted_by_id"))
            self.assertEqual(after, before[label])
        CurrentNode = current_apps.get_model("manuscripts", "ManuscriptNode")
        CurrentNode.objects.filter(pk=scene.pk).update(deleted_at=timezone.now(), deleted_by_id=user.pk)
        with self.assertRaises(IrreversibleError):
            MigrationExecutor(connection).migrate(old)
        self.assertTrue(CurrentNode.objects.filter(pk=scene.pk, deleted_at__isnull=False).exists())
