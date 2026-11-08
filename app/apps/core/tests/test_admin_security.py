from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import RequestFactory
from django.urls import reverse

from apps.characters.models import Character, CharacterMention
from apps.exports.models import ExportJob
from apps.manuscripts.models import ManuscriptNode
from apps.notes.models import Note
from apps.projects.models import Project
from apps.styles.models import StyleTemplate

from .helpers import SecurityTestCase


class AdminSecurityTests(SecurityTestCase):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save()
        self.client.force_login(self.user)
        self.request = RequestFactory().get("/admin/")
        self.request.user = self.user

    def url_for(self, obj, action="change"):
        return reverse(f"admin:{obj._meta.app_label}_{obj._meta.model_name}_{action}", args=[obj.pk])

    def content_objects(self):
        return (self.project, self.book, self.character, self.role, self.mention, self.note, self.job)

    def test_superuser_cannot_access_foreign_content_in_admin(self):
        for obj in (self.other_project, self.other_node, self.other_character):
            for action in ("change", "delete", "history"):
                with self.subTest(model=obj._meta.label, action=action):
                    self.assertEqual(self.client.get(self.url_for(obj, action)).status_code, 404)
                    self.assertEqual(self.client.post(self.url_for(obj, action), {"post": "yes"}).status_code, 404)

    def test_admin_lists_only_own_content(self):
        for model, foreign_name in ((Project, self.other_project.name), (ManuscriptNode, self.other_node.title),
                                    (Character, self.other_character.name)):
            response = self.client.get(reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist"))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, foreign_name)

    def test_readonly_content_is_viewable_but_post_cannot_change_or_delete(self):
        for status in ("FROZEN", "PENDING_DELETION"):
            self.set_status(status)
            before = self.snapshot()
            for obj in self.content_objects():
                with self.subTest(status=status, model=obj._meta.label):
                    self.assertEqual(self.client.get(self.url_for(obj)).status_code, 200)
                    self.assertEqual(self.client.post(self.url_for(obj), {"name": "Injected"}).status_code, 403)
                    self.assertEqual(self.client.post(self.url_for(obj, "delete"), {"post": "yes"}).status_code, 403)
            self.assertEqual(self.snapshot(), before)

    def test_deleted_content_is_not_visible_in_admin(self):
        self.set_status("DELETED")
        for obj in self.content_objects():
            with self.subTest(model=obj._meta.label):
                self.assertEqual(self.client.get(self.url_for(obj)).status_code, 404)

    def test_admin_foreign_key_choices_are_own_active_content(self):
        for model, field, expected in ((Character, "project", self.project),
                                      (Note, "node", self.scene),
                                      (CharacterMention, "character", self.character)):
            model_admin = admin.site._registry[model]
            form_field = model_admin.formfield_for_foreignkey(model._meta.get_field(field), self.request)
            self.assertIn(expected, form_field.queryset)
            self.set_status("FROZEN")
            form_field = model_admin.formfield_for_foreignkey(model._meta.get_field(field), self.request)
            self.assertFalse(form_field.queryset.exists())
            self.set_status("ACTIVE")

    def test_admin_bulk_delete_cannot_bypass_project_state(self):
        for status in ("FROZEN", "PENDING_DELETION"):
            self.set_status(status)
            before = self.snapshot()
            for obj in (self.scene, self.character, self.role, self.mention, self.note):
                model = type(obj)
                with self.subTest(status=status, model=model), self.assertRaises(PermissionDenied):
                    admin.site._registry[model].delete_queryset(self.request, model.objects.filter(pk=obj.pk))
            self.assertEqual(self.snapshot(), before)

    def test_admin_bulk_delete_cannot_include_foreign_content(self):
        with self.assertRaises(Http404):
            admin.site._registry[Character].delete_queryset(self.request, Character.objects.all())
        self.assertTrue(Character.objects.filter(pk=self.character.pk).exists())
        self.assertTrue(Character.objects.filter(pk=self.other_character.pk).exists())

    def test_project_and_user_physical_deletion_are_disabled(self):
        self.assertFalse(admin.site._registry[Project].has_delete_permission(self.request, self.project))
        self.assertFalse(admin.site._registry[get_user_model()].has_delete_permission(self.request, self.other_user))
        self.assertEqual(self.client.get(self.url_for(self.other_user, "delete")).status_code, 403)

    def test_image_admin_uses_private_route_without_file_url(self):
        Character.objects.filter(pk=self.character.pk).update(image=f"characters/{self.project.pk}/old.png")
        for status in ("ACTIVE", "FROZEN"):
            self.set_status(status)
            response = self.client.get(self.url_for(self.character))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, self.url("characters:image", character_pk=self.character.pk))
            self.assertNotContains(response, "old.png")

    def test_export_admin_is_readonly_and_links_to_authorized_download(self):
        ExportJob.objects.filter(pk=self.job.pk).update(status="DONE", file=f"exports/{self.user.pk}/{self.project.pk}/old.html")
        response = self.client.get(self.url_for(self.job))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.url("exports:download", export_pk=self.job.pk))
        self.assertNotContains(response, "old.html")
        self.assertEqual(self.client.post(self.url_for(self.job), {"file": "../../secret"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:exports_exportjob_add")).status_code, 403)

    def test_styles_admin_does_not_expose_or_delete_foreign_personal_styles(self):
        foreign_style = StyleTemplate.objects.create(user=self.other_user, name="Foreign private style")
        self.assertEqual(self.client.get(self.url_for(foreign_style)).status_code, 404)
        with self.assertRaises(Http404):
            admin.site._registry[StyleTemplate].delete_queryset(self.request, StyleTemplate.objects.all())
        self.assertTrue(StyleTemplate.objects.filter(pk=foreign_style.pk).exists())

    def test_admin_does_not_offer_new_role_on_readonly_character(self):
        self.set_status("FROZEN")
        self.character.refresh_from_db()
        inline = admin.site._registry[Character].get_inline_instances(self.request, self.character)[0]
        self.assertFalse(inline.has_add_permission(self.request, self.character))
        self.assertFalse(inline.has_change_permission(self.request, self.character))
        self.assertFalse(inline.has_delete_permission(self.request, self.character))
