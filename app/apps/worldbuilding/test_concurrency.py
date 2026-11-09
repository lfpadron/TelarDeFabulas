from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import Client, TransactionTestCase, skipUnlessDBFeature
from django.urls import reverse

from apps.projects.models import Project

from .models import WorldbuildingEntry as Entry
from .services import change_entry_category, create_entry, delete_entry, move_entry_up, update_entry


@skipUnlessDBFeature("has_select_for_update")
class WorldbuildingConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="world-race@example.test", is_staff=True, is_superuser=True)
        self.project = Project.objects.create(user=self.user, name="Concurrent world")
        self.entry = create_entry(self.project, category="POLITICS", title="Original title", short_description="Original brief", content="Original text")
        self.second = create_entry(self.project, category="POLITICS", title="Second")
        self.religion = create_entry(self.project, category="RELIGION", title="Faith")

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
        for category in Entry.Category.values:
            values = list(Entry.objects.filter(project=self.project, category=category).values_list("position", flat=True))
            self.assertEqual(values, list(range(len(values))))

    def test_two_updates_one_winner_without_mixed_fields(self):
        def edit(label):
            update_entry(self.entry, expected_revision=1, title=label, short_description=label, content=label)
            return label

        results = self.simultaneously(lambda: edit("Session A"), lambda: edit("Session B"))
        self.assertEqual(results.count("rejected"), 1)
        winner = next(result for result in results if result != "rejected")
        self.entry.refresh_from_db()
        self.assertEqual((self.entry.title, self.entry.short_description, self.entry.content, self.entry.revision), (winner, winner, winner, 2))

    def test_two_creates_unique_positions(self):
        def create():
            return create_entry(self.project, category="POLITICS", title="Concurrent entry", position=0).pk

        results = self.simultaneously(create, create)
        self.assertNotIn("rejected", results)
        self.assertEqual(len(set(results)), 2)
        self.assert_positions()

    def test_category_change_vs_text_edit(self):
        results = self.simultaneously(
            lambda: change_entry_category(self.entry, "HISTORY", expected_revision=1).pk,
            lambda: update_entry(self.entry, expected_revision=1, content="New text").pk)
        self.assertEqual(results.count("rejected"), 1)
        self.entry.refresh_from_db()
        self.assertIn((self.entry.category, self.entry.content), (("HISTORY", "Original text"), ("POLITICS", "New text")))
        self.assert_positions()

    def test_two_category_changes_same_destination(self):
        results = self.simultaneously(
            lambda: change_entry_category(self.entry, "HISTORY", expected_revision=1).pk,
            lambda: change_entry_category(self.religion, "HISTORY", expected_revision=1).pk)
        self.assertNotIn("rejected", results)
        self.assert_positions()

    def test_reorder_vs_edit_no_silent_loss(self):
        results = self.simultaneously(
            lambda: move_entry_up(self.second, expected_revision=1).pk,
            lambda: update_entry(self.entry, expected_revision=1, content="New text").pk)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.content, "Original text" if results[1] == "rejected" else "New text")
        self.assert_positions()

    def test_delete_vs_edit_no_resurrection(self):
        def delete():
            delete_entry(Entry.objects.get(pk=self.entry.pk), expected_revision=1)
            return "deleted"

        def edit():
            update_entry(self.entry, expected_revision=1, content="New text")
            return "edited"

        results = self.simultaneously(delete, edit)
        self.assertEqual(results.count("rejected"), 1)
        if "edited" in results:
            self.assertEqual(Entry.objects.get(pk=self.entry.pk).content, "New text")
        else:
            self.assertFalse(Entry.objects.filter(pk=self.entry.pk).exists())
        self.assert_positions()

    def admin_client(self):
        client = Client()
        client.force_login(self.user)
        return client

    def admin_post(self, client, content):
        return client.post(reverse("admin:worldbuilding_worldbuildingentry_change", args=[self.entry.pk]),
            {"title": "Admin title", "category": "POLITICS", "short_description": "Admin brief", "content": content,
             "expected_revision": 1, "_save": "Save"}).status_code

    def test_two_admin_submissions_one_conflict(self):
        first, second = self.admin_client(), self.admin_client()
        results = self.simultaneously(lambda: self.admin_post(first, "Admin A"), lambda: self.admin_post(second, "Admin B"))
        self.assertEqual(sorted(results), [302, 409])
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.revision, 2)
        self.assertEqual(self.entry.content, "Admin A" if results[0] == 302 else "Admin B")

    def test_admin_vs_service_same_revision(self):
        client = self.admin_client()

        def edit():
            update_entry(self.entry, expected_revision=1, content="Service text")
            return "edited"

        results = self.simultaneously(lambda: self.admin_post(client, "Admin text"), edit)
        self.assertIn(results, ([302, "rejected"], [409, "edited"]))
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.revision, 2)
        self.assertEqual(self.entry.content, "Admin text" if results[0] == 302 else "Service text")
