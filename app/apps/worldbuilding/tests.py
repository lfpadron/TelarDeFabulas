from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.http import Http404, QueryDict
from django.test import Client, RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.projects.models import Project

from .forms import EntryForm
from .models import WorldbuildingEntry as Entry
from .selectors import entry_sections
from .services import (RevisionConflict, change_entry_category, create_entry, delete_entry,
                       move_entry_down, move_entry_up, normalize_positions, update_entry)


class WorldbuildingTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(email="world-owner@example.test", user_type="PREMIUM")
        cls.other = get_user_model().objects.create_user(email="world-other@example.test", user_type="PREMIUM")
        cls.project = Project.objects.create(user=cls.owner, name="Worldbuilding")
        cls.foreign = Project.objects.create(user=cls.other, name="Private world")
        cls.own_other = Project.objects.create(user=cls.owner, name="Second owned world")
        cls.council = Entry.objects.create(project=cls.project, category="POLITICS", title="Consejo de Luz", short_description="Autoridad del reino", content="  Primer párrafo.\r\n\r\nSegundo párrafo.\n  ")
        cls.laws = Entry.objects.create(project=cls.project, category="POLITICS", title="Leyes del Reino", content="Leyes originales")
        cls.cult = Entry.objects.create(project=cls.project, category="RELIGION", title="Culto de los Constructores")
        cls.war = Entry.objects.create(project=cls.project, category="HISTORY", title="Guerra de los Cristales")
        cls.eclipse = Entry.objects.create(project=cls.project, category="HISTORY", title="Gran Eclipse")
        cls.secret = Entry.objects.create(project=cls.foreign, category="HISTORY", title="Private history", content="Secret text")
        cls.other_owned = Entry.objects.create(project=cls.own_other, category="HISTORY", title="Another history")

    def setUp(self):
        self.client.force_login(self.owner)

    def url(self, name, entry=None, project=None):
        kwargs = {"project_pk": (project or self.project).pk}
        if entry is not None:
            kwargs["entry_pk"] = entry.pk
        return reverse(f"worldbuilding:{name}", kwargs=kwargs)

    def data(self, **overrides):
        return {"title": self.council.title, "category": self.council.category,
                "short_description": self.council.short_description, "content": self.council.content,
                "expected_revision": self.council.revision, **overrides}

    def assert_positions(self):
        for category in Entry.Category.values:
            positions = list(Entry.objects.filter(project=self.project, category=category).values_list("position", flat=True))
            self.assertEqual(positions, list(range(len(positions))))


