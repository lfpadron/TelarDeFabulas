from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.characters.models import Character
from apps.manuscripts.models import ManuscriptNode
from apps.projects.models import Project


class Note(models.Model):
    class NoteType(models.TextChoices):
        NOTE = "NOTE", _("Nota")
        IDEA = "IDEA", _("Idea")
        TASK = "TASK", _("Pendiente")

    class NoteStatus(models.TextChoices):
        OPEN = "OPEN", _("Abierta")
        IN_PROGRESS = "IN_PROGRESS", _("En progreso")
        DONE = "DONE", _("Terminada")
        DISCARDED = "DISCARDED", _("Descartada")

    class Priority(models.TextChoices):
        LOW = "LOW", _("Baja")
        MEDIUM = "MEDIUM", _("Media")
        HIGH = "HIGH", _("Alta")
        URGENT = "URGENT", _("Urgente")

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="notes",
        verbose_name=_("proyecto"),
    )
    node = models.ForeignKey(
        ManuscriptNode,
        on_delete=models.SET_NULL,
        related_name="notes",
        null=True,
        blank=True,
        verbose_name=_("nodo de manuscrito"),
    )
    character = models.ForeignKey(
        Character,
        on_delete=models.SET_NULL,
        related_name="work_notes",
        null=True,
        blank=True,
        verbose_name=_("personaje"),
    )
    note_type = models.CharField(
        _("tipo"),
        max_length=10,
        choices=NoteType.choices,
        default=NoteType.NOTE,
    )
    title = models.CharField(_("título"), max_length=220)
    content = models.TextField(_("contenido"), blank=True)
    status = models.CharField(
        _("estado"),
        max_length=20,
        choices=NoteStatus.choices,
        default=NoteStatus.OPEN,
    )
    priority = models.CharField(
        _("prioridad"),
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    created_at = models.DateTimeField(_("creada"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizada"), auto_now=True)
    completed_at = models.DateTimeField(_("terminada"), null=True, blank=True)

    class Meta:
        verbose_name = _("nota")
        verbose_name_plural = _("notas")
        ordering = ["project", "-updated_at", "title"]
        indexes = [
            models.Index(fields=["project", "note_type"]),
            models.Index(fields=["project", "status"]),
            models.Index(fields=["project", "priority"]),
            models.Index(fields=["project", "-updated_at"]),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if self.project_id and self.project.status in (
            Project.ProjectStatus.DELETED,
            Project.ProjectStatus.PENDING_DELETION,
        ):
            raise ValidationError(_("No se pueden crear o editar notas en proyectos eliminados o pendientes de borrado."))
        if self.node_id and self.node.project_id != self.project_id:
            raise ValidationError({"node": _("El nodo debe pertenecer al mismo proyecto que la nota.")})
        if self.character_id and self.character.project_id != self.project_id:
            raise ValidationError({"character": _("El personaje debe pertenecer al mismo proyecto que la nota.")})

    def sync_completed_at(self):
        if self.status == self.NoteStatus.DONE and self.completed_at is None:
            self.completed_at = timezone.now()
        if self.status != self.NoteStatus.DONE:
            self.completed_at = None

    def save(self, *args, **kwargs):
        self.sync_completed_at()
        self.full_clean()
        return super().save(*args, **kwargs)
