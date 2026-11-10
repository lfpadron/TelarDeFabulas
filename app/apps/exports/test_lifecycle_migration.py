from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class ExportLifecycleMigrationTests(TransactionTestCase):
    def test_states_snapshots_and_historical_file_names_are_preserved(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        old = [target for target in latest if target[0] != "exports"] + [("exports", "0002_exportjob_enqueued_at_exportjob_export_mode_and_more")]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        apps = executor.loader.project_state(old).apps
        user = apps.get_model("accounts", "User").objects.create(email="lifecycle-migration@example.test", password="!")
        project = apps.get_model("projects", "Project").objects.create(user=user, name="Historical")
        style = apps.get_model("styles", "StyleTemplate").objects.create(name="Historical", is_system=True)
        jobs = []
        for status in ("PENDING", "DONE", "PROCESSING", "FAILED"):
            job = apps.get_model("exports", "ExportJob").objects.create(user=user, project=project,
                style_template=style, status=status, file=f"exports/{user.pk}/{project.pk}/{status}.html")
            apps.get_model("exports", "ExportSnapshot").objects.create(export_job=job, manifest_json={"private": "immutable original"},
                checksum="a" * 64, size_bytes=123, included_scene_count=1, excluded_scene_count=0, style_name="Snapshot style", scope_title="Captured")
            jobs.append((job.pk, job.file.name, status))
        snapshots = list(apps.get_model("exports", "ExportSnapshot").objects.order_by("pk").values())
        before = timezone.now()
        lifecycle = [target for target in latest if target[0] != "exports"] + [("exports", "0003_export_lifecycle")]
        MigrationExecutor(connection).migrate(lifecycle)
        apps = MigrationExecutor(connection).loader.project_state(lifecycle).apps
        self.assertEqual(snapshots, list(apps.get_model("exports", "ExportSnapshot").objects.order_by("pk").values()))
        for pk, name, status in jobs:
            job = apps.get_model("exports", "ExportJob").objects.get(pk=pk)
            self.assertEqual(job.status, {"DONE": "READY", "PENDING": "REQUESTED"}.get(status, status))
            self.assertEqual(job.file.name, name)
            self.assertFalse(job.notify_by_email)
            if status in ("DONE", "FAILED"):
                self.assertGreater(job.expires_at, before)
            self.assertEqual(job.attempt_count, 0)
