from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.test import Client, RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.characters.models import Character
from apps.geography.models import GeographicLocation as Location
from apps.projects.models import Project

from .forms import MembershipForm, MoveOrganizationForm, OrganizationForm
from .membership_services import delete_membership, save_membership
from .models import CharacterOrganizationMembership as Membership, Organization
from .selectors import organization_path, project_memberships, tree_events
from .services import (delete_organization, get_valid_parent_queryset, move_organization,
                       move_organization_down, move_organization_up, normalize_positions, save_organization)


class OrganizationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(email="org-owner@example.test", user_type="PREMIUM")
        cls.other = get_user_model().objects.create_user(email="org-other@example.test", user_type="PREMIUM")
        cls.project = Project.objects.create(user=cls.owner, name="Organizations")
        cls.foreign = Project.objects.create(user=cls.other, name="Private world")
        cls.own_other = Project.objects.create(user=cls.owner, name="Another owned world")
        cls.city = Location.objects.create(project=cls.project, name="Ciudad de Cristal", location_type="CITY")
        cls.foreign_city = Location.objects.create(project=cls.foreign, name="Secret city")
        cls.council = Organization.objects.create(project=cls.project, name="Consejo de Luz", organization_type="POLITICAL", headquarters=cls.city)
        cls.guard = Organization.objects.create(project=cls.project, parent=cls.council, name="Guardia de Cristal", organization_type="MILITARY",
                                              short_description="Guardia", detailed_description="Historia\nTradiciones")
        cls.academy = Organization.objects.create(project=cls.project, parent=cls.council, name="Academia", organization_type="ACADEMIC")
        cls.foreign_org = Organization.objects.create(project=cls.foreign, name="Secret organization")
        cls.own_other_org = Organization.objects.create(project=cls.own_other, name="Other owned organization")
        cls.rosariel = Character.objects.create(project=cls.project, name="Rosariel", biography="Original biography")
        cls.fernaud = Character.objects.create(project=cls.project, name="Fernaud")
        cls.foreign_character = Character.objects.create(project=cls.foreign, name="Secret character")
        cls.member = Membership.objects.create(character=cls.rosariel, organization=cls.guard, position_title="Comandante")

    def setUp(self):
        self.client.force_login(self.owner)

    def url(self, name, obj=None, project=None):
        kwargs = {"project_pk": (project or self.project).pk}
        if obj:
            kwargs["membership_pk" if name.startswith("membership_") else "organization_pk"] = obj.pk
        return reverse(f"organizations:{name}", kwargs=kwargs)

    def org_data(self, **overrides):
        return {"name": "New organization", "organization_type": "OTHER", "parent": "", "headquarters": "", **overrides}

    def member_data(self, **overrides):
        return {"character": self.rosariel.pk, "organization": self.council.pk, "position_title": "Consejera",
                "membership_status": "ACTIVE", "joined_at_text": "Año 412 de la Tercera Era", "left_at_text": "",
                "description": "Servicio al consejo", "return_to": "character", **overrides}

    def assert_positions(self):
        groups = {}
        for parent, position in Organization.objects.filter(project=self.project).values_list("parent_id", "position"):
            groups.setdefault(parent, []).append(position)
        for positions in groups.values():
            self.assertEqual(positions, list(range(1, len(positions) + 1)))


