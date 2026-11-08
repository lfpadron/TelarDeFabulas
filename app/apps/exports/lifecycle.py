import logging
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import Action, get_user_project, local_project_relations
from apps.projects.models import Project

from .files import publish_bytes, remove_artifacts, try_cleanup_lock
from .models import ExportAttempt, ExportEvent, ExportJob, ExportNotification, ExportSnapshot

logger = logging.getLogger(__name__)
TRANSITIONS = {
    "REQUESTED": {"PROCESSING", "DELETED"},
    "PROCESSING": {"READY", "FAILED"},
    "FAILED": {"REQUESTED", "DELETED"},
    "READY": {"DELETED"},
    "DELETED": set(),
}


def backoff(attempt):
    return timedelta(seconds=min(3600, settings.EXPORT_RETRY_BASE_SECONDS * 2 ** min(max(attempt - 1, 0), 10)))


def lease_duration():
    return timedelta(minutes=settings.EXPORT_STALE_MINUTES)


@contextmanager
def locked_job(job_id):
    with transaction.atomic():
        identity = ExportJob.objects.filter(pk=job_id).values("project_id").first()
        if identity is None:
            yield None
            return
        Project.objects.select_for_update().get(pk=identity["project_id"])
        yield ExportJob.objects.select_for_update().get(pk=job_id)


def transition(job, destination, code):
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("Export transitions require a locked transaction.")
    if destination not in TRANSITIONS.get(job.status, set()):
        raise ValidationError(_("La transición de estado no está permitida."))
    ExportEvent.objects.create(job=job, from_status=job.status, to_status=destination,
                               attempt_number=job.attempt_count, code=code)
    job.status = destination


def queue_notification(job):
    if job.notify_by_email and not job.deletion_requested_at:
        ExportNotification.objects.get_or_create(job=job, event=job.status, attempt_number=job.attempt_count)


def valid_claim(job, token):
    return bool(job and job.status == "PROCESSING" and job.execution_token == token
                and job.lease_expires_at and job.lease_expires_at > timezone.now()
                and not job.deletion_requested_at)


def claim_export(job_id):
    with locked_job(job_id) as job:
        if not job or job.status != "REQUESTED" or job.deletion_requested_at:
            return None
        if job.attempt_count >= job.max_attempts:
            # An inconsistent/historical REQUESTED row must not disappear silently.
            transition(job, "PROCESSING", "exhausted_claim")
            _fail(job, retryable=False, code="attempt_limit")
            return None
        try:
            remove_artifacts(job)
        except (OSError, ValueError, SuspiciousFileOperation):
            job.cleanup_error = _("No se pudieron limpiar los archivos parciales. Se reintentará la limpieza.")
            job.next_attempt_at = timezone.now() + backoff(job.attempt_count + 1)
            job.save()
            return None
        job.attempt_count += 1
        job.execution_token = uuid4()
        job.started_at = job.last_heartbeat_at = timezone.now()
        job.lease_expires_at = timezone.now() + lease_duration()
        job.finished_at = job.expires_at = job.next_attempt_at = None
        job.error_message = job.cleanup_error = ""
        job.retryable = False
        transition(job, "PROCESSING", "claimed")
        job.save()
        ExportAttempt.objects.create(token=job.execution_token, job=job, number=job.attempt_count)
        return job


def heartbeat(job_id, token):
    now = timezone.now()
    return ExportJob.objects.filter(pk=job_id, status="PROCESSING", execution_token=token,
                                    lease_expires_at__gt=now, deletion_requested_at__isnull=True).update(
        last_heartbeat_at=now, lease_expires_at=now + lease_duration()) == 1


def _fail(job, *, retryable, code):
    now = timezone.now()
    transition(job, "FAILED", code)
    job.finished_at = now
    job.expires_at = now + timedelta(days=settings.EXPORT_FAILED_RETENTION_DAYS)
    job.retryable = retryable
    job.next_attempt_at = now + backoff(job.attempt_count) if retryable and job.attempt_count < job.max_attempts else None
    job.error_message = (_("No se pudo completar este intento. Se reintentará automáticamente.") if job.next_attempt_at
                         else _("No pudimos completar la exportación. Solicita una nueva exportación o consulta al administrador."))
    if job.execution_token:
        job.attempts.filter(token=job.execution_token).update(finished_at=now, outcome=code)
    job.execution_token = job.lease_expires_at = None
    job.save()
    if not job.next_attempt_at:
        queue_notification(job)


