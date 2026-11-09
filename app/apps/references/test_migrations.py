from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ReferenceMigrationTests(TransactionTestCase):
    def test_additive_migration_preserves_entities(self):
        self.assertTrue(connection.settings_dict["NAME"].startswith("test_"))
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        old = [target for target in latest if target[0] != "references"]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        MigrationExecutor(connection).migrate([*old, ("references", None)])
        apps = MigrationExecutor(connection).loader.project_state(old).apps
        user = apps.get_model("accounts", "User").objects.create(email="ref-migration@example.test", password="!")
        project = apps.get_model("projects", "Project").objects.create(user=user, name="Original")
        for label, fields in (("worldbuilding.WorldbuildingEntry", {"category": "HISTORY", "title": "Original", "position": 0, "content": "Exact\r\nText"}),
                              ("organizations.Organization", {"name": "Original organization", "position": 1}),
                              ("geography.GeographicLocation", {"name": "Original city", "position": 1}),
                              ("characters.Character", {"name": "Original character"}),
                              ("manuscripts.ManuscriptNode", {"title": "Original book", "node_type": "BOOK"})):
            apps.get_model(label).objects.create(project=project, **fields)
        labels = ("accounts.User", "projects.Project", "worldbuilding.WorldbuildingEntry", "organizations.Organization",
                  "geography.GeographicLocation", "characters.Character", "manuscripts.ManuscriptNode")
        before = {label: list(apps.get_model(label).objects.values()) for label in labels}
        MigrationExecutor(connection).migrate(latest)
        apps = MigrationExecutor(connection).loader.project_state(latest).apps
        self.assertEqual(before, {label: list(apps.get_model(label).objects.values()) for label in labels})
        for label in ("ReferenceMaterial", "ReferenceAssociation", "ReferenceFileCleanup"):
            self.assertFalse(apps.get_model("references", label).objects.exists())