class OrganizationModelTests(OrganizationTestCase):
    def test_root_and_subordinate(self):
        self.assertIsNone(self.council.parent_id)
        self.assertEqual(self.guard.parent_id, self.council.pk)

    def test_name_and_project_required(self):
        for kwargs in ({"project": self.project, "name": ""}, {"project": self.project, "name": "  "}, {"name": "Missing project"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                Organization.objects.create(**kwargs)

    def test_all_types_valid(self):
        for value in Organization.OrganizationType.values:
            with self.subTest(value=value):
                self.assertEqual(Organization.objects.create(project=self.project, name=value, organization_type=value).organization_type, value)

    def test_other_custom_type(self):
        obj = Organization.objects.create(project=self.project, name="Order", custom_organization_type="Orden")
        self.assertEqual(obj.type_label, "Orden")

    def test_non_other_clears_custom_type(self):
        self.council.custom_organization_type = "Ignored"
        self.council.save()
        self.council.refresh_from_db()
        self.assertEqual(self.council.custom_organization_type, "")

    def test_update_fields_type_also_clears_custom(self):
        obj = Organization.objects.create(project=self.project, name="Order", custom_organization_type="Orden")
        obj.organization_type = "GUILD"
        obj.save(update_fields=["organization_type"])
        obj.refresh_from_db()
        self.assertEqual(obj.custom_organization_type, "")

    def test_invalid_type(self):
        with self.assertRaises(ValidationError):
            Organization.objects.create(project=self.project, name="Bad", organization_type="INVALID")

    def test_cross_project_parent_and_headquarters(self):
        for field, obj in (("parent", self.foreign_org), ("parent", self.own_other_org), ("headquarters", self.foreign_city)):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                Organization.objects.create(project=self.project, name="Bad", **{field: obj})

    def test_direct_and_indirect_cycles(self):
        for parent in (self.council, self.guard):
            with self.subTest(parent=parent), self.assertRaises(ValidationError):
                self.council.parent = parent
                self.council.save()

    def test_project_transfer_rejected(self):
        self.academy.project = self.own_other
        self.academy.parent = None
        with self.assertRaises(ValidationError):
            self.academy.save()

    def test_explicit_pk_cannot_overwrite(self):
        with self.assertRaises(ValidationError):
            Organization(id=self.guard.pk, project=self.project, name="Overwrite").save()

    def test_deleted_instance_not_resurrected(self):
        stale = Organization.objects.get(pk=self.academy.pk)
        self.academy.delete()
        with self.assertRaises(ValidationError):
            stale.save()

    def test_automatic_positions(self):
        obj = Organization.objects.create(project=self.project, name="Third", parent=self.council)
        self.assertEqual(obj.position, 3)
        self.assert_positions()

    def test_insert_at_position(self):
        obj = Organization.objects.create(project=self.project, name="First", parent=self.council, position=1)
        self.assertEqual(list(self.council.children.values_list("pk", flat=True)), [obj.pk, self.guard.pk, self.academy.pk])
        self.assert_positions()

    def test_normalize_positions(self):
        Organization.objects.filter(pk=self.guard.pk).update(position=10)
        Organization.objects.filter(pk=self.academy.pk).update(position=20)
        normalize_positions(self.project, self.council, user=self.owner)
        self.assert_positions()

    def test_normalize_foreign_parent_rejected(self):
        with self.assertRaises(ValidationError):
            normalize_positions(self.project, self.foreign_org)

    def test_database_constraints(self):
        for values in ({"position": 0}, {"organization_type": "BAD"}, {"name": ""}, {"parent_id": self.guard.pk},
                       {"custom_organization_type": "Invalid"}, {"position": self.academy.position}):
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                Organization.objects.filter(pk=self.guard.pk).update(**values)

    def test_duplicate_root_position_database_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Organization.objects.bulk_create([Organization(project=self.project, name="Bad", position=1)])

    def test_delete_children_blocked(self):
        with self.assertRaises(ValidationError):
            self.council.delete()
        with self.assertRaises(ProtectedError):
            Organization.objects.filter(pk=self.council.pk).delete()

    def test_delete_memberships_blocked_including_former(self):
        self.member.membership_status = "FORMER"
        self.member.save()
        with self.assertRaises(ValidationError):
            self.guard.delete()
        with self.assertRaises(ProtectedError):
            Organization.objects.filter(pk=self.guard.pk).delete()

    def test_delete_leaf_normalizes_positions(self):
        self.member.delete()
        self.guard.delete()
        self.academy.refresh_from_db()
        self.assertEqual(self.academy.position, 1)


class MovementTests(OrganizationTestCase):
    def test_move_preserves_identity_text_headquarters_and_memberships(self):
        self.guard.headquarters = self.city
        self.guard.save()
        before = (self.guard.pk, self.guard.name, self.guard.detailed_description, self.guard.short_description, self.guard.created_at, self.guard.headquarters_id)
        moved = move_organization(self.guard, self.academy, user=self.owner)
        self.assertEqual(before, (moved.pk, moved.name, moved.detailed_description, moved.short_description, moved.created_at, moved.headquarters_id))
        self.member.refresh_from_db()
        self.assertEqual(self.member.organization_id, moved.pk)
        self.assertEqual(moved.parent_id, self.academy.pk)
        self.assert_positions()

    def test_move_to_root(self):
        moved = move_organization(self.guard, None)
        self.assertIsNone(moved.parent_id)
        self.assertEqual(moved.position, 2)
        self.assert_positions()

    def test_move_up(self):
        move_organization_up(self.academy)
        self.assertEqual(list(self.council.children.values_list("pk", flat=True)), [self.academy.pk, self.guard.pk])

    def test_move_down(self):
        move_organization_down(self.guard)
        self.assertEqual(list(self.council.children.values_list("pk", flat=True)), [self.academy.pk, self.guard.pk])

    def test_move_boundaries(self):
        move_organization_up(self.guard)
        move_organization_down(self.academy)
        self.assert_positions()

    def test_move_cycles_rejected(self):
        for parent in (self.council, self.guard):
            with self.subTest(parent=parent), self.assertRaises(ValidationError):
                move_organization(self.council, parent)

    def test_move_cross_project_rejected(self):
        for parent in (self.foreign_org, self.own_other_org):
            with self.subTest(parent=parent), self.assertRaises(ValidationError):
                move_organization(self.guard, parent)

    def test_position_validation(self):
        for position in (-1, 0, "bad", 1.2):
            with self.subTest(position=position), self.assertRaises(ValidationError):
                move_organization(self.guard, None, position)
        self.assert_positions()

    def test_stale_text_save_keeps_move(self):
        move_organization(self.guard, self.academy)
        self.guard.detailed_description = "Updated text"
        self.guard.save()
        self.guard.refresh_from_db()
        self.assertEqual(self.guard.parent_id, self.academy.pk)
        self.assertEqual(self.guard.detailed_description, "Updated text")

    def test_stale_structural_conflict_rejected(self):
        move_organization(self.guard, self.academy)
        self.guard.parent = None
        with self.assertRaises(ValidationError):
            self.guard.save()

    def test_valid_parent_queryset_excludes_self_descendants_and_foreign(self):
        ids = set(get_valid_parent_queryset(self.project, self.council).values_list("pk", flat=True))
        self.assertEqual(ids, set())
        self.assertEqual(set(get_valid_parent_queryset(self.project, self.guard).values_list("pk", flat=True)), {self.council.pk, self.academy.pk})


class MembershipModelTests(OrganizationTestCase):
    def test_default_and_optional_fields(self):
        obj = Membership.objects.create(character=self.fernaud, organization=self.academy)
        self.assertEqual(obj.membership_status, "ACTIVE")
        self.assertEqual(obj.position_title, "")

    def test_multiple_organizations(self):
        Membership.objects.create(character=self.rosariel, organization=self.council, position_title="Consejera")
        self.assertEqual(self.rosariel.organization_memberships.count(), 2)

    def test_multiple_members(self):
        Membership.objects.create(character=self.fernaud, organization=self.guard)
        self.assertEqual(self.guard.memberships.count(), 2)

    def test_historical_roles_and_periods(self):
        for title, period in (("Aprendiz", "Era 1"), ("Comandante", "Era 2"), ("Comandante", "Era 3")):
            Membership.objects.create(character=self.rosariel, organization=self.guard, position_title=title,
                                      membership_status="FORMER", joined_at_text=period, left_at_text="Antes del Gran Eclipse")
        self.assertEqual(self.guard.memberships.count(), 4)

    def test_exact_duplicate_rejected_even_with_other_description(self):
        with self.assertRaises(ValidationError):
            Membership.objects.create(character=self.rosariel, organization=self.guard, position_title=" Comandante ", description="Different")

    def test_database_duplicate_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.bulk_create([Membership(character=self.rosariel, organization=self.guard, position_title="Comandante")])

    def test_invalid_status(self):
        self.member.membership_status = "BAD"
        with self.assertRaises(ValidationError):
            self.member.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membership.objects.filter(pk=self.member.pk).update(membership_status="BAD")

    def test_foreign_character(self):
        with self.assertRaises(ValidationError):
            Membership.objects.create(character=self.foreign_character, organization=self.guard)

    def test_foreign_organization(self):
        for org in (self.foreign_org, self.own_other_org):
            with self.subTest(org=org), self.assertRaises(ValidationError):
                Membership.objects.create(character=self.rosariel, organization=org)

    def test_transfer_between_projects_forbidden(self):
        self.member.character = self.foreign_character
        self.member.organization = self.foreign_org
        with self.assertRaises(ValidationError):
            self.member.save()

    def test_edit_role_status_and_period(self):
        self.member.position_title = "Capitana"
        self.member.membership_status = "FORMER"
        self.member.left_at_text = "Durante la Guerra de los Cristales"
        self.member.save()
        self.member.refresh_from_db()
        self.assertEqual((self.member.position_title, self.member.membership_status), ("Capitana", "FORMER"))
        self.assertEqual(self.member.left_at_text, "Durante la Guerra de los Cristales")

    def test_delete_preserves_entities(self):
        delete_membership(self.member, user=self.owner)
        self.rosariel.refresh_from_db()
        self.guard.refresh_from_db()
        self.assertEqual(self.rosariel.biography, "Original biography")
        self.assertEqual(self.guard.detailed_description, "Historia\nTradiciones")

    def test_stale_partial_update_preserves_new_role(self):
        current = Membership.objects.get(pk=self.member.pk)
        current.position_title = "New role"
        current.save()
        self.member.description = "New description"
        self.member.save(update_fields=["description"])
        self.member.refresh_from_db()
        self.assertEqual(self.member.position_title, "New role")

    def test_explicit_pk_overwrite_and_resurrection_rejected(self):
        with self.assertRaises(ValidationError):
            Membership(id=self.member.pk, character=self.rosariel, organization=self.council).save()
        stale = Membership.objects.get(pk=self.member.pk)
        self.member.delete()
        with self.assertRaises(ValidationError):
            stale.save()


class OrganizationViewTests(OrganizationTestCase):
    def test_project_navigation(self):
        response = self.client.get(reverse("projects:detail", args=[self.project.pk]))
        self.assertContains(response, self.url("tree"))

    def test_tree_native_collapsible_and_short_text_only(self):
        response = self.client.get(self.url("tree"))
        self.assertContains(response, "<details open>")
        self.assertContains(response, self.guard.name)
        self.assertNotContains(response, self.guard.detailed_description)

    def test_create_preselected_parent(self):
        response = self.client.get(self.url("create"), {"parent": self.council.pk})
        self.assertEqual(response.context["form"].initial["parent"], self.council.pk)
        response = self.client.post(self.url("create"), self.org_data(parent=self.council.pk))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.council.children.filter(name="New organization").exists())

    def test_invalid_preselection_returns_404(self):
        for raw in ("abc", "9" * 100, self.foreign_org.pk, self.own_other_org.pk):
            with self.subTest(raw=raw):
                self.assertEqual(self.client.get(self.url("create"), {"parent": raw}).status_code, 404)

    def test_edit_cannot_move_through_hidden_fields(self):
        response = self.client.post(self.url("edit", self.guard), self.org_data(name="Edited", parent=self.academy.pk, project=self.foreign.pk))
        self.assertEqual(response.status_code, 302)
        self.guard.refresh_from_db()
        self.assertEqual((self.guard.project_id, self.guard.parent_id), (self.project.pk, self.council.pk))

    def test_move_and_reorder_post_only(self):
        self.assertEqual(self.client.get(self.url("move_up", self.academy)).status_code, 405)
        self.assertEqual(self.client.post(self.url("move_up", self.academy)).status_code, 302)
        self.assertEqual(self.client.post(self.url("move_down", self.academy)).status_code, 302)
        self.assertEqual(self.client.post(self.url("move", self.guard), {"parent": self.academy.pk, "position": 1}).status_code, 302)
        self.guard.refresh_from_db()
        self.assertEqual(self.guard.parent_id, self.academy.pk)

    def test_invalid_move_form_preserves_structure(self):
        response = self.client.post(self.url("move", self.council), {"parent": self.guard.pk, "position": 1})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.council.refresh_from_db()
        self.assertIsNone(self.council.parent_id)

    def test_detail_headquarters_and_members(self):
        self.assertContains(self.client.get(self.url("detail", self.council)), self.city.name)
        response = self.client.get(self.url("detail", self.guard))
        for text in (self.rosariel.name, "Comandante", "Activa", "Historia"):
            self.assertContains(response, text)

    def test_create_membership_preselection_and_character_return(self):
        response = self.client.get(self.url("membership_create"), {"character": self.rosariel.pk})
        self.assertEqual(response.context["form"].initial["character"], self.rosariel.pk)
        response = self.client.post(self.url("membership_create"), self.member_data())
        self.assertRedirects(response, reverse("characters:detail", args=[self.project.pk, self.rosariel.pk]))
        self.assertContains(self.client.get(response.url), "Consejera")

    def test_membership_organization_preselection(self):
        response = self.client.get(self.url("membership_create"), {"organization": self.academy.pk})
        self.assertEqual(response.context["form"].initial["organization"], self.academy.pk)

    def test_foreign_membership_references_rejected(self):
        for values in ({"character": self.foreign_character.pk}, {"organization": self.foreign_org.pk}, {"organization": self.own_other_org.pk}, {"character": "bad"}):
            for method in (self.client.get, self.client.post):
                with self.subTest(values=values, method=method):
                    self.assertEqual(method(self.url("membership_create"), self.member_data(**values)).status_code, 404)

    def test_edit_membership(self):
        response = self.client.post(self.url("membership_edit", self.member), self.member_data(organization=self.guard.pk, position_title="Capitana", membership_status="FORMER"))
        self.assertEqual(response.status_code, 302)
        self.member.refresh_from_db()
        self.assertEqual((self.member.position_title, self.member.membership_status), ("Capitana", "FORMER"))

    def test_no_open_redirect(self):
        response = self.client.post(self.url("membership_create"), self.member_data(return_to="https://example.com"))
        self.assertEqual(response.url, self.url("detail", self.council))

    def test_membership_delete_confirmation_post(self):
        url = self.url("membership_delete", self.member)
        self.assertContains(self.client.get(url), "Confirmar eliminación")
        self.assertTrue(Membership.objects.filter(pk=self.member.pk).exists())
        self.assertEqual(self.client.post(url, {"return_to": "character"}).status_code, 302)
        self.assertFalse(Membership.objects.filter(pk=self.member.pk).exists())
        self.assertTrue(Character.objects.filter(pk=self.rosariel.pk).exists())
        self.assertTrue(Organization.objects.filter(pk=self.guard.pk).exists())

    def test_organization_delete_confirmation_and_blockers(self):
        for org in (self.council, self.guard):
            with self.subTest(org=org):
                response = self.client.post(self.url("delete", org))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["blockers"])
                self.assertTrue(Organization.objects.filter(pk=org.pk).exists())
        url = self.url("delete", self.academy)
        self.assertContains(self.client.get(url), "Confirmar eliminación")
        self.assertTrue(Organization.objects.filter(pk=self.academy.pk).exists())
        self.assertEqual(self.client.post(url).status_code, 302)

    def test_character_affiliations_show_period_and_status(self):
        self.member.joined_at_text = "Año 412"
        self.member.membership_status = "FORMER"
        self.member.save()
        response = self.client.get(reverse("characters:detail", args=[self.project.pk, self.rosariel.pk]))
        for text in ("Afiliaciones", self.guard.name, "Comandante", "Anterior", "Año 412", "Editar afiliación"):
            self.assertContains(response, text)

    def test_text_is_escaped(self):
        self.guard.detailed_description = "<script>alert(1)</script>"
        self.guard.save()
        response = self.client.get(self.url("detail", self.guard))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")