class ModelTests(WorldbuildingTestCase):
    def test_three_categories_and_multiple_entries(self):
        for category in Entry.Category.values:
            with self.subTest(category=category):
                entry = Entry.objects.create(project=self.project, category=category, title="Another entry")
                self.assertEqual(entry.category, category)
        self.assert_positions()

    def test_invalid_category(self):
        with self.assertRaises(ValidationError):
            Entry.objects.create(project=self.project, category="INVALID", title="Invalid")

    def test_project_required(self):
        with self.assertRaises(ValidationError):
            Entry.objects.create(category="POLITICS", title="Missing project")

    def test_empty_and_whitespace_title_rejected(self):
        for title in ("", "  ", "\n\t", "\u00a0"):
            with self.subTest(title=title), self.assertRaises(ValidationError):
                Entry.objects.create(project=self.project, category="HISTORY", title=title)

    def test_empty_content_allowed(self):
        self.assertEqual(self.cult.content, "")

    def test_content_whitespace_and_line_endings_preserved(self):
        self.council.refresh_from_db()
        self.assertEqual(self.council.content, "  Primer párrafo.\r\n\r\nSegundo párrafo.\n  ")

    def test_initial_revision(self):
        self.assertEqual(self.council.revision, 1)

    def test_positions_are_automatic_and_category_relative(self):
        self.assertEqual((self.council.position, self.laws.position, self.cult.position, self.war.position), (0, 1, 0, 0))

    def test_explicit_insert_position(self):
        entry = create_entry(self.project, category="POLITICS", title="First", position=0)
        self.assertEqual(list(Entry.objects.filter(project=self.project, category="POLITICS").values_list("pk", flat=True)), [entry.pk, self.council.pk, self.laws.pk])
        self.assert_positions()

    def test_negative_and_non_integer_position_rejected(self):
        for position in (-1, 1.5, "bad", True):
            with self.subTest(position=position), self.assertRaises(ValidationError):
                create_entry(self.project, category="HISTORY", title="Invalid", position=position)

    def test_database_constraints(self):
        for values in ({"position": -1}, {"category": "INVALID"}, {"title": ""}, {"title": "  "}, {"revision": 0}, {"position": 1}):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                Entry.objects.filter(pk=self.council.pk).update(**values)

    def test_unique_index_covers_project_category_order(self):
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, Entry._meta.db_table)
        constraint = constraints["wb_project_category_position"]
        self.assertTrue(constraint["unique"])
        self.assertEqual(constraint["columns"], ["project_id", "category", "position"])

    def test_project_cannot_change(self):
        self.council.project = self.own_other
        with self.assertRaises(ValidationError):
            self.council.save()

    def test_explicit_id_cannot_replace_existing_entry(self):
        with self.assertRaises(ValidationError):
            Entry(pk=self.council.pk, project=self.project, category="HISTORY", title="Overwrite").save()

    def test_model_save_increments_revision(self):
        self.council.title = "Updated council"
        self.council.save()
        self.assertEqual(self.council.revision, 2)
        self.council.refresh_from_db()
        self.assertEqual(self.council.title, "Updated council")

    def test_model_save_rejects_stale_instance(self):
        update_entry(self.council, expected_revision=1, content="Winner")
        self.council.content = "Loser"
        with self.assertRaises(RevisionConflict):
            self.council.save()
        self.council.refresh_from_db()
        self.assertEqual(self.council.content, "Winner")

    def test_deferred_instance_without_revision_cannot_blind_save(self):
        entry = Entry.objects.only("id", "project_id", "title").get(pk=self.council.pk)
        entry.title = "Blind save"
        with self.assertRaises(RevisionConflict):
            entry.save(update_fields=["title"])

    def test_revision_property_cannot_bypass_loaded_revision(self):
        update_entry(self.council, expected_revision=1, content="Winner")
        self.council.revision = 2
        self.council.content = "Loser"
        with self.assertRaises(RevisionConflict):
            self.council.save()

    def test_partial_update_and_noop(self):
        self.council.title = "New title"
        self.council.content = "Not saved"
        self.council.save(update_fields=["title"])
        self.assertEqual(self.council.content, "  Primer párrafo.\r\n\r\nSegundo párrafo.\n  ")
        self.assertEqual(self.council.revision, 2)
        self.council.save()
        self.assertEqual(self.council.revision, 2)

    def test_noneditable_update_fields_rejected(self):
        for field in ("project", "revision", "position", "created_at"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.council.save(update_fields=[field])

    def test_deleted_entry_cannot_be_resurrected(self):
        old = Entry.objects.get(pk=self.cult.pk)
        self.cult.delete()
        with self.assertRaises(ValidationError):
            old.save()


class ServiceTests(WorldbuildingTestCase):
    def test_create_entry_service(self):
        entry = create_entry(self.project, user=self.owner, category="RELIGION", title="New faith", content="Text")
        self.assertEqual((entry.position, entry.revision), (1, 1))

    def test_update_all_text_fields(self):
        current = update_entry(self.council, expected_revision=1, user=self.owner,
                               title="New title", short_description="New description", content="New\n\nText")
        self.assertEqual((current.pk, current.title, current.short_description, current.content, current.revision),
                         (self.council.pk, "New title", "New description", "New\n\nText", 2))

    def test_revision_must_match_integer(self):
        for value in (None, True, "1", 0, -1, 2):
            with self.subTest(value=value), self.assertRaises(RevisionConflict):
                update_entry(self.council, expected_revision=value, content="Bad")

    def test_stale_conflict_preserves_all_fields(self):
        current = update_entry(self.council, expected_revision=1, title="Winner", short_description="Description", content="Text")
        before = Entry.objects.filter(pk=current.pk).values().get()
        with self.assertRaises(RevisionConflict):
            update_entry(self.council, expected_revision=1, title="Loser", short_description="Lost description", content="Lost text", category="HISTORY")
        self.assertEqual(before, Entry.objects.filter(pk=current.pk).values().get())

    def test_move_up(self):
        moved = move_entry_up(self.laws, expected_revision=1, user=self.owner)
        self.assertEqual((moved.position, moved.revision), (0, 2))
        self.council.refresh_from_db()
        self.assertEqual((self.council.position, self.council.revision), (1, 2))
        self.assert_positions()

    def test_move_down(self):
        moved = move_entry_down(self.council, expected_revision=1)
        self.assertEqual(moved.position, 1)
        self.assert_positions()

    def test_boundary_move_is_noop(self):
        current = move_entry_up(self.council, expected_revision=1)
        self.assertEqual(current.revision, 1)
        current = move_entry_down(self.laws, expected_revision=1)
        self.assertEqual(current.revision, 1)

    def test_change_category_preserves_identity_and_text(self):
        before = (self.council.pk, self.council.title, self.council.short_description, self.council.content, self.council.created_at)
        current = change_entry_category(self.council, "HISTORY", expected_revision=1, user=self.owner)
        self.assertEqual(before, (current.pk, current.title, current.short_description, current.content, current.created_at))
        self.assertEqual((current.category, current.position, current.revision), ("HISTORY", 2, 2))
        self.assert_positions()

    def test_change_category_invalid_and_stale(self):
        with self.assertRaises(ValidationError):
            change_entry_category(self.council, "OTHER", expected_revision=1)
        change_entry_category(self.council, "HISTORY", expected_revision=1)
        with self.assertRaises(RevisionConflict):
            change_entry_category(self.council, "RELIGION", expected_revision=1)

    def test_reorder_invalidates_old_editor_without_losing_text(self):
        move_entry_up(self.laws, expected_revision=1)
        with self.assertRaises(RevisionConflict):
            update_entry(self.council, expected_revision=1, content="Stale text")
        self.council.refresh_from_db()
        self.assertEqual(self.council.content, "  Primer párrafo.\r\n\r\nSegundo párrafo.\n  ")

    def test_edit_does_not_overwrite_position(self):
        moved = move_entry_down(self.council, expected_revision=1)
        current = update_entry(self.council, expected_revision=moved.revision, content="Fresh text")
        self.assertEqual(current.position, 1)

    def test_normalize_positions(self):
        Entry.objects.filter(pk=self.council.pk).update(position=10)
        Entry.objects.filter(pk=self.laws.pk).update(position=20)
        normalize_positions(self.project, "POLITICS", user=self.owner)
        self.assert_positions()
        self.council.refresh_from_db()
        self.assertEqual(self.council.revision, 2)

    def test_delete_only_selected_entry_and_normalize(self):
        before_other = Entry.objects.filter(pk=self.secret.pk).values().get()
        delete_entry(self.council, expected_revision=1, user=self.owner)
        self.assertEqual(Entry.objects.filter(project=self.project).count(), 4)
        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())
        self.assertEqual(before_other, Entry.objects.filter(pk=self.secret.pk).values().get())
        self.assert_positions()

    def test_stale_delete_rejected(self):
        update_entry(self.council, expected_revision=1, content="New draft")
        with self.assertRaises(RevisionConflict):
            delete_entry(self.council, expected_revision=1)
        self.assertTrue(Entry.objects.filter(pk=self.council.pk).exists())

    def test_actor_enforced_for_all_services(self):
        operations = (
            lambda: create_entry(self.project, user=self.other, category="POLITICS", title="Bad"),
            lambda: update_entry(self.council, user=self.other, expected_revision=1, content="Bad"),
            lambda: move_entry_up(self.council, user=self.other, expected_revision=1),
            lambda: move_entry_down(self.council, user=self.other, expected_revision=1),
            lambda: change_entry_category(self.council, "HISTORY", user=self.other, expected_revision=1),
            lambda: normalize_positions(self.project, "POLITICS", user=self.other),
            lambda: delete_entry(self.council, user=self.other, expected_revision=1),
        )
        for operation in operations:
            with self.assertRaises(Http404):
                operation()

    def test_stale_project_state_rechecked(self):
        for status in ("FROZEN", "PENDING_DELETION", "DELETED"):
            Project.objects.filter(pk=self.project.pk).update(status=status)
            for operation in (self.council.save, self.council.delete,
                              lambda: create_entry(self.project, category="POLITICS", title="Bad"),
                              lambda: move_entry_up(self.council, expected_revision=1),
                              lambda: normalize_positions(self.project, "POLITICS")):
                with self.subTest(status=status), self.assertRaises(ValidationError):
                    operation()

    def test_unknown_update_field_rejected(self):
        with self.assertRaises(ValidationError):
            update_entry(self.council, expected_revision=1, project=self.foreign)

    def test_category_move_rolls_back_after_order_failure(self):
        from .services import _apply_order

        before = list(Entry.objects.order_by("pk").values())

        def fail_after_order(*args, **kwargs):
            _apply_order(*args, **kwargs)
            raise RuntimeError("Injected failure")

        with patch("apps.worldbuilding.services._apply_order", side_effect=fail_after_order), self.assertRaises(RuntimeError):
            update_entry(self.council, expected_revision=1, category="HISTORY", content="Not committed")
        self.assertEqual(before, list(Entry.objects.order_by("pk").values()))


