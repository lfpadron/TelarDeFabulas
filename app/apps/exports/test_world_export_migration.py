from django.db import connection, DatabaseError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class WorldExportMigrationTests(TransactionTestCase):
    def test_historical_rows_unchanged_and_reverse_guarded(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        old = [target for target in latest if target[0] != "exports"] + [("exports", "0003_export_lifecycle")]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        apps = executor.loader.project_state(old).apps
        user = apps.get_model("accounts", "User").objects.create(email="world-migration@example.test", password="!")
        project = apps.get_model("projects", "Project").objects.create(user=user, name="Original")
        style = apps.get_model("styles", "StyleTemplate").objects.create(name="Original", is_system=True)
        for format_, mode in (("HTML", "WORK"), ("EPUB", "WORK"), ("MARKDOWN", "WORK"), ("DOCX", "FINAL"), ("PDF", "FINAL")):
            job = apps.get_model("exports", "ExportJob").objects.create(user=user, project=project, style_template=style,
                format=format_, export_mode=mode, status="READY", file=f"exports/{user.pk}/{project.pk}/{format_}")
            apps.get_model("exports", "ExportSnapshot").objects.create(export_job=job,
                manifest_json={"schema_version": 1, "original": format_}, checksum="b" * 64, size_bytes=123,
                included_scene_count=2, excluded_scene_count=1, style_name="Captured", scope_title="Original")
        before = {name: list(apps.get_model("exports", name).objects.order_by("pk").values()) for name in ("ExportJob", "ExportSnapshot")}
        MigrationExecutor(connection).migrate(latest)
        apps = MigrationExecutor(connection).loader.project_state(latest).apps
        for name, rows in before.items():
            self.assertEqual(rows, list(apps.get_model("exports", name).objects.order_by("pk").values(*rows[0])))
        Job, Snapshot = apps.get_model("exports", "ExportJob"), apps.get_model("exports", "ExportSnapshot")
        self.assertEqual(set(Job.objects.values_list("scope_kind", flat=True)), {"MANUSCRIPT"})
        self.assertEqual(set(Snapshot.objects.values_list("included_entity_count", flat=True)), {0})
        with self.assertRaises(DatabaseError), transaction.atomic():
            Snapshot.objects.update(manifest_json={})
        reference = Job.objects.create(user_id=user.pk, project_id=project.pk, style_template_id=style.pk,
            export_mode="REFERENCE", scope_kind="WORLD_COMPENDIUM", format="MARKDOWN")
        with self.assertRaisesMessage(RuntimeError, "REFERENCE"):
            MigrationExecutor(connection).migrate(old)
        self.assertTrue(Job.objects.filter(pk=reference.pk).exists())
