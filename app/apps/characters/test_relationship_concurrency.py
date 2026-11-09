from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import Client, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from .models import CharacterRelationship as Relationship
from .relationship_services import delete_relationship, update_relationship
from .test_relationships import RelationshipFixtures


@skipUnlessDBFeature("has_select_for_update")
class RelationshipConcurrencyTests(RelationshipFixtures, TransactionTestCase):
    def race(self, *operations):
        barrier = Barrier(len(operations))

        def run(operation):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout TO '10s'")
                barrier.wait(timeout=15)
                try:
                    return operation()
                except ValidationError:
                    return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            futures = [pool.submit(run, operation) for operation in operations]
            return [future.result(timeout=30) for future in futures]

    def test_exact_duplicate_creation(self):
        results = self.race(lambda: self.relationship().pk, lambda: self.relationship().pk)
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(Relationship.objects.count(), 1)

    def test_inverse_mutual_creation(self):
        results = self.race(lambda: self.relationship(is_reciprocal=True).pk,
            lambda: self.relationship(source_character=self.target, target_character=self.source, is_reciprocal=True).pk)
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(Relationship.objects.count(), 1)

    def test_mutual_vs_inverse_unilateral(self):
        results = self.race(lambda: self.relationship(is_reciprocal=True).pk,
            lambda: self.relationship(source_character=self.target, target_character=self.source).pk)
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(Relationship.objects.count(), 1)

    def test_opposed_unilateral_both_allowed(self):
        results = self.race(lambda: self.relationship().pk,
            lambda: self.relationship(source_character=self.target, target_character=self.source).pk)
        self.assertNotIn("rejected", results)
        self.assertEqual(Relationship.objects.count(), 2)

    def test_promote_reciprocal_vs_inverse_creation(self):
        relationship = self.relationship()
        results = self.race(lambda: update_relationship(relationship, is_reciprocal=True).pk,
            lambda: self.relationship(source_character=self.target, target_character=self.source).pk)
        self.assertEqual(results.count("rejected"), 1)
        relationship.refresh_from_db()
        self.assertEqual(Relationship.objects.count(), 1 if relationship.is_reciprocal else 2)

    def test_competing_updates_to_same_type(self):
        first = self.relationship(relationship_type="TRUST")
        second = self.relationship(relationship_type="ALLY")
        results = self.race(lambda: update_relationship(first, relationship_type="FRIEND").pk,
            lambda: update_relationship(second, relationship_type="FRIEND").pk)
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(Relationship.objects.filter(relationship_type="FRIEND").count(), 1)
        self.assertEqual(Relationship.objects.count(), 2)

    def test_create_vs_character_delete(self):
        def delete():
            self.target.delete()
            return "deleted"
        results = self.race(delete, lambda: self.relationship().pk)
        self.assertEqual(results[0], "deleted")
        self.assertFalse(Relationship.objects.exists())

    def test_delete_vs_edit_never_resurrects(self):
        relationship = self.relationship()
        copy = Relationship.objects.get(pk=relationship.pk)

        def delete():
            delete_relationship(copy)
            return "deleted"
        results = self.race(delete, lambda: update_relationship(relationship, description="Edited").pk)
        self.assertEqual(results[0], "deleted")
        self.assertFalse(Relationship.objects.exists())

    def test_admin_vs_service_creation(self):
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        client = Client()
        client.force_login(self.user)

        def admin_create():
            return client.post(reverse("admin:characters_characterrelationship_add"), {
                "project": self.project.pk, **self.payload(), "is_reciprocal": "on", "_save": "Save"}).status_code
        results = self.race(admin_create, lambda: self.relationship(source_character=self.target, target_character=self.source).pk)
        self.assertIn(results[0], (200, 302))
        self.assertEqual(results[0] == 302, results[1] == "rejected")
        self.assertEqual(Relationship.objects.count(), 1)

    def test_admin_delete_vs_character_delete_is_controlled(self):
        self.user.is_staff = self.user.is_superuser = True
        self.user.save()
        client = Client()
        client.force_login(self.user)
        relationship = self.relationship()

        def admin_delete():
            return client.post(reverse("admin:characters_characterrelationship_delete", args=[relationship.pk]), {"post": "yes"}).status_code

        def character_delete():
            self.target.delete()
            return "deleted"
        results = self.race(admin_delete, character_delete)
        self.assertIn(results[0], (302, 404))
        self.assertEqual(results[1], "deleted")
        self.assertFalse(Relationship.objects.exists())
