import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.manuscripts.models import ManuscriptNode
from apps.notes.models import Note
from apps.projects.models import Project

from .models import Character, CharacterDramaticRole, CharacterMention


class CharacterTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_root)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)

        User = get_user_model()
        self.password = "safe-test-password"
        self.user = User.objects.create_user(email="writer@example.com", password=self.password)
        self.other_user = User.objects.create_user(email="other@example.com", password=self.password)
        self.project = Project.objects.create(user=self.user, name="Novela propia")
        self.other_project = Project.objects.create(user=self.other_user, name="Novela ajena")

    def character_payload(self, **overrides):
        payload = {
            "name": "Ariadna",
            "alias": "La hilandera",
            "importance": Character.Importance.SECUNDARIA,
            "narrative_role": Character.NarrativeRole.SECUNDARIO,
            "custom_narrative_role": "",
            "physical_description": "Cabello oscuro y mirada serena.",
            "psychological_description": "",
            "biography": "Nació junto al telar familiar.",
            "motivations": "Proteger su taller.",
            "goals": "Terminar su gran obra.",
            "fears": "",
            "virtues": "",
            "flaws": "",
            "character_arc": "",
            "notes": "Tiene una llave antigua.",
            "completion_status": Character.CompletionStatus.PARTIAL,
            "dramatic_roles": [CharacterDramaticRole.DramaticRole.ALIADO],
        }
        payload.update(overrides)
        return payload

    def create_url(self, project=None):
        project = project or self.project
        return reverse("characters:create", kwargs={"project_pk": project.pk})

    def detail_url(self, character, project=None):
        project = project or character.project
        return reverse("characters:detail", kwargs={"project_pk": project.pk, "character_pk": character.pk})

    def edit_url(self, character, project=None):
        project = project or character.project
        return reverse("characters:edit", kwargs={"project_pk": project.pk, "character_pk": character.pk})

    def delete_url(self, character, project=None):
        project = project or character.project
        return reverse("characters:delete", kwargs={"project_pk": project.pk, "character_pk": character.pk})

    def list_url(self, project=None):
        project = project or self.project
        return reverse("characters:list", kwargs={"project_pk": project.pk})

    def mention_create_url(self, project=None):
        project = project or self.project
        return reverse("characters:mention_create", kwargs={"project_pk": project.pk})

    def mention_edit_url(self, mention, project=None):
        project = project or mention.character.project
        return reverse("characters:mention_edit", kwargs={"project_pk": project.pk, "mention_pk": mention.pk})

    def mention_delete_url(self, mention, project=None):
        project = project or mention.character.project
        return reverse("characters:mention_delete", kwargs={"project_pk": project.pk, "mention_pk": mention.pk})

    def node_detail_url(self, node, project=None):
        project = project or node.project
        return reverse("manuscripts:detail", kwargs={"project_pk": project.pk, "node_pk": node.pk})

    def mention_payload(self, character, node, **overrides):
        payload = {
            "character": character.pk,
            "node": node.pk,
            "mention_type": CharacterMention.MentionType.APPEARS,
        }
        payload.update(overrides)
        return payload

    def test_authenticated_user_can_create_character_in_own_project(self):
        self.client.force_login(self.user)

        response = self.client.post(self.create_url(), self.character_payload())

        character = Character.objects.get(project=self.project)
        self.assertRedirects(response, self.detail_url(character))
        self.assertEqual(character.name, "Ariadna")
        self.assertEqual(character.dramatic_roles.count(), 1)

    def test_unauthenticated_user_is_redirected(self):
        response = self.client.get(self.list_url())

        self.assertRedirects(response, f"{reverse('login')}?next={self.list_url()}")

    def test_user_cannot_create_character_in_project_from_another_user(self):
        self.client.force_login(self.user)

        response = self.client.post(self.create_url(self.other_project), self.character_payload())

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Character.objects.filter(project=self.other_project).exists())

    def test_user_cannot_see_character_from_another_user_project(self):
        character = Character.objects.create(project=self.other_project, name="Ariadna ajena")
        self.client.force_login(self.user)

        response = self.client.get(self.detail_url(character))

        self.assertEqual(response.status_code, 404)

    def test_cannot_create_character_in_deleted_project(self):
        self.project.status = Project.ProjectStatus.DELETED
        self.project.deleted_at = timezone.now()
        self.project.save()
        self.client.force_login(self.user)

        response = self.client.post(self.create_url(), self.character_payload())

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": self.project.pk}))
        self.assertFalse(Character.objects.filter(project=self.project).exists())

    def test_cannot_create_character_in_pending_deletion_project(self):
        self.project.mark_for_deletion()
        self.client.force_login(self.user)

        response = self.client.post(self.create_url(), self.character_payload())

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": self.project.pk}))
        self.assertFalse(Character.objects.filter(project=self.project).exists())

    def test_completion_percentage_uses_importance_specific_fields(self):
        principal = Character(project=self.project, name="Principal", importance=Character.Importance.PRINCIPAL)
        secundaria = Character(
            project=self.project,
            name="Secundaria",
            importance=Character.Importance.SECUNDARIA,
            physical_description="Rasgos claros.",
            notes="Nota.",
        )
        figurante = Character(project=self.project, name="Figurante", importance=Character.Importance.FIGURANTE)

        self.assertEqual(principal.completion_percentage, 10)
        self.assertEqual(secundaria.completion_percentage, 50)
        self.assertEqual(figurante.completion_percentage, 33)

    def test_custom_narrative_role_is_cleared_when_role_is_not_other(self):
        character = Character.objects.create(
            project=self.project,
            name="Ariadna",
            narrative_role=Character.NarrativeRole.PROTAGONISTA,
            custom_narrative_role="Guardiana del umbral",
        )

        character.refresh_from_db()
        self.assertEqual(character.custom_narrative_role, "")

    def test_dramatic_role_custom_role_is_cleared_when_role_is_not_other(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        role = CharacterDramaticRole.objects.create(
            character=character,
            role=CharacterDramaticRole.DramaticRole.HEROE,
            custom_role="Otro papel",
        )

        role.refresh_from_db()
        self.assertEqual(role.custom_role, "")

    def test_character_mention_requires_character_and_node_from_same_project(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        other_node = ManuscriptNode.objects.create(project=self.other_project, title="Escena ajena")
        mention = CharacterMention(
            character=character,
            node=other_node,
            mention_type=CharacterMention.MentionType.APPEARS,
        )

        with self.assertRaises(ValidationError):
            mention.full_clean()

    def test_authenticated_user_can_create_mention_in_own_project(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        node = ManuscriptNode.objects.create(project=self.project, title="Escena propia")
        self.client.force_login(self.user)

        response = self.client.post(self.mention_create_url(), self.mention_payload(character, node))

        mention = CharacterMention.objects.get(character=character, node=node)
        self.assertRedirects(response, self.detail_url(character))
        self.assertEqual(mention.mention_type, CharacterMention.MentionType.APPEARS)

    def test_unauthenticated_user_is_redirected_from_mention_create(self):
        response = self.client.get(self.mention_create_url())

        self.assertRedirects(response, f"{reverse('login')}?next={self.mention_create_url()}")

    def test_user_cannot_create_mention_with_foreign_character(self):
        character = Character.objects.create(project=self.other_project, name="Ariadna ajena")
        node = ManuscriptNode.objects.create(project=self.project, title="Escena propia")
        self.client.force_login(self.user)

        response = self.client.post(self.mention_create_url(), self.mention_payload(character, node))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(CharacterMention.objects.exists())

    def test_user_cannot_create_mention_with_foreign_node(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        node = ManuscriptNode.objects.create(project=self.other_project, title="Escena ajena")
        self.client.force_login(self.user)

        response = self.client.post(self.mention_create_url(), self.mention_payload(character, node))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(CharacterMention.objects.exists())

    def test_create_mention_from_node_preselects_valid_node(self):
        node = ManuscriptNode.objects.create(project=self.project, title="Escena propia")
        self.client.force_login(self.user)

        response = self.client.get(f"{self.mention_create_url()}?node={node.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["node"], node.pk)

    def test_create_mention_from_character_preselects_valid_character(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        self.client.force_login(self.user)

        response = self.client.get(f"{self.mention_create_url()}?character={character.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["character"], character.pk)

    def test_user_can_edit_own_mention_type(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        node = ManuscriptNode.objects.create(project=self.project, title="Escena propia")
        mention = CharacterMention.objects.create(
            character=character,
            node=node,
            mention_type=CharacterMention.MentionType.APPEARS,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            self.mention_edit_url(mention),
            self.mention_payload(character, node, mention_type=CharacterMention.MentionType.POV),
        )

        mention.refresh_from_db()
        self.assertRedirects(response, self.detail_url(character))
        self.assertEqual(mention.mention_type, CharacterMention.MentionType.POV)

    def test_user_cannot_edit_foreign_mention(self):
        character = Character.objects.create(project=self.other_project, name="Ariadna ajena")
        node = ManuscriptNode.objects.create(project=self.other_project, title="Escena ajena")
        mention = CharacterMention.objects.create(
            character=character,
            node=node,
            mention_type=CharacterMention.MentionType.APPEARS,
        )
        self.client.force_login(self.user)

        response = self.client.get(self.mention_edit_url(mention, self.project))

        self.assertEqual(response.status_code, 404)

    def test_user_can_delete_own_mention(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        node = ManuscriptNode.objects.create(project=self.project, title="Escena propia")
        mention = CharacterMention.objects.create(
            character=character,
            node=node,
            mention_type=CharacterMention.MentionType.APPEARS,
        )
        self.client.force_login(self.user)

        response = self.client.post(self.mention_delete_url(mention))

        self.assertRedirects(response, self.detail_url(character))
        self.assertFalse(CharacterMention.objects.filter(pk=mention.pk).exists())

    def test_user_cannot_delete_foreign_mention(self):
        character = Character.objects.create(project=self.other_project, name="Ariadna ajena")
        node = ManuscriptNode.objects.create(project=self.other_project, title="Escena ajena")
        mention = CharacterMention.objects.create(
            character=character,
            node=node,
            mention_type=CharacterMention.MentionType.APPEARS,
        )
        self.client.force_login(self.user)

        response = self.client.post(self.mention_delete_url(mention, self.project))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(CharacterMention.objects.filter(pk=mention.pk).exists())

    def test_exact_duplicate_mentions_are_not_allowed(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        node = ManuscriptNode.objects.create(project=self.project, title="Escena propia")
        CharacterMention.objects.create(
            character=character,
            node=node,
            mention_type=CharacterMention.MentionType.APPEARS,
        )
        self.client.force_login(self.user)

        response = self.client.post(self.mention_create_url(), self.mention_payload(character, node))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ya existe una mención idéntica")
        self.assertEqual(CharacterMention.objects.count(), 1)

    def test_multiple_mention_types_for_same_character_and_node_are_allowed(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        node = ManuscriptNode.objects.create(project=self.project, title="Escena propia")
        CharacterMention.objects.create(
            character=character,
            node=node,
            mention_type=CharacterMention.MentionType.APPEARS,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            self.mention_create_url(),
            self.mention_payload(character, node, mention_type=CharacterMention.MentionType.POV),
        )

        self.assertRedirects(response, self.detail_url(character))
        self.assertEqual(CharacterMention.objects.filter(character=character, node=node).count(), 2)

    def test_node_detail_shows_mentioned_characters(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        node = ManuscriptNode.objects.create(project=self.project, title="Escena propia")
        CharacterMention.objects.create(
            character=character,
            node=node,
            mention_type=CharacterMention.MentionType.NARRATOR,
        )
        self.client.force_login(self.user)

        response = self.client.get(self.node_detail_url(node))

        self.assertContains(response, "Personajes en esta parte")
        self.assertContains(response, character.name)
        self.assertContains(response, CharacterMention.MentionType.NARRATOR.label)

    def test_character_detail_shows_mentioned_nodes(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        node = ManuscriptNode.objects.create(project=self.project, title="Escena propia")
        CharacterMention.objects.create(
            character=character,
            node=node,
            mention_type=CharacterMention.MentionType.MENTIONED,
        )
        self.client.force_login(self.user)

        response = self.client.get(self.detail_url(character))

        self.assertContains(response, "Apariciones y menciones")
        self.assertContains(response, node.title)
        self.assertContains(response, CharacterMention.MentionType.MENTIONED.label)

    def test_character_list_shows_mention_and_appearance_counts(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        node = ManuscriptNode.objects.create(project=self.project, title="Escena propia")
        CharacterMention.objects.create(
            character=character,
            node=node,
            mention_type=CharacterMention.MentionType.APPEARS,
        )
        CharacterMention.objects.create(
            character=character,
            node=node,
            mention_type=CharacterMention.MentionType.POV,
        )
        self.client.force_login(self.user)

        response = self.client.get(self.list_url())
        listed_character = response.context["characters"][0]

        self.assertContains(response, "Menciones")
        self.assertContains(response, "Apariciones")
        self.assertEqual(listed_character.mention_count, 2)
        self.assertEqual(listed_character.appearance_count, 1)

    def test_cannot_create_mention_in_deleted_project(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        node = ManuscriptNode.objects.create(project=self.project, title="Escena propia")
        self.project.status = Project.ProjectStatus.DELETED
        self.project.deleted_at = timezone.now()
        self.project.save()
        self.client.force_login(self.user)

        response = self.client.post(self.mention_create_url(), self.mention_payload(character, node))

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": self.project.pk}))
        self.assertFalse(CharacterMention.objects.exists())

    def test_cannot_create_mention_in_pending_deletion_project(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        node = ManuscriptNode.objects.create(project=self.project, title="Escena propia")
        self.project.mark_for_deletion()
        self.client.force_login(self.user)

        response = self.client.post(self.mention_create_url(), self.mention_payload(character, node))

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": self.project.pk}))
        self.assertFalse(CharacterMention.objects.exists())

    def test_character_list_only_shows_current_project_characters(self):
        own_character = Character.objects.create(project=self.project, name="Ariadna")
        Character.objects.create(project=self.other_project, name="Personaje ajeno")
        self.client.force_login(self.user)

        response = self.client.get(self.list_url())

        self.assertContains(response, own_character.name)
        self.assertNotContains(response, "Personaje ajeno")

    def test_image_upload_does_not_break_creation_or_editing(self):
        self.client.force_login(self.user)
        image = SimpleUploadedFile("portrait.gif", b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02L\x01\x00;", content_type="image/gif")

        response = self.client.post(self.create_url(), self.character_payload(image=image))

        character = Character.objects.get(project=self.project)
        self.assertRedirects(response, self.detail_url(character))
        self.assertTrue(character.image.name.startswith(f"characters/{self.project.pk}/"))

        edit_response = self.client.post(self.edit_url(character), self.character_payload(name="Ariadna editada"))
        character.refresh_from_db()
        self.assertRedirects(edit_response, self.detail_url(character))
        self.assertEqual(character.name, "Ariadna editada")

    def test_string_representations_are_readable(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        role = CharacterDramaticRole.objects.create(character=character, role=CharacterDramaticRole.DramaticRole.MENTOR)
        node = ManuscriptNode.objects.create(project=self.project, title="Escena")
        mention = CharacterMention.objects.create(
            character=character,
            node=node,
            mention_type=CharacterMention.MentionType.POV,
        )

        self.assertEqual(str(character), "Ariadna")
        self.assertIn("Ariadna", str(role))
        self.assertIn("Escena", str(mention))

    def test_character_detail_shows_linked_work_notes(self):
        character = Character.objects.create(project=self.project, name="Ariadna")
        linked_note = Note.objects.create(
            project=self.project,
            character=character,
            title="Nota visible desde personaje",
            note_type=Note.NoteType.IDEA,
            priority=Note.Priority.HIGH,
        )
        Note.objects.create(project=self.project, title="Nota sin personaje")
        self.client.force_login(self.user)

        response = self.client.get(self.detail_url(character))

        self.assertContains(response, "Notas, ideas y pendientes asociados")
        self.assertContains(response, linked_note.title)
        self.assertContains(response, linked_note.get_note_type_display())
        self.assertContains(response, linked_note.get_priority_display())
        self.assertNotContains(response, "Nota sin personaje")
