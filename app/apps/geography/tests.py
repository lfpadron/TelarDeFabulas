from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.test import Client, RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.characters.forms import CharacterForm
from apps.characters.models import Character, CharacterDramaticRole
from apps.projects.models import Project

from .forms import GeographicLocationForm, MoveLocationForm
from .models import GeographicLocation as Location
from .selectors import location_path, tree_events
from .services import (delete_location, get_valid_parent_queryset, move_location,
                       move_location_down, move_location_up, normalize_positions)


class GeographyTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(email="geo-owner@example.test", password="geo-test-password", user_type="PREMIUM")
        cls.other = get_user_model().objects.create_user(email="geo-other@example.test", password="geo-test-password", user_type="PREMIUM")
        cls.project = Project.objects.create(user=cls.owner, name="Geography")
        cls.foreign = Project.objects.create(user=cls.other, name="Private world")
        cls.world = Location.objects.create(project=cls.project, name="Mundo", location_type="WORLD")
        cls.province = Location.objects.create(project=cls.project, name="Provincia A", parent=cls.world, location_type="PROVINCE")
        cls.destination = Location.objects.create(project=cls.project, name="Provincia B", parent=cls.world, location_type="PROVINCE")
        cls.city = Location.objects.create(project=cls.project, parent=cls.province, location_type="CITY", name="Ciudad A",
                                         short_description="Descripcion breve", detailed_description="Historia\nCultura\nClima")
        cls.foreign_location = Location.objects.create(project=cls.foreign, name="Private city", location_type="CITY")
        cls.resident = Character.objects.create(project=cls.project, name="Elena", residence=cls.city, biography="Ficha intacta")

    def setUp(self):
        self.client.force_login(self.owner)

    def url(self, name, location=None, project=None):
        kwargs = {"project_pk": (project or self.project).pk}
        if location:
            kwargs["location_pk"] = location.pk
        return reverse(f"geography:{name}", kwargs=kwargs)