class HeadquartersTests(OrganizationTestCase):
    def test_multiple_organizations_in_location(self):
        self.guard.headquarters = self.city
        self.guard.save()
        response = self.client.get(reverse("geography:detail", args=[self.project.pk, self.city.pk]))
        self.assertContains(response, self.council.name)
        self.assertContains(response, self.guard.name)

    def test_location_delete_model_and_ui_blocked(self):
        with self.assertRaises(ValidationError):
            self.city.delete()
        response = self.client.post(reverse("geography:delete", args=[self.project.pk, self.city.pk]))
        self.assertContains(response, "sede de organizaciones")
        self.council.refresh_from_db()
        self.assertEqual(self.council.headquarters_id, self.city.pk)

    def test_detaching_headquarters_allows_delete(self):
        self.council.headquarters = None
        self.council.save(update_fields=["headquarters"])
        self.city.delete()
        self.council.refresh_from_db()
        self.assertIsNone(self.council.headquarters_id)

    def test_set_null_fallback_never_cascades_organizations(self):
        Location.objects.filter(pk=self.city.pk).delete()
        self.council.refresh_from_db()
        self.assertIsNone(self.council.headquarters_id)

    def test_foreign_corrupt_headquarters_hidden(self):
        Organization.objects.filter(pk=self.foreign_org.pk).update(headquarters=self.city)
        response = self.client.get(reverse("geography:detail", args=[self.project.pk, self.city.pk]))
        self.assertNotContains(response, self.foreign_org.name)


