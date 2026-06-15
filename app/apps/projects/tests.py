from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Project


class ProjectViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.password = "safe-test-password"
        self.free_user = User.objects.create_user(
            email="free@example.com",
            password=self.password,
            user_type=User.UserType.FREE,
        )
        self.premium_user = User.objects.create_user(
            email="premium@example.com",
            password=self.password,
            user_type=User.UserType.PREMIUM,
        )
        self.other_user = User.objects.create_user(
            email="other@example.com",
            password=self.password,
            user_type=User.UserType.FREE,
        )

    def project_payload(self, name="Proyecto de prueba"):
        return {
            "name": name,
            "description": "Una historia en preparación.",
            "language": Project.Language.ES,
            "locale": Project.Locale.ES_MX,
        }

    def test_authenticated_user_can_create_project(self):
        self.client.force_login(self.free_user)
        response = self.client.post(reverse("projects:create"), self.project_payload())

        project = Project.objects.get(user=self.free_user)
        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": project.pk}))
        self.assertEqual(project.name, "Proyecto de prueba")
        self.assertEqual(project.status, Project.ProjectStatus.ACTIVE)

    def test_unauthenticated_user_is_redirected(self):
        response = self.client.get(reverse("projects:list"))

        self.assertRedirects(response, f"{reverse('login')}?next={reverse('projects:list')}")

    def test_free_user_cannot_create_more_than_one_non_deleted_project(self):
        Project.objects.create(user=self.free_user, name="Proyecto uno")
        self.client.force_login(self.free_user)

        response = self.client.post(reverse("projects:create"), self.project_payload("Proyecto dos"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Project.objects.filter(user=self.free_user).count(), 1)
        self.assertContains(response, "cuenta gratuita")

    def test_premium_user_can_create_up_to_ten_projects(self):
        for number in range(9):
            Project.objects.create(user=self.premium_user, name=f"Proyecto {number}")
        self.client.force_login(self.premium_user)

        response = self.client.post(reverse("projects:create"), self.project_payload("Proyecto diez"))

        self.assertEqual(Project.objects.filter(user=self.premium_user).count(), 10)
        project = Project.objects.get(user=self.premium_user, name="Proyecto diez")
        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": project.pk}))

    def test_premium_user_cannot_create_more_than_ten_projects(self):
        for number in range(10):
            Project.objects.create(user=self.premium_user, name=f"Proyecto {number}")
        self.client.force_login(self.premium_user)

        response = self.client.post(reverse("projects:create"), self.project_payload("Proyecto once"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Project.objects.filter(user=self.premium_user).count(), 10)
        self.assertContains(response, "cuenta premium")

    def test_user_cannot_see_project_from_another_user(self):
        project = Project.objects.create(user=self.other_user, name="Proyecto ajeno")
        self.client.force_login(self.free_user)

        response = self.client.get(reverse("projects:detail", kwargs={"pk": project.pk}))

        self.assertEqual(response.status_code, 404)

    def test_mark_for_deletion_changes_status_to_pending_deletion(self):
        project = Project.objects.create(user=self.free_user, name="Proyecto para borrar")
        self.client.force_login(self.free_user)

        response = self.client.post(reverse("projects:delete", kwargs={"pk": project.pk}))

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": project.pk}))
        project.refresh_from_db()
        self.assertEqual(project.status, Project.ProjectStatus.PENDING_DELETION)
        self.assertIsNotNone(project.deletion_requested_at)

    def test_mark_for_deletion_assigns_scheduled_deletion_at(self):
        project = Project.objects.create(user=self.free_user, name="Proyecto con fecha")
        self.client.force_login(self.free_user)
        before = timezone.now() + timedelta(days=89)
        after = timezone.now() + timedelta(days=91)

        self.client.post(reverse("projects:delete", kwargs={"pk": project.pk}))

        project.refresh_from_db()
        self.assertIsNotNone(project.scheduled_deletion_at)
        self.assertGreater(project.scheduled_deletion_at, before)
        self.assertLess(project.scheduled_deletion_at, after)

    def test_cannot_mark_pending_project_for_deletion_twice(self):
        project = Project.objects.create(
            user=self.free_user,
            name="Proyecto ya pendiente",
            status=Project.ProjectStatus.PENDING_DELETION,
            deletion_requested_at=timezone.now(),
            scheduled_deletion_at=timezone.now() + timedelta(days=90),
        )
        original_scheduled_deletion_at = project.scheduled_deletion_at
        self.client.force_login(self.free_user)

        response = self.client.post(reverse("projects:delete", kwargs={"pk": project.pk}))

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": project.pk}))
        project.refresh_from_db()
        self.assertEqual(project.scheduled_deletion_at, original_scheduled_deletion_at)

    def test_restore_project_returns_it_to_active(self):
        project = Project.objects.create(
            user=self.free_user,
            name="Proyecto restaurable",
            status=Project.ProjectStatus.PENDING_DELETION,
            frozen_at=timezone.now(),
            deletion_requested_at=timezone.now(),
            scheduled_deletion_at=timezone.now() + timedelta(days=90),
        )
        self.client.force_login(self.free_user)

        response = self.client.post(reverse("projects:restore", kwargs={"pk": project.pk}))

        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": project.pk}))
        project.refresh_from_db()
        self.assertEqual(project.status, Project.ProjectStatus.ACTIVE)
        self.assertIsNone(project.frozen_at)
        self.assertIsNone(project.deletion_requested_at)
        self.assertIsNone(project.scheduled_deletion_at)

    def test_deleted_project_does_not_count_for_limit(self):
        Project.objects.create(
            user=self.free_user,
            name="Proyecto eliminado",
            status=Project.ProjectStatus.DELETED,
            deleted_at=timezone.now(),
        )
        self.client.force_login(self.free_user)

        response = self.client.post(reverse("projects:create"), self.project_payload("Proyecto nuevo"))

        self.assertEqual(Project.objects.filter(user=self.free_user).count(), 2)
        project = Project.objects.get(user=self.free_user, name="Proyecto nuevo")
        self.assertRedirects(response, reverse("projects:detail", kwargs={"pk": project.pk}))

    def test_project_list_only_shows_current_user_projects(self):
        own_project = Project.objects.create(user=self.free_user, name="Proyecto propio")
        Project.objects.create(user=self.other_user, name="Proyecto ajeno")
        self.client.force_login(self.free_user)

        response = self.client.get(reverse("projects:list"))

        self.assertContains(response, own_project.name)
        self.assertNotContains(response, "Proyecto ajeno")
