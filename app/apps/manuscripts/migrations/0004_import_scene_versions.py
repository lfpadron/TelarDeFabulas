import hashlib
import re

from django.db import migrations
from django.db.migrations.exceptions import IrreversibleError
from django.utils import timezone


STAGES = {
    "PENDING": "DRAFT", "IN_PROGRESS": "DRAFT", "DRAFT": "DRAFT",
    "REVIEW": "REVIEW", "FINISHED": "REVIEW",
    "PUBLISHABLE": "FINAL", "PUBLISHED": "FINAL",
}
WORDS = re.compile(r"\b[\w]+(?:[-'][\w]+)?\b", re.UNICODE)


def import_scene_versions(apps, schema_editor):
    Node = apps.get_model("manuscripts", "ManuscriptNode")
    Version = apps.get_model("manuscripts", "SceneVersion")
    Project = apps.get_model("projects", "Project")
    using = schema_editor.connection.alias
    # Maintenance window required: project first, then scene, like normal writers.
    list(Project.objects.using(using).order_by("pk").select_for_update().values_list("pk", flat=True))
    imported_at = timezone.now()
    for scene in Node.objects.using(using).filter(node_type="SCENE").order_by("pk").select_for_update().iterator(chunk_size=200):
        source_hash = hashlib.sha256(scene.content.encode("utf-8")).hexdigest()
        versions = Version.objects.using(using).filter(scene_id=scene.pk)
        previous_import = versions.exclude(legacy_source_hash="").first()
        if previous_import:
            if previous_import.legacy_source_hash != source_hash:
                raise RuntimeError(f"Legacy source changed for scene {scene.pk}; manual review required.")
            continue
        if versions.exists():
            # Never assume an existing V1 is ours, or overwrite post-migration work.
            continue
        if scene.status not in STAGES:
            raise RuntimeError(f"Unknown legacy status for scene {scene.pk}; manual review required.")
        stage = STAGES[scene.status]
        version = Version.objects.using(using).create(
            scene_id=scene.pk, version_number=1, editorial_stage=stage,
            content=scene.content, word_count=len(WORDS.findall(scene.content)), revision=1,
            is_current_final=stage == "FINAL", finalized_at=imported_at if stage == "FINAL" else None,
            legacy_source_hash=source_hash,
        )
        Version.objects.using(using).filter(pk=version.pk).update(created_at=scene.created_at, updated_at=scene.updated_at)
        Node.objects.using(using).filter(pk=scene.pk).update(current_draft_version_id=version.pk if stage != "FINAL" else None)


def reverse_import(apps, schema_editor):
    if apps.get_model("manuscripts", "SceneVersion").objects.using(schema_editor.connection.alias).exists():
        raise IrreversibleError("Scene versions exist. Keep the additive schema; do not discard editorial history.")


class Migration(migrations.Migration):
    dependencies = [("manuscripts", "0003_scene_versions")]
    operations = [migrations.RunPython(import_scene_versions, reverse_import)]
