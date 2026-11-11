from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone
from docx import Document

from apps.core.tests.helpers import SecurityTestCase
from apps.exports.docx import build_export_docx
from apps.exports.epub import build_export_epub
from apps.exports.pdf import build_export_pdf
from apps.exports.services import build_export_html, ordered_project_nodes, render_export_html, selected_content

from .models import ManuscriptNode, SceneVersion
from .services import move_node
from .version_services import (
    RevisionConflict, create_scene_version, finalize_scene_version,
    get_current_draft_version, get_current_final_version, get_scene_content_for_export,
    restore_scene_version, select_scene_versions, update_scene_version,
)


class SceneVersionTests(SecurityTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_chapter = ManuscriptNode.objects.create(project=cls.other_project, parent=cls.other_node, node_type="CHAPTER", title="Private chapter")
        cls.foreign_scene = ManuscriptNode.objects.create(project=cls.other_project, parent=cls.other_chapter, node_type="SCENE", title="Foreign scene", content="Foreign private text")

    def setUp(self):
        super().setUp()
        self.v1 = get_current_draft_version(self.scene)

    def snapshot(self):
        return {**super().snapshot(), "versions": list(SceneVersion.objects.order_by("pk").values())}

    def version_url(self, name, version=None, scene=None):
        scene = scene or self.scene
        kwargs = {"project_pk": scene.project_id, "node_pk": scene.pk}
        if name not in ("version_history", "version_create"):
            kwargs["version_pk"] = (version or self.v1).pk
        return reverse("manuscripts:" + name, kwargs=kwargs)

    def create(self, source=None, **kwargs):
        return create_scene_version(self.scene, user=self.user, source_version=source,
                                    expected_revision=source.revision if source else None, **kwargs)

    def edit(self, version=None, **kwargs):
        version = version or self.v1
        return update_scene_version(self.scene, version, user=self.user, expected_revision=version.revision, **kwargs)

    def finalize(self, version=None):
        version = version or self.v1
        return finalize_scene_version(self.scene, version, user=self.user, expected_revision=version.revision)

    def test_new_scene_has_initial_draft_and_legacy_text_is_preserved(self):
        self.assertEqual(self.v1.content, self.scene.content)
        self.assertEqual(self.v1.editorial_stage, "DRAFT")
        self.assertEqual(self.v1.version_number, 1)

    def test_initial_revision_is_one(self):
        self.assertEqual(self.v1.revision, 1)

    def test_initial_word_count_is_calculated(self):
        self.assertEqual(self.v1.word_count, 2)

    def test_model_accepts_scene(self):
        SceneVersion(scene=self.scene, version_number=2).full_clean()

    def test_model_rejects_book(self):
        with self.assertRaises(ValidationError):
            SceneVersion(scene=self.book, version_number=1).full_clean()

    def test_model_rejects_chapter(self):
        with self.assertRaises(ValidationError):
            SceneVersion(scene=self.chapter, version_number=1).full_clean()

    def test_service_rejects_non_scene_types(self):
        for node in (self.book, self.chapter):
            with self.assertRaises(ValidationError):
                create_scene_version(node, user=self.user)

    def test_database_rejects_duplicate_version_numbers(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SceneVersion.objects.bulk_create([SceneVersion(scene=self.scene, version_number=1)])

    def test_database_rejects_nonpositive_number_and_revision(self):
        for values in ({"version_number": 0}, {"version_number": 2, "revision": 0}):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                SceneVersion.objects.bulk_create([SceneVersion(scene=self.scene, **values)])

    def test_database_rejects_unknown_editorial_stage(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SceneVersion.objects.filter(pk=self.v1.pk).update(editorial_stage="INVALID")

    def test_database_requires_finalized_date(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SceneVersion.objects.filter(pk=self.v1.pk).update(editorial_stage="FINAL")

    def test_database_rejects_current_final_draft(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            SceneVersion.objects.filter(pk=self.v1.pk).update(is_current_final=True)

    def test_database_allows_only_one_current_final(self):
        self.finalize()
        v2 = self.create(content="Another")
        with self.assertRaises(IntegrityError), transaction.atomic():
            SceneVersion.objects.filter(pk=v2.pk).update(editorial_stage="FINAL", finalized_at=timezone.now(), is_current_final=True)

    def test_create_new_version_allocates_next_number(self):
        self.assertEqual(self.create().version_number, 2)
        self.assertEqual(self.create().version_number, 3)

    def test_copy_preserves_exact_text_and_records_source(self):
        source = self.edit(content="  Ni\u00f1a.\r\n\t\n")
        copied = self.create(source)
        self.assertEqual(copied.content, source.content)
        self.assertEqual(copied.based_on_id, source.pk)
        self.assertEqual(copied.revision, 1)

    def test_new_version_becomes_working_draft(self):
        v2 = self.create()
        self.scene.refresh_from_db()
        self.assertEqual(get_current_draft_version(self.scene), v2)

    def test_edit_draft_increments_revision_and_count(self):
        result = self.edit(content="One two three")
        self.assertEqual((result.revision, result.word_count), (2, 3))

    def test_review_is_editable(self):
        reviewed = self.edit(editorial_stage="REVIEW")
        self.assertEqual(self.edit(reviewed, content="Reviewed text").editorial_stage, "REVIEW")

    def test_edit_does_not_change_legacy_columns(self):
        before = ManuscriptNode.objects.values().get(pk=self.scene.pk)
        self.edit(content="New source of truth")
        self.assertEqual(ManuscriptNode.objects.values().get(pk=self.scene.pk), before)

    def test_legacy_model_save_cannot_edit_scene_text(self):
        before = self.snapshot()
        self.scene.content = "Lost update"
        with self.assertRaises(ValidationError):
            self.scene.save()
        self.assertEqual(self.snapshot(), before)

    def test_direct_version_save_and_delete_are_blocked(self):
        before = self.snapshot()
        for action in (self.v1.save, self.v1.delete):
            with self.assertRaises(ValidationError):
                action()
        self.assertEqual(self.snapshot(), before)

    def test_final_content_cannot_be_edited(self):
        final = self.finalize()
        before = self.snapshot()
        with self.assertRaises(ValidationError):
            self.edit(final, content="Forbidden")
        self.assertEqual(self.snapshot(), before)

    def test_finalize_sets_date_and_clears_active_pointer(self):
        final = self.finalize()
        self.scene.refresh_from_db()
        self.assertIsNotNone(final.finalized_at)
        self.assertIsNone(get_current_draft_version(self.scene))
        self.assertEqual(get_current_final_version(self.scene), final)

    def test_finalizing_older_draft_keeps_other_working_draft(self):
        v2 = self.create()
        self.finalize(self.v1)
        self.scene.refresh_from_db()
        self.assertEqual(get_current_draft_version(self.scene), v2)

    def test_replacing_final_preserves_historical_final(self):
        final = self.finalize()
        before = SceneVersion.objects.values().get(pk=final.pk)
        second = self.finalize(self.create(final))
        after = SceneVersion.objects.values().get(pk=final.pk)
        before["is_current_final"] = False
        self.assertEqual(after, before)
        self.assertEqual(get_current_final_version(self.scene), second)
        self.assertEqual(self.scene.versions.filter(editorial_stage="FINAL").count(), 2)

    def test_draft_after_final_does_not_modify_approved_text(self):
        final = self.finalize()
        before = SceneVersion.objects.values().get(pk=final.pk)
        self.edit(self.create(final), content="New draft")
        self.assertEqual(SceneVersion.objects.values().get(pk=final.pk), before)

    def test_restore_creates_new_draft_without_overwriting_history(self):
        self.create(content="Other text")
        before = list(self.scene.versions.values())
        restored = restore_scene_version(self.scene, self.v1, user=self.user, expected_revision=1)
        self.assertEqual(restored.version_number, 3)
        self.assertEqual(restored.content, self.v1.content)
        self.assertEqual(list(self.scene.versions.exclude(pk=restored.pk).values()), before)

    def test_stale_revision_rejected_without_changes(self):
        self.edit(content="First editor")
        before = self.snapshot()
        with self.assertRaises(RevisionConflict):
            self.edit(content="Second editor")
        self.assertEqual(self.snapshot(), before)

    def test_stale_finalize_and_copy_rejected(self):
        self.edit(content="Latest")
        before = self.snapshot()
        for operation in (self.finalize, lambda: self.create(self.v1)):
            with self.assertRaises(RevisionConflict):
                operation()
        self.assertEqual(self.snapshot(), before)

    def test_cannot_set_final_through_edit_service(self):
        with self.assertRaises(ValidationError):
            self.edit(editorial_stage="FINAL")

    def test_cannot_copy_or_restore_foreign_scene_version(self):
        source = get_current_draft_version(self.foreign_scene)
        for operation in (lambda: self.create(source), lambda: restore_scene_version(self.scene, source, user=self.user, expected_revision=1)):
            with self.assertRaises(Http404):
                operation()

    def test_service_checks_owner_and_missing_actor(self):
        for user in (self.other_user, None):
            with self.assertRaises(Http404):
                create_scene_version(self.scene, user=user)

    def test_active_pointer_must_target_same_scene(self):
        self.scene.current_draft_version = get_current_draft_version(self.foreign_scene)
        with self.assertRaises(ValidationError):
            self.scene.full_clean()

    def test_active_pointer_cannot_point_to_final(self):
        self.scene.current_draft_version = self.finalize()
        with self.assertRaises(ValidationError):
            self.scene.full_clean()

    def test_type_change_cannot_orphan_versions(self):
        self.scene.node_type = "CHAPTER"
        self.scene.parent = self.book
        with self.assertRaises(ValidationError):
            self.scene.save()

    def test_metadata_save_does_not_restore_stale_working_pointer(self):
        second = self.create()
        self.scene.title = "Updated title"
        self.scene.save()
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.current_draft_version_id, second.pk)

    def test_editing_older_draft_does_not_switch_active_draft(self):
        second = self.create()
        self.edit(content="Old draft edited")
        self.scene.refresh_from_db()
        self.assertEqual(self.scene.current_draft_version_id, second.pk)

    def test_history_visible_and_paginated_without_full_text(self):
        self.assertContains(self.client.get(self.version_url("version_history")), "V1")
        response = self.client.get(self.version_url("version_history"))
        self.assertIn("content", response.context["page_obj"][0].get_deferred_fields())

    def test_scene_detail_reads_version_instead_of_legacy(self):
        updated = self.edit(content="Version source")
        response = self.client.get(self.url("manuscripts:detail", node_pk=self.scene.pk))
        self.assertContains(response, updated.content)
        self.assertNotContains(response, self.scene.content)

    def test_old_scene_edit_form_cannot_overwrite_text(self):
        response = self.client.post(self.url("manuscripts:edit", node_pk=self.scene.pk), {"title": "Updated", "content": "Bypass", "status": "PUBLISHED", "is_publishable": "on"})
        self.assertEqual(response.status_code, 302)
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.content, "Private prose.")
        self.assertEqual(self.v1.revision, 1)

    def test_form_preserves_whitespace_and_revision(self):
        text = " \r\n First line.\n\t "
        response = self.client.post(self.version_url("version_edit"), {"content": text, "revision": 1})
        self.assertEqual(response.status_code, 302)
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.content, text)
        self.assertEqual(self.v1.revision, 2)

    def test_conflict_returns_409_and_keeps_submitted_text(self):
        self.edit(content="Committed text")
        payload = '<script>alert("draft")</script> Uncommitted text'
        response = self.client.post(self.version_url("version_edit"), {"content": payload, "revision": 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.context["form"]["content"].value(), payload)
        self.assertContains(response, "&lt;script&gt;", status_code=409)
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.content, "Committed text")

    def test_missing_revision_does_not_save(self):
        response = self.client.post(self.version_url("version_edit"), {"content": "No revision"})
        self.assertEqual(response.status_code, 400)
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.revision, 1)

    def test_edit_after_concurrent_finalize_keeps_submitted_text(self):
        self.finalize()
        response = self.client.post(self.version_url("version_edit"), {"content": "Uncommitted", "revision": 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.context["form"]["content"].value(), "Uncommitted")

    def test_final_edit_get_is_forbidden(self):
        self.finalize()
        self.assertEqual(self.client.get(self.version_url("version_edit")).status_code, 403)

    def test_mutation_actions_require_post(self):
        before = self.snapshot()
        for name in ("version_create", "version_review", "version_finalize", "version_restore"):
            self.assertEqual(self.client.get(self.version_url(name)).status_code, 405)
        self.assertEqual(self.snapshot(), before)

    def test_review_finalize_and_restore_posts(self):
        self.assertEqual(self.client.post(self.version_url("version_review"), {"revision": 1}).status_code, 302)
        self.assertEqual(self.client.post(self.version_url("version_finalize"), {"revision": 2}).status_code, 302)
        self.assertEqual(self.client.post(self.version_url("version_restore"), {"revision": 3}).status_code, 302)
        self.assertEqual(self.scene.versions.count(), 2)
        self.assertEqual(get_current_final_version(self.scene).pk, self.v1.pk)

    def test_create_post_copies_source(self):
        response = self.client.post(self.version_url("version_create"), {"source_version": self.v1.pk, "revision": 1})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.scene.versions.get(version_number=2).content, self.v1.content)

    def test_post_actions_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        before = self.snapshot()
        for name in ("version_edit", "version_create", "version_review", "version_finalize", "version_restore"):
            self.assertEqual(client.post(self.version_url(name), {"source_version": self.v1.pk, "revision": 1}).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_foreign_user_cannot_access_any_version_route(self):
        self.client.force_login(self.other_user)
        for name in ("version_history", "version_detail", "version_edit"):
            self.assertEqual(self.client.get(self.version_url(name)).status_code, 404)
        for name in ("version_create", "version_review", "version_finalize", "version_restore"):
            self.assertEqual(self.client.post(self.version_url(name), {"source_version": self.v1.pk, "revision": 1}).status_code, 404)

    def test_wrong_scene_version_and_copy_source_return_404(self):
        foreign = get_current_draft_version(self.foreign_scene)
        self.assertEqual(self.client.get(self.version_url("version_detail", foreign)).status_code, 404)
        self.assertEqual(self.client.post(self.version_url("version_create"), {"source_version": foreign.pk, "revision": 1}).status_code, 404)

    def test_frozen_and_pending_allow_reading_only(self):
        for status in ("FROZEN", "PENDING_DELETION"):
            self.set_status(status)
            before = self.snapshot()
            self.assertEqual(self.client.get(self.version_url("version_history")).status_code, 200)
            self.assertEqual(self.client.get(self.version_url("version_detail")).status_code, 200)
            self.assertEqual(self.client.get(self.version_url("version_edit")).status_code, 403)
            for name in ("version_create", "version_review", "version_finalize", "version_restore", "version_edit"):
                self.assertEqual(self.client.post(self.version_url(name), {"source_version": self.v1.pk, "revision": 1, "content": "Blocked"}).status_code, 403)
            self.assertEqual(self.snapshot(), before)

    def test_deleted_project_blocks_reading_and_writing(self):
        self.set_status("DELETED")
        self.assertEqual(self.client.get(self.version_url("version_history")).status_code, 404)
        self.assertEqual(self.client.post(self.version_url("version_finalize"), {"revision": 1}).status_code, 404)

    def test_admin_is_readonly_even_for_superuser(self):
        self.user.is_staff = self.user.is_superuser = True
        request = RequestFactory().get("/admin/")
        request.user = self.user
        model_admin = admin.site._registry[SceneVersion]
        fields = model_admin.get_readonly_fields(request, self.v1)
        self.assertEqual(len(fields), len(set(fields)))
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request, self.v1))
        self.assertFalse(model_admin.has_delete_permission(request, self.v1))
        self.assertIn(self.v1, model_admin.get_queryset(request))
        self.assertNotIn(get_current_draft_version(self.foreign_scene), model_admin.get_queryset(request))

    def test_scene_move_preserves_all_versions_and_relationships(self):
        self.create(self.finalize())
        before = list(self.scene.versions.values())
        chapter = ManuscriptNode.objects.create(project=self.project, parent=self.book, node_type="CHAPTER", title="Destination")
        move_node(self.scene, chapter, user=self.user)
        self.assertEqual(list(self.scene.versions.values()), before)
        self.note.refresh_from_db()
        self.mention.refresh_from_db()
        self.assertEqual((self.note.node_id, self.mention.node_id), (self.scene.pk, self.scene.pk))

    def test_export_work_prefers_active_draft_over_final(self):
        self.finalize()
        self.create(content="Work edition")
        self.assertEqual(get_scene_content_for_export(self.scene), "Work edition")

    def test_export_falls_back_to_final_when_no_draft(self):
        final = self.finalize()
        self.assertEqual(get_scene_content_for_export(self.scene), final.content)

    def test_final_selection_never_falls_back_to_draft(self):
        self.assertEqual(get_scene_content_for_export(self.scene, mode="FINAL"), "")
        final = self.finalize()
        self.create(content="Do not publish")
        self.assertEqual(get_scene_content_for_export(self.scene, mode="FINAL"), final.content)

    def test_export_materializes_each_scene_once(self):
        with self.assertNumQueries(1):
            selected = select_scene_versions([self.scene])
        ordered = ordered_project_nodes(self.project)
        self.edit(content="Later change")
        exported = next(node for node in ordered if node.pk == self.scene.pk)
        self.assertEqual(selected_content(exported), selected[self.scene.pk]["content"])
        self.assertEqual(exported.export_version_id, self.v1.pk)

    def test_html_and_preview_use_versioned_text(self):
        self.edit(content="Versioned prose")
        self.capture_export()
        for html in (build_export_html(self.job), render_export_html(self.project, self.style, max_words=100).html):
            self.assertIn("Versioned prose", html)
            self.assertNotIn("Private prose.", html)
        response = self.client.get(self.url("exports:preview"))
        self.assertContains(response, "Versioned prose")

    def test_docx_uses_versioned_text(self):
        self.edit(content="Versioned prose")
        self.capture_export()
        text = "\n".join(p.text for p in Document(BytesIO(build_export_docx(self.job))).paragraphs)
        self.assertIn("Versioned prose", text)
        self.assertNotIn("Private prose.", text)

    def test_pdf_uses_versioned_html_and_renders(self):
        self.edit(content="Versioned prose")
        self.capture_export()
        from apps.exports.pdf import build_export_pdf_html
        self.assertIn("Versioned prose", build_export_pdf_html(self.job))
        self.assertTrue(build_export_pdf(self.job).startswith(b"%PDF"))

    def test_epub_uses_versioned_text(self):
        self.edit(content="Versioned prose")
        self.capture_export()
        with ZipFile(BytesIO(build_export_epub(self.job))) as archive:
            text = "\n".join(archive.read(name).decode() for name in archive.namelist() if name.endswith(".xhtml"))
        self.assertIn("Versioned prose", text)
        self.assertNotIn("Private prose.", text)

    def test_finalize_rolls_back_old_designation_on_failure(self):
        self.finalize()
        second = self.create()
        before = self.snapshot()
        with patch.object(SceneVersion, "full_clean", side_effect=ValidationError("Injected")):
            with self.assertRaises(ValidationError):
                self.finalize(second)
        self.assertEqual(self.snapshot(), before)

    def test_historical_final_can_be_designated_without_rewriting_its_history(self):
        first = self.finalize()
        before = SceneVersion.objects.values().get(pk=first.pk)
        self.finalize(self.create(first))
        self.finalize(first)
        self.assertEqual(SceneVersion.objects.values().get(pk=first.pk), before)
        self.assertEqual(self.scene.versions.filter(is_current_final=True).count(), 1)

    def test_scene_deletion_confirmation_warns_about_version_history(self):
        response = self.client.get(self.url("manuscripts:delete", node_pk=self.scene.pk))
        self.assertContains(response, "todas sus versiones, notas y menciones se conservarán")
        self.assertEqual(self.scene.versions.count(), 1)
