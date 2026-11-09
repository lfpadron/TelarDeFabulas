from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class GeographyMigrationTests(TransactionTestCase):
    def test_additive_schema_preserves_existing_characters(self):
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        old = [target for target in latest if target[0] not in ("geography", "characters", "organizations", "references")]
        old += [("organizations", None), ("geography", None), ("characters", "0002_validate_private_images")]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        executor = MigrationExecutor(connection)
        executor.migrate(old)
        apps = executor.loader.project_state([target for target in old if target[1] is not None]).apps
        user = apps.get_model("accounts", "User").objects.create(email="geo-migration@example.test", password="!")
        project = apps.get_model("projects", "Project").objects.create(user=user, name="Historical project")
        character_model = apps.get_model("characters", "Character")
        character = character_model.objects.create(project=project, name="Original", biography="Exact text\r\nSecond line", image="characters/original.png")
        role_model = apps.get_model("characters", "CharacterDramaticRole")
        role_model.objects.create(character=character, role="MENTOR")
        before = list(character_model.objects.values())
        roles = list(role_model.objects.values())
        MigrationExecutor(connection).migrate(latest)
        apps = MigrationExecutor(connection).loader.project_state(latest).apps
        after = list(apps.get_model("characters", "Character").objects.values())
        for row in after:
            self.assertIsNone(row.pop("residence_id"))
        self.assertEqual(after, before)
        self.assertEqual(list(apps.get_model("characters", "CharacterDramaticRole").objects.values()), roles)
        self.assertFalse(apps.get_model("geography", "GeographicLocation").objects.exists())
