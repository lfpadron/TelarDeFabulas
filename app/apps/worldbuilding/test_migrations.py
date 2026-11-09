from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class WorldbuildingMigrationTests(TransactionTestCase):
    def test_additive_schema_preserves_original_entities(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        old = [target for target in latest if target[0] not in ("worldbuilding", "references")] + [("worldbuilding", None)]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        apps = executor.loader.project_state([target for target in old if target[1] is not None]).apps
        user = apps.get_model("accounts", "User").objects.create(email="world-migration@example.test", password="!")
        project = apps.get_model("projects", "Project").objects.create(user=user, name="Original project")
        location = apps.get_model("geography", "GeographicLocation").objects.create(project=project, name="Original city", position=1)
        character = apps.get_model("characters", "Character").objects.create(project=project, name="Original character", residence=location, biography="Exact\r\nText")
        organization = apps.get_model("organizations", "Organization").objects.create(project=project, name="Original organization", position=1, headquarters=location)
        apps.get_model("organizations", "CharacterOrganizationMembership").objects.create(character=character, organization=organization, position_title="Original role")
        labels = [("accounts", "User"), ("projects", "Project"), ("characters", "Character"),
                  ("geography", "GeographicLocation"), ("organizations", "Organization"),
                  ("organizations", "CharacterOrganizationMembership")]
        before = {label: list(apps.get_model(*label).objects.values()) for label in labels}
        MigrationExecutor(connection).migrate(latest)
        apps = MigrationExecutor(connection).loader.project_state(latest).apps
        self.assertEqual(before, {label: list(apps.get_model(*label).objects.values()) for label in labels})
        self.assertFalse(apps.get_model("worldbuilding", "WorldbuildingEntry").objects.exists())
