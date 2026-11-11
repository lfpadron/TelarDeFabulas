from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Max, Q
from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import check_project_permission

from .hierarchy import validate_node_hierarchy
from .models import ManuscriptNode, SceneVersion, count_words
from .visibility import require_visible_node
from .services import lock_project


class RevisionConflict(ValidationError):
    def __init__(self):
        super().__init__(_("La escena fue modificada desde otra sesión. Tus cambios no se guardaron para evitar sobrescribir una versión más reciente."))


def _lock_scene(scene, user):
    using = scene._state.db or "default"
    project = lock_project(scene.project_id, using=using, user=user)
    check_project_permission(user, project, "EDIT")
    current = ManuscriptNode.objects.using(using).select_for_update().get(pk=scene.pk, project=project)
    require_visible_node(current)
    if current.node_type != ManuscriptNode.NodeType.SCENE:
        raise ValidationError(_("Las versiones solo pueden pertenecer a una escena."))
    current.project = project
    validate_node_hierarchy(current)
    return current


def _version_for_scene(scene, version):
    try:
        return SceneVersion.objects.using(scene._state.db).select_for_update().get(pk=version.pk, scene=scene)
    except SceneVersion.DoesNotExist:
        raise Http404(_("Versión no encontrada.")) from None


def _check_revision(version, expected_revision):
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision != version.revision:
        raise RevisionConflict()


def _create_version_locked(scene, content, based_on=None):
    using = scene._state.db or "default"
    number = (SceneVersion.objects.using(using).filter(scene=scene).aggregate(number=Max("version_number"))["number"] or 0) + 1
    version = SceneVersion(scene=scene, version_number=number, content=content, word_count=count_words(content), based_on=based_on)
    version.full_clean()
    models.Model.save(version, force_insert=True, using=using)
    ManuscriptNode.objects.using(using).filter(pk=scene.pk).update(current_draft_version=version)
    scene.current_draft_version = version
    return version


def create_scene_version(scene, *, user, source_version=None, expected_revision=None, content=None):
    with transaction.atomic(using=scene._state.db or "default"):
        scene = _lock_scene(scene, user)
        if source_version is not None:
            source_version = _version_for_scene(scene, source_version)
            _check_revision(source_version, expected_revision)
            if content is not None:
                raise ValidationError(_("Una copia usa el contenido exacto de la versión de origen."))
            content = source_version.content
        return _create_version_locked(scene, content if content is not None else "", source_version)


def restore_scene_version(scene, version, *, user, expected_revision):
    return create_scene_version(scene, user=user, source_version=version, expected_revision=expected_revision)


def update_scene_version(scene, version, *, user, expected_revision, content=None, editorial_stage=None):
    with transaction.atomic(using=scene._state.db or "default"):
        scene = _lock_scene(scene, user)
        current = _version_for_scene(scene, version)
        _check_revision(current, expected_revision)
        if current.editorial_stage == SceneVersion.EditorialStage.FINAL:
            raise ValidationError(_("Una versión definitiva no se edita. Crea una nueva versión a partir de ella."))
        if editorial_stage is not None:
            if editorial_stage not in ("DRAFT", "REVIEW"):
                raise ValidationError(_("Usa la acción de finalizar para designar una definitiva."))
            current.editorial_stage = editorial_stage
        if content is not None:
            current.content = content
        current.word_count = count_words(current.content)
        current.revision += 1
        current.full_clean()
        models.Model.save(current, using=scene._state.db, update_fields=["content", "editorial_stage", "word_count", "revision", "updated_at"])
        # Editing an older draft does not silently switch the scene's active draft.
        return current


def finalize_scene_version(scene, version, *, user, expected_revision):
    with transaction.atomic(using=scene._state.db or "default"):
        scene = _lock_scene(scene, user)
        current = _version_for_scene(scene, version)
        _check_revision(current, expected_revision)
        SceneVersion.objects.using(scene._state.db).filter(scene=scene, is_current_final=True).exclude(pk=current.pk).update(is_current_final=False)
        if current.editorial_stage != SceneVersion.EditorialStage.FINAL:
            current.editorial_stage = SceneVersion.EditorialStage.FINAL
            current.finalized_at = timezone.now()
            current.revision += 1
            current.is_current_final = True
            current.full_clean()
            models.Model.save(current, using=scene._state.db, update_fields=["editorial_stage", "finalized_at", "revision", "is_current_final", "updated_at"])
        elif not current.is_current_final:
            SceneVersion.objects.using(scene._state.db).filter(pk=current.pk).update(is_current_final=True)
            current.is_current_final = True
        if scene.current_draft_version_id == current.pk:
            ManuscriptNode.objects.using(scene._state.db).filter(pk=scene.pk).update(current_draft_version=None)
        return current


def get_current_draft_version(scene):
    return scene.versions.filter(pk=F("scene__current_draft_version_id"), editorial_stage__in=["DRAFT", "REVIEW"]).first()


def get_current_final_version(scene):
    return scene.versions.filter(is_current_final=True).first()


def select_scene_versions(scenes, *, mode="WORK", include_content=True):
    """Materialize selection and text in one SQL statement, once per render."""
    if mode not in ("WORK", "FINAL"):
        raise ValueError("Unknown export mode")
    scene_ids = [scene.pk for scene in scenes if scene.node_type == ManuscriptNode.NodeType.SCENE]
    selected, drafts = {}, {}
    fields = ["id", "scene_id", "version_number", "editorial_stage", "is_current_final", "word_count", "revision", "scene__current_draft_version_id"]
    if include_content:
        fields.append("content")
    rows = SceneVersion.objects.filter(scene_id__in=scene_ids).filter(
        Q(is_current_final=True) | Q(pk=F("scene__current_draft_version_id"), editorial_stage__in=["DRAFT", "REVIEW"])
    ).values(*fields)
    for row in rows:
        if row["is_current_final"]:
            selected[row["scene_id"]] = row
        if row["id"] == row["scene__current_draft_version_id"] and row["editorial_stage"] != "FINAL":
            drafts[row["scene_id"]] = row
    if mode == "WORK":
        selected.update(drafts)
        if set(scene_ids) - selected.keys():
            raise ValidationError(_("Hay escenas sin versión de trabajo ni definitiva. Revisa la migración de contenido."))
    return selected


def get_scene_content_for_export(scene, *, mode="WORK"):
    require_visible_node(scene)
    version = select_scene_versions([scene], mode=mode).get(scene.pk)
    return version["content"] if version else ""
