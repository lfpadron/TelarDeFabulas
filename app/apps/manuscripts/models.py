import re

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Max
from django.utils.translation import gettext_lazy as _

from apps.projects.models import Project
from apps.core.permissions import validate_project_action

from .hierarchy import validate_node_hierarchy


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
    title = models.CharField(_("título"), max_length=220, blank=True)
    short_description = models.TextField(_("descripción breve"), blank=True, default="")
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
        return self.display_title

    @property
    def display_title(self):
        if self.title.strip():
            return self.title
        return _("%(type)s %(number)s") % {"type": self.get_node_type_display(), "number": self.position or self.pk or 1}

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_structure = {name: instance.__dict__[name] for name in
                                      ("project_id", "parent_id", "node_type", "position") if name in instance.__dict__}
        return instance

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        self._loaded_structure = {name: self.__dict__[name] for name in
                                  ("project_id", "parent_id", "node_type", "position") if name in self.__dict__}

    def descendant_ids(self):
        if not self.pk:
            return set()

        seen = set()
        pending = [self.pk]
        while pending:
            child_ids = list(
                self.__class__.objects.filter(project_id=self.project_id, parent_id__in=pending)
                .exclude(pk__in=seen)
                .values_list("pk", flat=True)
            )
            seen.update(child_ids)
            pending = child_ids
        return seen

    def clean(self):
        super().clean()
        if self.pk and not self._state.adding:
            old_project = type(self).objects.filter(pk=self.pk).values_list("project_id", flat=True).first()
            if old_project != self.project_id:
                raise ValidationError({"project": _("No se permite trasladar nodos a otro proyecto.")})
        project = self.project if self.project_id else None
        if project:
            validate_project_action(project)
        validate_node_hierarchy(self)
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
        from .services import save_node

        return save_node(self, *args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        from .services import delete_node

        return delete_node(self, using=using, keep_parents=keep_parents)

    def can_delete_safely(self):
        return not self.children.exists()
