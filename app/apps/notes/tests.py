from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.characters.models import Character
from apps.manuscripts.models import ManuscriptNode
from apps.projects.models import Project

from .models import Note


class NoteTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.password = "safe-test-password"
        self.user = User.objects.create_user(email="writer@example.com", password=self.password)
        self.other_user = User.objects.create_user(email="other@example.com", password=self.password)
        self.project = Project.objects.create(user=self.user, name="Novela propia")
        self.other_project = Project.objects.create(user=self.other_user, name="Novela ajena")
        self.node = ManuscriptNode.objects.create(project=self.project, title="Escena propia")
        self.other_node = ManuscriptNode.objects.create(project=self.other_project, title="Escena ajena")
        self.character = Character.objects.create(project=self.project, name="Ariadna")
        self.other_character = Character.objects.create(project=self.other_project, name="Ariadna ajena")

    def note_payload(self, **overrides):
        payload = {
            "note_type": Note.NoteType.NOTE,
            "title": "Nota de trabajo",
            "content": "Recordar revisar el tono de la escena.",
            "status": Note.NoteStatus.OPEN,
            "priority": Note.Priority.MEDIUM,
            "node": "",
            "character": "",
        }
        payload.update(overrides)
        return payload

    def create_url(self, project=None):
        project = project or self.project
        return reverse("notes:create", kwargs={"project_pk": project.pk})

    def detail_url(self, note, project=None):
        project = project or note.project
        return reverse("notes:detail", kwargs={"project_pk": project.pk, "note_pk": note.pk})

    def edit_url(self, note, project=None):
        project = project or note.project
        return reverse("notes:edit", kwargs={"project_pk": project.pk, "note_pk": note.pk})

    def delete_url(self, note, project=None):
        project = project or note.project
        return reverse("notes:delete", kwargs={"project_pk": project.pk, "note_pk": note.pk})

    def list_url(self, project=None):
        project = project or self.project
        return reverse("notes:list", kwargs={"project_pk": project.pk})

    def test_authenticated_user_can_create_note_in_own_project(self):
        self.client.force_login(self.user)

        response = self.client.post(self.create_url(), self.note_payload())

        note = Note.objects.get(project=self.project)
        self.assertRedirects(response, self.detail_url(note))
        self.assertEqual(note.title, "Nota de trabajo")

    def test_unauthenticated_user_is_redirected(self):
        response = self.client.get(self.list_url())

        self.assertRedirects(response, f"{reverse('login')}?next={self.list_url()}")

    def test_user_cannot_create_note_in_project_from_another_user(self):
        self.client.force_login(self.user)

        response = self.client.post(self.create_url(self.other_project), self.note_payload())

        self.assertEqual(response.status_code, 404)
        self.assertFalse(Note.objects.filter(project=self.other_project).exists())

    def test_user_cannot_see_note_from_another_user_project(self):
        note = Note.objects.create(project=self.other_project, title="Nota ajena")
        self.client.force_login(self.user)

        response = self.client.get(self.detail_url(note))

        self.assertEqual(response.status_code, 404)

    def test_node_must_belong_to_same_project(self):
        note = Note(project=self.project, node=self.other_node, title="Nodo inválido")

        with self.assertRaises(ValidationError):
            note.full_clean()

    def test_character_must_belong_to_same_project(self):
        note = Note(project=self.project, character=self.other_character, title="Personaje inválido")

        with self.assertRaises(ValidationError):
            note.full_clean()

    def test_can_create_project_only_note(self):
        note = Note.objects.create(project=self.project, title="Solo proyecto")

        self.assertIsNone(note.node)
        self.assertIsNone(note.character)

    def test_can_create_note_with_node_and_character(self):
        note = Note.objects.create(
            project=self.project,
            node=self.node,
            character=self.character,
            title="Cruce de escena y personaje",
        )

        self.assertEqual(note.node, self.node)
        self.assertEqual(note.character, self.character)

    def test_cannot_create_note_in_deleted_project(self):
        self.project.status = Project.ProjectStatus.DELETED
        self.project.deleted_at = timezone.now()
        self.project.save()
        self.client.force_login(self.user)

        response = self.client.post(self.create_url(), self.note_payload())

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": self.project.pk}))
        self.assertFalse(Note.objects.filter(project=self.project).exists())

    def test_cannot_create_note_in_pending_deletion_project(self):
        self.project.mark_for_deletion()
        self.client.force_login(self.user)

        response = self.client.post(self.create_url(), self.note_payload())

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": self.project.pk}))
        self.assertFalse(Note.objects.filter(project=self.project).exists())

    def test_done_status_fills_completed_at(self):
        note = Note.objects.create(project=self.project, title="Terminar arco", status=Note.NoteStatus.DONE)

        self.assertIsNotNone(note.completed_at)

    def test_leaving_done_status_clears_completed_at(self):
        note = Note.objects.create(project=self.project, title="Terminar arco", status=Note.NoteStatus.DONE)

        note.status = Note.NoteStatus.OPEN
        note.save()

        note.refresh_from_db()
        self.assertIsNone(note.completed_at)

    def test_filter_by_note_type_works(self):
        Note.objects.create(project=self.project, title="Idea filtrada", note_type=Note.NoteType.IDEA)
        Note.objects.create(project=self.project, title="Tarea fuera", note_type=Note.NoteType.TASK)
        self.client.force_login(self.user)

        response = self.client.get(self.list_url(), {"type": Note.NoteType.IDEA})

        self.assertContains(response, "Idea filtrada")
        self.assertNotContains(response, "Tarea fuera")

    def test_filter_by_status_works(self):
        Note.objects.create(project=self.project, title="Abierta filtrada", status=Note.NoteStatus.OPEN)
        Note.objects.create(project=self.project, title="Descartada fuera", status=Note.NoteStatus.DISCARDED)
        self.client.force_login(self.user)

        response = self.client.get(self.list_url(), {"status": Note.NoteStatus.OPEN})

        self.assertContains(response, "Abierta filtrada")
        self.assertNotContains(response, "Descartada fuera")

    def test_filter_by_priority_works(self):
        Note.objects.create(project=self.project, title="Alta filtrada", priority=Note.Priority.HIGH)
        Note.objects.create(project=self.project, title="Baja fuera", priority=Note.Priority.LOW)
        self.client.force_login(self.user)

        response = self.client.get(self.list_url(), {"priority": Note.Priority.HIGH})

        self.assertContains(response, "Alta filtrada")
        self.assertNotContains(response, "Baja fuera")

    def test_note_list_only_shows_current_project_notes(self):
        own_note = Note.objects.create(project=self.project, title="Nota propia")
        Note.objects.create(project=self.other_project, title="Nota ajena")
        self.client.force_login(self.user)

        response = self.client.get(self.list_url())

        self.assertContains(response, own_note.title)
        self.assertNotContains(response, "Nota ajena")

    def test_can_delete_note_with_confirmation(self):
        note = Note.objects.create(project=self.project, title="Nota borrable")
        self.client.force_login(self.user)

        response = self.client.post(self.delete_url(note))

        self.assertRedirects(response, self.list_url())
        self.assertFalse(Note.objects.filter(pk=note.pk).exists())

    def test_create_note_from_node_querystring_preselects_valid_node(self):
        self.client.force_login(self.user)

        response = self.client.get(self.create_url(), {"node": self.node.pk})

        self.assertEqual(response.context["form"].initial["node"], self.node.pk)
        self.assertContains(response, self.node.title)

    def test_create_note_from_character_querystring_preselects_valid_character(self):
        self.client.force_login(self.user)

        response = self.client.get(self.create_url(), {"character": self.character.pk})

        self.assertEqual(response.context["form"].initial["character"], self.character.pk)
        self.assertContains(response, self.character.name)

    def test_invalid_querystring_association_is_ignored(self):
        self.client.force_login(self.user)

        response = self.client.get(self.create_url(), {"node": self.other_node.pk, "character": self.other_character.pk})

        self.assertNotIn("node", response.context["form"].initial)
        self.assertNotIn("character", response.context["form"].initial)
