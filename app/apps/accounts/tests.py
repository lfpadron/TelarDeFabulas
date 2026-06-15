from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class UserModelTests(TestCase):
    def test_create_user_with_email(self):
        user = get_user_model().objects.create_user(
            email="writer@example.com",
            password="safe-test-password",
        )

        self.assertEqual(user.email, "writer@example.com")
        self.assertTrue(user.check_password("safe-test-password"))

    def test_create_superuser(self):
        user = get_user_model().objects.create_superuser(
            email="admin@example.com",
            password="safe-test-password",
        )

        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.user_type, get_user_model().UserType.TECH_ADMIN)

    def test_new_user_defaults(self):
        user = get_user_model().objects.create_user(
            email="default@example.com",
            password="safe-test-password",
        )

        self.assertEqual(user.user_type, get_user_model().UserType.FREE)
        self.assertEqual(user.status, get_user_model().UserStatus.ACTIVE)
        self.assertEqual(user.preferred_locale, get_user_model().PreferredLocale.ES_MX)


class AccountViewTests(TestCase):
    def setUp(self):
        self.password = "safe-test-password"
        self.user = get_user_model().objects.create_user(
            email="writer@example.com",
            password=self.password,
            display_alias="La Pluma",
        )

    def test_login_with_email(self):
        response = self.client.post(
            reverse("login"),
            {
                "username": self.user.email,
                "password": self.password,
            },
        )

        self.assertRedirects(response, reverse("profile"))
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))

    def test_home_greets_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))

        self.assertContains(response, "Hola, La Pluma.")

    def test_profile_requires_authentication(self):
        response = self.client.get(reverse("profile"))

        self.assertRedirects(response, f"{reverse('login')}?next={reverse('profile')}")

    def test_register_creates_user_and_logs_in(self):
        response = self.client.post(
            reverse("register"),
            {
                "email": "new-writer@example.com",
                "secondary_email": "backup@example.com",
                "name": "Nueva Escritora",
                "display_alias": "La Nueva Pluma",
                "preferred_locale": "es-mx",
                "password1": "safe-test-password-123",
                "password2": "safe-test-password-123",
            },
        )

        self.assertRedirects(response, reverse("profile"))
        user = get_user_model().objects.get(email="new-writer@example.com")
        self.assertEqual(user.user_type, get_user_model().UserType.FREE)
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))

    def test_authenticated_user_can_update_profile(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("profile"),
            {
                "secondary_email": "backup@example.com",
                "name": "Autora de Prueba",
                "display_alias": "La Pluma Roja",
                "preferred_locale": "en-us",
                "timezone": "America/Mexico_City",
            },
        )

        self.assertRedirects(response, reverse("profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.secondary_email, "backup@example.com")
        self.assertEqual(self.user.display_alias, "La Pluma Roja")
        self.assertEqual(self.user.preferred_locale, "en-us")
