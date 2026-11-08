from io import BytesIO
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from apps.characters.models import Character, CharacterDramaticRole, CharacterMention
from apps.exports.models import ExportJob
from apps.exports.job_services import request_export
from apps.manuscripts.models import ManuscriptNode
from apps.notes.models import Note
from apps.projects.models import Project
from apps.styles.models import StyleTemplate


def image_upload(image_format="PNG", filename=None):
    output = BytesIO()
    Image.new("RGB", (3, 3), "white").save(output, format=image_format)
    suffix = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}[image_format]
    return SimpleUploadedFile(filename or f"portrait.{suffix}", output.getvalue(), content_type=f"image/{suffix}")


class SecurityTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(email="owner@example.test", user_type="PREMIUM")
        cls.other_user = User.objects.create_user(email="other@example.test", user_type="PREMIUM")
        cls.project = Project.objects.create(user=cls.user, name="Owner project")
        cls.other_project = Project.objects.create(user=cls.other_user, name="Foreign private project")
        cls.book = ManuscriptNode.objects.create(project=cls.project, title="Book", node_type="BOOK")
        cls.chapter = ManuscriptNode.objects.create(project=cls.project, title="Chapter", parent=cls.book, node_type="CHAPTER")
        cls.scene = ManuscriptNode.objects.create(project=cls.project, title="Scene", parent=cls.chapter, node_type="SCENE", content="Private prose.")
        cls.other_node = ManuscriptNode.objects.create(project=cls.other_project, title="Foreign private node")
        cls.character = Character.objects.create(project=cls.project, name="Owner character")
        cls.other_character = Character.objects.create(project=cls.other_project, name="Foreign private character")
        cls.role = CharacterDramaticRole.objects.create(character=cls.character, role="MENTOR")
        cls.mention = CharacterMention.objects.create(character=cls.character, node=cls.scene, mention_type="APPEARS")
        cls.note = Note.objects.create(project=cls.project, title="Owner note", node=cls.scene, character=cls.character)
        cls.style = StyleTemplate.objects.create(name="System style", is_system=True)
        cls.personal_style = StyleTemplate.objects.create(name="Owner style", user=cls.user)
        cls.job = ExportJob.objects.create(user=cls.user, project=cls.project, root_node=cls.book, style_template=cls.style)

    def setUp(self):
        self.client.force_login(self.user)

    def capture_export(self, **overrides):
        self.job = request_export(**{"user": self.user, "project": self.project,
                                     "style_template": self.style, "root_node": self.job.root_node,
                                     "request_key": uuid4(), **overrides})
        return self.job

    def url(self, name, **kwargs):
        if name.startswith("projects:"):
            return reverse(name, kwargs=kwargs or {"pk": self.project.pk})
        return reverse(name, kwargs={"project_pk": self.project.pk, **kwargs})

    def set_status(self, status):
        Project.objects.filter(pk=self.project.pk).update(status=status)
        self.project.refresh_from_db()

    def snapshot(self):
        return {model._meta.label: list(model.objects.order_by("pk").values()) for model in (
            Project, ManuscriptNode, Character, CharacterDramaticRole, CharacterMention, Note, ExportJob, StyleTemplate,
        )}

    def character_payload(self, **overrides):
        return {"name": "Updated character", "importance": "PRINCIPAL", "narrative_role": "PROTAGONISTA",
                "completion_status": "DRAFT", "dramatic_roles": ["MENTOR"], **overrides}

    def mutation_requests(self):
        node = {"title": "Updated scene", "parent": self.chapter.pk, "node_type": "SCENE", "status": "DRAFT", "position": 2, "content": "Updated prose."}
        note = {"title": "Updated note", "note_type": "NOTE", "status": "OPEN", "priority": "MEDIUM", "node": self.scene.pk, "character": self.character.pk}
        mention = {"character": self.character.pk, "node": self.scene.pk, "mention_type": "MENTIONED"}
        return [
            (self.url("projects:edit"), {"name": "Changed", "language": "es", "locale": "es-mx"}),
            (self.url("projects:delete"), {}),
            (self.url("manuscripts:create"), node),
            (self.url("manuscripts:edit", node_pk=self.scene.pk), node),
            (self.url("manuscripts:delete", node_pk=self.scene.pk), {}),
            (self.url("manuscripts:move", node_pk=self.scene.pk), {"parent": self.chapter.pk, "position": 1}),
            (self.url("manuscripts:move_up", node_pk=self.scene.pk), {}),
            (self.url("manuscripts:move_down", node_pk=self.scene.pk), {}),
            (self.url("characters:create"), self.character_payload()),
            (self.url("characters:edit", character_pk=self.character.pk), self.character_payload()),
            (self.url("characters:delete", character_pk=self.character.pk), {}),
            (self.url("characters:mention_create"), mention),
            (self.url("characters:mention_edit", mention_pk=self.mention.pk), mention),
            (self.url("characters:mention_delete", mention_pk=self.mention.pk), {}),
            (self.url("notes:create"), note),
            (self.url("notes:edit", note_pk=self.note.pk), note),
            (self.url("notes:delete", note_pk=self.note.pk), {}),
        ]

    def reading_urls(self):
        return [self.url("projects:detail"), self.url("manuscripts:tree"),
                self.url("manuscripts:detail", node_pk=self.scene.pk), self.url("characters:list"),
                self.url("characters:detail", character_pk=self.character.pk), self.url("notes:list"),
                self.url("notes:detail", note_pk=self.note.pk), self.url("exports:list"),
                self.url("exports:detail", export_pk=self.job.pk), self.url("exports:preview")]