class ViewTests(WorldbuildingTestCase):
    def test_navigation(self):
        self.assertContains(self.client.get(reverse("projects:detail", args=[self.project.pk])), self.url("list"))

    def test_three_sections_without_content(self):
        response = self.client.get(self.url("list"))
        for text in ("Construcción de mundos", "Política", "Religión", "Historia", self.council.title, self.council.short_description):
            self.assertContains(response, text)
        self.assertNotContains(response, "Primer párrafo")
        self.assertNotContains(response, "Private history")

    def test_category_filter(self):
        response = self.client.get(self.url("list"), {"category": "RELIGION"})
        self.assertEqual([s["category"] for s in response.context["sections"]], ["RELIGION"])
        self.assertContains(response, self.cult.title)
        self.assertNotContains(response, self.council.title)

    def test_search_title_and_description_but_not_content(self):
        for query in ("consejo", "autoridad"):
            response = self.client.get(self.url("list"), {"q": query})
            self.assertContains(response, self.council.title)
            self.assertNotContains(response, self.laws.title)
        self.assertNotContains(self.client.get(self.url("list"), {"q": "Primer párrafo"}), self.council.title)

    def test_invalid_filters(self):
        for values in ({"category": "INVALID"}, {"q": "x" * 201}):
            self.assertEqual(self.client.get(self.url("list"), values).status_code, 400)

    def test_create_with_preselection(self):
        response = self.client.get(self.url("create"), {"category": "HISTORY"})
        self.assertEqual(response.context["form"].initial["category"], "HISTORY")
        self.assertEqual(self.client.get(self.url("create"), {"category": "INVALID"}).status_code, 404)
        response = self.client.post(self.url("create"), self.data(title="New history", category="HISTORY", project=self.foreign.pk))
        self.assertEqual(response.status_code, 302)
        entry = Entry.objects.get(project=self.project, title="New history")
        self.assertRedirects(response, self.url("detail", entry))

    def test_detail_preserves_text_and_escapes_html(self):
        current = update_entry(self.council, expected_revision=1, content="First\n\nSecond\n<script>alert(1)</script>")
        response = self.client.get(self.url("detail", current))
        self.assertContains(response, 'class="world-text"')
        self.assertContains(response, "First\n\nSecond\n&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")

    def test_edit_preserves_whitespace(self):
        text = "  Opening\r\n\r\nIndented\n\tEnding  "
        response = self.client.post(self.url("edit", self.council), self.data(content=text, short_description="  Brief\n "))
        self.assertEqual(response.status_code, 302)
        self.council.refresh_from_db()
        self.assertEqual(self.council.content, text)
        self.assertEqual(self.council.short_description, "  Brief\n ")
        self.assertEqual(self.council.revision, 2)

    def test_edit_category_preserves_id_and_order(self):
        self.assertEqual(self.client.post(self.url("edit", self.council), self.data(category="HISTORY")).status_code, 302)
        self.council.refresh_from_db()
        self.assertEqual((self.council.category, self.council.position), ("HISTORY", 2))
        self.assert_positions()

    def test_conflict_409_preserves_all_submitted_fields_and_original_revision(self):
        update_entry(self.council, expected_revision=1, content="Winning content")
        response = self.client.post(self.url("edit", self.council), self.data(title="Recover title", short_description="Recover description", content="Recover\n\nText", category="RELIGION"))
        self.assertEqual(response.status_code, 409)
        form = response.context["form"]
        for key, value in {"title": "Recover title", "short_description": "Recover description", "content": "Recover\n\nText", "category": "RELIGION"}.items():
            self.assertEqual(form[key].value(), value)
        self.assertEqual(str(form["expected_revision"].value()), "1")
        self.assertContains(response, 'target="_blank"', status_code=409)
        self.assertContains(response, "siguen en este formulario", status_code=409)
        self.council.refresh_from_db()
        self.assertEqual(self.council.content, "Winning content")
        self.assertEqual(self.council.title, "Consejo de Luz")

    def test_missing_or_invalid_revision_never_saves(self):
        for value in ("", "abc", "0", "9" * 100):
            response = self.client.post(self.url("edit", self.council), self.data(content="Bad", expected_revision=value))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
        self.council.refresh_from_db()
        self.assertEqual(self.council.revision, 1)

    def test_change_category_route(self):
        self.assertEqual(self.client.get(self.url("change_category", self.council)).status_code, 200)
        response = self.client.post(self.url("change_category", self.council), {"category": "HISTORY", "expected_revision": 1})
        self.assertRedirects(response, self.url("detail", self.council))
        self.council.refresh_from_db()
        self.assertEqual(self.council.category, "HISTORY")

    def test_stale_change_category_preserves_selection(self):
        update_entry(self.council, expected_revision=1, title="New title")
        response = self.client.post(self.url("change_category", self.council), {"category": "HISTORY", "expected_revision": 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.context["form"]["category"].value(), "HISTORY")

    def test_order_post_only(self):
        self.assertEqual(self.client.get(self.url("move_up", self.laws)).status_code, 405)
        self.assertEqual(self.client.post(self.url("move_up", self.laws), {"expected_revision": 1}).status_code, 302)
        self.assertEqual(self.client.post(self.url("move_down", self.laws), {"expected_revision": 2}).status_code, 302)
        self.assert_positions()

    def test_stale_reorder_and_missing_revision(self):
        update_entry(self.council, expected_revision=1, content="New text")
        self.assertEqual(self.client.post(self.url("move_down", self.council), {"expected_revision": 1}).status_code, 409)
        self.assertEqual(self.client.post(self.url("move_down", self.council)).status_code, 400)

    def test_delete_confirmation_and_post(self):
        url = self.url("delete", self.council)
        self.assertContains(self.client.get(url), "Confirmar eliminación")
        self.assertTrue(Entry.objects.filter(pk=self.council.pk).exists())
        self.assertEqual(self.client.post(url, {"expected_revision": 1}).status_code, 302)
        self.assertFalse(Entry.objects.filter(pk=self.council.pk).exists())
        self.assertEqual(Entry.objects.filter(project=self.project).count(), 4)

    def test_stale_delete_confirmation(self):
        self.client.get(self.url("delete", self.council))
        update_entry(self.council, expected_revision=1, content="New text")
        response = self.client.post(self.url("delete", self.council), {"expected_revision": 1})
        self.assertEqual(response.status_code, 409)
        self.assertTrue(Entry.objects.filter(pk=self.council.pk).exists())

    def test_mobile_fields_and_no_rich_editor(self):
        form = self.client.get(self.url("edit", self.council)).context["form"]
        self.assertEqual(form.fields["content"].widget.attrs["rows"], 18)
        self.assertEqual(form.fields["category"].widget.input_type, "select")


class PermissionTests(WorldbuildingTestCase):
    def read_urls(self):
        return [self.url("list"), self.url("detail", self.council)]

    def write_urls(self):
        return [self.url(name, self.council if name != "create" else None)
                for name in ("create", "edit", "delete", "change_category", "move_up", "move_down")]

    def test_anonymous_redirects_to_login(self):
        self.client.logout()
        for url in self.read_urls() + self.write_urls():
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_foreign_owner_read_and_write_404(self):
        self.client.force_login(self.other)
        for url in self.read_urls():
            self.assertEqual(self.client.get(url).status_code, 404)
        for url in self.write_urls():
            self.assertEqual(self.client.post(url, self.data()).status_code, 404)

    def test_entry_from_different_project_404_even_if_owned(self):
        for entry in (self.secret, self.other_owned):
            self.assertEqual(self.client.get(self.url("detail", entry)).status_code, 404)
            self.assertEqual(self.client.post(self.url("edit", entry), self.data()).status_code, 404)

    def test_admin_types_cannot_access_foreign_content(self):
        for kind in ("BUSINESS_ADMIN", "TECH_ADMIN"):
            self.other.user_type = kind
            self.other.is_staff = self.other.is_superuser = True
            self.other.save()
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(self.url("list")).status_code, 404)
            self.assertEqual(self.client.post(self.url("edit", self.council), self.data()).status_code, 404)

    def test_read_only_states(self):
        for status in ("FROZEN", "PENDING_DELETION"):
            Project.objects.filter(pk=self.project.pk).update(status=status)
            for url in self.read_urls():
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "Cambiar categoría")
                self.assertNotContains(response, "Eliminar")
            for url in self.write_urls():
                self.assertEqual(self.client.post(url, self.data()).status_code, 403)

    def test_deleted_project_inaccessible(self):
        Project.objects.filter(pk=self.project.pk).update(status="DELETED")
        for url in self.read_urls():
            self.assertEqual(self.client.get(url).status_code, 404)
        for url in self.write_urls():
            self.assertEqual(self.client.post(url, self.data()).status_code, 404)

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for url in self.write_urls():
            self.assertEqual(client.post(url, self.data()).status_code, 403)

    def test_private_headers(self):
        response = self.client.get(self.url("list"))
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])

    def test_form_project_scope(self):
        with self.assertRaises(ValidationError):
            EntryForm(instance=self.secret, project=self.project)


