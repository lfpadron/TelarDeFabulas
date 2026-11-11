from unittest.mock import patch
from uuid import uuid4

from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.http import Http404
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.characters.forms import CharacterMentionForm
from apps.characters.models import CharacterMention
from apps.core.tests.helpers import SecurityTestCase
from apps.exports.forms import ExportJobForm, ExportPreviewForm
from apps.exports.job_services import request_export
from apps.exports.models import ExportJob
from apps.exports.services import build_export_html, ordered_project_nodes
from apps.exports.snapshots import build_manifest, get_export_document
from apps.notes.forms import NoteForm
from apps.notes.models import Note
from apps.references.forms import AssociationForm
from apps.references.models import ReferenceAssociation
from apps.references.services import attach_reference, create_reference
from apps.references.selectors import project_associations

from .models import ManuscriptNode, SceneVersion
from .services import get_valid_parent_queryset, move_node, move_node_down
from .trash import get_trash_items, restore_node, soft_delete_node
from .trash_views import RestoreNodeForm
from .version_services import create_scene_version, finalize_scene_version, get_current_draft_version, get_scene_content_for_export, update_scene_version
from .visibility import get_visible_manuscript_tree


class ManuscriptTrashTests(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.part = ManuscriptNode.objects.create(project=self.project, parent=self.book, node_type="PART", title="Part")
        self.chapter = move_node(self.chapter, self.part)
        self.other_chapter = ManuscriptNode.objects.create(project=self.project, parent=self.book, node_type="CHAPTER", title="Destination")
        self.scene2 = ManuscriptNode.objects.create(project=self.project, parent=self.chapter, node_type="SCENE", title="Scene B", content="TEXT_B")
        v1 = get_current_draft_version(self.scene)
        self.final = finalize_scene_version(self.scene, v1, user=self.user, expected_revision=v1.revision)
        self.draft = create_scene_version(self.scene, user=self.user, content="TEXT_A_DRAFT")
        v2 = get_current_draft_version(self.scene2)
        finalize_scene_version(self.scene2, v2, user=self.user, expected_revision=v2.revision)
        self.scene.refresh_from_db()
        self.before_versions = list(SceneVersion.objects.order_by("pk").values())

    def visible_ids(self):
        return set(ManuscriptNode.objects.filter(project=self.project).visible().values_list("pk", flat=True))

    def remove(self, node=None):
        return soft_delete_node(node or self.scene, user=self.user)

    def restore(self, node=None, **kwargs):
        return restore_node(node or self.scene, user=self.user, **kwargs)

    def assert_versions(self):
        self.assertEqual(list(SceneVersion.objects.order_by("pk").values()), self.before_versions)
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.current_draft_version_id, self.draft.pk)
        self.assertEqual(self.scene.versions.get(is_current_final=True).pk, self.final.pk)

    def assert_roundtrip(self, node):
        ids = set(ManuscriptNode.objects.values_list("pk", flat=True))
        subtree = {node.pk, *node.descendant_ids()}
        self.remove(node)
        self.assertFalse(subtree & self.visible_ids())
        self.restore(node)
        self.assertTrue(subtree <= self.visible_ids())
        self.assertEqual(set(ManuscriptNode.objects.values_list("pk", flat=True)), ids)
        self.assert_versions()

    def test_scene_roundtrip_preserves_identity_and_all_versions(self):
        self.assert_roundtrip(self.scene)

    def test_chapter_roundtrip_restores_active_subtree(self):
        self.assert_roundtrip(self.chapter)

    def test_part_roundtrip_restores_active_subtree(self):
        self.assert_roundtrip(self.part)

    def test_book_roundtrip_restores_active_subtree(self):
        self.assert_roundtrip(self.book)

    def test_only_direct_root_is_stamped(self):
        self.remove(self.chapter)
        self.scene.refresh_from_db()
        self.assertIsNone(self.scene.deleted_at)
        self.assertIsNone(self.scene.deleted_by_id)
        self.assertEqual(ManuscriptNode.objects.filter(deleted_at__isnull=False).count(), 1)

    def test_actor_and_date_recorded(self):
        node = self.remove()
        self.assertIsNotNone(node.deleted_at)
        self.assertEqual(node.deleted_by, self.user)

    def test_delete_is_idempotent(self):
        first = self.remove().deleted_at
        self.assertEqual(self.remove().deleted_at, first)
        self.assert_versions()

    def test_restore_is_idempotent_and_does_not_move_active_node(self):
        self.remove()
        current = self.restore()
        before = ManuscriptNode.objects.values().get(pk=current.pk)
        self.restore(new_parent=self.other_chapter)
        self.assertEqual(ManuscriptNode.objects.values().get(pk=current.pk), before)

    def test_previous_scene_deletion_survives_chapter_restore(self):
        first = self.remove().deleted_at
        self.remove(self.chapter)
        self.restore(self.chapter)
        self.assertNotIn(self.scene.pk, self.visible_ids())
        self.assertIn(self.scene2.pk, self.visible_ids())
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.deleted_at, first)
        self.restore()
        self.assert_versions()

    def test_nested_independent_deletions_remain_separate(self):
        self.remove()
        self.remove(self.chapter)
        self.remove(self.book)
        self.restore(self.book)
        self.assertNotIn(self.chapter.pk, self.visible_ids())
        self.restore(self.chapter)
        self.assertNotIn(self.scene.pk, self.visible_ids())

    def test_hidden_child_can_restore_under_new_parent_without_restoring_ancestor(self):
        self.remove(self.chapter)
        self.assertEqual(self.restore(new_parent=self.other_chapter).pk, self.scene.pk)
        self.assertIn(self.scene.pk, self.visible_ids())
        self.assertNotIn(self.chapter.pk, self.visible_ids())
        self.assertNotIn(self.scene2.pk, self.visible_ids())
        self.assert_versions()

    def test_direct_child_can_restore_under_new_parent(self):
        self.remove()
        self.remove(self.chapter)
        self.restore(new_parent=self.other_chapter)
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.parent_id, self.other_chapter.pk)
        self.assertIsNone(self.scene.deleted_at)

    def test_deleted_original_parent_requires_destination(self):
        self.remove(self.chapter)
        with self.assertRaises(ValidationError):
            self.restore()
        self.assertNotIn(self.scene.pk, self.visible_ids())

    def test_invalid_parent_type_rejected_atomically(self):
        self.remove()
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            self.restore(new_parent=self.book)
        self.assertEqual(self.snapshot(), before)

    def test_cross_project_parent_rejected(self):
        self.remove(self.book)
        with self.assertRaises(ValidationError):
            self.restore(self.book, new_parent=self.other_node)
        self.assertNotIn(self.book.pk, self.visible_ids())

    def test_self_parent_rejected(self):
        self.remove(self.chapter)
        with self.assertRaises(ValidationError):
            self.restore(self.chapter, new_parent=self.chapter)

    def test_descendant_parent_rejected(self):
        self.remove(self.book)
        with self.assertRaises(ValidationError):
            self.restore(self.book, new_parent=self.chapter)
        self.assert_versions()

    def test_scene_cannot_restore_at_project_root(self):
        self.remove()
        with self.assertRaises(ValidationError):
            self.restore(new_parent=None)

    def test_restore_rolls_back_on_position_failure(self):
        self.remove()
        before = self.snapshot()
        with patch("apps.manuscripts.services._write_positions", side_effect=RuntimeError("test")):
            with self.assertRaises(RuntimeError):
                self.restore()
        self.assertEqual(self.snapshot(), before)

    def test_positions_normalized_after_delete_and_restore(self):
        self.remove()
        self.scene2.refresh_from_db()
        self.assertEqual(self.scene2.position, 1)
        self.restore(position=1)
        self.assertEqual(list(ManuscriptNode.objects.filter(parent=self.chapter).visible().order_by("position").values_list("position", flat=True)), [1, 2])

    def test_position_clamped_without_overwriting_existing_node(self):
        self.remove()
        self.restore(position=999)
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.position, 2)
        self.assert_versions()

    def test_notes_mentions_and_references_remain_linked(self):
        ref = create_reference(self.project, user=self.user, title="Source", material_type="BIBLIOGRAPHY")
        assoc = attach_reference(ref, self.scene, user=self.user)
        before = {model: list(model.objects.values()) for model in (Note, CharacterMention, ReferenceAssociation)}
        self.remove(self.book)
        self.restore(self.book)
        for model, rows in before.items():
            self.assertEqual(list(model.objects.values()), rows)
        self.assertEqual(assoc.manuscript_node_id, self.scene.pk)

    def test_stale_save_cannot_resurrect_hidden_node(self):
        self.remove(self.chapter)
        self.scene.title = "Stale edit"
        with self.assertRaises(ValidationError):
            self.scene.save()
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.title, "Scene")

    def test_direct_tombstone_assignment_cannot_bypass_service(self):
        self.scene.deleted_by = self.user
        with self.assertRaises(ValidationError):
            self.scene.save()

    def test_hidden_node_cannot_move(self):
        self.remove(self.chapter)
        with self.assertRaises(ValidationError):
            move_node(self.scene, self.other_chapter, user=self.user)

    def test_active_node_cannot_move_under_hidden_parent(self):
        self.remove(self.part)
        with self.assertRaises(ValidationError):
            move_node(self.other_chapter, self.part, user=self.user)

    def test_hidden_node_cannot_receive_new_child(self):
        self.remove(self.chapter)
        with self.assertRaises(ValidationError):
            ManuscriptNode.objects.create(project=self.project, parent=self.chapter, node_type="SCENE")

    def test_hidden_scene_cannot_receive_new_version(self):
        self.remove(self.chapter)
        with self.assertRaises(ValidationError):
            create_scene_version(self.scene, user=self.user, content="Forbidden")
        self.assert_versions()

    def test_hidden_scene_cannot_edit_version(self):
        self.remove(self.chapter)
        with self.assertRaises(ValidationError):
            update_scene_version(self.scene, self.draft, user=self.user, expected_revision=self.draft.revision, content="Forbidden")
        self.assert_versions()

    def test_hidden_scene_cannot_finalize_version(self):
        self.remove(self.chapter)
        with self.assertRaises(ValidationError):
            finalize_scene_version(self.scene, self.draft, user=self.user, expected_revision=self.draft.revision)
        self.assert_versions()

    def test_new_note_and_mention_for_hidden_node_rejected(self):
        self.remove(self.chapter)
        with self.assertRaises(ValidationError):
            Note.objects.create(project=self.project, node=self.scene, title="Forbidden")
        with self.assertRaises(ValidationError):
            CharacterMention.objects.create(character=self.character, node=self.scene, mention_type="POV")

    def test_new_reference_for_hidden_node_rejected(self):
        ref = create_reference(self.project, user=self.user, title="Source", material_type="BIBLIOGRAPHY")
        self.remove(self.chapter)
        with self.assertRaises(ValidationError):
            attach_reference(ref, self.scene, user=self.user)

    def test_normal_tree_excludes_hidden_nodes(self):
        self.remove(self.chapter)
        response = self.client.get(self.url("manuscripts:tree"))
        self.assertNotIn(self.scene.pk, {row["node"].pk for row in response.context["tree_rows"]})
        self.assertNotIn(self.scene.pk, {node.pk for node, depth in get_visible_manuscript_tree(self.project)})

    def test_normal_details_and_version_history_return_404(self):
        self.remove(self.chapter)
        for name in ("detail", "edit", "move", "delete", "version_history"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(self.url(f"manuscripts:{name}", node_pk=self.scene.pk)).status_code, 404)
        self.assertEqual(self.client.get(self.url("manuscripts:version_detail", node_pk=self.scene.pk, version_pk=self.draft.pk)).status_code, 404)

    def test_all_normal_selectors_exclude_hidden_nodes(self):
        self.remove(self.chapter)
        queries = [NoteForm(project=self.project).fields["node"].queryset,
                   CharacterMentionForm(project=self.project).fields["node"].queryset,
                   ExportJobForm(project=self.project, user=self.user).fields["root_node"].queryset,
                   ExportPreviewForm(project=self.project, user=self.user).fields["root_node"].queryset,
                   AssociationForm(project=self.project).fields["manuscript_node"].queryset,
                   get_valid_parent_queryset(self.project, node_type="SCENE")]
        for query in queries:
            self.assertFalse(query.filter(pk__in=[self.chapter.pk, self.scene.pk, self.scene2.pk]).exists())

    def test_normal_notes_and_mentions_hidden_then_reappear(self):
        self.remove(self.chapter)
        self.assertEqual(self.client.get(self.url("notes:detail", note_pk=self.note.pk)).status_code, 404)
        response = self.client.get(self.url("characters:detail", character_pk=self.character.pk))
        self.assertEqual(list(response.context["character_mentions"]), [])
        self.assertEqual(list(response.context["linked_notes"]), [])
        self.restore(self.chapter)
        self.assertEqual(self.client.get(self.url("notes:detail", note_pk=self.note.pk)).status_code, 200)

    def test_reference_link_hidden_without_removing_association(self):
        ref = create_reference(self.project, user=self.user, title="Source", material_type="BIBLIOGRAPHY")
        link = attach_reference(ref, self.scene, user=self.user)
        self.remove(self.chapter)
        self.assertFalse(project_associations(self.project).filter(pk=link.pk).exists())
        self.assertTrue(ReferenceAssociation.objects.filter(pk=link.pk).exists())
        self.restore(self.chapter)
        self.assertTrue(project_associations(self.project).filter(pk=link.pk).exists())

    def test_work_excludes_deleted_scene(self):
        self.remove()
        manifest = build_manifest(self.project, self.style)
        self.assertNotIn(self.scene.pk, {row["node_id"] for row in manifest["ordered_nodes"]})

    def test_final_excludes_deleted_scene(self):
        self.remove()
        manifest = build_manifest(self.project, self.style, mode="FINAL")
        self.assertNotIn(self.scene.pk, {row["node_id"] for row in manifest["ordered_nodes"]})
        self.assertIn(self.scene2.pk, {row["node_id"] for row in manifest["ordered_nodes"]})

    def test_work_excludes_descendants_of_deleted_chapter(self):
        self.remove(self.chapter)
        manifest = build_manifest(self.project, self.style)
        self.assertFalse({self.scene.pk, self.scene2.pk} & {row["node_id"] for row in manifest["ordered_nodes"]})

    def test_final_without_visible_final_is_rejected(self):
        self.remove(self.chapter)
        with self.assertRaises(ValidationError):
            build_manifest(self.project, self.style, mode="FINAL")

    def test_preview_excludes_hidden_content(self):
        self.remove(self.chapter)
        response = self.client.get(self.url("exports:preview"), {"style_template": self.style.pk})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "TEXT_A_DRAFT")
        self.assertNotContains(response, "TEXT_B")

    def test_hidden_export_root_is_rejected(self):
        self.remove(self.chapter)
        with self.assertRaises(Http404):
            request_export(user=self.user, project=self.project, style_template=self.style, root_node=self.scene, request_key=uuid4())

    def test_old_snapshot_and_export_links_survive(self):
        job = request_export(user=self.user, project=self.project, style_template=self.style, root_node=self.scene, request_key=uuid4())
        before = (job.snapshot.manifest_json, job.snapshot.checksum)
        self.remove(self.book)
        job.refresh_from_db()
        self.assertEqual(job.root_node_id, self.scene.pk)
        self.assertEqual((job.snapshot.manifest_json, job.snapshot.checksum), before)
        self.assertIn("TEXT_A_DRAFT", build_export_html(job))
        self.assertEqual(get_export_document(job).nodes[0].node_id, self.scene.pk)

    def test_legacy_export_selector_excludes_hidden_nodes(self):
        self.remove(self.chapter)
        self.assertNotIn(self.scene.pk, {node.pk for node in ordered_project_nodes(self.project)})

    def test_owner_trash_has_basic_metadata_and_no_scene_prose(self):
        self.remove(self.chapter)
        response = self.client.get(self.url("manuscripts:trash"))
        self.assertContains(response, "Oculto por ancestro")
        self.assertNotContains(response, "TEXT_A_DRAFT")
        items = {item["node"].pk: item for item in get_trash_items(self.project, user=self.user)}
        self.assertEqual(items[self.chapter.pk]["affected_count"], 2)
        self.assertEqual(items[self.scene.pk]["location"], "Book / Part / Chapter")
        self.assertFalse(items[self.scene.pk]["direct"])

    def test_affected_count_excludes_previously_deleted_subtree(self):
        self.remove()
        self.remove(self.chapter)
        item = next(item for item in get_trash_items(self.project, user=self.user) if item["node"].pk == self.chapter.pk)
        self.assertEqual(item["affected_count"], 1)

    def test_trash_detail_is_readonly_and_escaped(self):
        self.scene.title = "<script>bad</script>"
        self.scene.save()
        self.remove()
        response = self.client.get(self.url("manuscripts:trash_detail", node_pk=self.scene.pk))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "TEXT_A_DRAFT")
        self.assertNotContains(response, "<textarea")

    def test_foreign_user_cannot_read_or_restore(self):
        self.remove()
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(self.url("manuscripts:trash")).status_code, 404)
        for method in (self.client.get, self.client.post):
            self.assertEqual(method(self.url("manuscripts:trash_restore", node_pk=self.scene.pk)).status_code, 404)
        with self.assertRaises(Http404):
            restore_node(self.scene, user=self.other_user)
        with self.assertRaises(Http404):
            soft_delete_node(self.scene, user=self.other_user)

    def test_frozen_trash_readonly(self):
        self.check_readonly("FROZEN")

    def test_pending_deletion_trash_readonly(self):
        self.check_readonly("PENDING_DELETION")

    def check_readonly(self, status):
        self.remove()
        self.set_status(status)
        self.assertEqual(self.client.get(self.url("manuscripts:trash")).status_code, 200)
        self.assertEqual(self.client.post(self.url("manuscripts:trash_restore", node_pk=self.scene.pk)).status_code, 403)
        with self.assertRaises(PermissionDenied):
            self.restore()
        with self.assertRaises(PermissionDenied):
            self.remove(self.scene2)

    def test_deleted_project_trash_inaccessible(self):
        self.remove()
        self.set_status("DELETED")
        self.assertEqual(self.client.get(self.url("manuscripts:trash")).status_code, 404)
        self.assertEqual(self.client.post(self.url("manuscripts:trash_restore", node_pk=self.scene.pk)).status_code, 404)

    def test_get_restore_is_confirmation_only(self):
        self.remove()
        response = self.client.get(self.url("manuscripts:trash_restore", node_pk=self.scene.pk))
        self.assertContains(response, "Confirmar restauración")
        self.assertNotIn(self.scene.pk, self.visible_ids())

    def test_restore_post_uses_csrf(self):
        self.remove()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        url = self.url("manuscripts:trash_restore", node_pk=self.scene.pk)
        self.assertEqual(client.post(url, {"parent": self.chapter.pk}).status_code, 403)
        client.get(url)
        response = client.post(url, {"parent": self.chapter.pk, "csrfmiddlewaretoken": client.cookies["csrftoken"].value})
        self.assertRedirects(response, self.url("manuscripts:detail", node_pk=self.scene.pk))
        self.assert_versions()

    def test_restore_form_omits_hidden_and_foreign_parents(self):
        self.remove(self.chapter)
        form = RestoreNodeForm(node=self.scene)
        self.assertEqual(list(form.fields["parent"].queryset), [self.other_chapter])

    def test_subtree_delete_post_no_longer_requires_empty_node(self):
        response = self.client.post(self.url("manuscripts:delete", node_pk=self.book.pk))
        self.assertRedirects(response, self.url("manuscripts:tree"))
        self.assertEqual(self.visible_ids(), set())
        self.assert_versions()

    def admin_request(self):
        self.user.is_staff = self.user.is_superuser = True
        request = RequestFactory().get("/admin/")
        request.user = self.user
        return request

    def test_admin_blocks_physical_delete_and_bulk_delete(self):
        model_admin = admin.site._registry[ManuscriptNode]
        request = self.admin_request()
        self.assertFalse(model_admin.has_delete_permission(request, self.scene))
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertNotIn("delete_selected", model_admin.get_actions(request))
        for operation in (lambda: model_admin.delete_model(request, self.scene),
                          lambda: model_admin.delete_queryset(request, ManuscriptNode.objects.filter(pk=self.scene.pk))):
            with self.assertRaises(PermissionDenied):
                operation()
        self.assert_versions()

    def test_admin_distinguishes_three_states_and_blocks_editing(self):
        self.remove(self.chapter)
        model_admin = admin.site._registry[ManuscriptNode]
        request = self.admin_request()
        rows = {row.pk: row for row in model_admin.get_queryset(request)}
        self.assertEqual(rows[self.book.pk].trash_state, "ACTIVE")
        self.assertEqual(rows[self.chapter.pk].trash_state, "DELETED")
        self.assertEqual(rows[self.scene.pk].trash_state, "HIDDEN")
        self.assertFalse(model_admin.has_change_permission(request, self.scene))

    def test_admin_normal_search_excludes_hidden_text(self):
        self.remove(self.chapter)
        model_admin = admin.site._registry[ManuscriptNode]
        request = self.admin_request()
        query, _ = model_admin.get_search_results(request, model_admin.get_queryset(request), "TEXT_A_DRAFT")
        self.assertFalse(query.exists())

    def test_admin_fk_selector_excludes_hidden_nodes(self):
        self.remove(self.chapter)
        model_admin = admin.site._registry[Note]
        field = model_admin.formfield_for_foreignkey(Note._meta.get_field("node"), self.admin_request())
        self.assertFalse(field.queryset.filter(pk=self.scene.pk).exists())

    def test_visibility_queries_do_not_grow_per_node(self):
        self.remove(self.chapter)
        with CaptureQueriesContext(connection) as queries:
            list(ManuscriptNode.objects.filter(project=self.project).visible())
        self.assertEqual(len(queries), 2)

    def test_restored_scene_can_move_and_edit_version_normally(self):
        self.remove(self.chapter)
        self.restore(self.chapter)
        move_node_down(self.scene, user=self.user)
        version = update_scene_version(self.scene, self.draft, user=self.user, expected_revision=self.draft.revision, content="Recovered edit")
        self.assertEqual(version.content, "Recovered edit")
        self.final.refresh_from_db()
        self.assertTrue(self.final.is_current_final)

    def test_hidden_references_do_not_break_world_export(self):
        ref = create_reference(self.project, user=self.user, title="Source", material_type="BIBLIOGRAPHY")
        attach_reference(ref, self.scene, user=self.user)
        self.remove(self.chapter)
        job = request_export(user=self.user, project=self.project, style_template=self.style, request_key=uuid4(),
                             export_mode="REFERENCE", export_format="MARKDOWN", scope_kind="REFERENCES_ALL")
        document = get_export_document(job)
        self.assertTrue(document.nodes)
        self.assertNotIn("Scene", "\n".join(node.content for node in document.nodes))

    def test_malicious_post_cannot_use_foreign_destination(self):
        self.remove()
        response = self.client.post(self.url("manuscripts:trash_restore", node_pk=self.scene.pk), {"parent": self.other_node.pk})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertNotIn(self.scene.pk, self.visible_ids())

    def test_stale_project_object_cannot_read_deleted_project_trash(self):
        self.remove()
        type(self.project).objects.filter(pk=self.project.pk).update(status="DELETED")
        with self.assertRaises(Http404):
            get_trash_items(self.project, user=self.user)

    def test_single_scene_legacy_export_helper_rejects_hidden_content(self):
        self.remove(self.chapter)
        with self.assertRaises(ValidationError):
            get_scene_content_for_export(self.scene)

    def test_auditor_counts_trash_without_false_duplicate_positions(self):
        from .audit import build_audit_report

        self.remove()
        report = build_audit_report()
        self.assertEqual(report["manuscripts"]["trash"]["direct"], 1)
        self.assertEqual(report["manuscripts"]["hierarchy"]["duplicate_positions"], [])
