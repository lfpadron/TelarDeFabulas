from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.manuscripts.models import ManuscriptNode
from apps.projects.models import Project
from apps.styles.models import StyleTemplate


def export_upload_path(instance, filename):
    return f"exports/{instance.user_id}/{instance.project_id}/{filename}"


class ExportJob(models.Model):
    class ExportFormat(models.TextChoices):
        HTML = "HTML", _("HTML")
        DOCX = "DOCX", _("DOCX")
        PDF = "PDF", _("PDF")
        EPUB = "EPUB", _("EPUB")

    class ExportStatus(models.TextChoices):
        PENDING = "PENDING", _("Pendiente")
        PROCESSING = "PROCESSING", _("Procesando")
        DONE = "DONE", _("Terminada")
        FAILED = "FAILED", _("Fallida")

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
        default=ExportStatus.PENDING,
    )
    file = models.FileField(_("archivo"), upload_to=export_upload_path, blank=True)
    error_message = models.TextField(_("mensaje de error"), blank=True)
    created_at = models.DateTimeField(_("creado"), auto_now_add=True)
    started_at = models.DateTimeField(_("iniciado"), null=True, blank=True)
    finished_at = models.DateTimeField(_("finalizado"), null=True, blank=True)

    class Meta:
        verbose_name = _("trabajo de exportación")
        verbose_name_plural = _("trabajos de exportación")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "project", "-created_at"]),
            models.Index(fields=["status", "format"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.project} - {self.format} - {self.get_status_display()}"

    def clean(self):
        super().clean()
        errors = {}

        if self.project_id and self.user_id and self.project.user_id != self.user_id:
            errors["project"] = _("Solo puedes exportar proyectos propios.")

        if self.project_id and self.project.status == Project.ProjectStatus.DELETED:
            errors["project"] = _("No se puede exportar un proyecto eliminado.")

        if self.project_id and self.project.status == Project.ProjectStatus.PENDING_DELETION:
            errors["project"] = _("No se puede exportar un proyecto pendiente de borrado.")

        if self.root_node_id and self.project_id and self.root_node.project_id != self.project_id:
            errors["root_node"] = _("El nodo raíz debe pertenecer al mismo proyecto.")

        if self.style_template_id and self.user_id:
            style_is_visible = self.style_template.is_system or self.style_template.user_id == self.user_id
            if not style_is_visible:
                errors["style_template"] = _("La plantilla de estilo debe ser del sistema o propia.")

        if errors:
            raise ValidationError(errors)
