from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class HierarchyMigrationTests(TransactionTestCase):
    def test_additive_migration_preserves_legacy_ids_text_and_references(self):
        # Only the isolated test database is migrated backwards to exercise the old schema.
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        old = [target for target in latest if target[0] not in ("manuscripts", "exports", "references")] + [
            ("manuscripts", "0001_initial"), ("exports", "0002_exportjob_enqueued_at_exportjob_export_mode_and_more")]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        apps = executor.loader.project_state(old).apps
        User = apps.get_model("accounts", "User")
        Project = apps.get_model("projects", "Project")
        Node = apps.get_model("manuscripts", "ManuscriptNode")
        Note = apps.get_model("notes", "Note")
        Character = apps.get_model("characters", "Character")
        Mention = apps.get_model("characters", "CharacterMention")
        Style = apps.get_model("styles", "StyleTemplate")
        Job = apps.get_model("exports", "ExportJob")
        user = User.objects.create(email="migration@example.test", password="!")
        project = Project.objects.create(user=user, name="Legacy project")
        fragment = Node.objects.create(project=project, node_type="FRAGMENT", title="Old fragment", position=42,
                                       content="  Texto exacto: niña.\r\n\t", word_count=77, status="REVIEW", is_publishable=True)
        note = Note.objects.create(project=project, node=fragment, title="Note")
        character = Character.objects.create(project=project, name="Character")
        mention = Mention.objects.create(character=character, node=fragment, mention_type="APPEARS")
        style = Style.objects.create(is_system=True, name="System")
        job = Job.objects.create(user=user, project=project, root_node=fragment, style_template=style, status="DONE", file="historic.html")
        before = Node.objects.values().get(pk=fragment.pk)
        MigrationExecutor(connection).migrate(latest)
        apps = MigrationExecutor(connection).loader.project_state(latest).apps
        after = apps.get_model("manuscripts", "ManuscriptNode").objects.values().get(pk=fragment.pk)
        self.assertEqual(after.pop("short_description"), "")
        self.assertIsNone(after.pop("current_draft_version_id"))
        self.assertIsNone(after.pop("deleted_at"))
        self.assertIsNone(after.pop("deleted_by_id"))
        self.assertEqual(after, before)
        self.assertEqual(apps.get_model("notes", "Note").objects.get(pk=note.pk).node_id, fragment.pk)
        self.assertEqual(apps.get_model("characters", "CharacterMention").objects.get(pk=mention.pk).node_id, fragment.pk)
        self.assertEqual(apps.get_model("exports", "ExportJob").objects.get(pk=job.pk).root_node_id, fragment.pk)
        self.assertEqual(apps.get_model("exports", "ExportJob").objects.get(pk=job.pk).file.name, "historic.html")
