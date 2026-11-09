from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class RelationshipMigrationTests(TransactionTestCase):
    def test_additive_schema_preserves_characters_and_existing_connections(self):
        self.assertTrue(connection.settings_dict["NAME"].startswith("test_"))
        latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        old = [target for target in latest if target[0] != "characters"] + [("characters", "0003_character_residence")]
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest))
        MigrationExecutor(connection).migrate(old)
        apps = MigrationExecutor(connection).loader.project_state(old).apps
        user = apps.get_model("accounts.User").objects.create(email="relationship-migration@example.test", password="!")
        project = apps.get_model("projects.Project").objects.create(user=user, name="Original project")
        location = apps.get_model("geography.GeographicLocation").objects.create(project=project, name="Original location", position=1)
        character = apps.get_model("characters.Character").objects.create(project=project, name="Original character", residence=location,
            biography="Original\r\n  Text", image="characters/original.png")
        apps.get_model("characters.CharacterDramaticRole").objects.create(character=character, role="INTERES_ROMANTICO")
        node_model = apps.get_model("manuscripts.ManuscriptNode")
        book = node_model.objects.create(project=project, node_type="BOOK", title="Original book")
        chapter = node_model.objects.create(project=project, parent=book, node_type="CHAPTER", title="Original chapter")
        scene = node_model.objects.create(project=project, parent=chapter, node_type="SCENE", title="Original scene")
        version = apps.get_model("manuscripts.SceneVersion").objects.create(scene=scene, version_number=1, content="Original scene text")
        node_model.objects.filter(pk=scene.pk).update(current_draft_version=version)
        apps.get_model("characters.CharacterMention").objects.create(character=character, node=scene, mention_type="POV")
        organization = apps.get_model("organizations.Organization").objects.create(project=project, name="Original organization", position=1, headquarters=location)
        apps.get_model("organizations.CharacterOrganizationMembership").objects.create(character=character, organization=organization, position_title="Original role")
        reference = apps.get_model("references.ReferenceMaterial").objects.create(project=project, title="Original reference")
        apps.get_model("references.ReferenceAssociation").objects.create(reference=reference, character=character)
        labels = ("accounts.User", "projects.Project", "characters.Character", "characters.CharacterDramaticRole", "characters.CharacterMention",
            "geography.GeographicLocation", "organizations.Organization", "organizations.CharacterOrganizationMembership", "references.ReferenceMaterial",
            "references.ReferenceAssociation", "manuscripts.ManuscriptNode", "manuscripts.SceneVersion")
        before = {label: list(apps.get_model(label).objects.order_by("pk").values()) for label in labels}
        MigrationExecutor(connection).migrate(latest)
        apps = MigrationExecutor(connection).loader.project_state(latest).apps
        self.assertEqual(before, {label: list(apps.get_model(label).objects.order_by("pk").values()) for label in labels})
        self.assertFalse(apps.get_model("characters.CharacterRelationship").objects.exists())
