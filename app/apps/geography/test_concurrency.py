from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from apps.characters.models import Character
from apps.projects.models import Project

from .models import GeographicLocation as Location
from .services import delete_location, move_location, move_location_down, move_location_up


@skipUnlessDBFeature("has_select_for_update")
class GeographyConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="geo-concurrency@example.test")
        self.project = Project.objects.create(user=self.user, name="Concurrent geography")
        self.parents = [Location.objects.create(project=self.project, name=f"Parent {i}") for i in range(3)]
        self.cities = [Location.objects.create(project=self.project, parent=self.parents[0], name=f"City {i}",
                                              detailed_description=f"History {i}") for i in range(2)]

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
        for parent_id, position in Location.objects.filter(project=self.project).order_by("position").values_list("parent_id", "position"):
            groups.setdefault(parent_id, []).append(position)
        for values in groups.values():
            self.assertEqual(values, list(range(1, len(values) + 1)))

    def create_city(self):
        return Location.objects.create(project_id=self.project.pk, parent_id=self.parents[1].pk, name="New", position=1).pk

    def move_city(self, index, parent_index=1):
        return move_location(Location.objects.get(pk=self.cities[index].pk), self.parents[parent_index], 1).pk

    def test_concurrent_creates(self):
        results = self.simultaneously(self.create_city, self.create_city)
        self.assertEqual(len(set(results)), 2)
        self.assertNotIn("rejected", results)
        self.assert_positions()

    def test_concurrent_moves_same_destination(self):
        self.assertEqual(self.simultaneously(lambda: self.move_city(0), lambda: self.move_city(1)), [row.pk for row in self.cities])
        self.assert_positions()

    def test_concurrent_create_and_move(self):
        self.assertNotIn("rejected", self.simultaneously(self.create_city, lambda: self.move_city(0)))
        self.assertEqual(Location.objects.filter(parent=self.parents[1]).count(), 2)
        self.assert_positions()

    def test_concurrent_moves_same_location(self):
        pk = self.cities[0].pk
        self.assertEqual(self.simultaneously(lambda: self.move_city(0, 1), lambda: self.move_city(0, 2)), [pk, pk])
        self.assertEqual(Location.objects.get(pk=pk).detailed_description, "History 0")
        self.assert_positions()

    def test_competing_moves_cannot_create_cycle(self):
        a, b = self.parents[1:]
        results = self.simultaneously(lambda: move_location(Location.objects.get(pk=a.pk), b).pk,
                                      lambda: move_location(Location.objects.get(pk=b.pk), a).pk)
        self.assertEqual(results.count("rejected"), 1)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertFalse(a.parent_id == b.pk and b.parent_id == a.pk)
        self.assert_positions()

    def test_concurrent_up_down(self):
        self.assertNotIn("rejected", self.simultaneously(
            lambda: move_location_up(Location.objects.get(pk=self.cities[1].pk)).pk,
            lambda: move_location_down(Location.objects.get(pk=self.cities[0].pk)).pk))
        self.assert_positions()

    def test_edit_during_move_preserves_text_and_structure(self):
        old = Location.objects.get(pk=self.cities[0].pk)

        def edit():
            old.detailed_description = "Concurrent description"
            old.save()

        self.assertNotIn("rejected", self.simultaneously(edit, lambda: self.move_city(0)))
        old.refresh_from_db()
        self.assertEqual(old.parent_id, self.parents[1].pk)
        self.assertEqual(old.detailed_description, "Concurrent description")
        self.assert_positions()

    def test_residence_assignment_vs_deletion(self):
        character = Character.objects.create(project=self.project, name="Resident", biography="Original sheet")
        location = self.parents[1]

        def assign():
            current = Character.objects.get(pk=character.pk)
            current.residence_id = location.pk
            current.save()

        results = self.simultaneously(assign, lambda: delete_location(Location.objects.get(pk=location.pk)))
        self.assertEqual(results.count("rejected"), 1)
        character.refresh_from_db()
        self.assertEqual(character.biography, "Original sheet")
        if character.residence_id:
            self.assertTrue(Location.objects.filter(pk=character.residence_id).exists())
        else:
            self.assertFalse(Location.objects.filter(pk=location.pk).exists())
        self.assert_positions()

    def test_child_creation_vs_parent_deletion(self):
        parent = self.parents[1]

        def create():
            return Location.objects.create(project_id=self.project.pk, parent_id=parent.pk, name="Child").pk

        results = self.simultaneously(create, lambda: delete_location(Location.objects.get(pk=parent.pk)))
        self.assertEqual(results.count("rejected"), 1)
        self.assertEqual(Location.objects.filter(parent_id=parent.pk).exists(), Location.objects.filter(pk=parent.pk).exists())
        self.assert_positions()
