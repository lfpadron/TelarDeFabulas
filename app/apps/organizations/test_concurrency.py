from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.characters.models import Character
from apps.geography.models import GeographicLocation
from apps.geography.services import delete_location
from apps.projects.models import Project

from .models import CharacterOrganizationMembership as Membership, Organization
from .services import delete_organization, move_organization


@skipUnlessDBFeature("has_select_for_update")
class OrganizationConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="org-concurrency@example.test")
        self.project = Project.objects.create(user=self.user, name="Concurrent organizations")
        self.parents = [Organization.objects.create(project=self.project, name=f"Parent {i}") for i in range(3)]
        self.children = [Organization.objects.create(project=self.project, parent=self.parents[0], name=f"Child {i}") for i in range(2)]
        self.character = Character.objects.create(project=self.project, name="Concurrent member")

    def simultaneously(self, *operations):
        barrier = Barrier(len(operations))

        def run(operation):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout TO '8s'")
                barrier.wait(timeout=15)
                try:
                    return operation()
                except ValidationError:
                    return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            futures = [pool.submit(run, operation) for operation in operations]
            return [future.result(timeout=25) for future in futures]

    def assert_positions(self):
        groups = {}
        for parent, position in Organization.objects.filter(project=self.project).values_list("parent_id", "position"):
            groups.setdefault(parent, []).append(position)
        for positions in groups.values():
            self.assertEqual(positions, list(range(1, len(positions) + 1)))

    def test_concurrent_create_at_first_position(self):
        def create():
            return Organization.objects.create(project_id=self.project.pk, parent_id=self.parents[1].pk, name="New", position=1).pk

        results = self.simultaneously(create, create)
        self.assertNotIn("rejected", results)
        self.assertEqual(len(set(results)), 2)
        self.assert_positions()

    def test_concurrent_move_same_destination(self):
        self.assertNotIn("rejected", self.simultaneously(*[
            lambda pk=child.pk: move_organization(Organization.objects.get(pk=pk), self.parents[1], 1).pk
            for child in self.children]))
        self.assert_positions()

    def test_competing_moves_do_not_create_cycle(self):
        a, b = self.parents[1:]
        results = self.simultaneously(lambda: move_organization(Organization.objects.get(pk=a.pk), b).pk,
                                     lambda: move_organization(Organization.objects.get(pk=b.pk), a).pk)
        self.assertEqual(results.count("rejected"), 1)
        self.assert_positions()

    def test_stale_edit_during_move_preserves_structure(self):
        old = Organization.objects.get(pk=self.children[0].pk)

        def edit():
            old.detailed_description = "Updated during move"
            old.save()

        self.assertNotIn("rejected", self.simultaneously(edit,
            lambda: move_organization(Organization.objects.get(pk=old.pk), self.parents[1]).pk))
        old.refresh_from_db()
        self.assertEqual(old.parent_id, self.parents[1].pk)
        self.assertEqual(old.detailed_description, "Updated during move")
        self.assert_positions()

    def test_concurrent_duplicate_memberships(self):
        def create():
            return Membership.objects.create(character_id=self.character.pk, organization_id=self.parents[1].pk, position_title="Role").pk

        self.assertEqual(self.simultaneously(create, create).count("rejected"), 1)
        self.assertEqual(Membership.objects.count(), 1)

    def test_membership_creation_vs_organization_delete(self):
        organization = self.parents[1]

        def create():
            return Membership.objects.create(character_id=self.character.pk, organization_id=organization.pk).pk

        results = self.simultaneously(create, lambda: delete_organization(Organization.objects.get(pk=organization.pk)))
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(Membership.objects.filter(organization_id=organization.pk).exists(), Organization.objects.filter(pk=organization.pk).exists())
        self.assertTrue(Character.objects.filter(pk=self.character.pk).exists())

    def test_headquarters_assignment_vs_location_delete(self):
        location = GeographicLocation.objects.create(project=self.project, name="Headquarters")

        def assign():
            org = Organization.objects.get(pk=self.parents[1].pk)
            org.headquarters_id = location.pk
            org.save()

        results = self.simultaneously(assign, lambda: delete_location(GeographicLocation.objects.get(pk=location.pk)))
        self.assertEqual(results.count("rejected"), 1)
        self.parents[1].refresh_from_db()
        self.assertEqual(bool(self.parents[1].headquarters_id), GeographicLocation.objects.filter(pk=location.pk).exists())
