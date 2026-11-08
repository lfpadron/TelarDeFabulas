from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from apps.characters.forms import CharacterForm
from apps.characters.models import Character, CharacterDramaticRole, CharacterMention
from apps.core.permissions import Action, can_access_project, project_allows_action
from apps.exports.models import ExportJob
from apps.exports.tasks import generate_export_job
from apps.manuscripts.models import ManuscriptNode
from apps.manuscripts.services import move_node, move_node_down, move_node_up
from apps.notes.models import Note
from apps.projects.models import Project
from apps.styles.models import StyleTemplate

from .helpers import SecurityTestCase


class ProjectAuthorizationTests(SecurityTestCase):
    def assert_mutations_blocked(self, code):
        before = self.snapshot()
        for url, payload in self.mutation_requests():
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, payload).status_code, code)
        self.assertEqual(self.snapshot(), before)

    def assert_reading_allowed(self):
        for url in self.reading_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_other_user_cannot_read_any_project_content(self):
        self.client.force_login(self.other_user)
        for url in self.reading_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_other_user_cannot_create_edit_delete_move_or_manage_mentions(self):
        self.client.force_login(self.other_user)
        self.assert_mutations_blocked(404)

    def test_other_user_cannot_export(self):
        self.client.force_login(self.other_user)
        with patch("apps.exports.views.generate_export_job.delay") as delay:
            response = self.client.post(self.url("exports:create"), {"format": "HTML", "style_template": self.style.pk})
        self.assertEqual(response.status_code, 404)
        delay.assert_not_called()

    def test_frozen_project_allows_reading(self):
        self.set_status("FROZEN")
        self.assert_reading_allowed()

    def test_frozen_project_blocks_all_mutations(self):
        self.set_status("FROZEN")
        self.assert_mutations_blocked(403)

    def test_pending_project_allows_reading(self):
        self.set_status("PENDING_DELETION")
        self.assert_reading_allowed()

    def test_pending_project_blocks_all_mutations(self):
        self.set_status("PENDING_DELETION")
        self.assert_mutations_blocked(403)

    def test_deleted_project_blocks_every_endpoint(self):
        self.set_status("DELETED")
        self.assert_mutations_blocked(404)
        urls = self.reading_urls() + [self.url("characters:image", character_pk=self.character.pk),
                self.url("exports:download", export_pk=self.job.pk), self.url("exports:create")]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(self.url("projects:restore")).status_code, 404)
        self.assertNotContains(self.client.get(reverse("projects:list")), self.project.name)

    def test_readonly_projects_can_be_exported_without_source_changes(self):
        for status in ("FROZEN", "PENDING_DELETION"):
            self.set_status(status)
            before = list(ManuscriptNode.objects.order_by("pk").values())
            with self.subTest(status=status), patch("apps.exports.views.generate_export_job.delay") as delay:
                response = self.client.post(self.url("exports:create"), {"format": "HTML", "style_template": self.style.pk})
            self.assertEqual(response.status_code, 302)
            delay.assert_called_once()
            self.assertEqual(list(ManuscriptNode.objects.order_by("pk").values()), before)

    def test_owner_can_restore_frozen_and_pending_projects(self):
        for status in ("FROZEN", "PENDING_DELETION"):
            self.set_status(status)
            self.assertEqual(self.client.post(self.url("projects:restore")).status_code, 302)
            self.project.refresh_from_db()
            self.assertEqual(self.project.status, "ACTIVE")

    def test_restore_is_not_available_to_other_users_or_active_projects(self):
        self.assertEqual(self.client.post(self.url("projects:restore")).status_code, 403)
        self.set_status("FROZEN")
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.post(self.url("projects:restore")).status_code, 404)
        self.project.refresh_from_db()
        self.assertEqual(self.project.status, "FROZEN")

    def test_get_never_performs_deletion_or_restoration(self):
        before = self.snapshot()
        for url, _ in self.mutation_requests():
            with self.subTest(url=url):
                self.assertIn(self.client.get(url).status_code, (200, 405))
        self.assertEqual(self.client.get(self.url("projects:restore")).status_code, 405)
        self.assertEqual(self.snapshot(), before)

    def test_csrf_is_required_for_all_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        before = self.snapshot()
        for url, payload in self.mutation_requests() + [(self.url("projects:restore"), {})]:
            with self.subTest(url=url):
                self.assertEqual(client.post(url, payload).status_code, 403)
        self.assertEqual(self.snapshot(), before)

    def test_delete_confirmation_with_valid_csrf_works(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        url = self.url("notes:delete", note_pk=self.note.pk)
        self.assertContains(client.get(url), 'method="post"')
        self.assertTrue(Note.objects.filter(pk=self.note.pk).exists())
        self.assertEqual(client.post(url, {"csrfmiddlewaretoken": client.cookies["csrftoken"].value}).status_code, 302)
        self.assertFalse(Note.objects.filter(pk=self.note.pk).exists())

    def test_readonly_templates_do_not_offer_content_writes(self):
        self.set_status("FROZEN")
        response = self.client.get(self.url("manuscripts:detail", node_pk=self.scene.pk))
        self.assertNotContains(response, self.url("manuscripts:edit", node_pk=self.scene.pk))
        self.assertNotContains(response, self.url("characters:mention_create"))
        response = self.client.get(self.url("projects:detail"))
        self.assertNotContains(response, self.url("projects:delete"))
        self.assertContains(response, self.url("projects:restore"))

    def test_direct_move_services_do_not_normalize_readonly_projects(self):
        ManuscriptNode.objects.filter(pk=self.scene.pk).update(position=9)
        self.set_status("FROZEN")
        before = self.snapshot()
        for operation in (move_node_up, move_node_down, lambda node: move_node(node, self.chapter, 1)):
            with self.subTest(operation=operation), self.assertRaises(ValidationError):
                operation(self.scene)
        self.assertEqual(self.snapshot(), before)

    def test_model_and_form_validation_reject_frozen_project_writes(self):
        self.set_status("FROZEN")
        for instance in (ManuscriptNode(project=self.project, title="No"),
                         Character(project=self.project, name="No"), Note(project=self.project, title="No")):
            with self.subTest(model=type(instance)), self.assertRaises(ValidationError):
                instance.save()
        form = CharacterForm(self.character_payload(), project=self.project)
        self.assertFalse(form.is_valid())

    def test_worker_rechecks_project_permissions(self):
        self.set_status("DELETED")
        with patch("apps.exports.tasks.build_export_html") as render:
            generate_export_job.run(self.job.pk)
        render.assert_not_called()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "FAILED")
        self.assertFalse(self.job.file)

    def test_worker_rechecks_export_owner(self):
        ExportJob.objects.filter(pk=self.job.pk).update(user=self.other_user)
        with patch("apps.exports.tasks.build_export_html") as render:
            generate_export_job.run(self.job.pk)
        render.assert_not_called()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "FAILED")

    def test_character_roles_save_atomically(self):
        form = CharacterForm(self.character_payload(dramatic_roles=["ALIADO"]), instance=self.character, project=self.project)
        self.assertTrue(form.is_valid(), form.errors)
        before = self.snapshot()
        with patch("apps.characters.forms.CharacterDramaticRole.objects.create", side_effect=RuntimeError("test")):
            with self.assertRaises(RuntimeError):
                form.save()
        self.assertEqual(self.snapshot(), before)

    def test_corrupt_cross_project_references_do_not_leak_names(self):
        Note.objects.filter(pk=self.note.pk).update(node=self.other_node)
        CharacterMention.objects.filter(pk=self.mention.pk).update(node=self.other_node)
        ExportJob.objects.filter(pk=self.job.pk).update(root_node=self.other_node)
        for url in (self.url("notes:list"), self.url("characters:detail", character_pk=self.character.pk), self.url("exports:list")):
            with self.subTest(url=url):
                self.assertNotContains(self.client.get(url), self.other_node.title)
        self.assertEqual(self.client.get(self.url("notes:detail", note_pk=self.note.pk)).status_code, 404)
        self.assertEqual(self.client.get(self.url("exports:detail", export_pk=self.job.pk)).status_code, 404)

    def test_foreign_child_id_in_owned_project_is_404(self):
        for name, kwargs in (("manuscripts:edit", {"node_pk": self.other_node.pk}),
                             ("characters:edit", {"character_pk": self.other_character.pk})):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(self.url(name, **kwargs)).status_code, 404)
                self.assertEqual(self.client.post(self.url(name, **kwargs), {}).status_code, 404)

    def test_profile_cannot_escalate_permissions(self):
        response = self.client.post(reverse("profile"), {"name": "Owner", "preferred_locale": "es-mx", "timezone": "America/Mexico_City",
                                                       "user_type": "TECH_ADMIN", "status": "DELETED", "is_staff": "on", "is_superuser": "on"})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.user_type, "PREMIUM")
        self.assertEqual(self.user.status, "ACTIVE")
        self.assertFalse(self.user.is_staff or self.user.is_superuser)

    def test_referenced_style_deletion_is_controlled(self):
        ExportJob.objects.filter(pk=self.job.pk).update(style_template=self.personal_style)
        response = self.client.post(reverse("styles:delete", args=[self.personal_style.pk]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no puede borrarse")
        self.assertTrue(StyleTemplate.objects.filter(pk=self.personal_style.pk).exists())

    def test_style_actions_never_access_another_users_style(self):
        self.client.force_login(self.other_user)
        for action in ("detail", "edit", "delete", "duplicate"):
            with self.subTest(action=action):
                self.assertEqual(self.client.post(reverse(f"styles:{action}", args=[self.personal_style.pk])).status_code, 404)

    def test_unknown_project_state_is_denied(self):
        self.set_status("UNKNOWN")
        for action in Action:
            self.assertFalse(can_access_project(self.user, self.project, action))
        self.assertEqual(self.client.get(self.url("projects:detail")).status_code, 404)

    def test_anonymous_and_disabled_accounts_have_no_project_permissions(self):
        self.user.is_active = False
        for user in (AnonymousUser(), self.user):
            for action in Action:
                self.assertFalse(can_access_project(user, self.project, action))

    def test_corrupt_export_style_reference_does_not_leak_foreign_style(self):
        foreign_style = StyleTemplate.objects.create(user=self.other_user, name="Foreign secret style")
        ExportJob.objects.filter(pk=self.job.pk).update(style_template=foreign_style)
        self.assertNotContains(self.client.get(self.url("exports:list")), foreign_style.name)
        self.assertEqual(self.client.get(self.url("exports:detail", export_pk=self.job.pk)).status_code, 404)

    def test_policy_matrix(self):
        for status in Project.ProjectStatus.values:
            self.project.status = status
            for action in Action:
                with self.subTest(status=status, action=action):
                    expected = status != "DELETED" if action in (Action.VIEW, Action.EXPORT, Action.DOWNLOAD) else (
                        status in ("FROZEN", "PENDING_DELETION") if action == Action.RESTORE else status == "ACTIVE"
                    )
                    self.assertEqual(project_allows_action(self.project, action), expected)
                    self.assertEqual(can_access_project(self.user, self.project, action), expected)
                    self.assertFalse(can_access_project(self.other_user, self.project, action))
