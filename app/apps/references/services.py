import os
from uuid import uuid4

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Sum
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import Action, check_project_permission, validate_project_action
from apps.projects.models import Project

from .files import enqueue_cleanup, reference_path
from .models import ReferenceAssociation, ReferenceFileCleanup, ReferenceMaterial, TARGETS
from .validators import validate_reference_upload


TEXT_FIELDS = ("material_type", "title", "short_description", "notes", "author", "publication_year_text", "publisher", "source_url")


class ReferenceConflict(ValidationError):
    def __init__(self):
        super().__init__(_("La referencia cambió desde que la abriste. Tus cambios no se guardaron para evitar sobrescribir la revisión actual."))


def check_revision(reference, expected):
    if type(expected) is not int or reference.revision != expected:
        raise ReferenceConflict()


def lock_project(pk, user=None, action=Action.EDIT):
    project = Project.objects.select_for_update().filter(pk=pk).first()
    if project is None:
        raise ValidationError(_("El proyecto ya no existe."))
    if user is not None:
        check_project_permission(user, project, action)
    validate_project_action(project, action)
    return project


def project_storage_bytes(project):
    active = ReferenceMaterial.objects.filter(project=project).aggregate(total=Sum("file_size"))["total"] or 0
    pending = ReferenceFileCleanup.objects.filter(project_id=project.pk).aggregate(total=Sum("file_size"))["total"] or 0
    return active + pending


def check_upload_quota(project, upload_size):
    # Charge the old file until physical cleanup completes, including replacement headroom.
    if project_storage_bytes(project) + upload_size > settings.REFERENCE_PROJECT_STORAGE_MAX_MB * 1024 * 1024:
        raise ValidationError(_("El proyecto no tiene espacio suficiente para este archivo. Los archivos pendientes de limpieza también ocupan espacio."))


def _discard_new(project_id, name, size):
    if not name:
        return
    try:
        reference_path(project_id, name).unlink(missing_ok=True)
    except OSError:
        enqueue_cleanup(project_id, name, size)


def _write_upload(project, upload):
    name = f"references/{project.pk}/{uuid4().hex}{upload.extension}"
    path = reference_path(project.pk, name)
    created = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            created = True
            output.write(upload.content)
            output.flush()
            os.fsync(output.fileno())
    except OSError:
        if created:
            _discard_new(project.pk, name, upload.size)
        raise ValidationError(_("No se pudo guardar el archivo. La referencia anterior permanece intacta.")) from None
    return name


def _persist(project_id, *, reference=None, expected_revision=None, user=None, file=None, clear_file=False, entity=None, **data):
    if not set(data) <= set(TEXT_FIELDS):
        raise ValidationError(_("La referencia contiene campos no editables."))
    upload = validate_reference_upload(file) if file else None
    new_name = None
    try:
        with transaction.atomic():
            project = lock_project(project_id, user, Action.EDIT if reference else Action.CREATE)
            if reference is None:
                current = ReferenceMaterial(project=project)
            else:
                current = ReferenceMaterial.objects.select_for_update().filter(project=project, pk=reference.pk).first()
                if current is None:
                    raise ValidationError(_("La referencia ya no existe en este proyecto."))
                check_revision(current, expected_revision)
                current.project = project
            old_name, old_size = current.file.name, current.file_size
            for key, value in data.items():
                setattr(current, key, value)
            if clear_file:
                current.file = ""
                current.file_size, current.mime_type, current.original_filename = 0, "", ""
            if upload:
                check_upload_quota(project, upload.size)
                current.file = f"references/{project.pk}/{uuid4().hex}{upload.extension}"
                current.file_size, current.mime_type, current.original_filename = upload.size, upload.mime_type, upload.original_filename
            current.full_clean()
            if upload:
                new_name = _write_upload(project, upload)
                current.file = new_name
            if reference:
                current.revision += 1
            models.Model.save(current)
            if entity is not None:
                attach_reference(current, entity, user=user)
            if old_name and current.file.name != old_name:
                enqueue_cleanup(project.pk, old_name, old_size)
            current._loaded_revision = current.revision
            return current
    except Exception:
        if new_name:
            _discard_new(project_id, new_name, upload.size)
        raise


def create_reference(project, *, user=None, **data):
    return _persist(project.pk, user=user, **data)


def update_reference(reference, *, expected_revision, user=None, **data):
    return _persist(reference.project_id, reference=reference, expected_revision=expected_revision, user=user, **data)


