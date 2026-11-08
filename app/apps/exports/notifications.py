import logging
from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _, override

from .lifecycle import backoff
from .models import ExportNotification, ExportJob

logger = logging.getLogger(__name__)
MAX_DELIVERY_ATTEMPTS = 8

# Explicit locales keep transactional mail localized before the UI has full catalogs.
MESSAGES = {
    "es-mx": {
        "READY": (_("Tu exportación de Telar de Fábulas está lista"),
                  _("Tu exportación ha terminado correctamente.\n\nPuedes descargarla desde tu cuenta de Telar de Fábulas.\n\nEl archivo estará disponible hasta: %(date)s.\n\n%(url)s")),
        "FAILED": (_("No pudimos completar tu exportación"),
                   _("La exportación solicitada no pudo completarse.\n\nPuedes consultar el estado desde tu cuenta de Telar de Fábulas.\n\n%(url)s")),
    },
    "en-us": {
        "READY": (_("Your Telar de Fábulas export is ready"),
                  _("Your export completed successfully.\n\nDownload it from your Telar de Fábulas account.\n\nThe file is available until: %(date)s.\n\n%(url)s")),
        "FAILED": (_("We could not complete your export"),
                   _("The requested export could not be completed.\n\nCheck its status in your Telar de Fábulas account.\n\n%(url)s")),
    },
}


def send_notification(notification_id):
    now = timezone.now()
    with transaction.atomic():
        notice = ExportNotification.objects.select_for_update().filter(pk=notification_id).first()
        if (not notice or notice.sent_at or notice.attempts >= MAX_DELIVERY_ATTEMPTS
                or (notice.next_attempt_at and notice.next_attempt_at > now)
                or (notice.lease_expires_at and notice.lease_expires_at > now)):
            return False
        job = ExportJob.objects.select_related("user", "project").get(pk=notice.job_id)
        if (not job.notify_by_email or job.deletion_requested_at or job.status != notice.event
                or job.attempt_count != notice.attempt_number or job.user_id != job.project.user_id
                or not job.user.is_active or job.project.status == "DELETED"
                or (job.expires_at and job.expires_at <= now)):
            return False
        token = uuid4()
        notice.claim_token = token
        notice.lease_expires_at = now + timedelta(minutes=5)
        notice.attempts += 1
        notice.save()
    locale = job.user.preferred_locale if job.user.preferred_locale in MESSAGES else "es-mx"
    url = settings.PUBLIC_BASE_URL + reverse("exports:detail", args=[job.project_id, job.pk])
    try:
        with override(locale):
            subject, body = MESSAGES[locale][notice.event]
            message = EmailMessage(str(subject), str(body) % {
                "url": url, "date": job.expires_at.strftime("%Y-%m-%d %H:%M UTC") if job.expires_at else "-",
            }, settings.DEFAULT_FROM_EMAIL, [job.user.email],
                headers={"Message-ID": f"<telar-export-{notice.pk}-{job.request_key}@localhost>"})
            if message.send(fail_silently=False) != 1:
                raise OSError("Mail backend did not accept message.")
    except Exception as exc:
        ExportNotification.objects.filter(pk=notice.pk, claim_token=token, sent_at__isnull=True).update(
            claim_token=None, lease_expires_at=None, next_attempt_at=timezone.now() + backoff(notice.attempts),
            last_error="delivery_failed")
        logger.warning("Export mail failed: notification=%s type=%s", notice.pk, type(exc).__name__)
        return False
    with transaction.atomic():
        updated = ExportNotification.objects.filter(pk=notice.pk, claim_token=token, sent_at__isnull=True).update(
            sent_at=timezone.now(), claim_token=None, lease_expires_at=None, next_attempt_at=None, last_error="")
        if updated:
            ExportJob.objects.filter(pk=job.pk).update(notification_sent_at=timezone.now())
    return bool(updated)
