from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.manuscripts.models import ManuscriptNode
from apps.projects.models import Project
from apps.styles.models import StyleTemplate
from apps.core.permissions import Action, project_allows_action


def export_upload_path(instance, filename):
    return f"exports/{instance.user_id}/{instance.project_id}/{filename}"


def default_max_attempts():
    return settings.EXPORT_MAX_ATTEMPTS


class ExportJob(models.Model):
    class ExportMode(models.TextChoices):
        WORK = "WORK", _("Exportación de trabajo")
        FINAL = "FINAL", _("Exportación definitiva")

    class ExportFormat(models.TextChoices):
        MARKDOWN = "MARKDOWN", _("Markdown")
        HTML = "HTML", _("HTML")
        DOCX = "DOCX", _("DOCX")
        PDF = "PDF", _("PDF")
        EPUB = "EPUB", _("EPUB")

    class ExportStatus(models.TextChoices):
        REQUESTED = "REQUESTED", _("Solicitada")
        PROCESSING = "PROCESSING", _("En proceso")
        READY = "READY", _("Lista para descargar")
        FAILED = "FAILED", _("Fallida")
        DELETED = "DELETED", _("Borrada")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="export_jobs",
        verbose_name=_("usuario"),
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="export_jobs",
        verbose_name=_("proyecto"),
    )
    root_node = models.ForeignKey(
        ManuscriptNode,
        on_delete=models.SET_NULL,
        related_name="export_jobs",
        null=True,
        blank=True,
        verbose_name=_("nodo raíz"),
    )
    style_template = models.ForeignKey(
        StyleTemplate,
        on_delete=models.PROTECT,
        related_name="export_jobs",
        verbose_name=_("plantilla de estilo"),
    )
    format = models.CharField(
        _("formato"),
        max_length=10,
        choices=ExportFormat.choices,
        default=ExportFormat.HTML,
    )
    status = models.CharField(
        _("estado"),
        max_length=20,
        choices=ExportStatus.choices,
        default=ExportStatus.REQUESTED,
    )
    file = models.FileField(_("archivo"), upload_to=export_upload_path, max_length=255, blank=True)
    export_mode = models.CharField(_("modalidad"), max_length=10, choices=ExportMode.choices, default=ExportMode.WORK)
    request_key = models.UUIDField(_("clave de solicitud"), null=True, blank=True, unique=True, editable=False)
    enqueued_at = models.DateTimeField(_("enviado a la cola"), null=True, blank=True, editable=False)
    error_message = models.TextField(_("mensaje de error"), blank=True)
    created_at = models.DateTimeField(_("creado"), auto_now_add=True)
    started_at = models.DateTimeField(_("iniciado"), null=True, blank=True)
    finished_at = models.DateTimeField(_("finalizado"), null=True, blank=True)
    notify_by_email = models.BooleanField(_("Notificarme por correo cuando termine"), default=True)
    attempt_count = models.PositiveIntegerField(_("intentos"), default=0, editable=False)
    max_attempts = models.PositiveIntegerField(_("máximo de intentos"), default=default_max_attempts, editable=False)
    execution_token = models.UUIDField(null=True, editable=False)
    last_heartbeat_at = models.DateTimeField(null=True, editable=False)
    lease_expires_at = models.DateTimeField(null=True, editable=False)
    next_attempt_at = models.DateTimeField(null=True, editable=False)
    retryable = models.BooleanField(default=False, editable=False)
    dispatch_count = models.PositiveIntegerField(default=0, editable=False)
    expires_at = models.DateTimeField(_("caduca"), null=True, editable=False)
    deleted_at = models.DateTimeField(_("borrada"), null=True, editable=False)
    deletion_requested_at = models.DateTimeField(null=True, editable=False)
    cleanup_error = models.CharField(max_length=240, blank=True, editable=False)
    notification_sent_at = models.DateTimeField(_("correo enviado"), null=True, editable=False)

    class Meta:
        verbose_name = _("trabajo de exportación")
        verbose_name_plural = _("trabajos de exportación")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "project", "-created_at"]),
            models.Index(fields=["status", "format"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["status", "next_attempt_at"], name="export_recovery_idx"),
            models.Index(fields=["status", "expires_at"], name="export_expiry_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=["REQUESTED", "PROCESSING", "FAILED", "READY", "DELETED"]), name="export_valid_status"),
            models.CheckConstraint(condition=models.Q(max_attempts__gte=1, max_attempts__lte=10), name="export_attempt_limit"),
        ]

    @property
    def downloadable(self):
        return bool(self.status == "READY" and self.file and not self.deletion_requested_at
                    and (self.expires_at is None or self.expires_at > timezone.now()))

    @property
    def can_delete(self):
        return self.status in ("READY", "FAILED", "REQUESTED")

    @property
    def can_retry(self):
        return (self.status == "FAILED" and self.retryable and self.attempt_count < self.max_attempts
                and not self.deletion_requested_at and (self.expires_at is None or self.expires_at > timezone.now()))

    def __str__(self):
        return f"{self.project} - {self.format} - {self.get_status_display()}"

    def clean(self):
        super().clean()
        errors = {}

        if self.project_id and self.user_id and self.project.user_id != self.user_id:
            errors["project"] = _("Solo puedes exportar proyectos propios.")

        if self.project_id and not project_allows_action(self.project, Action.EXPORT):
            errors["project"] = _("No se puede exportar un proyecto eliminado.")

        if self.root_node_id and self.project_id and self.root_node.project_id != self.project_id:
            errors["root_node"] = _("El nodo raíz debe pertenecer al mismo proyecto.")

        if self.style_template_id and self.user_id:
            style_is_visible = self.style_template.is_system or self.style_template.user_id == self.user_id
            if not style_is_visible:
                errors["style_template"] = _("La plantilla de estilo debe ser del sistema o propia.")

        if errors:
            raise ValidationError(errors)


class ExportSnapshot(models.Model):
    export_job = models.OneToOneField(ExportJob, on_delete=models.CASCADE, related_name="snapshot", verbose_name=_("exportación"))
    created_at = models.DateTimeField(_("capturado"), auto_now_add=True)
    manifest_json = models.JSONField(_("manifiesto privado"))
    checksum = models.CharField(_("SHA-256"), max_length=64, editable=False)
    size_bytes = models.PositiveIntegerField(_("bytes"), editable=False)
    included_scene_count = models.PositiveIntegerField(_("escenas incluidas"), editable=False)
    excluded_scene_count = models.PositiveIntegerField(_("escenas excluidas"), editable=False)
    style_name = models.CharField(_("estilo capturado"), max_length=180, editable=False)
    scope_title = models.CharField(_("título capturado"), max_length=220, editable=False)

    class Meta:
        verbose_name = _("snapshot de exportación")
        verbose_name_plural = _("snapshots de exportación")

    def __str__(self):
        return _("Snapshot de exportación %(id)s") % {"id": self.export_job_id}

    def save(self, *args, **kwargs):
        raise ValidationError(_("El snapshot es inmutable y se crea al solicitar la exportación."))

    def delete(self, *args, **kwargs):
        raise ValidationError(_("El snapshot no se elimina de forma independiente."))


class ExportAttempt(models.Model):
    token = models.UUIDField(primary_key=True, editable=False)
    job = models.ForeignKey(ExportJob, on_delete=models.CASCADE, related_name="attempts")
    number = models.PositiveIntegerField()
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True)
    outcome = models.CharField(max_length=24, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["job", "number"], name="export_unique_attempt")]


class ExportEvent(models.Model):
    job = models.ForeignKey(ExportJob, on_delete=models.CASCADE, related_name="events")
    created_at = models.DateTimeField(auto_now_add=True)
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    attempt_number = models.PositiveIntegerField()
    code = models.CharField(max_length=40)

    class Meta:
        ordering = ["created_at", "pk"]


class ExportNotification(models.Model):
    job = models.ForeignKey(ExportJob, on_delete=models.CASCADE, related_name="notifications")
    event = models.CharField(max_length=20, choices=[("READY", _("Lista para descargar")), ("FAILED", _("Fallida"))])
    attempt_number = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True)
    claim_token = models.UUIDField(null=True)
    lease_expires_at = models.DateTimeField(null=True)
    last_error = models.CharField(max_length=80, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["job", "event", "attempt_number"], name="export_unique_notification")]
