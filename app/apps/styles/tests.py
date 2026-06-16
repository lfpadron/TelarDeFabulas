from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import StyleTemplate


class StyleTemplateTests(TestCase):
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
            user_type=User.UserType.PREMIUM,
        )

    def style_payload(self, name="Estilo propio", **overrides):
        payload = {
            "name": name,
            "description": "Configuración de exportación para pruebas.",
            "font_category": StyleTemplate.FontCategory.SERIF,
            "font_heading": "Libre Baskerville",
            "font_body": "Merriweather",
            "heading_size": "18.00",
            "body_size": "12.00",
            "line_spacing": "1.50",
            "paragraph_spacing": "8.00",
            "margin_top": "25.00",
            "margin_bottom": "25.00",
            "margin_left": "25.00",
            "margin_right": "25.00",
            "text_alignment": StyleTemplate.TextAlignment.JUSTIFY,
            "first_line_indent": "0.00",
            "scene_separator": "***",
            "include_page_numbers": "on",
            "config_json": "{}",
        }
        payload.update(overrides)
        return payload

    def create_system_style(self, name="Sobrio"):
        return StyleTemplate.objects.create(
            name=name,
            is_system=True,
            font_category=StyleTemplate.FontCategory.SANS_SERIF,
            font_heading="Inter",
            font_body="Inter",
            text_alignment=StyleTemplate.TextAlignment.LEFT,
        )

    def test_authenticated_user_can_see_system_styles(self):
        system_style = self.create_system_style()
        self.client.force_login(self.free_user)

        response = self.client.get(reverse("styles:list"))

        self.assertContains(response, system_style.name)

    def test_free_user_cannot_create_personal_style(self):
        self.client.force_login(self.free_user)

        response = self.client.post(reverse("styles:create"), self.style_payload())

        self.assertRedirects(response, reverse("styles:list"))
        self.assertFalse(StyleTemplate.objects.filter(user=self.free_user).exists())

    def test_premium_user_can_create_personal_style(self):
        self.client.force_login(self.premium_user)

        response = self.client.post(reverse("styles:create"), self.style_payload())

        style = StyleTemplate.objects.get(user=self.premium_user)
        self.assertRedirects(response, reverse("styles:detail", kwargs={"style_pk": style.pk}))
        self.assertEqual(style.name, "Estilo propio")
        self.assertFalse(style.is_system)

    def test_premium_user_can_edit_own_style(self):
        style = StyleTemplate.objects.create(user=self.premium_user, name="Borrador")
        self.client.force_login(self.premium_user)

        response = self.client.post(reverse("styles:edit", kwargs={"style_pk": style.pk}), self.style_payload("Pulido"))

        self.assertRedirects(response, reverse("styles:detail", kwargs={"style_pk": style.pk}))
        style.refresh_from_db()
        self.assertEqual(style.name, "Pulido")

    def test_user_cannot_edit_style_from_another_user(self):
        style = StyleTemplate.objects.create(user=self.other_user, name="Ajeno")
        self.client.force_login(self.premium_user)

        response = self.client.get(reverse("styles:edit", kwargs={"style_pk": style.pk}))

        self.assertEqual(response.status_code, 404)

    def test_premium_user_can_duplicate_system_style(self):
        system_style = self.create_system_style()
        self.client.force_login(self.premium_user)

        response = self.client.post(reverse("styles:duplicate", kwargs={"style_pk": system_style.pk}))

        duplicate = StyleTemplate.objects.get(user=self.premium_user)
        self.assertRedirects(response, reverse("styles:detail", kwargs={"style_pk": duplicate.pk}))
        self.assertEqual(duplicate.name, f"Copia de {system_style.name}")

    def test_duplicate_is_assigned_to_user_and_is_not_system(self):
        system_style = self.create_system_style()
        self.client.force_login(self.premium_user)

        self.client.post(reverse("styles:duplicate", kwargs={"style_pk": system_style.pk}))

        duplicate = StyleTemplate.objects.get(user=self.premium_user)
        self.assertEqual(duplicate.user, self.premium_user)
        self.assertFalse(duplicate.is_system)

    def test_free_user_cannot_duplicate_style(self):
        system_style = self.create_system_style()
        self.client.force_login(self.free_user)

        response = self.client.post(reverse("styles:duplicate", kwargs={"style_pk": system_style.pk}))

        self.assertRedirects(response, reverse("styles:list"))
        self.assertEqual(StyleTemplate.objects.filter(user=self.free_user).count(), 0)

    def test_user_cannot_delete_style_from_another_user(self):
        style = StyleTemplate.objects.create(user=self.other_user, name="Ajeno")
        self.client.force_login(self.premium_user)

        response = self.client.post(reverse("styles:delete", kwargs={"style_pk": style.pk}))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(StyleTemplate.objects.filter(pk=style.pk).exists())

    def test_system_style_cannot_be_deleted_from_ui(self):
        system_style = self.create_system_style()
        self.client.force_login(self.premium_user)

        response = self.client.post(reverse("styles:delete", kwargs={"style_pk": system_style.pk}))

        self.assertRedirects(response, reverse("styles:detail", kwargs={"style_pk": system_style.pk}))
        self.assertTrue(StyleTemplate.objects.filter(pk=system_style.pk).exists())

    def test_system_style_cannot_have_user(self):
        style = StyleTemplate(name="Sistema inválido", user=self.premium_user, is_system=True)

        with self.assertRaises(ValidationError):
            style.full_clean()

    def test_personal_style_requires_user(self):
        style = StyleTemplate(name="Personal inválido", is_system=False)

        with self.assertRaises(ValidationError):
            style.full_clean()

    def test_seed_system_styles_command_creates_four_styles(self):
        call_command("seed_system_styles", stdout=StringIO())

        self.assertEqual(StyleTemplate.objects.filter(is_system=True).count(), 4)
        self.assertTrue(StyleTemplate.objects.filter(name="Medio loco", is_system=True).exists())

    def test_seed_system_styles_command_is_idempotent(self):
        call_command("seed_system_styles", stdout=StringIO())
        call_command("seed_system_styles", stdout=StringIO())

        self.assertEqual(StyleTemplate.objects.filter(is_system=True).count(), 4)

    def test_list_shows_system_and_own_styles_but_not_other_personal_styles(self):
        system_style = self.create_system_style()
        own_style = StyleTemplate.objects.create(user=self.premium_user, name="Propio")
        StyleTemplate.objects.create(user=self.other_user, name="Ajeno")
        self.client.force_login(self.premium_user)

        response = self.client.get(reverse("styles:list"))

        self.assertContains(response, system_style.name)
        self.assertContains(response, own_style.name)
        self.assertNotContains(response, "Ajeno")