class PermissionTests(OrganizationTestCase):
    def endpoints(self):
        return [self.url(name, obj) for name, obj in (
            ("tree", None), ("detail", self.guard), ("create", None), ("edit", self.guard),
            ("move", self.guard), ("delete", self.guard), ("membership_create", None),
            ("membership_edit", self.member), ("membership_delete", self.member))]

    def test_authentication_required(self):
        self.client.logout()
        for url in self.endpoints():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)

    def test_foreign_owner_404_for_read_and_write(self):
        self.client.force_login(self.other)
        for url in self.endpoints():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        for url in self.endpoints()[2:]:
            self.assertEqual(self.client.post(url).status_code, 404)
        self.assertEqual(self.client.post(self.url("move_up", self.guard)).status_code, 404)

    def test_business_and_technical_admin_no_content_bypass(self):
        for user_type in ("BUSINESS_ADMIN", "TECH_ADMIN"):
            self.other.user_type = user_type
            self.other.is_superuser = self.other.is_staff = True
            self.other.save()
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(self.url("detail", self.guard)).status_code, 404)
            self.assertEqual(self.client.post(self.url("membership_edit", self.member)).status_code, 404)

    def test_read_only_states_and_hidden_actions(self):
        for status in ("FROZEN", "PENDING_DELETION"):
            Project.objects.filter(pk=self.project.pk).update(status=status)
            for url in self.endpoints()[:2]:
                self.assertEqual(self.client.get(url).status_code, 200)
            for url in self.endpoints()[2:] + [self.url("move_up", self.guard), self.url("move_down", self.guard)]:
                with self.subTest(status=status, url=url):
                    self.assertEqual(self.client.post(url).status_code, 403)
            response = self.client.get(self.url("detail", self.guard))
            self.assertNotContains(response, "Agregar afiliación")
            self.assertNotContains(response, "Editar afiliación")

    def test_deleted_project_404(self):
        Project.objects.filter(pk=self.project.pk).update(status="DELETED")
        for url in self.endpoints():
            self.assertEqual(self.client.get(url).status_code, 404)
        for url in self.endpoints()[2:]:
            self.assertEqual(self.client.post(url).status_code, 404)

    def test_service_actor_enforced(self):
        for operation in (lambda: move_organization(self.guard, None, user=self.other),
                          lambda: save_organization(self.guard, user=self.other),
                          lambda: save_membership(self.member, user=self.other),
                          lambda: delete_membership(self.member, user=self.other),
                          lambda: delete_organization(self.academy, user=self.other)):
            with self.assertRaises(Http404):
                operation()

    def test_stale_project_state_cannot_write_through_model(self):
        Project.objects.filter(pk=self.project.pk).update(status="FROZEN")
        for operation in (self.guard.save, self.member.save, self.member.delete, self.academy.delete,
                          lambda: move_organization(self.guard, None), lambda: normalize_positions(self.project)):
            with self.assertRaises(ValidationError):
                operation()

    def test_csrf_on_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for url in self.endpoints()[2:] + [self.url("move_up", self.guard), self.url("move_down", self.guard)]:
            self.assertEqual(client.post(url).status_code, 403)

    def test_forms_scope_same_project(self):
        form = OrganizationForm(project=self.project)
        self.assertNotIn(self.foreign_org, form.fields["parent"].queryset)
        self.assertNotIn(self.own_other_org, form.fields["parent"].queryset)
        self.assertNotIn(self.foreign_city, form.fields["headquarters"].queryset)
        membership = MembershipForm(self.member_data(organization=self.own_other_org.pk), project=self.project)
        self.assertFalse(membership.is_valid())
        move = MoveOrganizationForm(project=self.project, organization=self.council)
        self.assertFalse(move.fields["parent"].queryset.exists())

    def test_corrupt_cross_project_membership_hidden(self):
        Membership.objects.filter(pk=self.member.pk).update(character=self.foreign_character)
        self.assertFalse(project_memberships(self.project).exists())
        self.assertEqual(self.client.get(self.url("membership_edit", self.member)).status_code, 404)