def fail_export(job_id, token, *, retryable, code):
    with locked_job(job_id) as job:
        if not valid_claim(job, token):
            return False
        try:
            remove_artifacts(job)
        except (OSError, ValueError, SuspiciousFileOperation):
            job.cleanup_error = _("La limpieza de archivos parciales está pendiente.")
        _fail(job, retryable=retryable, code=code)
        return True


def publish_export(job_id, token, content):
    with locked_job(job_id) as job:
        if not valid_claim(job, token):
            return False
        get_user_project(job.user, job.project_id, Action.EXPORT, for_update=True)
        if not local_project_relations(ExportJob.objects.filter(pk=job.pk)).exists():
            raise PermissionError("Invalid export relations.")
        # File writes and fencing share the row lock; an expired worker cannot create a late orphan.
        job.file = publish_bytes(job, token, content)
        transition(job, "READY", "published")
        job.finished_at = timezone.now()
        job.expires_at = job.finished_at + timedelta(days=settings.EXPORT_READY_RETENTION_DAYS)
        job.execution_token = job.lease_expires_at = job.next_attempt_at = None
        job.error_message = ""
        job.save()
        job.attempts.filter(token=token).update(finished_at=job.finished_at, outcome="published")
        queue_notification(job)
        return True


def prepare_retry(job):
    if not job.can_retry or not ExportSnapshot.objects.filter(export_job=job).exists():
        raise ValidationError(_("Esta exportación no admite más reintentos. Solicita una nueva exportación."))
    remove_artifacts(job)
    transition(job, "REQUESTED", "retry_requested")
    job.enqueued_at = job.next_attempt_at = job.finished_at = job.expires_at = None
    job.error_message = job.cleanup_error = ""
    job.file = ""
    job.save()


def recover_job(job_id):
    from .job_services import enqueue_export

    with locked_job(job_id) as job:
        if not job or job.deletion_requested_at:
            return
        now = timezone.now()
        if job.status == "PROCESSING" and (job.lease_expires_at is None or job.lease_expires_at <= now):
            _fail(job, retryable=True, code="lease_expired")
        if job.status == "FAILED" and job.can_retry and job.next_attempt_at and job.next_attempt_at <= now:
            try:
                prepare_retry(job)
            except (OSError, ValueError, SuspiciousFileOperation):
                job.cleanup_error = _("La limpieza de archivos parciales está pendiente.")
                job.next_attempt_at = now + backoff(job.attempt_count)
                job.save()
        if job.status == "REQUESTED" and (job.next_attempt_at is None or job.next_attempt_at <= now):
            transaction.on_commit(lambda: enqueue_export(job.pk), robust=True)


def delete_export(job_id, *, user=None, expired=False):
    with locked_job(job_id) as job:
        if job is None:
            return False
        if user is not None:
            get_user_project(user, job.project_id, Action.EXPORT, for_update=True)
            if job.user_id != user.pk:
                from django.http import Http404
                raise Http404
        if job.status == "DELETED":
            return True
        if not job.can_delete:
            raise ValidationError(_("No se puede borrar una exportación en proceso."))
        if expired and (job.status not in ("READY", "FAILED") or not job.expires_at or job.expires_at > timezone.now()):
            return False
        job.deletion_requested_at = job.deletion_requested_at or timezone.now()
        job.next_attempt_at = None
        job.save()
    # Commit the tombstone before filesystem operations, which cannot roll back.
    return finish_deletion(job_id, expired=expired)


def finish_deletion(job_id, *, expired=False):
    with locked_job(job_id) as job:
        if job is None or job.status == "DELETED":
            return True
        if not job.deletion_requested_at or not job.can_delete:
            return False
        if not try_cleanup_lock(job.pk):
            return False
        try:
            if job.project.user_id != job.user_id:
                raise ValueError("Invalid export owner.")
            remove_artifacts(job)
        except (OSError, ValueError, SuspiciousFileOperation):
            job.cleanup_error = _("No se pudo completar el borrado. Se reintentará automáticamente.")
            job.save(update_fields=["cleanup_error"])
            logger.warning("Export cleanup pending: job=%s", job.pk)
            return False
        ExportSnapshot.objects.filter(export_job=job).delete()
        transition(job, "DELETED", "expired" if expired else "deleted")
        job.deleted_at = timezone.now()
        job.file = job.error_message = job.cleanup_error = ""
        job.execution_token = job.lease_expires_at = None
        job.save()
        return True
