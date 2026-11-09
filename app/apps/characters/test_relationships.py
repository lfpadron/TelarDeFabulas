from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.http import Http404
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.projects.models import Project
from .models import Character, CharacterDramaticRole, CharacterRelationship as Relationship
from .relationship_forms import CharacterRelationshipForm
from .relationship_selectors import relationship_groups
from .relationship_services import create_relationship, delete_relationship, get_relationships_for_character, update_relationship


class RelationshipFixtures:
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(email="relationships@example.test", user_type="PREMIUM")
        self.other = get_user_model().objects.create_user(email="foreign-relationships@example.test")
        self.project = Project.objects.create(user=self.user, name="Relationships")
        self.second_project = Project.objects.create(user=self.user, name="Second project")
        self.foreign_project = Project.objects.create(user=self.other, name="Foreign project")
        self.source = Character.objects.create(project=self.project, name="Rosariel", biography="Original biography")
        self.target = Character.objects.create(project=self.project, name="Fernaud")
        self.third = Character.objects.create(project=self.project, name="Arkan")
        self.same_owner_character = Character.objects.create(project=self.second_project, name="Second character")
        self.foreign = Character.objects.create(project=self.foreign_project, name="Foreign secret")

    def relationship(self, **data):
        return create_relationship(self.project, **{"source_character": self.source, "target_character": self.target,
            "relationship_type": "TRUST", **data})

    def payload(self, **data):
        return {"source_character": self.source.pk, "target_character": self.target.pk, "relationship_type": "TRUST",
            "custom_relationship_type": "", "description": "First paragraph\r\n  Second paragraph", **data}

    def url(self, action, relationship=None, character=None, project=None):
        args = [(project or self.project).pk]
        args.append((character or self.source).pk if action in ("list", "create") else relationship.pk)
        return reverse("characters:relationship_" + action, args=args)