class OrganizationAdminTests(OrganizationTestCase):
    def setUp(self):
        super().setUp()
        self.owner.is_staff = self.owner.is_superuser = True
        self.owner.save()
        self.request = RequestFactory().get("/admin/")
        self.request.user = self.owner

    def test_admin_owner_scope_for_both_models(self):
        org_admin = admin.site._registry[Organization]
        member_admin = admin.site._registry[Membership]
        self.assertNotIn(self.foreign_org, org_admin.get_queryset(self.request))
        foreign_member = Membership.objects.create(character=self.foreign_character, organization=self.foreign_org)
        self.assertNotIn(foreign_member, member_admin.get_queryset(self.request))
        with self.assertRaises(Http404):
            org_admin.get_object(self.request, str(self.foreign_org.pk))

    def test_admin_relation_form_scoped_and_cross_project_clean(self):
        request = RequestFactory().get("/admin/", {"project": self.project.pk})
        request.user = self.owner
        form = admin.site._registry[Organization].get_form(request)
        self.assertNotIn(self.own_other_org, form.base_fields["parent"].queryset)
        request = RequestFactory().post("/admin/", self.member_data(organization=self.own_other_org.pk))
        request.user = self.owner
        form = admin.site._registry[Membership].get_form(request)
        self.assertFalse(form(request.POST).is_valid())

    def test_admin_read_only_and_blocked_delete(self):
        org_admin = admin.site._registry[Organization]
        self.assertFalse(org_admin.has_delete_permission(self.request, self.guard))
        Project.objects.filter(pk=self.project.pk).update(status="FROZEN")
        self.guard.project.refresh_from_db()
        self.assertFalse(org_admin.has_change_permission(self.request, self.guard))

    def test_admin_bulk_delete_disabled(self):
        for model in (Organization, Membership):
            model_admin = admin.site._registry[model]
            self.assertEqual(model_admin.get_actions(self.request), {})
            with self.assertRaises(PermissionDenied):
                model_admin.delete_queryset(self.request, model.objects.all())

    def test_admin_pages_render(self):
        for name in ("organizations_organization_changelist", "organizations_characterorganizationmembership_changelist",
                     "organizations_organization_add", "organizations_characterorganizationmembership_add"):
            self.assertEqual(self.client.get(reverse(f"admin:{name}")).status_code, 200)


