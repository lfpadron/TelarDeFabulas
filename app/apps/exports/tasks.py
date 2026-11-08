import logging
from threading import Event, Thread

from django.db import OperationalError, connections
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import override

from config.celery import app
from apps.core.permissions import Action, get_user_project, local_project_relations

from .docx import build_export_docx
from .epub import build_export_epub
from .markdown import build_export_markdown
from .models import ExportJob, ExportNotification
from .pdf import build_export_pdf
from .services import build_export_html
from .snapshots import get_export_document
from .lifecycle import claim_export, delete_export, fail_export, heartbeat, lease_duration, publish_export, recover_job
from .notifications import MAX_DELIVERY_ATTEMPTS, send_notification

logger = logging.getLogger(__name__)


class Heartbeat:
    def __init__(self, job):
        self.job_id, self.token = job.pk, job.execution_token
        self.stop = Event()
        self.thread = Thread(target=self.run, daemon=True, name="export-heartbeat")

    def run(self):
        try:
            while not self.stop.wait(min(30, max(0.1, lease_duration().total_seconds() / 3))):
                try:
                    if not heartbeat(self.job_id, self.token):
                        break
                except OperationalError:
                    logger.warning("Export heartbeat unavailable: job=%s", self.job_id)
                    break
        finally:
            connections.close_all()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=5)


@app.task(name="apps.exports.generate_export_job", acks_late=True, ignore_result=True)
def generate_export_job(export_job_id):
    job = claim_export(export_job_id)
    if job is None:
        return
    token = job.execution_token
    try:
        with Heartbeat(job):
            get_user_project(job.user, job.project_id, Action.EXPORT)
            if not local_project_relations(ExportJob.objects.filter(pk=job.pk)).exists():
                raise PermissionError("Invalid export relations.")
            document = get_export_document(job)
            builders = {"MARKDOWN": build_export_markdown, "HTML": build_export_html, "DOCX": build_export_docx,
                        "PDF": build_export_pdf, "EPUB": build_export_epub}
            with override(document.locale):
                content = builders[job.format](job, document=document)
            if isinstance(content, str):
                content = content.encode("utf-8")
            publish_export(job.pk, token, content)
    except Exception as exc:
        transient = isinstance(exc, (OSError, OperationalError, TimeoutError)) and not isinstance(exc, PermissionError)
        logger.warning("Export attempt failed: job=%s attempt=%s type=%s", job.pk, job.attempt_count, type(exc).__name__)
        try:
            fail_export(job.pk, token, retryable=transient, code="transient_error" if transient else "permanent_error")
        except OperationalError:
            logger.warning("Export failure persistence unavailable: job=%s", job.pk)


@app.task(name="apps.exports.recover_exports", ignore_result=True)
def recover_exports():
    now = timezone.now()
    eligible = ExportJob.objects.filter(
        Q(status="REQUESTED", next_attempt_at__isnull=True) | Q(status="REQUESTED", next_attempt_at__lte=now)
        | Q(status="PROCESSING", lease_expires_at__lte=now) | Q(status="PROCESSING", lease_expires_at__isnull=True)
        | Q(status="FAILED", next_attempt_at__lte=now) | Q(deletion_requested_at__isnull=False)
    ).exclude(status="DELETED").order_by("pk").values_list("pk", "deletion_requested_at")
    for job_id, deletion in eligible.iterator(chunk_size=200):
        if deletion:
            delete_export(job_id)
        else:
            recover_job(job_id)


@app.task(name="apps.exports.cleanup_expired_exports", ignore_result=True)
def cleanup_expired_exports():
    jobs = ExportJob.objects.filter(status__in=["READY", "FAILED"], expires_at__lte=timezone.now()).order_by("expires_at").values_list("pk", flat=True)
    for job_id in jobs.iterator(chunk_size=200):
        delete_export(job_id, expired=True)


@app.task(name="apps.exports.send_pending_notifications", ignore_result=True)
def send_pending_notifications():
    now = timezone.now()
    notices = ExportNotification.objects.filter(sent_at__isnull=True, attempts__lt=MAX_DELIVERY_ATTEMPTS,
        job__deletion_requested_at__isnull=True, job__status__in=["READY", "FAILED"],
        event=F("job__status"), attempt_number=F("job__attempt_count"), job__notify_by_email=True,
        job__user__is_active=True, job__user_id=F("job__project__user_id"),
        job__project__status__in=["ACTIVE", "FROZEN", "PENDING_DELETION"]).filter(
            Q(job__expires_at__isnull=True) | Q(job__expires_at__gt=now)).filter(
            Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)).filter(
            Q(lease_expires_at__isnull=True) | Q(lease_expires_at__lte=now)).order_by("pk").values_list("pk", flat=True)[:100]
    for notice_id in list(notices):
        send_notification(notice_id)