class LocationModelTests(GeographyTestCase):
    def test_root_without_universe(self):
        self.assertIsNone(self.world.parent_id)
        self.assertEqual(self.world.position, 1)

    def test_child_with_flexible_type(self):
        child = Location.objects.create(project=self.project, parent=self.city, name="Universo local", location_type="UNIVERSE")
        self.assertEqual(child.parent_id, self.city.pk)

    def test_all_location_types(self):
        for value in Location.LocationType.values:
            with self.subTest(value=value):
                location = Location.objects.create(project=self.project, name=value, location_type=value)
                self.assertEqual(location.location_type, value)

    def test_foreign_parent_rejected(self):
        with self.assertRaises(ValidationError):
            Location.objects.create(project=self.project, name="Invalid", parent=self.foreign_location)

    def test_self_parent_rejected(self):
        self.city.parent = self.city
        with self.assertRaises(ValidationError):
            self.city.save()

    def test_indirect_cycle_rejected(self):
        self.world.parent = self.city
        with self.assertRaises(ValidationError):
            self.world.save()

    def test_empty_or_whitespace_name_rejected(self):
        for name in ("", "   "):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                Location.objects.create(project=self.project, name=name)

    def test_other_custom_type(self):
        location = Location.objects.create(project=self.project, name="Puerto", location_type="OTHER", custom_location_type="Archipielago")
        self.assertEqual(location.type_label, "Archipielago")

    def test_invalid_type_rejected(self):
        with self.assertRaises(ValidationError):
            Location.objects.create(project=self.project, name="Invalid", location_type="ARBITRARY")

    def test_positions_append(self):
        third = Location.objects.create(project=self.project, name="Third", parent=self.world)
        self.assertEqual(third.position, 3)

    def test_explicit_position_inserts(self):
        first = Location.objects.create(project=self.project, name="First", parent=self.world, position=1)
        self.assertEqual(list(self.world.children.values_list("pk", flat=True)), [first.pk, self.province.pk, self.destination.pk])
        self.assertEqual(list(self.world.children.values_list("position", flat=True)), [1, 2, 3])

    def test_normalize_positions(self):
        Location.objects.filter(pk=self.province.pk).update(position=10)
        Location.objects.filter(pk=self.destination.pk).update(position=20)
        normalize_positions(self.project, self.world, user=self.owner)
        self.assertEqual(list(self.world.children.values_list("position", flat=True)), [1, 2])

    def test_foreign_normalization_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_positions(self.project, self.foreign_location)

    def test_database_rejects_duplicate_root_positions(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Location.objects.bulk_create([Location(project=self.project, name="Duplicate", position=1)])

    def test_database_rejects_duplicate_child_positions(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Location.objects.filter(pk=self.destination.pk).update(position=self.province.position)

    def test_database_rejects_invalid_type_position_and_self_parent(self):
        for values in ({"location_type": "INVALID"}, {"position": 0}, {"parent_id": self.city.pk}, {"name": ""}):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                Location.objects.filter(pk=self.city.pk).update(**values)

    def test_project_identity_immutable(self):
        self.city.project = self.foreign
        self.city.parent = None
        with self.assertRaises(ValidationError):
            self.city.save()

    def test_delete_children_blocked_even_via_queryset(self):
        with self.assertRaises(ValidationError):
            self.province.delete()
        with self.assertRaises(ProtectedError):
            Location.objects.filter(pk=self.province.pk).delete()

    def test_delete_residents_blocked(self):
        with self.assertRaises(ValidationError):
            self.city.delete()
        self.resident.refresh_from_db()
        self.assertEqual(self.resident.residence_id, self.city.pk)

    def test_delete_after_detach_preserves_character(self):
        self.resident.residence = None
        self.resident.save(update_fields=["residence"])
        self.city.delete()
        self.resident.refresh_from_db()
        self.assertEqual(self.resident.biography, "Ficha intacta")
        self.assertIsNone(self.resident.residence_id)

    def test_delete_normalizes_siblings(self):
        delete_location(self.destination)
        new = Location.objects.create(project=self.project, parent=self.world, name="New")
        self.assertEqual(new.position, 2)


class LocationMovementTests(GeographyTestCase):
    def test_move_preserves_identity_descriptions_and_residents(self):
        before = (self.city.pk, self.city.name, self.city.short_description, self.city.detailed_description, self.city.created_at)
        moved = move_location(self.city, self.destination, user=self.owner)
        self.assertEqual(before, (moved.pk, moved.name, moved.short_description, moved.detailed_description, moved.created_at))
        self.assertEqual(moved.parent_id, self.destination.pk)
        self.resident.refresh_from_db()
        self.assertEqual(self.resident.residence_id, moved.pk)

    def test_move_to_root(self):
        moved = move_location(self.city, None)
        self.assertIsNone(moved.parent_id)
        self.assertEqual(moved.position, 2)

    def test_move_up(self):
        move_location_up(self.destination)
        self.assertEqual(list(self.world.children.values_list("pk", flat=True)), [self.destination.pk, self.province.pk])

    def test_move_down(self):
        move_location_down(self.province)
        self.assertEqual(list(self.world.children.values_list("pk", flat=True)), [self.destination.pk, self.province.pk])

    def test_reorder_boundaries(self):
        move_location_up(self.province)
        move_location_down(self.destination)
        self.assertEqual(list(self.world.children.values_list("position", flat=True)), [1, 2])

    def test_move_cross_project_rejected(self):
        with self.assertRaises(ValidationError):
            move_location(self.city, self.foreign_location)

    def test_move_cycle_rejected(self):
        for parent in (self.world, self.city):
            with self.subTest(parent=parent), self.assertRaises(ValidationError):
                move_location(self.world, parent)

    def test_move_invalid_position_rejected(self):
        for position in (0, -1, "invalid", 1.5):
            with self.subTest(position=position), self.assertRaises(ValidationError):
                move_location(self.city, None, position)

    def test_move_large_position_appends(self):
        self.assertEqual(move_location(self.city, None, 999).position, 2)

    def test_stale_description_save_preserves_move(self):
        old = Location.objects.get(pk=self.city.pk)
        move_location(self.city, self.destination)
        old.detailed_description = "New description"
        old.save()
        old.refresh_from_db()
        self.assertEqual(old.parent_id, self.destination.pk)
        self.assertEqual(old.detailed_description, "New description")

    def test_stale_structural_save_rejected(self):
        old = Location.objects.get(pk=self.city.pk)
        move_location(self.city, self.destination)
        old.parent = None
        with self.assertRaises(ValidationError):
            old.save()

    def test_valid_parents_exclude_self_descendants_foreign(self):
        ids = set(get_valid_parent_queryset(self.project, self.province).values_list("pk", flat=True))
        self.assertEqual(ids, {self.world.pk, self.destination.pk})

    def test_path_changes_after_move(self):
        moved = move_location(self.city, self.destination)
        with self.assertNumQueries(1):
            path = location_path(moved)
        self.assertEqual([row.pk for row in path], [self.world.pk, self.destination.pk, self.city.pk])

    def test_failed_save_rolls_back_order(self):
        self.city.name = ""
        self.city.parent = self.destination
        with self.assertRaises(ValidationError):
            self.city.save()
        self.city.refresh_from_db()
        self.assertEqual(self.city.parent_id, self.province.pk)


class ResidenceTests(GeographyTestCase):
    def test_optional_residence(self):
        self.assertIsNone(Character.objects.create(project=self.project, name="Traveler").residence_id)

    def test_same_project_residence(self):
        self.assertEqual(self.resident.residence_id, self.city.pk)

    def test_foreign_residence_rejected(self):
        self.resident.residence = self.foreign_location
        with self.assertRaises(ValidationError):
            self.resident.save()

    def test_character_project_change_rejected(self):
        self.resident.project = self.foreign
        self.resident.residence = None
        with self.assertRaises(ValidationError):
            self.resident.save()

    def test_form_scopes_locations(self):
        form = CharacterForm(project=self.project)
        self.assertIn(self.city, form.fields["residence"].queryset)
        self.assertNotIn(self.foreign_location, form.fields["residence"].queryset)
        self.assertFalse(CharacterForm().fields["residence"].queryset.exists())

    def test_post_residence_updates_without_changing_sheet_or_roles(self):
        role = CharacterDramaticRole.objects.create(character=self.resident, role="MENTOR")
        form = CharacterForm(instance=self.resident, project=self.project)
        data = {key: form[key].value() or "" for key in form.fields if key != "image"}
        data["residence"] = self.destination.pk
        data["dramatic_roles"] = [role.role]
        response = self.client.post(reverse("characters:edit", args=[self.project.pk, self.resident.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.resident.refresh_from_db()
        self.assertEqual(self.resident.residence_id, self.destination.pk)
        self.assertEqual(self.resident.biography, "Ficha intacta")
        self.assertEqual(list(self.resident.dramatic_roles.values_list("role", flat=True)), ["MENTOR"])

    def test_post_foreign_residence_rejected(self):
        data = {"name": "Elena", "importance": "SECUNDARIA", "narrative_role": "SECUNDARIO",
                "completion_status": "DRAFT", "residence": self.foreign_location.pk}
        form = CharacterForm(data, project=self.project, instance=self.resident)
        self.assertFalse(form.is_valid())
        self.assertIn("residence", form.errors)

    def test_character_detail_links_residence(self):
        response = self.client.get(reverse("characters:detail", args=[self.project.pk, self.resident.pk]))
        self.assertContains(response, self.url("detail", self.city))
        self.assertContains(response, "Habitante de")

    def test_location_lists_multiple_residents(self):
        second = Character.objects.create(project=self.project, name="Mateo", residence=self.city)
        response = self.client.get(self.url("detail", self.city))
        for resident in (self.resident, second):
            self.assertContains(response, reverse("characters:detail", args=[self.project.pk, resident.pk]))

    def test_corrupt_cross_project_residence_not_exposed(self):
        Character.objects.filter(pk=self.resident.pk).update(residence=self.foreign_location)
        response = self.client.get(reverse("characters:detail", args=[self.project.pk, self.resident.pk]))
        self.assertEqual(response.status_code, 404)


class GeographyViewTests(GeographyTestCase):
    def test_tree_collapsible_hierarchy_without_long_description(self):
        response = self.client.get(self.url("tree"))
        self.assertContains(response, "<details open>", count=4)
        self.assertContains(response, f'data-location-id="{self.city.pk}"')
        self.assertContains(response, self.city.short_description)
        self.assertNotContains(response, self.city.detailed_description)
        self.assertNotContains(response, "Private city")

    def test_tree_has_constant_query_count_and_no_long_fields(self):
        with CaptureQueriesContext(connection) as queries:
            events = tree_events(self.project)
        self.assertEqual(len(queries), 1)
        self.assertNotIn("detailed_description", queries[0]["sql"])
        self.assertEqual(len(events), 8)

    def test_deep_tree_is_iterative(self):
        rows = [Location(id=100000 + i, project=self.project, parent_id=100000 + i - 1 if i else None,
                         name=f"Depth {i}", position=100 if i == 0 else 1) for i in range(1100)]
        Location.objects.bulk_create(rows)
        with self.assertNumQueries(1):
            events = tree_events(self.project)
        self.assertEqual(len(events), 2208)
        with self.assertNumQueries(1):
            self.assertEqual(len(location_path(rows[-1])), 1100)

    def test_corrupt_cycle_reported_not_looped_or_silently_omitted(self):
        Location.objects.filter(pk=self.world.pk).update(parent=self.city)
        with self.assertRaises(ValidationError):
            tree_events(self.project)
        with self.assertRaises(ValidationError):
            location_path(self.city)

    def test_detail_has_path_children_and_descriptions(self):
        response = self.client.get(self.url("detail", self.city))
        self.assertContains(response, "Ruta jerárquica")
        self.assertContains(response, self.city.detailed_description)
        self.assertContains(response, self.province.name)
        response = self.client.get(self.url("detail", self.world))
        self.assertContains(response, self.url("detail", self.destination))

    def test_project_navigation(self):
        self.assertContains(self.client.get(reverse("projects:detail", args=[self.project.pk])), self.url("tree"))

    def test_create_child(self):
        response = self.client.get(self.url("create") + f"?parent={self.city.pk}")
        self.assertEqual(response.context["form"].initial["parent"], self.city.pk)
        response = self.client.post(self.url("create"), {"name": "Barrio", "location_type": "OTHER", "parent": self.city.pk})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Location.objects.get(name="Barrio").parent_id, self.city.pk)

    def test_edit_descriptions_ignores_posted_parent_project_and_position(self):
        response = self.client.post(self.url("edit", self.city), {"name": self.city.name, "location_type": "CITY",
            "short_description": "New short", "detailed_description": "New long", "parent": self.foreign_location.pk,
            "project": self.foreign.pk, "position": 999})
        self.assertEqual(response.status_code, 302)
        self.city.refresh_from_db()
        self.assertEqual(self.city.short_description, "New short")
        self.assertEqual(self.city.detailed_description, "New long")
        self.assertEqual((self.city.project_id, self.city.parent_id, self.city.position), (self.project.pk, self.province.pk, 1))

    def test_move_post(self):
        response = self.client.post(self.url("move", self.city), {"parent": self.destination.pk, "position": 1})
        self.assertRedirects(response, self.url("tree"))
        self.city.refresh_from_db()
        self.assertEqual(self.city.parent_id, self.destination.pk)

    def test_forged_move_and_parent_creation(self):
        for url, data in ((self.url("move", self.city), {"parent": self.foreign_location.pk}),
                          (self.url("create"), {"name": "Invalid", "location_type": "CITY", "parent": self.foreign_location.pk})):
            response = self.client.post(url, data)
            self.assertEqual(response.status_code, 200)
            self.assertIn("parent", response.context["form"].errors)

    def test_foreign_or_invalid_create_parent_get_404(self):
        for pk in (self.foreign_location.pk, "invalid", 999999):
            self.assertEqual(self.client.get(self.url("create") + f"?parent={pk}").status_code, 404)

    def test_delete_requires_confirmation_and_post(self):
        response = self.client.get(self.url("delete", self.destination))
        self.assertContains(response, "Confirmar eliminación")
        self.assertTrue(Location.objects.filter(pk=self.destination.pk).exists())
        response = self.client.post(self.url("delete", self.destination))
        self.assertRedirects(response, self.url("tree"))
        self.assertFalse(Location.objects.filter(pk=self.destination.pk).exists())

    def test_delete_blockers_explained(self):
        for location, message in ((self.world, "ubicaciones hijas"), (self.city, "personajes habitantes")):
            response = self.client.post(self.url("delete", location))
            self.assertContains(response, message)
            self.assertNotContains(response, "Confirmar eliminación")
            self.assertTrue(Location.objects.filter(pk=location.pk).exists())

    def test_reorder_post_only(self):
        for name in ("move_up", "move_down"):
            self.assertEqual(self.client.get(self.url(name, self.destination)).status_code, 405)
            self.assertEqual(self.client.post(self.url(name, self.destination)).status_code, 302)

    def test_csrf_required_on_all_writes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for name, location in (("create", None), ("edit", self.city), ("move", self.city),
                               ("delete", self.city), ("move_up", self.city), ("move_down", self.city)):
            self.assertEqual(client.post(self.url(name, location), {}).status_code, 403)

    def test_text_is_escaped(self):
        self.city.name = '<script>alert("name")</script>'
        self.city.detailed_description = '<img src=x onerror="alert(1)">'
        self.city.save()
        for name, location in (("tree", None), ("detail", self.city)):
            response = self.client.get(self.url(name, location))
            self.assertNotContains(response, "<script>")
            self.assertContains(response, "&lt;script&gt;")

    def test_residents_and_children_paginated(self):
        Character.objects.bulk_create([Character(project=self.project, name=f"Person {i}", residence=self.city) for i in range(55)])
        Location.objects.bulk_create([Location(project=self.project, parent=self.city, name=f"Child {i}", position=i + 1) for i in range(55)])
        response = self.client.get(self.url("detail", self.city))
        self.assertEqual(len(response.context["residents"]), 50)
        self.assertEqual(len(response.context["children"]), 50)
        response = self.client.get(self.url("detail", self.city) + "?residents_page=2&children_page=2")
        self.assertEqual(len(response.context["residents"]), 6)
        self.assertEqual(len(response.context["children"]), 5)


class GeographySecurityTests(GeographyTestCase):
    def test_anonymous_redirect(self):
        self.client.logout()
        for name, location in (("tree", None), ("detail", self.city), ("create", None), ("edit", self.city), ("move", self.city), ("delete", self.city)):
            self.assertEqual(self.client.get(self.url(name, location)).status_code, 302)

    def test_other_user_cannot_read_or_mutate(self):
        self.client.force_login(self.other)
        for name, location in (("tree", None), ("detail", self.city), ("create", None), ("edit", self.city),
                               ("move", self.city), ("delete", self.city), ("move_up", self.city), ("move_down", self.city)):
            self.assertEqual(self.client.post(self.url(name, location)).status_code, 405 if name in ("tree", "detail") else 404)
            if name not in ("move_up", "move_down"):
                self.assertEqual(self.client.get(self.url(name, location)).status_code, 404)

    def test_foreign_location_in_owned_project_url_404(self):
        for name in ("detail", "edit", "move", "delete"):
            self.assertEqual(self.client.get(self.url(name, self.foreign_location)).status_code, 404)

    def test_frozen_and_pending_read_only(self):
        for status in ("FROZEN", "PENDING_DELETION"):
            Project.objects.filter(pk=self.project.pk).update(status=status)
            for name, location in (("tree", None), ("detail", self.city)):
                response = self.client.get(self.url(name, location))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, self.url("edit", self.city))
            for name, location in (("create", None), ("edit", self.city), ("move", self.city), ("delete", self.city),
                                   ("move_up", self.city), ("move_down", self.city)):
                self.assertEqual(self.client.post(self.url(name, location), {}).status_code, 403)

    def test_deleted_inaccessible(self):
        Project.objects.filter(pk=self.project.pk).update(status="DELETED")
        for name, location in (("tree", None), ("detail", self.city), ("create", None), ("edit", self.city), ("move", self.city), ("delete", self.city)):
            self.assertEqual(self.client.get(self.url(name, location)).status_code, 404)

    def test_services_recheck_stale_project_status(self):
        for status in ("FROZEN", "PENDING_DELETION", "DELETED"):
            Project.objects.filter(pk=self.project.pk).update(status=status)
            for operation in (lambda: self.city.save(), lambda: move_location(self.city, None),
                              lambda: normalize_positions(self.project), lambda: delete_location(self.destination),
                              lambda: self.resident.save()):
                with self.subTest(status=status), self.assertRaises(ValidationError):
                    operation()

    def test_service_actor_cannot_bypass_ownership(self):
        for operation in (lambda: move_location(self.city, None, user=self.other),
                          lambda: delete_location(self.destination, user=self.other),
                          lambda: normalize_positions(self.project, user=self.other)):
            with self.assertRaises(Http404):
                operation()

    def test_private_cache_headers(self):
        response = self.client.get(self.url("tree"))
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("Cookie", response["Vary"])

    def test_admin_owner_scope_even_for_superuser(self):
        self.owner.is_staff = self.owner.is_superuser = True
        self.owner.user_type = "BUSINESS_ADMIN"
        self.owner.save()
        response = self.client.get(reverse("admin:geography_geographiclocation_changelist"))
        self.assertContains(response, self.city.name)
        self.assertNotContains(response, self.foreign_location.name)
        response = self.client.get(reverse("admin:geography_geographiclocation_change", args=[self.foreign_location.pk]))
        self.assertEqual(response.status_code, 404)

    def test_admin_blocks_referenced_delete_and_bulk_delete(self):
        self.owner.is_staff = self.owner.is_superuser = True
        self.owner.save()
        model_admin = admin.site._registry[Location]
        request = RequestFactory().get("/admin/")
        request.user = self.owner
        self.assertFalse(model_admin.has_delete_permission(request, self.city))
        self.assertFalse(model_admin.has_delete_permission(request, self.world))
        with self.assertRaises(PermissionDenied):
            model_admin.delete_queryset(request, Location.objects.filter(pk=self.destination.pk))

    def test_admin_creates_and_edits_location(self):
        self.owner.is_staff = self.owner.is_superuser = True
        self.owner.save()
        response = self.client.post(reverse("admin:geography_geographiclocation_add"), {
            "project": self.project.pk, "parent": self.world.pk, "name": "Admin location", "location_type": "OTHER", "_save": "Save"})
        self.assertEqual(response.status_code, 302)
        location = Location.objects.get(name="Admin location")
        response = self.client.post(reverse("admin:geography_geographiclocation_change", args=[location.pk]), {
            "name": "Admin edited", "location_type": "CITY", "detailed_description": "More detail", "_save": "Save"})
        self.assertEqual(response.status_code, 302)
        location.refresh_from_db()
        self.assertEqual(location.parent_id, self.world.pk)
        self.assertEqual(location.detailed_description, "More detail")

    def test_admin_character_residence_scoped(self):
        self.owner.is_staff = self.owner.is_superuser = True
        self.owner.save()
        second_project = Project.objects.create(user=self.owner, name="Second own project")
        extra = Location.objects.create(project=second_project, name="Other own city")
        response = self.client.get(reverse("admin:characters_character_change", args=[self.resident.pk]))
        choices = response.context["adminform"].form.fields["residence"].queryset
        self.assertIn(self.city, choices)
        self.assertNotIn(extra, choices)
        self.assertNotIn(self.foreign_location, choices)
