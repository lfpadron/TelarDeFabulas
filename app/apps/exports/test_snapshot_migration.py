from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ExportSnapshotMigrationTests(TransactionTestCase):
    def test_additive_migration_preserves_historical_job_file_and_status(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        old = [target for target in latest if target[0] != "exports"] + [("exports", "0001_initial")]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        apps = executor.loader.project_state(old).apps
        user = apps.get_model("accounts", "User").objects.create(email="snapshot-migration@example.test", password="!")
        project = apps.get_model("projects", "Project").objects.create(user=user, name="Historical project")
        style = apps.get_model("styles", "StyleTemplate").objects.create(name="Historical style", is_system=True)
        job = apps.get_model("exports", "ExportJob").objects.create(user=user, project=project, style_template=style,
                                                                    file="exports/historical.html", status="DONE")
        before = apps.get_model("exports", "ExportJob").objects.values().get(pk=job.pk)
        snapshot_schema = [target for target in latest if target[0] != "exports"] + [("exports", "0002_exportjob_enqueued_at_exportjob_export_mode_and_more")]
        MigrationExecutor(connection).migrate(snapshot_schema)
        apps = MigrationExecutor(connection).loader.project_state(snapshot_schema).apps
        after = apps.get_model("exports", "ExportJob").objects.values().get(pk=job.pk)
        self.assertEqual(after.pop("export_mode"), "WORK")
        self.assertIsNone(after.pop("request_key"))
        self.assertIsNone(after.pop("enqueued_at"))
        self.assertEqual(after, before)
        self.assertFalse(apps.get_model("exports", "ExportSnapshot").objects.exists())