class AdminTests(WorldbuildingTestCase):
    def setUp(self):
        super().setUp()
        self.owner.is_superuser = self.owner.is_staff = True
        self.owner.save()
        self.model_admin = admin.site._registry[Entry]
        self.request = RequestFactory().get("/admin/")
        self.request.user = self.owner
        self.change_url = reverse("admin:worldbuilding_worldbuildingentry_change", args=[self.council.pk])

    def test_admin_list_and_search_scope(self):
        response = self.client.get(reverse("admin:worldbuilding_worldbuildingentry_changelist"))
        self.assertContains(response, self.council.title)
        self.assertNotContains(response, self.secret.title)
        with self.assertRaises(Http404):
            self.model_admin.get_object(self.request, str(self.secret.pk))

    def test_admin_create(self):
        url = reverse("admin:worldbuilding_worldbuildingentry_add")
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, self.data(title="Admin entry", project=self.project.pk, _save="Save"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Entry.objects.filter(project=self.project, title="Admin entry").exists())

    def test_admin_correct_revision_saves(self):
        response = self.client.get(self.change_url)
        self.assertContains(response, 'name="expected_revision"')
        response = self.client.post(self.change_url, self.data(content="Admin update", _save="Save"))
        self.assertEqual(response.status_code, 302)
        self.council.refresh_from_db()
        self.assertEqual((self.council.content, self.council.revision), ("Admin update", 2))

    def test_admin_stale_revision_preserves_submitted_text(self):
        update_entry(self.council, expected_revision=1, content="Web winner")
        response = self.client.post(self.change_url, self.data(title="Recover title", content="Admin unsaved\n\nText", _save="Save"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.context["adminform"].form["content"].value(), "Admin unsaved\n\nText")
        self.assertContains(response, "siguen en este formulario", status_code=409)
        self.council.refresh_from_db()
        self.assertEqual(self.council.content, "Web winner")

    def test_admin_cannot_omit_revision(self):
        data = self.data(content="Bad", _save="Save")
        data.pop("expected_revision")
        response = self.client.post(self.change_url, data)
        self.assertEqual(response.status_code, 200)
        self.council.refresh_from_db()
        self.assertEqual(self.council.revision, 1)

    def test_admin_cannot_transfer_or_create_foreign_project(self):
        self.client.post(self.change_url, self.data(project=self.foreign.pk, content="Owned edit", _save="Save"))
        self.council.refresh_from_db()
        self.assertEqual(self.council.project_id, self.project.pk)
        self.assertEqual(self.client.post(reverse("admin:worldbuilding_worldbuildingentry_add"), self.data(project=self.foreign.pk)).status_code, 404)

    def test_admin_frozen_and_deleted(self):
        Project.objects.filter(pk=self.project.pk).update(status="FROZEN")
        self.assertEqual(self.client.post(self.change_url, self.data()).status_code, 403)
        Project.objects.filter(pk=self.project.pk).update(status="DELETED")
        self.assertEqual(self.client.get(self.change_url).status_code, 404)

    def test_admin_delete_disabled(self):
        self.assertFalse(self.model_admin.has_delete_permission(self.request, self.council))
        self.assertEqual(self.model_admin.get_actions(self.request), {})
        with self.assertRaises(PermissionDenied):
            self.model_admin.delete_queryset(self.request, Entry.objects.all())


class PerformanceTests(WorldbuildingTestCase):
    def test_sections_do_not_load_content(self):
        with CaptureQueriesContext(connection) as queries:
            sections = entry_sections(self.project, QueryDict())
            for section in sections:
                for entry in section["page"]:
                    self.assertIn("content", entry.get_deferred_fields())
                    str(entry)
        self.assertLessEqual(len(queries), 6)
        self.assertFalse(any('"content"' in query["sql"] for query in queries))

    def test_pagination_query_count_is_bounded(self):
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.url("list"))
        Entry.objects.bulk_create([Entry(project=self.project, category="POLITICS", title=f"Entry {i}", position=i+2, content="Long text " * 1000) for i in range(120)])
        with CaptureQueriesContext(connection) as large:
            response = self.client.get(self.url("list"))
        self.assertLessEqual(len(large), len(small) + 1)
        self.assertEqual(len(response.context["sections"][0]["page"]), 50)
        response = self.client.get(self.url("list"), {"politics_page": 3, "q": "Entry"})
        self.assertEqual(len(response.context["sections"][0]["page"]), 20)
        self.assertContains(response, "q=Entry")

    def test_reorder_never_selects_full_text(self):
        with CaptureQueriesContext(connection) as queries:
            move_entry_up(self.laws, expected_revision=1)
        self.assertFalse(any('"content"' in query["sql"] for query in queries))

    def test_search_reorder_flags_use_full_category(self):
        sections = entry_sections(self.project, QueryDict(), query="Leyes")
        row = list(sections[0]["page"])[0]
        self.assertTrue(row.can_move_up)
        self.assertFalse(row.can_move_down)

    def test_invalid_page_numbers_are_safe(self):
        for value in ("abc", "-1", "9" * 200):
            self.assertEqual(self.client.get(self.url("list"), {"politics_page": value}).status_code, 200)
