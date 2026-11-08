from io import BytesIO
from unittest.mock import patch
from xml.etree import ElementTree
from zipfile import ZipFile

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.urls import reverse
from docx import Document

from apps.core.tests.helpers import SecurityTestCase
from apps.exports.docx import build_export_docx
from apps.exports.epub import build_export_epub
from apps.exports.models import ExportJob
from apps.exports.pdf import build_export_pdf
from apps.exports.services import build_export_html, ordered_project_nodes

from .forms import ManuscriptNodeForm
from .hierarchy import ALLOWED_CHILD_TYPES, editable_node_ids, load_structure
from .models import ManuscriptNode
from .services import get_valid_parent_queryset, move_node, move_node_down, move_node_up, normalize_positions


class HierarchyTests(SecurityTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.book_b = ManuscriptNode.objects.create(project=cls.project, title="Book B")
        cls.part_a = ManuscriptNode.objects.create(project=cls.project, parent=cls.book, node_type="PART", title="Part A")
        cls.part_b = ManuscriptNode.objects.create(project=cls.project, parent=cls.book_b, node_type="PART", title="Part B")
        cls.chapter = move_node(cls.chapter, cls.part_a)
        cls.chapter2 = ManuscriptNode.objects.create(project=cls.project, parent=cls.part_a, node_type="CHAPTER", title="Chapter 2")
        cls.chapter3 = ManuscriptNode.objects.create(project=cls.project, parent=cls.book, node_type="CHAPTER", title="Chapter 3")
        cls.chapter4 = ManuscriptNode.objects.create(project=cls.project, parent=cls.part_b, node_type="CHAPTER", title="Chapter 4")
        cls.scene2 = ManuscriptNode.objects.create(project=cls.project, parent=cls.chapter, node_type="SCENE", title="Scene 2", content="Original scene two.")

    def create(self, kind, parent=None, **kwargs):
        return ManuscriptNode.objects.create(project=self.project, parent=parent, node_type=kind, **{"title": kind, **kwargs})

    def legacy(self, **kwargs):
        node = ManuscriptNode(project=self.project, node_type="FRAGMENT", title="Legacy fragment", position=99, **kwargs)
        ManuscriptNode.objects.bulk_create([node])
        return node

    def assert_invalid(self, operation):
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            operation()
        self.assertEqual(self.snapshot(), before)

    def assert_positions(self):
        groups = {}
        for parent, position in ManuscriptNode.objects.filter(project=self.project).order_by("position").values_list("parent_id", "position"):
            groups.setdefault(parent, []).append(position)
        for parent, positions in groups.items():
            self.assertEqual(positions, list(range(1, len(positions) + 1)), parent)

    def test_book_root_is_valid_and_multiple_books_are_allowed(self):
        self.assertIsNone(self.create("BOOK").parent)

    def test_book_cannot_have_parent(self):
        self.assert_invalid(lambda: self.create("BOOK", self.book))

    def test_part_under_book_is_valid(self):
        self.assertEqual(self.create("PART", self.book).parent, self.book)

    def test_part_under_chapter_is_rejected(self):
        self.assert_invalid(lambda: self.create("PART", self.chapter))

    def test_chapter_under_book_is_valid(self):
        self.assertEqual(self.create("CHAPTER", self.book).parent, self.book)

    def test_chapter_under_part_is_valid(self):
        self.assertEqual(self.create("CHAPTER", self.part_a).parent, self.part_a)

    def test_chapter_root_is_rejected(self):
        self.assert_invalid(lambda: self.create("CHAPTER"))

    def test_scene_under_chapter_is_valid(self):
        self.assertEqual(self.create("SCENE", self.chapter).parent, self.chapter)

    def test_scene_under_book_is_rejected(self):
        self.assert_invalid(lambda: self.create("SCENE", self.book))

    def test_scene_under_part_is_rejected(self):
        self.assert_invalid(lambda: self.create("SCENE", self.part_a))

    def test_scene_cannot_have_children(self):
        for kind in ManuscriptNode.NodeType.values:
            with self.subTest(kind=kind):
                self.assert_invalid(lambda: self.create(kind, self.scene))

    def test_new_fragment_is_rejected_by_model(self):
        self.assert_invalid(lambda: self.create("FRAGMENT", self.chapter))

    def test_full_parent_child_matrix(self):
        parents = (None, self.book, self.part_a, self.chapter, self.scene)
        for parent in parents:
            for kind in ManuscriptNode.NodeType.values:
                expected = kind == "BOOK" if parent is None else kind in ALLOWED_CHILD_TYPES[parent.node_type]
                node = ManuscriptNode(project=self.project, parent=parent, node_type=kind, title=kind)
                with self.subTest(parent=parent, kind=kind):
                    if expected:
                        node.full_clean()
                    else:
                        with self.assertRaises(ValidationError):
                            node.full_clean()

    def test_node_requires_project(self):
        with self.assertRaises(ValidationError):
            ManuscriptNode(title="Missing project").full_clean()

    def test_parent_from_other_project_is_rejected(self):
        self.assert_invalid(lambda: self.create("CHAPTER", self.other_node))

    def test_model_cannot_change_existing_project(self):
        self.scene.project = self.other_project
        self.assert_invalid(self.scene.full_clean)
        self.assert_invalid(self.scene.save)

    def test_type_change_cannot_invalidate_children(self):
        self.chapter.node_type = "SCENE"
        self.chapter.parent = self.chapter4
        self.assert_invalid(self.chapter.save)

    def test_move_rejects_invalid_descendants_without_repair(self):
        self.legacy(parent=self.scene, content="Preserve me")
        self.assert_invalid(lambda: move_node(self.scene, self.chapter4))

    def test_move_to_self_is_rejected(self):
        self.assert_invalid(lambda: move_node(self.chapter, self.chapter))

    def test_move_to_descendant_is_rejected(self):
        self.assert_invalid(lambda: move_node(self.part_a, self.scene))

    def test_move_between_projects_is_rejected(self):
        self.assert_invalid(lambda: move_node(self.chapter, self.other_node))

    def test_scene_move_preserves_identity_content_and_all_references(self):
        ExportJob.objects.filter(pk=self.job.pk).update(root_node=self.scene, status="DONE", file="historical.html")
        before = ManuscriptNode.objects.values().get(pk=self.scene.pk)
        references = (self.note.node_id, self.mention.node_id)
        moved = move_node(self.scene, self.chapter4, user=self.user)
        after = ManuscriptNode.objects.values().get(pk=moved.pk)
        for field in before.keys() - {"parent_id", "position", "updated_at"}:
            self.assertEqual(after[field], before[field], field)
        self.note.refresh_from_db()
        self.mention.refresh_from_db()
        self.job.refresh_from_db()
        self.assertEqual((self.note.node_id, self.mention.node_id), references)
        self.assertEqual(self.job.root_node_id, self.scene.pk)
        self.assertEqual(self.job.status, "DONE")
        self.assertEqual(self.job.file.name, "historical.html")
        self.assertEqual(moved.parent, self.chapter4)
        self.assert_positions()

    def test_chapter_moves_between_parts_with_same_id(self):
        moved = move_node(self.chapter, self.part_b)
        self.assertEqual(moved.pk, self.chapter.pk)
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.parent_id, moved.pk)
        self.assert_positions()

    def test_chapter_moves_from_part_to_book_with_same_id(self):
        self.assertEqual(move_node(self.chapter, self.book_b).pk, self.chapter.pk)
        self.assert_positions()

    def test_part_moves_between_books_with_same_id(self):
        self.assertEqual(move_node(self.part_a, self.book_b).pk, self.part_a.pk)
        self.chapter.refresh_from_db()
        self.assertEqual(self.chapter.parent_id, self.part_a.pk)
        self.assert_positions()

    def test_move_up(self):
        self.assertEqual(move_node_up(self.scene2).position, 1)
        self.assert_positions()

    def test_move_down(self):
        self.assertEqual(move_node_down(self.scene).position, 2)
        self.assert_positions()

    def test_model_create_and_save_positions_are_unique(self):
        first = self.create("SCENE", self.chapter, position=1)
        second = self.create("SCENE", self.chapter, position=1)
        first.refresh_from_db()
        first.position = 1
        first.save()
        self.assert_positions()
        self.assertTrue(ManuscriptNode.objects.filter(pk=second.pk).exists())

    def test_normalization_runs_under_policy_and_keeps_content(self):
        ManuscriptNode.objects.filter(pk__in=[self.scene.pk, self.scene2.pk]).update(position=8)
        before = list(ManuscriptNode.objects.filter(project=self.project).order_by("pk").values_list("pk", "content", "status"))
        normalize_positions(self.project, self.chapter)
        self.assert_positions()
        self.assertEqual(list(ManuscriptNode.objects.filter(project=self.project).order_by("pk").values_list("pk", "content", "status")), before)

    def test_delete_normalizes_remaining_siblings(self):
        pk = self.scene.pk
        self.scene.delete()
        self.assertFalse(ManuscriptNode.objects.filter(pk=pk).exists())
        self.assert_positions()

    def test_move_rolls_back_both_groups_on_write_failure(self):
        from .services import _write_positions

        calls = 0
        def fail_second(siblings, using):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected failure")
            return _write_positions(siblings, using)
        before = self.snapshot()
        with patch("apps.manuscripts.services._write_positions", side_effect=fail_second), self.assertRaises(RuntimeError):
            move_node(self.scene, self.chapter4)
        self.assertEqual(self.snapshot(), before)

    def test_readonly_project_states_block_all_structural_services(self):
        for status in ("FROZEN", "PENDING_DELETION", "DELETED"):
            self.set_status(status)
            for operation in (lambda: move_node(self.scene, self.chapter4), lambda: move_node_up(self.scene),
                              lambda: move_node_down(self.scene), lambda: normalize_positions(self.project, self.chapter),
                              self.scene.save, self.scene.delete):
                with self.subTest(status=status):
                    self.assert_invalid(operation)

    def test_authorized_service_rejects_foreign_user(self):
        from django.http import Http404

        with self.assertRaises(Http404):
            move_node(self.scene, self.chapter4, user=self.other_user)

    def test_scene_title_is_optional_and_label_not_persisted(self):
        node = self.create("SCENE", self.chapter, title="")
        self.assertEqual(node.title, "")
        self.assertEqual(node.display_title, f"Escena {node.position}")
        move_node_up(node)
        node.refresh_from_db()
        self.assertEqual(node.title, "")
        self.assertEqual(str(node), f"Escena {node.position}")

    def test_container_titles_are_required(self):
        for kind, parent in (("BOOK", None), ("PART", self.book), ("CHAPTER", self.part_a)):
            for title in ("", "   "):
                with self.subTest(kind=kind, title=title):
                    self.assert_invalid(lambda: self.create(kind, parent, title=title))

    def test_short_description_saves_and_displays_safely(self):
        self.scene.short_description = '<script>alert("description")</script>'
        self.scene.save()
        response = self.client.get(self.url("manuscripts:detail", node_pk=self.scene.pk))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>")
        self.scene.refresh_from_db()
        self.assertTrue(self.scene.short_description.startswith("<script>"))

    def test_description_can_be_created_and_edited_through_forms(self):
        payload = {"parent": self.chapter.pk, "node_type": "SCENE", "title": "", "short_description": "Brief description", "status": "DRAFT"}
        form = ManuscriptNodeForm(payload, project=self.project)
        self.assertTrue(form.is_valid(), form.errors)
        node = form.save()
        form = ManuscriptNodeForm({**payload, "short_description": "Changed"}, project=self.project, instance=node)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().short_description, "Changed")

    def test_edit_form_does_not_accept_structural_fields(self):
        payload = {"title": "Changed", "status": "DRAFT", "content": "Text", "parent": self.chapter4.pk, "node_type": "BOOK", "position": 99}
        form = ManuscriptNodeForm(payload, project=self.project, instance=self.scene)
        self.assertTrue(form.is_valid(), form.errors)
        node = form.save()
        self.assertEqual((node.parent_id, node.node_type), (self.chapter.pk, "SCENE"))
        self.assertNotIn("parent", form.fields)

    def test_stale_text_instance_does_not_undo_committed_move(self):
        stale = ManuscriptNode.objects.get(pk=self.scene.pk)
        move_node(self.scene, self.chapter4)
        stale.content = "Edited after move."
        stale.save()
        stale.refresh_from_db()
        self.assertEqual(stale.parent_id, self.chapter4.pk)
        self.assertEqual(stale.word_count, 3)
        self.assert_positions()

    def test_stale_structural_change_is_rejected(self):
        stale = ManuscriptNode.objects.get(pk=self.scene.pk)
        move_node(self.scene, self.chapter4)
        stale.parent = self.chapter2
        self.assert_invalid(stale.save)

    def test_reloaded_moved_instance_can_be_edited(self):
        moved = move_node(self.scene, self.chapter4)
        moved.content = "New text"
        moved.save()
        self.assertEqual(moved.word_count, 2)

    def test_legacy_fragment_is_readable_exportable_and_immutable(self):
        legacy = self.legacy(parent=self.chapter, content="Exact legacy text.\n\n")
        before = self.snapshot()
        self.assertContains(self.client.get(self.url("manuscripts:tree")), "Legacy fragment")
        self.assertContains(self.client.get(self.url("manuscripts:detail", node_pk=legacy.pk)), "Exact legacy text.")
        self.job.root_node = legacy
        self.assertIn("Exact legacy text.", build_export_html(self.job))
        for action in ("edit", "move", "delete", "move_up", "move_down"):
            self.assertEqual(self.client.post(self.url(f"manuscripts:{action}", node_pk=legacy.pk), {}).status_code, 403)
        for operation in (legacy.save, legacy.delete, lambda: move_node(legacy, self.chapter4)):
            self.assert_invalid(operation)
        legacy.node_type = "SCENE"
        self.assert_invalid(legacy.save)
        self.assertEqual(self.snapshot(), before)

    def test_new_fragment_rejected_in_form_and_admin_choices(self):
        form = ManuscriptNodeForm({"node_type": "FRAGMENT", "title": "No", "status": "DRAFT"}, project=self.project)
        self.assertFalse(form.is_valid())
        request = RequestFactory().get("/admin/")
        request.user = self.user
        choices = admin.site._registry[ManuscriptNode].formfield_for_choice_field(ManuscriptNode._meta.get_field("node_type"), request).choices
        self.assertNotIn("FRAGMENT", dict(choices))

    def test_legacy_order_is_not_rewritten_as_a_side_effect(self):
        self.legacy(parent=self.chapter, content="Keep")
        self.assert_invalid(lambda: normalize_positions(self.project, self.chapter))
        self.assert_invalid(lambda: move_node(self.scene2, self.chapter4))

    def test_legacy_root_blocks_structural_controls_but_not_reading(self):
        leaf = self.create("BOOK", title="Leaf book")
        self.legacy()
        response = self.client.get(self.url("manuscripts:tree"))
        self.assertFalse(response.context["can_create_book"])
        rows = {row["node"].pk: row for row in response.context["tree_rows"]}
        self.assertFalse(rows[leaf.pk]["can_delete"])
        self.assertTrue(rows[leaf.pk]["editable"])
        self.user.is_staff = self.user.is_superuser = True
        request = RequestFactory().get("/admin/")
        request.user = self.user
        self.assertFalse(admin.site._registry[ManuscriptNode].has_delete_permission(request, leaf))

    def test_admin_create_beside_legacy_root_returns_form_error_without_writes(self):
        self.legacy()
        before = self.snapshot()
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        response = self.client.post(reverse("admin:manuscripts_manuscriptnode_add"), {
            "project": self.project.pk, "node_type": "BOOK", "title": "Blocked",
            "status": "DRAFT", "position": 1, "_save": "Save",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["adminform"].form.non_field_errors())
        self.assertEqual(self.snapshot(), before)

    def test_legacy_foreign_parent_stays_readable_without_leaking_parent(self):
        ManuscriptNode.objects.filter(pk=self.scene.pk).update(parent=self.other_node)
        before = self.snapshot()
        for name, kwargs in (("manuscripts:tree", {}), ("manuscripts:detail", {"node_pk": self.scene.pk})):
            response = self.client.get(self.url(name, **kwargs))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, self.other_node.title)
        self.assertContains(response, self.scene.content)
        self.assertEqual(self.snapshot(), before)

    def test_legacy_cycles_are_listed_and_exported_once(self):
        ManuscriptNode.objects.filter(pk=self.book.pk).update(parent=self.scene)
        before = self.snapshot()
        response = self.client.get(self.url("manuscripts:tree"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Legado")
        self.assertEqual(len(response.context["tree_rows"]), ManuscriptNode.objects.filter(project=self.project).count())
        exported = ordered_project_nodes(self.project)
        self.assertEqual(len(exported), len({node.pk for node in exported}))
        self.assertEqual(self.snapshot(), before)

    def test_parent_choices_follow_matrix_and_owner(self):
        choices = get_valid_parent_queryset(self.project, self.scene)
        self.assertIn(self.chapter4, choices)
        self.assertNotIn(self.book, choices)
        self.assertNotIn(self.part_a, choices)
        self.assertFalse(get_valid_parent_queryset(self.project, self.book).exists())

    def test_create_child_view_prefills_parent_and_allowed_types(self):
        response = self.client.get(self.url("manuscripts:create"), {"parent": self.chapter.pk})
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial["parent"], self.chapter)
        self.assertEqual(dict(form.fields["node_type"].choices), {"SCENE": "Escena"})
        self.assertFalse(form.fields["title"].required)
        self.assertEqual(self.client.get(self.url("manuscripts:create"), {"parent": self.scene.pk}).status_code, 403)

    def test_tree_only_shows_valid_actions(self):
        response = self.client.get(self.url("manuscripts:tree"))
        rows = {row["node"].pk: row for row in response.context["tree_rows"]}
        self.assertFalse(rows[self.scene.pk]["can_create_child"])
        self.assertFalse(rows[self.book.pk]["can_delete"])
        self.assertTrue(rows[self.chapter4.pk]["can_create_child"])
        self.assertTrue(rows[self.scene.pk]["can_delete"])

    def test_export_order_and_headings_work_with_optional_parts(self):
        ordered = ordered_project_nodes(self.project)
        by_id = {node.pk: node for node in ordered}
        self.assertEqual(by_id[self.scene.pk].export_depth, 3)
        self.assertEqual(by_id[self.chapter3.pk].export_depth, 1)
        self.job.root_node = None
        html = build_export_html(self.job)
        indices = [html.index(f'id="node-{node.pk}"') for node in ordered]
        self.assertEqual(indices, sorted(indices))
        self.assertIn(f"<h4>{self.scene.title}</h4>", html)

    def test_docx_epub_and_pdf_accept_both_hierarchy_paths(self):
        self.create("SCENE", self.chapter3, title="", content="Direct chapter scene.")
        self.job.root_node = None
        ordered = ordered_project_nodes(self.project)
        doc = Document(BytesIO(build_export_docx(self.job)))
        self.assertEqual([p.text for p in doc.paragraphs if p.style.name.startswith("Heading")], [node.display_title for node in ordered])
        with ZipFile(BytesIO(build_export_epub(self.job))) as archive:
            package = ElementTree.fromstring(archive.read("EPUB/content.opf"))
            spine = package.find("{*}spine")
            self.assertEqual([item.attrib["idref"] for item in spine if item.attrib["idref"] != "nav"], [f"node-{node.pk}" for node in ordered])
        self.assertTrue(build_export_pdf(self.job).startswith(b"%PDF"))

    def test_movement_does_not_recount_or_rewrite_content(self):
        ManuscriptNode.objects.filter(pk=self.scene.pk).update(word_count=123, content="  Unicode: niña.\r\n\t")
        moved = move_node(self.scene, self.chapter4)
        self.assertEqual(moved.word_count, 123)
        self.assertEqual(moved.content, "  Unicode: niña.\r\n\t")
