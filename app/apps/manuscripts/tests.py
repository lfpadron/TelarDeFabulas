from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.characters.models import Character, CharacterMention
from apps.notes.models import Note
from apps.projects.models import Project

from .models import ManuscriptNode
from .services import move_node, move_node_down, move_node_up


class ManuscriptNodeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.password = "safe-test-password"
        self.user = User.objects.create_user(email="writer@example.com", password=self.password)
        self.other_user = User.objects.create_user(email="other@example.com", password=self.password)
        self.project = Project.objects.create(user=self.user, name="Novela propia")
        self.other_project = Project.objects.create(user=self.other_user, name="Novela ajena")

    def node_payload(self, **overrides):
        payload = {
            "node_type": ManuscriptNode.NodeType.BOOK,
            "title": "Capítulo uno",
            "content": "Érase una vez una historia breve.",
            "status": ManuscriptNode.NodeStatus.DRAFT,
            "position": "",
        }
        payload.update(overrides)
        return payload

    def create_node_url(self, project=None):
        project = project or self.project
        return reverse("manuscripts:create", kwargs={"project_pk": project.pk})

    def detail_url(self, node, project=None):
        project = project or node.project
        return reverse("manuscripts:detail", kwargs={"project_pk": project.pk, "node_pk": node.pk})

    def edit_url(self, node, project=None):
        project = project or node.project
        return reverse("manuscripts:edit", kwargs={"project_pk": project.pk, "node_pk": node.pk})

    def delete_url(self, node, project=None):
        project = project or node.project
        return reverse("manuscripts:delete", kwargs={"project_pk": project.pk, "node_pk": node.pk})

    def move_url(self, node, project=None):
        project = project or node.project
        return reverse("manuscripts:move", kwargs={"project_pk": project.pk, "node_pk": node.pk})

    def move_up_url(self, node, project=None):
        project = project or node.project
        return reverse("manuscripts:move_up", kwargs={"project_pk": project.pk, "node_pk": node.pk})

    def move_down_url(self, node, project=None):
        project = project or node.project
        return reverse("manuscripts:move_down", kwargs={"project_pk": project.pk, "node_pk": node.pk})

    def tree_url(self, project=None):
        project = project or self.project
        return reverse("manuscripts:tree", kwargs={"project_pk": project.pk})

    def move_payload(self, **overrides):
        payload = {
            "parent": "",
            "position": "",
        }
        payload.update(overrides)
        return payload

    def create_book_with_chapters_and_scenes(self):
        book = ManuscriptNode.objects.create(
            project=self.project,
            node_type=ManuscriptNode.NodeType.BOOK,
            title="Libro",
        )
        chapter_one = ManuscriptNode.objects.create(
            project=self.project,
            parent=book,
            node_type=ManuscriptNode.NodeType.CHAPTER,
            title="Capítulo uno",
        )
        chapter_two = ManuscriptNode.objects.create(
            project=self.project,
            parent=book,
            node_type=ManuscriptNode.NodeType.CHAPTER,
            title="Capítulo dos",
        )
        scene_one = ManuscriptNode.objects.create(
            project=self.project,
            parent=chapter_one,
            node_type=ManuscriptNode.NodeType.SCENE,
            title="Escena uno",
        )
        scene_two = ManuscriptNode.objects.create(
            project=self.project,
            parent=chapter_one,
            node_type=ManuscriptNode.NodeType.SCENE,
            title="Escena dos",
        )
        return book, chapter_one, chapter_two, scene_one, scene_two

    def test_authenticated_user_can_create_node_in_own_project(self):
        self.client.force_login(self.user)

        response = self.client.post(self.create_node_url(), self.node_payload(is_publishable="on"))

        node = ManuscriptNode.objects.get(project=self.project)
        self.assertRedirects(response, self.detail_url(node))
        self.assertEqual(node.title, "Capítulo uno")
        self.assertTrue(node.is_publishable)

    def test_unauthenticated_user_is_redirected(self):
        response = self.client.get(self.tree_url())

        self.assertRedirects(response, f"{reverse('login')}?next={self.tree_url()}")

    def test_user_cannot_create_node_in_project_from_another_user(self):
        self.client.force_login(self.user)

        response = self.client.post(self.create_node_url(self.other_project), self.node_payload())

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ManuscriptNode.objects.filter(project=self.other_project).exists())

    def test_user_cannot_see_node_from_another_user_project(self):
        node = ManuscriptNode.objects.create(project=self.other_project, title="Nodo ajeno")
        self.client.force_login(self.user)

        response = self.client.get(self.detail_url(node))

        self.assertEqual(response.status_code, 404)

    def test_parent_must_belong_to_same_project(self):
        parent = ManuscriptNode.objects.create(project=self.other_project, title="Padre ajeno")
        node = ManuscriptNode(project=self.project, parent=parent, title="Nodo inválido")

        with self.assertRaises(ValidationError):
            node.full_clean()

    def test_node_cannot_be_its_own_parent(self):
        node = ManuscriptNode.objects.create(project=self.project, title="Nodo")
        node.parent = node

        with self.assertRaises(ValidationError):
            node.full_clean()

    def test_node_cannot_use_descendant_as_parent(self):
        parent = ManuscriptNode.objects.create(project=self.project, title="Padre")
        child = ManuscriptNode.objects.create(project=self.project, parent=parent, node_type="CHAPTER", title="Hijo")
        parent.parent = child

        with self.assertRaises(ValidationError):
            parent.full_clean()

    def test_word_count_is_calculated_on_save(self):
        node = ManuscriptNode.objects.create(
            project=self.project,
            title="Conteo",
            content="Uno dos, tres. Cuatro",
        )

        self.assertEqual(node.word_count, 4)

    def test_empty_content_has_zero_word_count(self):
        node = ManuscriptNode.objects.create(project=self.project, title="Vacío", content="")

        self.assertEqual(node.word_count, 0)

    def test_missing_position_assigns_next_sibling_position(self):
        parent = ManuscriptNode.objects.create(project=self.project, title="Libro")
        first = ManuscriptNode.objects.create(project=self.project, parent=parent, node_type="CHAPTER", title="Escena uno")
        second = ManuscriptNode.objects.create(project=self.project, parent=parent, node_type="CHAPTER", title="Escena dos")

        self.assertEqual(first.position, 1)
        self.assertEqual(second.position, 2)

    def test_cannot_delete_node_with_children(self):
        parent = ManuscriptNode.objects.create(project=self.project, title="Padre")
        ManuscriptNode.objects.create(project=self.project, parent=parent, node_type="CHAPTER", title="Hijo")
        self.client.force_login(self.user)

        response = self.client.post(self.delete_url(parent))

        self.assertRedirects(response, self.detail_url(parent))
        self.assertTrue(ManuscriptNode.objects.filter(pk=parent.pk).exists())

    def test_can_delete_node_without_children(self):
        node = ManuscriptNode.objects.create(project=self.project, title="Hoja")
        self.client.force_login(self.user)

        response = self.client.post(self.delete_url(node))

        self.assertRedirects(response, self.tree_url())
        self.assertFalse(ManuscriptNode.objects.filter(pk=node.pk).exists())

    def test_cannot_create_node_in_deleted_project(self):
        self.project.status = Project.ProjectStatus.DELETED
        self.project.deleted_at = timezone.now()
        self.project.save()
        self.client.force_login(self.user)

        response = self.client.post(self.create_node_url(), self.node_payload())

        self.assertEqual(response.status_code, 404)
        self.assertFalse(ManuscriptNode.objects.filter(project=self.project).exists())

    def test_cannot_create_node_in_pending_deletion_project(self):
        self.project.mark_for_deletion()
        self.client.force_login(self.user)

        response = self.client.post(self.create_node_url(), self.node_payload())

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ManuscriptNode.objects.filter(project=self.project).exists())

    def test_tree_view_only_shows_nodes_for_current_project(self):
        own_node = ManuscriptNode.objects.create(project=self.project, title="Nodo propio")
        ManuscriptNode.objects.create(project=self.other_project, title="Nodo ajeno")
        self.client.force_login(self.user)

        response = self.client.get(self.tree_url())

        self.assertContains(response, own_node.title)
        self.assertNotContains(response, "Nodo ajeno")

    def test_is_publishable_is_saved_correctly(self):
        self.client.force_login(self.user)

        self.client.post(self.create_node_url(), self.node_payload(is_publishable="on"))

        node = ManuscriptNode.objects.get(project=self.project)
        self.assertTrue(node.is_publishable)

    def test_parent_field_is_limited_to_project_nodes(self):
        own_parent = ManuscriptNode.objects.create(project=self.project, title="Padre propio")
        other_parent = ManuscriptNode.objects.create(project=self.other_project, title="Padre ajeno")
        self.client.force_login(self.user)

        response = self.client.get(self.create_node_url(), {"parent": own_parent.pk})

        self.assertContains(response, own_parent.title)
        self.assertNotContains(response, other_parent.title)

    def test_parent_field_excludes_current_node_and_descendants(self):
        book = ManuscriptNode.objects.create(project=self.project, title="Libro")
        parent = ManuscriptNode.objects.create(project=self.project, parent=book, node_type="CHAPTER", title="Padre")
        child = ManuscriptNode.objects.create(project=self.project, parent=parent, node_type="SCENE", title="Hijo")
        sibling = ManuscriptNode.objects.create(project=self.project, title="Hermano")
        self.client.force_login(self.user)

        response = self.client.get(self.move_url(parent))
        parent_choices = response.context["form"].fields["parent"].queryset

        self.assertIn(sibling, parent_choices)
        self.assertNotIn(child, parent_choices)
        self.assertNotIn(parent, parent_choices)

    def test_can_edit_node_without_changing_project(self):
        book, chapter_one, chapter_two, node, scene_two = self.create_book_with_chapters_and_scenes()
        self.client.force_login(self.user)

        response = self.client.post(
            self.edit_url(node),
            self.node_payload(title="Nuevo título", node_type=ManuscriptNode.NodeType.SCENE),
        )

        self.assertRedirects(response, self.detail_url(node))
        node.refresh_from_db()
        self.assertEqual(node.project, self.project)
        self.assertEqual(node.title, "Nuevo título")
        self.assertEqual(node.node_type, ManuscriptNode.NodeType.SCENE)

    def test_authenticated_user_can_move_own_node(self):
        book, chapter_one, chapter_two, scene_one, scene_two = self.create_book_with_chapters_and_scenes()
        self.client.force_login(self.user)

        response = self.client.post(
            self.move_url(scene_one),
            self.move_payload(parent=chapter_two.pk, position=1),
        )

        scene_one.refresh_from_db()
        self.assertRedirects(response, self.detail_url(scene_one))
        self.assertEqual(scene_one.parent, chapter_two)
        self.assertEqual(scene_one.position, 1)

    def test_unauthenticated_user_is_redirected_from_move_view(self):
        node = ManuscriptNode.objects.create(project=self.project, title="Nodo")

        response = self.client.get(self.move_url(node))

        self.assertRedirects(response, f"{reverse('login')}?next={self.move_url(node)}")

    def test_user_cannot_move_node_from_another_user_project(self):
        node = ManuscriptNode.objects.create(project=self.other_project, title="Nodo ajeno")
        self.client.force_login(self.user)

        response = self.client.get(self.move_url(node))

        self.assertEqual(response.status_code, 404)

    def test_user_cannot_move_node_to_parent_from_another_project(self):
        book, chapter_one, chapter_two, scene_one, scene_two = self.create_book_with_chapters_and_scenes()
        other_parent = ManuscriptNode.objects.create(
            project=self.other_project,
            node_type=ManuscriptNode.NodeType.BOOK,
            title="Capítulo ajeno",
        )
        self.client.force_login(self.user)

        response = self.client.post(self.move_url(scene_one), self.move_payload(parent=other_parent.pk))

        scene_one.refresh_from_db()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(scene_one.parent, chapter_one)

    def test_user_cannot_move_node_under_itself(self):
        book = ManuscriptNode.objects.create(project=self.project, title="Libro")
        node = ManuscriptNode.objects.create(
            project=self.project,
            parent=book,
            node_type=ManuscriptNode.NodeType.CHAPTER,
            title="Capítulo",
        )
        self.client.force_login(self.user)

        response = self.client.post(self.move_url(node), self.move_payload(parent=node.pk))

        node.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(node.parent, book)

    def test_user_cannot_move_node_under_descendant(self):
        book, chapter_one, chapter_two, scene_one, scene_two = self.create_book_with_chapters_and_scenes()
        self.client.force_login(self.user)

        response = self.client.post(self.move_url(chapter_one), self.move_payload(parent=scene_one.pk))

        chapter_one.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(chapter_one.parent, book)

    def test_move_node_up_swaps_positions(self):
        book, chapter_one, chapter_two, scene_one, scene_two = self.create_book_with_chapters_and_scenes()

        move_node_up(scene_two)

        scene_one.refresh_from_db()
        scene_two.refresh_from_db()
        self.assertEqual(scene_two.position, 1)
        self.assertEqual(scene_one.position, 2)

    def test_move_node_down_swaps_positions(self):
        book, chapter_one, chapter_two, scene_one, scene_two = self.create_book_with_chapters_and_scenes()

        move_node_down(scene_one)

        scene_one.refresh_from_db()
        scene_two.refresh_from_db()
        self.assertEqual(scene_two.position, 1)
        self.assertEqual(scene_one.position, 2)

    def test_moving_node_to_another_parent_preserves_content_and_metadata(self):
        book, chapter_one, chapter_two, scene_one, scene_two = self.create_book_with_chapters_and_scenes()
        # Historical metadata is preserved by moves, even after text is versioned.
        ManuscriptNode.objects.filter(pk=scene_one.pk).update(
            content="Uno dos tres cuatro.", status=ManuscriptNode.NodeStatus.REVIEW,
            is_publishable=True, word_count=4,
        )
        scene_one.refresh_from_db()
        note = Note.objects.create(project=self.project, node=scene_one, title="Nota asociada")
        character = Character.objects.create(project=self.project, name="Ariadna")
        mention = CharacterMention.objects.create(
            character=character,
            node=scene_one,
            mention_type=CharacterMention.MentionType.APPEARS,
        )
        original_word_count = scene_one.word_count

        move_node(scene_one, chapter_two, 1)

        scene_one.refresh_from_db()
        note.refresh_from_db()
        mention.refresh_from_db()
        self.assertEqual(scene_one.parent, chapter_two)
        self.assertEqual(scene_one.content, "Uno dos tres cuatro.")
        self.assertEqual(scene_one.word_count, original_word_count)
        self.assertEqual(scene_one.status, ManuscriptNode.NodeStatus.REVIEW)
        self.assertTrue(scene_one.is_publishable)
        self.assertEqual(note.node, scene_one)
        self.assertEqual(mention.node, scene_one)

    def test_positions_are_normalized_after_move(self):
        parent = ManuscriptNode.objects.create(project=self.project, node_type=ManuscriptNode.NodeType.BOOK, title="Padre")
        first = ManuscriptNode.objects.create(
            project=self.project,
            parent=parent,
            node_type=ManuscriptNode.NodeType.CHAPTER,
            title="Uno",
            position=10,
        )
        second = ManuscriptNode.objects.create(
            project=self.project,
            parent=parent,
            node_type=ManuscriptNode.NodeType.CHAPTER,
            title="Dos",
            position=30,
        )
        third = ManuscriptNode.objects.create(
            project=self.project,
            parent=parent,
            node_type=ManuscriptNode.NodeType.CHAPTER,
            title="Tres",
            position=50,
        )

        move_node(third, parent, 1)

        ordered_titles = list(
            ManuscriptNode.objects.filter(parent=parent).order_by("position").values_list("title", "position")
        )
        self.assertEqual(ordered_titles, [("Tres", 1), ("Uno", 2), ("Dos", 3)])

    def test_cannot_move_node_in_deleted_project(self):
        node = ManuscriptNode.objects.create(project=self.project, title="Nodo")
        self.project.status = Project.ProjectStatus.DELETED
        self.project.deleted_at = timezone.now()
        self.project.save()
        self.client.force_login(self.user)

        response = self.client.post(self.move_url(node), self.move_payload(position=1))

        self.assertEqual(response.status_code, 404)

    def test_cannot_move_node_in_pending_deletion_project(self):
        node = ManuscriptNode.objects.create(project=self.project, title="Nodo")
        self.project.mark_for_deletion()
        self.client.force_login(self.user)

        response = self.client.post(self.move_url(node), self.move_payload(position=1))

        self.assertEqual(response.status_code, 403)

    def test_tree_renders_move_up_and_down_actions(self):
        book, chapter_one, chapter_two, scene_one, scene_two = self.create_book_with_chapters_and_scenes()
        self.client.force_login(self.user)

        response = self.client.get(self.tree_url())

        self.assertContains(response, "Mover")
        self.assertContains(response, "Subir")
        self.assertContains(response, "Bajar")

    def test_move_view_parent_queryset_excludes_invalid_parents(self):
        book, chapter_one, chapter_two, scene_one, scene_two = self.create_book_with_chapters_and_scenes()
        fragment = ManuscriptNode(
            project=self.project,
            node_type=ManuscriptNode.NodeType.FRAGMENT,
            title="Fragmento",
        )
        # Historic rows are imported without running the new creation policy.
        ManuscriptNode.objects.bulk_create([fragment])
        self.client.force_login(self.user)

        response = self.client.get(self.move_url(scene_one))
        parent_choices = response.context["form"].fields["parent"].queryset

        self.assertIn(chapter_two, parent_choices)
        self.assertNotIn(scene_one, parent_choices)
        self.assertNotIn(fragment, parent_choices)
