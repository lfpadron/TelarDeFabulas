import shutil
import tempfile
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse

from apps.characters.models import Character, CharacterDramaticRole, CharacterRelationship
from apps.geography.models import GeographicLocation
from apps.manuscripts.models import ManuscriptNode
from apps.organizations.models import Organization, CharacterOrganizationMembership
from apps.projects.models import Project
from apps.references.models import ReferenceMaterial, ReferenceAssociation
from apps.styles.models import StyleTemplate
from apps.worldbuilding.models import WorldbuildingEntry

from .job_services import request_export
from .snapshots import get_export_document


class WorldExportFixture:
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(email="world-owner@example.test")
        self.other_user = get_user_model().objects.create_user(email="world-other@example.test")
        self.project = Project.objects.create(user=self.user, name="World original")
        self.other_project = Project.objects.create(user=self.other_user, name="FOREIGN PROJECT")
        self.style = StyleTemplate.objects.create(user=self.user, name="Original style", include_table_of_contents=True)
        self.country = GeographicLocation.objects.create(project=self.project, name="Kingdom", location_type="COUNTRY")
        self.city = GeographicLocation.objects.create(project=self.project, parent=self.country, name="Harbor", location_type="CITY")
        self.guild = Organization.objects.create(project=self.project, name="Council", organization_type="POLITICAL", headquarters=self.city)
        self.branch = Organization.objects.create(project=self.project, parent=self.guild, name="Archive", organization_type="ACADEMIC")
        self.ada = Character.objects.create(project=self.project, name="Ada", alias="Archivist", biography="BIO ORIGINAL", residence=self.city)
        self.ben = Character.objects.create(project=self.project, name="Ben", biography="BEN ORIGINAL")
        self.cora = Character.objects.create(project=self.project, name="Cora")
        CharacterDramaticRole.objects.create(character=self.ada, role="HEROE")
        self.relation = CharacterRelationship.objects.create(project=self.project, source_character=self.ada,
            target_character=self.ben, relationship_type="MENTOR", description="RELATION ORIGINAL")
        self.mutual = CharacterRelationship.objects.create(project=self.project, source_character=self.cora,
            target_character=self.ada, relationship_type="FRIEND", is_reciprocal=True)
        self.membership = CharacterOrganizationMembership.objects.create(character=self.ada, organization=self.guild,
            position_title="Archivist", joined_at_text="Year of rain", description="MEMBERSHIP ORIGINAL")
        self.politics = WorldbuildingEntry.objects.create(project=self.project, title="Assembly", category="POLITICS", content="FIRST PARAGRAPH\n\nSECOND PARAGRAPH")
        self.religion = WorldbuildingEntry.objects.create(project=self.project, title="Ritual", category="RELIGION", content='<script>alert("unsafe")</script>')
        self.reference = ReferenceMaterial.objects.create(project=self.project, title="Atlas", author="Writer", publication_year_text="Era of rain", publisher="Press", notes="REFERENCE ORIGINAL")
        self.link = ReferenceMaterial.objects.create(project=self.project, title="Chronicle", material_type="LINK", source_url="https://example.com/history")
        self.association = ReferenceAssociation.objects.create(reference=self.reference, character=self.ada, description="ASSOCIATION ORIGINAL")
        self.book = ManuscriptNode.objects.create(project=self.project, title="DO NOT EXPORT", content="MANUSCRIPT SECRET")
        self.foreign = Character.objects.create(project=self.other_project, name="FOREIGN CHARACTER")
        self.foreign_reference = ReferenceMaterial.objects.create(project=self.other_project, title="FOREIGN REFERENCE")
        self.enterContext(patch("apps.exports.job_services.enqueue_export"))
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        self.enterContext(override_settings(MEDIA_ROOT=media, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"))
        self.client.force_login(self.user)

    def request(self, **kwargs):
        return request_export(**{"user": self.user, "project": self.project, "style_template": self.style,
            "request_key": uuid4(), "export_mode": "REFERENCE", "scope_kind": "WORLD_COMPENDIUM", "export_format": "MARKDOWN", **kwargs})

    def sections(self, job, kind=None):
        return [n for n in get_export_document(job).nodes if kind is None or n.source_kind == kind]

    def contents(self, job):
        return "\n".join(n.title + "\n" + n.content for n in self.sections(job))

    def ids(self, job, kind):
        return [n.source_id for n in self.sections(job, kind)]

    def url(self, name="world_create", job=None, project=None):
        kwargs = {"project_pk": (project or self.project).pk}
        if job is not None:
            kwargs["export_pk"] = job.pk
        return reverse(f"exports:{name}", kwargs=kwargs)

    def post_data(self, **kwargs):
        return {"scope_kind": "WORLD_COMPENDIUM", "format": "MARKDOWN", "style_template": self.style.pk,
                "request_key": str(uuid4()), **kwargs}
