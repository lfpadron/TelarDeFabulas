import logging
from uuid import UUID

from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import Action, get_user_project
from apps.manuscripts.models import ManuscriptNode
from apps.styles.models import StyleTemplate

from .models import ExportJob, ExportSnapshot
from .snapshots import build_manifest, manifest_digest
from .world_exports import build_world_manifest, normalize_selection
from .lifecycle import backoff, lease_duration, prepare_retry


logger = logging.getLogger(__name__)


def enqueue_export(job_id):
    from .tasks import generate_export_job

    with transaction.atomic():
        job = ExportJob.objects.select_for_update().filter(pk=job_id).first()
        now = timezone.now()
        if (not job or job.status != "REQUESTED" or job.deletion_requested_at
                or (job.next_attempt_at and job.next_attempt_at > now)
                or (job.enqueued_at and job.enqueued_at + lease_duration() > now)):
            return
        job.dispatch_count += 1
        try:
            generate_export_job.apply_async(args=[job.pk], retry=False)
        except Exception:
            job.error_message = _("No fue posible enviar a la cola. La solicitud está conservada; puedes reintentar el envío.")
            logger.warning("Export enqueue failed: job=%s", job.pk)
            job.next_attempt_at = now + backoff(job.dispatch_count)
        else:
            job.enqueued_at = now
            job.next_attempt_at = now + lease_duration()
            job.error_message = ""
        job.save(update_fields=["enqueued_at", "error_message", "dispatch_count", "next_attempt_at"])


def request_export(*, user, project, style_template, root_node=None, export_format="HTML", export_mode="WORK", request_key,
                   expected_counts=None, notify_by_email=True, scope_kind="MANUSCRIPT", entity_id=None, category="", include_descendants=False):
    try:
        key = UUID(str(request_key))
    except (TypeError, ValueError, AttributeError):
        raise ValidationError(_("La clave de solicitud no es válida. Vuelve a abrir el formulario.")) from None
    with transaction.atomic():
        project = get_user_project(user, project.pk, Action.EXPORT, for_update=True)
        selection = None
        if export_mode == "REFERENCE":
            selection = normalize_selection(scope_kind, entity_id, category, include_descendants)
            if root_node is not None or expected_counts is not None:
                raise ValidationError(_("Una exportación de consulta no admite selección de escenas."))
        elif scope_kind != "MANUSCRIPT" or entity_id is not None or category or include_descendants:
            raise ValidationError(_("La selección de entidades requiere la modalidad de consulta."))
        previous = ExportJob.objects.filter(request_key=key).first()
        if previous:
            if previous.user_id != user.pk or previous.project_id != project.pk:
                raise ValidationError(_("La clave de solicitud ya fue utilizada."))
            if previous.status == "DELETED" or previous.deletion_requested_at:
                raise ValidationError(_("La solicitud fue borrada. Abre un formulario nuevo."))
            original_manifest = previous.snapshot.manifest_json
            original_root = original_manifest["root_node_id"]
            if previous.scope_kind != scope_kind or original_manifest.get("selection") != selection:
                raise ValidationError(_("La solicitud ya existe con otro alcance. Abre un formulario nuevo."))
            if (previous.style_template_id, previous.format, previous.export_mode, original_root, previous.notify_by_email) != (style_template.pk, export_format, export_mode, root_node.pk if root_node else None, notify_by_email):
                raise ValidationError(_("La solicitud ya existe con otra selección. Abre un formulario nuevo."))
            return previous
        style = get_object_or_404(StyleTemplate.objects.select_for_update().filter(Q(is_system=True) | Q(user=user)), pk=style_template.pk)
        if root_node is not None:
            root_node = get_object_or_404(ManuscriptNode, pk=root_node.pk, project=project)
        job = ExportJob(user=user, project=project, style_template=style, root_node=root_node,
                        format=export_format, export_mode=export_mode, scope_kind=scope_kind, request_key=key, notify_by_email=notify_by_email)
        job.full_clean()
        creator = user.display_alias or user.name or user.email
        manifest = (build_world_manifest(project, style, selection=selection, creator=creator) if selection is not None else
                    build_manifest(project, style, root_node=root_node, mode=export_mode, creator=creator))
        if expected_counts is not None and expected_counts != (manifest["included_scene_count"], manifest["excluded_scene_count"]):
            raise ValidationError(_("La selección cambió. Revisa nuevamente el conteo antes de confirmar."))
        manifest.update(user_id=user.pk, format=export_format)
        checksum, size = manifest_digest(manifest)
        try:
            with transaction.atomic():
                job.save()
        except IntegrityError:
            raise ValidationError(_("La clave de solicitud ya fue utilizada. Abre un formulario nuevo.")) from None
        snapshot = ExportSnapshot(export_job=job, manifest_json=manifest, checksum=checksum, size_bytes=size,
                                  included_scene_count=manifest["included_scene_count"], excluded_scene_count=manifest["excluded_scene_count"],
                                  included_entity_count=manifest.get("included_entity_count", 0), style_name=style.name, scope_title=manifest["title"][:220])
        snapshot.full_clean()
        models.Model.save(snapshot, force_insert=True)
        transaction.on_commit(lambda: enqueue_export(job.pk), robust=True)
        return job


def retry_export(job, *, user):
    with transaction.atomic():
        get_user_project(user, job.project_id, Action.EXPORT, for_update=True)
        current = get_object_or_404(ExportJob.objects.select_for_update(), pk=job.pk, user=user)
        if not ExportSnapshot.objects.filter(export_job=current).exists():
            raise ValidationError(_("Un trabajo histórico sin snapshot no se regenera. Solicita una nueva exportación."))
        if current.status == "REQUESTED" and not current.enqueued_at and not current.deletion_requested_at:
            current.next_attempt_at = None
            current.save(update_fields=["next_attempt_at"])
        else:
            try:
                prepare_retry(current)
            except (OSError, ValueError, SuspiciousFileOperation):
                raise ValidationError(_("La limpieza de archivos parciales sigue pendiente. Intenta más tarde.")) from None
        transaction.on_commit(lambda: enqueue_export(current.pk), robust=True)
        return current
