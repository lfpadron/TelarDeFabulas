from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class OrganizationMigrationTests(TransactionTestCase):
    def test_additive_schema_preserves_existing_rows(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        old = [target for target in latest if target[0] not in ("organizations", "references")] + [("organizations", None)]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        apps = executor.loader.project_state([target for target in old if target[1] is not None]).apps
        user = apps.get_model("accounts", "User").objects.create(email="org-migration@example.test", password="!")
        project = apps.get_model("projects", "Project").objects.create(user=user, name="Original world")
        location = apps.get_model("geography", "GeographicLocation").objects.create(project=project, name="Original city", position=1,
            detailed_description="Original history\r\nExact text")
        character = apps.get_model("characters", "Character").objects.create(project=project, name="Original character", residence=location,
            biography="Original biography", image="characters/original.png")
        apps.get_model("characters", "CharacterDramaticRole").objects.create(character=character, role="MENTOR")
        labels = [("accounts", "User"), ("projects", "Project"), ("geography", "GeographicLocation"),
                  ("characters", "Character"), ("characters", "CharacterDramaticRole")]
        before = {label: list(apps.get_model(*label).objects.values()) for label in labels}
        MigrationExecutor(connection).migrate(latest)
        apps = MigrationExecutor(connection).loader.project_state(latest).apps
        self.assertEqual(before, {label: list(apps.get_model(*label).objects.values()) for label in labels})
        self.assertFalse(apps.get_model("organizations", "Organization").objects.exists())
        self.assertFalse(apps.get_model("organizations", "CharacterOrganizationMembership").objects.exists())