class RelationshipModelTests(RelationshipFixtures, TestCase):
    def test_unilateral_defaults(self):
        relationship = Relationship.objects.create(project=self.project, source_character=self.source, target_character=self.target)
        self.assertFalse(relationship.is_reciprocal)
        self.assertEqual(relationship.relationship_type, "FRIEND")
        self.assertIsNotNone(relationship.created_at)
        self.assertIsNotNone(relationship.updated_at)

    def test_reciprocal_single_record_without_reordering_endpoints(self):
        relationship = self.relationship(source_character=self.target, target_character=self.source, is_reciprocal=True)
        self.assertEqual(Relationship.objects.count(), 1)
        self.assertEqual((relationship.source_character_id, relationship.target_character_id), (self.target.pk, self.source.pk))

    def test_all_defined_types(self):
        self.assertEqual(len(Relationship.RelationshipType.values), 15)
        for kind in Relationship.RelationshipType.values:
            relationship = self.relationship(relationship_type=kind, custom_relationship_type="Vínculo" if kind == "OTHER" else "")
            self.assertEqual(relationship.relationship_type, kind)

    def test_required_project(self):
        with self.assertRaises(ValidationError):
            Relationship(source_character=self.source, target_character=self.target).save()

    def test_required_source(self):
        with self.assertRaises(ValidationError):
            create_relationship(self.project, target_character=self.target)

    def test_required_target(self):
        with self.assertRaises(ValidationError):
            create_relationship(self.project, source_character=self.source)

    def test_self_relationship_rejected(self):
        with self.assertRaises(ValidationError):
            self.relationship(target_character=self.source)

    def test_other_project_same_owner_rejected(self):
        for key in ("source_character", "target_character"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                self.relationship(**{key: self.same_owner_character})

    def test_foreign_author_rejected(self):
        with self.assertRaises(ValidationError):
            self.relationship(target_character=self.foreign)

    def test_clean_also_validates_cross_project(self):
        relationship = Relationship(project=self.project, source_character=self.source, target_character=self.foreign)
        with self.assertRaises(ValidationError):
            relationship.full_clean()

    def test_invalid_type(self):
        with self.assertRaises(ValidationError):
            self.relationship(relationship_type="INVALID")

    def test_other_requires_nonblank_custom_type(self):
        for custom in ("", "  \t\n"):
            with self.assertRaises(ValidationError):
                self.relationship(relationship_type="OTHER", custom_relationship_type=custom)

    def test_other_custom_type_is_trimmed(self):
        relationship = self.relationship(relationship_type="OTHER", custom_relationship_type="  Vínculo mágico  ")
        self.assertEqual(relationship.type_label, "Vínculo mágico")

    def test_custom_type_cleared_for_standard_type(self):
        relationship = self.relationship(custom_relationship_type="Do not replace TRUST")
        self.assertEqual(relationship.custom_relationship_type, "")

    def test_exact_duplicate(self):
        self.relationship()
        with self.assertRaises(ValidationError):
            self.relationship(description="Different description")

    def test_custom_label_is_not_an_extra_identity(self):
        self.relationship(relationship_type="OTHER", custom_relationship_type="First")
        with self.assertRaises(ValidationError):
            self.relationship(relationship_type="OTHER", custom_relationship_type="Second")

    def test_same_pair_different_types(self):
        for kind in ("FRIEND", "TRUST", "ALLY"):
            self.relationship(relationship_type=kind)
        self.assertEqual(Relationship.objects.count(), 3)

    def test_two_opposed_unilateral_relationships_allowed(self):
        self.relationship()
        self.relationship(source_character=self.target, target_character=self.source)
        self.assertEqual(Relationship.objects.count(), 2)

    def test_mutual_inverse_duplicate_rejected(self):
        self.relationship(is_reciprocal=True)
        with self.assertRaises(ValidationError):
            self.relationship(source_character=self.target, target_character=self.source, is_reciprocal=True)

    def test_unilateral_inverse_of_mutual_rejected(self):
        self.relationship(is_reciprocal=True)
        with self.assertRaises(ValidationError):
            self.relationship(source_character=self.target, target_character=self.source)

    def test_mutual_inverse_of_unilateral_rejected(self):
        self.relationship()
        with self.assertRaises(ValidationError):
            self.relationship(source_character=self.target, target_character=self.source, is_reciprocal=True)

    def test_directional_types_cannot_be_reciprocal(self):
        for kind in ("PARENT", "CHILD", "MENTOR", "STUDENT"):
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                self.relationship(relationship_type=kind, is_reciprocal=True)

    def test_other_types_can_be_reciprocal(self):
        for kind in set(Relationship.RelationshipType.values) - {"PARENT", "CHILD", "MENTOR", "STUDENT"}:
            self.relationship(relationship_type=kind, is_reciprocal=True, custom_relationship_type="Magic" if kind == "OTHER" else "")

    def test_no_automatic_semantic_inverse_or_dramatic_role(self):
        self.relationship(relationship_type="MENTOR")
        self.assertEqual(Relationship.objects.count(), 1)
        self.assertFalse(CharacterDramaticRole.objects.exists())

    def test_sql_exact_duplicate(self):
        self.relationship()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Relationship.objects.bulk_create([Relationship(project=self.project, source_character=self.source, target_character=self.target, relationship_type="TRUST")])

    def test_sql_reciprocal_inverse_duplicate(self):
        self.relationship(is_reciprocal=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Relationship.objects.bulk_create([Relationship(project=self.project, source_character=self.target, target_character=self.source, relationship_type="TRUST", is_reciprocal=True)])

    def test_sql_checks(self):
        for data in ({"target_character": self.source}, {"relationship_type": "WRONG"},
                     {"relationship_type": "PARENT", "is_reciprocal": True},
                     {"relationship_type": "OTHER", "custom_relationship_type": "   "}, {"custom_relationship_type": "Invalid"}):
            with self.subTest(data=data), self.assertRaises(IntegrityError), transaction.atomic():
                Relationship.objects.bulk_create([Relationship(**{"project": self.project, "source_character": self.source, "target_character": self.target, **data})])

    def test_fk_indexes_present(self):
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, Relationship._meta.db_table)
        for column in ("project_id", "source_character_id", "target_character_id"):
            self.assertTrue(any(c["index"] and c["columns"] == [column] for c in constraints.values()), column)


class RelationshipServiceTests(RelationshipFixtures, TestCase):
    def test_update_retains_identity_and_creation_time(self):
        relationship = self.relationship()
        updated = update_relationship(relationship, target_character=self.third, relationship_type="RIVAL", description="New\r\nText", is_reciprocal=True)
        self.assertEqual((updated.pk, updated.created_at), (relationship.pk, relationship.created_at))
        self.assertEqual((updated.target_character, updated.description, updated.is_reciprocal), (self.third, "New\r\nText", True))

    def test_update_other_to_standard_clears_custom(self):
        relationship = self.relationship(relationship_type="OTHER", custom_relationship_type="Magic")
        self.assertEqual(update_relationship(relationship, relationship_type="FRIEND").custom_relationship_type, "")

    def test_promoting_to_reciprocal_rejects_existing_inverse(self):
        relationship = self.relationship()
        self.relationship(source_character=self.target, target_character=self.source)
        with self.assertRaises(ValidationError):
            update_relationship(relationship, is_reciprocal=True)
        relationship.refresh_from_db()
        self.assertFalse(relationship.is_reciprocal)

    def test_reciprocal_can_become_unilateral(self):
        relationship = self.relationship(is_reciprocal=True)
        update_relationship(relationship, is_reciprocal=False)
        self.relationship(source_character=self.target, target_character=self.source)
        self.assertEqual(Relationship.objects.count(), 2)

    def test_update_collision_keeps_original(self):
        relationship = self.relationship()
        self.relationship(relationship_type="ALLY")
        with self.assertRaises(ValidationError):
            update_relationship(relationship, relationship_type="ALLY", description="Lost")
        relationship.refresh_from_db()
        self.assertEqual((relationship.relationship_type, relationship.description), ("TRUST", ""))

    def test_delete_only_relationship(self):
        relationship = self.relationship()
        other = self.relationship(relationship_type="ALLY")
        before = list(Character.objects.order_by("pk").values())
        delete_relationship(relationship, user=self.user)
        self.assertEqual(list(Character.objects.order_by("pk").values()), before)
        self.assertEqual(list(Relationship.objects.values_list("pk", flat=True)), [other.pk])

    def test_delete_character_cascades_only_incident_relationships(self):
        self.relationship()
        self.relationship(source_character=self.third, target_character=self.source, relationship_type="ENEMY")
        preserved = self.relationship(source_character=self.target, target_character=self.third, relationship_type="ALLY")
        self.source.delete()
        self.assertEqual(list(Relationship.objects.values_list("pk", flat=True)), [preserved.pk])
        self.assertTrue(Character.objects.filter(pk=self.target.pk).exists())
        self.assertTrue(Character.objects.filter(pk=self.third.pk).exists())

    def test_no_transfer_to_another_project(self):
        relationship = self.relationship()
        relationship.project = self.second_project
        with self.assertRaises(ValidationError):
            relationship.save()

    def test_noneditable_fields_rejected(self):
        relationship = self.relationship()
        for key in ("project", "id", "created_at"):
            with self.assertRaises(ValidationError):
                update_relationship(relationship, **{key: self.second_project})

    def test_model_save_update_fields_preserves_other_current_fields(self):
        relationship = self.relationship()
        update_relationship(relationship, target_character=self.third, is_reciprocal=True)
        relationship.description = "Partial edit"
        relationship.save(update_fields=["description"])
        self.assertEqual((relationship.target_character_id, relationship.is_reciprocal, relationship.description), (self.third.pk, True, "Partial edit"))

    def test_model_save_rejects_explicit_identity(self):
        with self.assertRaises(ValidationError):
            Relationship(pk=123, project=self.project, source_character=self.source, target_character=self.target).save()

    def test_save_of_deleted_instance_does_not_resurrect(self):
        relationship = self.relationship()
        delete_relationship(Relationship.objects.get(pk=relationship.pk))
        with self.assertRaises(ValidationError):
            relationship.save()
        self.assertFalse(Relationship.objects.exists())

    def test_fresh_project_status_checked(self):
        relationship = self.relationship()
        Project.objects.filter(pk=self.project.pk).update(status="FROZEN")
        for operation in (lambda: self.relationship(relationship_type="ALLY"), lambda: update_relationship(relationship, description="Blocked"), lambda: delete_relationship(relationship)):
            with self.assertRaises(ValidationError):
                operation()

    def test_service_actor_must_own_project(self):
        relationship = self.relationship()
        for operation in (lambda: self.relationship(relationship_type="ALLY", user=self.other), lambda: update_relationship(relationship, user=self.other),
                          lambda: delete_relationship(relationship, user=self.other), lambda: list(get_relationships_for_character(self.source, user=self.other))):
            with self.assertRaises(Http404):
                operation()

    def test_failed_update_rolls_back(self):
        relationship = self.relationship(description="Original")
        with patch("apps.characters.relationship_services.models.Model.save", side_effect=RuntimeError("Simulated failure")):
            with self.assertRaises(RuntimeError):
                update_relationship(relationship, description="Not saved")
        relationship.refresh_from_db()
        self.assertEqual(relationship.description, "Original")

    def test_query_returns_incoming_outgoing_and_mutual_once(self):
        outgoing = self.relationship()
        incoming = self.relationship(source_character=self.third, target_character=self.source, relationship_type="ENEMY")
        mutual = self.relationship(source_character=self.target, target_character=self.source, relationship_type="FRIEND", is_reciprocal=True)
        unrelated = self.relationship(source_character=self.target, target_character=self.third, relationship_type="ALLY")
        found = list(get_relationships_for_character(self.source))
        self.assertCountEqual([row.pk for row in found], [outgoing.pk, incoming.pk, mutual.pk])
        self.assertNotIn(unrelated, found)


class RelationshipWebTests(RelationshipFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_outgoing_and_incoming_groups(self):
        relationship = self.relationship()
        for character, title in ((self.source, "Relaciones salientes"), (self.target, "Relaciones entrantes")):
            response = self.client.get(self.url("list", character=character))
            groups = {str(g["title"]): list(g["page"]) for g in response.context["relationship_groups"]}
            self.assertEqual(groups[title], [relationship])
            self.assertEqual(sum(len(rows) for rows in groups.values()), 1)
            self.assertContains(response, "&rarr;")

    def test_mutual_group_in_both_character_details(self):
        relationship = self.relationship(is_reciprocal=True)
        for character in (self.source, self.target):
            response = self.client.get(reverse("characters:detail", args=[self.project.pk, character.pk]))
            self.assertEqual(list(response.context["relationship_groups"][2]["page"]), [relationship])
            self.assertContains(response, "&harr;")

    def test_empty_groups(self):
        self.assertContains(self.client.get(self.url("list")), "Sin relaciones en este grupo.", count=3)

    def test_source_preselected_from_character_page(self):
        response = self.client.get(self.url("create"))
        self.assertEqual(response.context["form"].initial["source_character"], self.source.pk)

    def test_form_choices_are_project_local(self):
        form = CharacterRelationshipForm(project=self.project)
        for key in ("source_character", "target_character"):
            self.assertCountEqual(form.fields[key].queryset, [self.source, self.target, self.third])

    def test_create_preserves_description(self):
        response = self.client.post(self.url("create"), self.payload())
        self.assertRedirects(response, self.url("list"))
        self.assertEqual(Relationship.objects.get().description, self.payload()["description"])

    def test_changing_preselected_source_within_project(self):
        self.client.post(self.url("create"), self.payload(source_character=self.third.pk))
        self.assertEqual(Relationship.objects.get().source_character, self.third)

    def test_forged_endpoint_rejected(self):
        for character in (self.same_owner_character, self.foreign):
            response = self.client.post(self.url("create"), self.payload(target_character=character.pk))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
            self.assertFalse(Relationship.objects.exists())

    def test_duplicate_form_error(self):
        self.relationship()
        response = self.client.post(self.url("create"), self.payload())
        self.assertContains(response, "Ya existe una relación")
        self.assertEqual(Relationship.objects.count(), 1)

    def test_reciprocal_directional_form_error(self):
        response = self.client.post(self.url("create"), self.payload(relationship_type="PARENT", is_reciprocal="on"))
        self.assertTrue(response.context["form"].errors["is_reciprocal"])
        self.assertFalse(Relationship.objects.exists())

    def test_edit_all_fields_and_keep_identity(self):
        relationship = self.relationship()
        response = self.client.post(self.url("edit", relationship), self.payload(source_character=self.third.pk, relationship_type="OTHER", custom_relationship_type="Vínculo mágico", is_reciprocal="on"))
        self.assertEqual(response.status_code, 302)
        relationship.refresh_from_db()
        self.assertEqual((relationship.source_character, relationship.type_label, relationship.is_reciprocal), (self.third, "Vínculo mágico", True))

    def test_custom_type_is_cleared_in_form(self):
        self.client.post(self.url("create"), self.payload(custom_relationship_type="Ignored"))
        self.assertEqual(Relationship.objects.get().custom_relationship_type, "")

    def test_detail_escapes_description_and_custom_label(self):
        relationship = self.relationship(description='<script>alert("not executed")</script>\r\nText', relationship_type="OTHER", custom_relationship_type="<b>Type</b>")
        response = self.client.get(self.url("detail", relationship))
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(response, "&lt;b&gt;Type&lt;/b&gt;")
        self.assertNotContains(response, '<script>alert')

    def test_delete_confirmation_get_does_not_write(self):
        relationship = self.relationship()
        response = self.client.get(self.url("delete", relationship))
        self.assertContains(response, "Esta acción no se puede deshacer")
        self.assertTrue(Relationship.objects.filter(pk=relationship.pk).exists())

    def test_delete_post_keeps_characters(self):
        relationship = self.relationship()
        self.assertRedirects(self.client.post(self.url("delete", relationship)), self.url("list"))
        self.assertFalse(Relationship.objects.exists())
        self.assertEqual(Character.objects.filter(project=self.project).count(), 3)

    def test_return_to_incoming_character_is_local(self):
        relationship = self.relationship()
        response = self.client.post(self.url("edit", relationship) + f"?character={self.target.pk}", self.payload())
        self.assertRedirects(response, self.url("list", character=self.target))

    def test_return_context_is_validated(self):
        relationship = self.relationship()
        for value in ("bad", "-1", "0", "9" * 30, str(self.same_owner_character.pk), str(self.foreign.pk)):
            self.assertEqual(self.client.get(self.url("edit", relationship) + "?character=" + value).status_code, 404)

    def test_no_external_redirect(self):
        response = self.client.post(self.url("create") + "?next=https://example.test/", self.payload())
        self.assertRedirects(response, self.url("list"))

    def test_safe_methods_and_private_cache(self):
        relationship = self.relationship()
        self.assertEqual(self.client.post(self.url("list")).status_code, 405)
        self.assertEqual(self.client.post(self.url("detail", relationship)).status_code, 405)
        self.assertEqual(self.client.put(self.url("edit", relationship)).status_code, 405)
        response = self.client.get(self.url("detail", relationship))
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])

    def test_character_or_relationship_must_belong_to_url_project(self):
        relationship = self.relationship()
        for action in ("list", "create", "detail", "edit", "delete"):
            self.assertEqual(self.client.get(self.url(action, relationship, project=self.second_project)).status_code, 404)