class PerformanceTests(OrganizationTestCase):
    def test_tree_single_query_deferred_long_text(self):
        with self.assertNumQueries(1):
            events = tree_events(self.project)
        for event in events:
            if event["kind"] == "open":
                self.assertIn("detailed_description", event["organization"].get_deferred_fields())

    def test_path_single_query(self):
        with self.assertNumQueries(1):
            path = organization_path(self.guard)
        self.assertEqual([obj.pk for obj in path], [self.council.pk, self.guard.pk])

    def test_memberships_no_per_row_queries(self):
        Membership.objects.bulk_create([Membership(character=self.rosariel, organization=self.guard, position_title=f"Role {i}") for i in range(60)])
        with self.assertNumQueries(1):
            for obj in project_memberships(self.project):
                str(obj.character)
                str(obj.organization)

    def test_paginated_detail_query_count_does_not_grow(self):
        url = self.url("detail", self.guard)
        with CaptureQueriesContext(connection) as baseline:
            self.client.get(url)
        Membership.objects.bulk_create([Membership(character=self.rosariel, organization=self.guard, position_title=f"Role {i}") for i in range(60)])
        with CaptureQueriesContext(connection) as expanded:
            response = self.client.get(url)
        self.assertEqual(len(response.context["memberships"]), 50)
        self.assertLessEqual(len(expanded), len(baseline) + 1)
        self.assertEqual(len(self.client.get(url, {"memberships_page": 2}).context["memberships"]), 11)

    def test_deep_iterative_tree(self):
        # Bulk creation isolates traversal cost from intentionally serialized model writes.
        start = 100000
        Organization.objects.bulk_create([Organization(id=start+i, project=self.project, name=f"Level {i}",
            parent_id=start+i-1 if i else None, position=1 if i else 2) for i in range(1100)])
        with self.assertNumQueries(1):
            events = tree_events(self.project)
        self.assertEqual(len(events), 2206)

    def test_corrupt_cycle_fails_closed(self):
        Organization.objects.filter(pk=self.council.pk).update(parent=self.guard)
        with self.assertRaises(ValidationError):
            tree_events(self.project)
        response = self.client.get(self.url("tree"))
        self.assertContains(response, "Requiere revisión")