def save_reference(instance, *args, user=None, **kwargs):
    if not instance.project_id:
        raise ValidationError(_("La referencia debe pertenecer a un proyecto."))
    fields = kwargs.get("update_fields")
    if fields is not None and not fields:
        return
    if args or kwargs.get("force_insert") and not instance._state.adding or kwargs.get("using") not in (None, "default"):
        raise ValidationError(_("Operación de guardado no permitida."))
    editable = set(TEXT_FIELDS) | {"file"}
    if fields is not None and not set(fields) <= editable:
        raise ValidationError(_("La referencia contiene campos no editables."))
    if instance._state.adding and instance.pk is not None:
        raise ValidationError(_("El identificador se asigna automáticamente."))
    selected = editable if fields is None else set(fields)
    data = {key: getattr(instance, key) for key in TEXT_FIELDS if key in selected}
    if "file" in selected:
        if instance.file and not instance.file._committed:
            data["file"] = instance.file
        elif instance.file:
            if instance._state.adding or not ReferenceMaterial.objects.filter(pk=instance.pk, project_id=instance.project_id, file=instance.file.name).exists():
                raise ValidationError(_("No se permite asignar rutas de archivos existentes."))
        else:
            data["clear_file"] = True
    saved = (create_reference(instance.project, user=user, **data) if instance._state.adding else
             update_reference(instance, expected_revision=getattr(instance, "_loaded_revision", None), user=user, **data))
    for field in instance._meta.concrete_fields:
        setattr(instance, field.attname, getattr(saved, field.attname))
    instance._state.adding, instance._state.db, instance._loaded_revision = False, saved._state.db, saved.revision


def delete_reference(reference, *, expected_revision=None, user=None, using=None):
    with transaction.atomic():
        project = lock_project(reference.project_id, user, Action.DELETE)
        current = ReferenceMaterial.objects.select_for_update().filter(pk=reference.pk, project=project).first()
        if current is None:
            raise ValidationError(_("La referencia ya no existe."))
        check_revision(current, expected_revision if expected_revision is not None else getattr(reference, "_loaded_revision", None))
        result = models.Model.delete(current)
        reference.pk = None
        return result


def entity_field(entity):
    for key, (label, *metadata) in TARGETS.items():
        if isinstance(entity, apps.get_model(label)):
            return key
    raise ValidationError(_("Tipo de entidad no permitido."))


def attach_reference(reference, entity, *, description="", user=None):
    association = ReferenceAssociation(reference=reference, description=description, **{entity_field(entity): entity})
    save_association(association, user=user)
    return association


def save_association(association, *args, user=None, **kwargs):
    with transaction.atomic():
        ref = ReferenceMaterial.objects.filter(pk=association.reference_id).only("project_id").first()
        if ref is None:
            raise ValidationError(_("La referencia ya no existe."))
        project = lock_project(ref.project_id, user)
        reference = ReferenceMaterial.objects.select_for_update().filter(pk=ref.pk, project=project).first()
        if reference is None:
            raise ValidationError(_("La referencia ya no existe."))
        if association.pk:
            current = ReferenceAssociation.objects.select_for_update().filter(pk=association.pk, reference=reference).first()
            if current is None or association._state.adding or any(getattr(current, f"{key}_id") != getattr(association, f"{key}_id") for key in TARGETS):
                raise ValidationError(_("No se permite cambiar la identidad de una asociación."))
        association.reference = reference
        reference.project = project
        keys = [key for key in TARGETS if getattr(association, f"{key}_id")]
        if len(keys) != 1:
            raise ValidationError(_("Selecciona exactamente una entidad."))
        key = keys[0]
        entity = apps.get_model(TARGETS[key][0]).objects.filter(pk=getattr(association, f"{key}_id"), project=project).first()
        if entity is None:
            raise ValidationError(_("La referencia y la entidad deben pertenecer al mismo proyecto."))
        setattr(association, key, entity)
        association.full_clean()
        return models.Model.save(association, *args, **kwargs)


def detach_reference(association, *, user=None):
    with transaction.atomic():
        project = lock_project(association.reference.project_id, user, Action.DELETE)
        current = ReferenceAssociation.objects.filter(pk=association.pk, reference__project=project).first()
        if current is None:
            raise ValidationError(_("La asociación ya no existe."))
        result = models.Model.delete(current)
        association.pk = None
        return result


def get_references_for_entity(entity, *, user=None):
    from .selectors import project_associations
    if user is not None:
        check_project_permission(user, entity.project)
    field = entity_field(entity)
    return project_associations(entity.project, include_hidden=field != "manuscript_node").filter(**{field: entity})