class RelationshipPermissionTests(RelationshipFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.relationship_record = self.relationship()
        self.client.force_login(self.user)

    def test_anonymous(self):
        self.client.logout()
        for action in ("list", "create", "detail", "edit", "delete"):
            self.assertEqual(self.client.get(self.url(action, self.relationship_record)).status_code, 302)

    def test_foreign_users_and_admins_404(self):
        for kind in ("FREE", "BUSINESS_ADMIN", "TECH_ADMIN"):
            self.other.user_type = kind
            self.other.is_staff = self.other.is_superuser = True
            self.other.save()
            self.client.force_login(self.other)
            for action in ("list", "create", "detail", "edit", "delete"):
                self.assertEqual(self.client.get(self.url(action, self.relationship_record)).status_code, 404)
                if action in ("create", "edit", "delete"):
                    self.assertEqual(self.client.post(self.url(action, self.relationship_record), self.payload()).status_code, 404)

    def test_frozen_read_only(self):
        self.assert_read_only("FROZEN")

    def test_pending_deletion_read_only(self):
        self.assert_read_only("PENDING_DELETION")

    def assert_read_only(self, status):
        Project.objects.filter(pk=self.project.pk).update(status=status)
        for action in ("list", "detail"):
            response = self.client.get(self.url(action, self.relationship_record))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Agregar relación")
            self.assertNotContains(response, "Editar relación")
        for action in ("create", "edit", "delete"):
            self.assertEqual(self.client.post(self.url(action, self.relationship_record), self.payload()).status_code, 403)

    def test_deleted_inaccessible(self):
        Project.objects.filter(pk=self.project.pk).update(status="DELETED")
        for action in ("list", "create", "detail", "edit", "delete"):
            self.assertEqual(self.client.get(self.url(action, self.relationship_record)).status_code, 404)

    def test_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for action in ("create", "edit", "delete"):
            self.assertEqual(client.post(self.url(action, self.relationship_record), self.payload()).status_code, 403)

    def test_corrupt_cross_project_relationship_hidden(self):
        Relationship.objects.filter(pk=self.relationship_record.pk).update(target_character=self.foreign)
        self.assertNotContains(self.client.get(self.url("list")), "Foreign secret")
        for action in ("detail", "edit", "delete"):
            self.assertEqual(self.client.get(self.url(action, self.relationship_record)).status_code, 404)


class RelationshipAdminTests(RelationshipFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        self.add_url = reverse("admin:characters_characterrelationship_add")

    def test_add_and_change(self):
        response = self.client.get(self.add_url)
        self.assertContains(response, "Rosariel")
        self.assertNotContains(response, "Foreign secret")
        self.assertEqual(self.client.post(self.add_url, {"project": self.project.pk, **self.payload(), "_save": "Save"}).status_code, 302)
        relationship = Relationship.objects.get()
        url = reverse("admin:characters_characterrelationship_change", args=[relationship.pk])
        self.assertEqual(self.client.post(url, {**self.payload(description="Edited in admin"), "_save": "Save"}).status_code, 302)
        relationship.refresh_from_db()
        self.assertEqual(relationship.description, "Edited in admin")

    def test_invalid_relationships_rejected(self):
        for data in ({"target_character": self.same_owner_character.pk}, {"target_character": self.source.pk},
                     {"relationship_type": "MENTOR", "is_reciprocal": "on"}, {"relationship_type": "OTHER"}):
            response = self.client.post(self.add_url, {"project": self.project.pk, **self.payload(**data), "_save": "Save"})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["adminform"].form.errors)
            self.assertFalse(Relationship.objects.exists())

    def test_admin_reciprocal_duplicate_rejected(self):
        self.relationship(is_reciprocal=True)
        response = self.client.post(self.add_url, {"project": self.project.pk, **self.payload(source_character=self.target.pk, target_character=self.source.pk), "_save": "Save"})
        self.assertContains(response, "Ya existe una relación inversa")
        self.assertEqual(Relationship.objects.count(), 1)

    def test_admin_foreign_content_404(self):
        second = Character.objects.create(project=self.foreign_project, name="Foreign two")
        relationship = create_relationship(self.foreign_project, source_character=self.foreign, target_character=second)
        self.assertEqual(self.client.get(reverse("admin:characters_characterrelationship_change", args=[relationship.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("admin:characters_characterrelationship_changelist")), "Foreign secret")
        self.assertEqual(self.client.post(self.add_url, {"project": self.foreign_project.pk, **self.payload()}).status_code, 404)

    def test_admin_frozen_view_and_write_denied(self):
        relationship = self.relationship()
        Project.objects.filter(pk=self.project.pk).update(status="FROZEN")
        url = reverse("admin:characters_characterrelationship_change", args=[relationship.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, self.payload()).status_code, 403)

    def test_admin_individual_delete_without_characters(self):
        relationship = self.relationship()
        url = reverse("admin:characters_characterrelationship_delete", args=[relationship.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 302)
        self.assertFalse(Relationship.objects.exists())
        self.assertTrue(Character.objects.filter(pk=self.source.pk).exists())

    def test_admin_corrupt_endpoint_hidden(self):
        relationship = self.relationship()
        Relationship.objects.filter(pk=relationship.pk).update(target_character=self.foreign)
        self.assertNotContains(self.client.get(reverse("admin:characters_characterrelationship_changelist")), "Foreign secret")
        self.assertEqual(self.client.get(reverse("admin:characters_characterrelationship_change", args=[relationship.pk])).status_code, 404)


class RelationshipPerformanceTests(RelationshipFixtures, TestCase):
    def test_more_than_one_thousand_relationships_still_paginate(self):
        targets = Character.objects.bulk_create([Character(project=self.project, name=f"Person {i:04}") for i in range(1200)])
        Relationship.objects.bulk_create([Relationship(project=self.project, source_character=self.source, target_character=target, description="Private long text " * 100)
            for target in targets])
        self.client.force_login(self.user)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url("list"), {"outgoing_page": 24})
        self.assertLessEqual(len(queries), 12)
        page = response.context["relationship_groups"][0]["page"]
        self.assertEqual((page.paginator.count, page.paginator.num_pages, len(page)), (1200, 24, 50))
        self.assertNotContains(response, "Private long text")

    def test_selector_one_query_without_descriptions_or_character_biographies(self):
        for kind in ("TRUST", "FRIEND", "ALLY"):
            self.relationship(relationship_type=kind, description="Large" * 1000)
        query = get_relationships_for_character(self.source)
        with self.assertNumQueries(1):
            for relationship in query:
                str(relationship)
                self.assertIn("description", relationship.get_deferred_fields())
                self.assertIn("biography", relationship.source_character.get_deferred_fields())

    def test_group_pagination_is_bounded(self):
        targets = Character.objects.bulk_create([Character(project=self.project, name=f"Target {i:03}") for i in range(60)])
        Relationship.objects.bulk_create([Relationship(project=self.project, source_character=self.source, target_character=target) for target in targets])
        self.client.force_login(self.user)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url("list"))
        self.assertLessEqual(len(queries), 12)
        self.assertEqual(len(response.context["relationship_groups"][0]["page"]), 50)
        self.assertNotContains(response, "Target 059")
        sql = [q["sql"] for q in queries if 'FROM "characters_characterrelationship"' in q["sql"]]
        self.assertTrue(sql)
        self.assertTrue(all('"description"' not in text and '"biography"' not in text for text in sql))
        response = self.client.get(self.url("list"), {"outgoing_page": 2})
        self.assertEqual(len(response.context["relationship_groups"][0]["page"]), 10)

    def test_invalid_page_is_controlled(self):
        self.relationship()
        groups = relationship_groups(self.source, {"outgoing_page": "invalid", "incoming_page": "99999"})
        self.assertEqual(groups[0]["page"].number, 1)

    def test_character_fields_roles_and_completion_unchanged(self):
        CharacterDramaticRole.objects.create(character=self.source, role="INTERES_ROMANTICO")
        before = list(Character.objects.order_by("pk").values())
        roles = list(CharacterDramaticRole.objects.values())
        completion = self.source.completion_percentage
        relationship = self.relationship(relationship_type="ROMANTIC_INTEREST", is_reciprocal=True)
        update_relationship(relationship, description="Only a relationship")
        delete_relationship(relationship)
        self.assertEqual(before, list(Character.objects.order_by("pk").values()))
        self.assertEqual(roles, list(CharacterDramaticRole.objects.values()))
        self.assertEqual(completion, self.source.completion_percentage)
