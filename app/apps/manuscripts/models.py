import re

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Max
from django.utils.translation import gettext_lazy as _

from apps.projects.models import Project


WORD_RE = re.compile(r"\b[\wáéíóúÁÉÍÓÚñÑüÜ]+(?:[-'][\wáéíóúÁÉÍÓÚñÑüÜ]+)?\b", re.UNICODE)


def count_words(text):
    if not text:
        return 0
    return len(WORD_RE.findall(text))


class ManuscriptNode(models.Model):
    class NodeType(models.TextChoices):
        BOOK = "BOOK", _("Libro")
        PART = "PART", _("Parte")
        CHAPTER = "CHAPTER", _("Capítulo")
        SCENE = "SCENE", _("Escena")
        FRAGMENT = "FRAGMENT", _("Fragmento")

    class NodeStatus(models.TextChoices):
        PENDING = "PENDING", _("Pendiente")
        IN_PROGRESS = "IN_PROGRESS", _("En progreso")
        DRAFT = "DRAFT", _("Borrador")
        REVIEW = "REVIEW", _("Revisión")
        FINISHED = "FINISHED", _("Terminado")
        PUBLISHABLE = "PUBLISHABLE", _("Publicable")
        PUBLISHED = "PUBLISHED", _("Publicado")

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="manuscript_nodes",
        verbose_name=_("proyecto"),
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="children",
        null=True,
        blank=True,
        verbose_name=_("padre"),
    )
    node_type = models.CharField(
        _("tipo de nodo"),
        max_length=20,
        choices=NodeType.choices,
        default=NodeType.BOOK,
    )
    title = models.CharField(_("título"), max_length=220)
    content = models.TextField(_("contenido"), blank=True)
    status = models.CharField(
        _("estado"),
        max_length=20,
        choices=NodeStatus.choices,
        default=NodeStatus.PENDING,
    )
    position = models.PositiveIntegerField(_("posición"), null=True, blank=True)
    is_publishable = models.BooleanField(_("es publicable"), default=False)
    word_count = models.PositiveIntegerField(_("conteo de palabras"), default=0, editable=False)
    created_at = models.DateTimeField(_("creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado"), auto_now=True)

    class Meta:
        verbose_name = _("nodo de manuscrito")
        verbose_name_plural = _("nodos de manuscrito")
        ordering = ["project", "parent_id", "position", "created_at"]
        indexes = [
            models.Index(fields=["project", "parent", "position"]),
            models.Index(fields=["project", "node_type"]),
            models.Index(fields=["project", "status"]),
        ]

    def __str__(self):
        return self.title

    def descendant_ids(self):
        if not self.pk:
            return set()

        seen = set()
        pending = [self.pk]
        while pending:
            child_ids = list(
                self.__class__.objects.filter(parent_id__in=pending)
                .exclude(pk__in=seen)
                .values_list("pk", flat=True)
            )
            seen.update(child_ids)
            pending = child_ids
        return seen

    def clean(self):
        super().clean()
        project = self.project if self.project_id else None
        if project and project.status in (
            Project.ProjectStatus.DELETED,
            Project.ProjectStatus.PENDING_DELETION,
        ):
            raise ValidationError(_("No se pueden crear o editar nodos en proyectos eliminados o pendientes de borrado."))
        if self.parent_id and self.pk and self.parent_id == self.pk:
            raise ValidationError({"parent": _("Un nodo no puede ser su propio padre.")})
        if self.parent_id and self.parent_id in self.descendant_ids():
            raise ValidationError({"parent": _("Un nodo no puede tener como padre a uno de sus descendientes.")})
        if self.parent and self.parent.project_id != self.project_id:
            raise ValidationError({"parent": _("El nodo padre debe pertenecer al mismo proyecto.")})
        if self.position is not None and self.position < 1:
            raise ValidationError({"position": _("La posición debe ser un entero positivo.")})

    @classmethod
    def siblings(cls, project, parent):
        return cls.objects.filter(project=project, parent=parent)

    @classmethod
    def next_position(cls, project, parent):
        last_position = cls.siblings(project, parent).aggregate(max_position=Max("position"))["max_position"]
        return (last_position or 0) + 1

    def assign_next_position(self):
        self.position = self.next_position(self.project, self.parent)

    def save(self, *args, **kwargs):
        if not self.position:
            self.assign_next_position()
        self.word_count = count_words(self.content)
        self.full_clean()
        return super().save(*args, **kwargs)

    def can_delete_safely(self):
        return not self.children.exists()
