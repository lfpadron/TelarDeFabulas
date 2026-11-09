from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import validate_project_action


class WorldbuildingEntry(models.Model):
    class Category(models.TextChoices):
        POLITICS = "POLITICS", _("Política")
        RELIGION = "RELIGION", _("Religión")
        HISTORY = "HISTORY", _("Historia")

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE,
                               related_name="worldbuilding_entries", verbose_name=_("Proyecto"))
    category = models.CharField(_("Categoría"), max_length=12, choices=Category.choices)
    title = models.CharField(_("Título"), max_length=180)
    short_description = models.CharField(_("Descripción breve"), max_length=300, blank=True)
    content = models.TextField(_("Contenido"), blank=True)
    position = models.PositiveIntegerField(_("Posición"), blank=True)
    revision = models.PositiveBigIntegerField(_("Revisión"), default=1, editable=False)
    created_at = models.DateTimeField(_("Creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Actualizado"), auto_now=True)

    class Meta:
        ordering = ["category", "position", "pk"]
        verbose_name = _("entrada de construcción de mundos")
        verbose_name_plural = _("entradas de construcción de mundos")
        constraints = [
            # This unique index also serves ordered project/category queries.
            models.UniqueConstraint(fields=["project", "category", "position"], name="wb_project_category_position"),
            models.CheckConstraint(condition=models.Q(category__in=["POLITICS", "RELIGION", "HISTORY"]), name="wb_category_valid"),
            models.CheckConstraint(condition=models.Q(title__regex=r"\S"), name="wb_title_required"),
            models.CheckConstraint(condition=models.Q(position__gte=0), name="wb_position_nonnegative"),
            models.CheckConstraint(condition=models.Q(revision__gte=1), name="wb_revision_positive"),
        ]

    def __str__(self):
        return self.title

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_revision = instance.__dict__.get("revision")
        return instance

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        if kwargs.get("fields") is None or "revision" in kwargs["fields"]:
            self._loaded_revision = self.__dict__.get("revision")

    def clean(self):
        super().clean()
        if not self.title or not self.title.strip():
            raise ValidationError({"title": _("El título no puede estar vacío ni contener solo espacios.")})
        if self.project_id:
            validate_project_action(self.project)
            if self.pk and type(self).objects.using(self._state.db).filter(pk=self.pk).exclude(project_id=self.project_id).exists():
                raise ValidationError(_("No se permite trasladar entradas a otro proyecto."))

    def save(self, *args, **kwargs):
        from .services import save_entry

        return save_entry(self, *args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        from .services import delete_entry

        return delete_entry(self, using=using, keep_parents=keep_parents)
