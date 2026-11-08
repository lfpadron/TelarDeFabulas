from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import validate_project_action


class GeographicLocation(models.Model):
    class LocationType(models.TextChoices):
        UNIVERSE = "UNIVERSE", _("Universo")
        WORLD = "WORLD", _("Mundo")
        CONTINENT = "CONTINENT", _("Continente")
        EMPIRE = "EMPIRE", _("Imperio")
        KINGDOM = "KINGDOM", _("Reino")
        COUNTRY = "COUNTRY", _("País")
        PROVINCE = "PROVINCE", _("Provincia")
        CITY = "CITY", _("Ciudad")
        OTHER = "OTHER", _("Otro")

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE,
                               related_name="geographic_locations", verbose_name=_("Proyecto"))
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True,
                              related_name="children", verbose_name=_("Ubicación padre"))
    location_type = models.CharField(_("Tipo"), max_length=12, choices=LocationType.choices,
                                    default=LocationType.OTHER)
    custom_location_type = models.CharField(_("Tipo personalizado"), max_length=100, blank=True)
    name = models.CharField(_("Nombre"), max_length=180)
    short_description = models.CharField(_("Descripción breve"), max_length=300, blank=True)
    detailed_description = models.TextField(_("Desarrollo detallado"), blank=True)
    position = models.PositiveIntegerField(_("Posición"), blank=True, db_index=True)
    created_at = models.DateTimeField(_("Creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Actualizado"), auto_now=True)

    class Meta:
        verbose_name = _("ubicación geográfica")
        verbose_name_plural = _("ubicaciones geográficas")
        ordering = ["position", "pk"]
        indexes = [models.Index(fields=["project", "parent", "position"], name="geo_project_parent_order")]
        constraints = [
            models.UniqueConstraint(fields=["project", "parent", "position"],
                                    nulls_distinct=False, name="geo_sibling_position_unique"),
            models.CheckConstraint(condition=models.Q(position__gte=1), name="geo_position_positive"),
            models.CheckConstraint(condition=~models.Q(name=""), name="geo_name_required"),
            models.CheckConstraint(condition=models.Q(parent__isnull=True) | ~models.Q(parent=models.F("pk")),
                                   name="geo_not_own_parent"),
            models.CheckConstraint(condition=models.Q(location_type__in=[
                "UNIVERSE", "WORLD", "CONTINENT", "EMPIRE", "KINGDOM", "COUNTRY", "PROVINCE", "CITY", "OTHER",
            ]), name="geo_location_type_valid"),
        ]

    def __str__(self):
        return self.name

    @property
    def type_label(self):
        if self.location_type == self.LocationType.OTHER and self.custom_location_type:
            return self.custom_location_type
        return self.get_location_type_display()

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_structure = {key: instance.__dict__[key] for key in ("parent_id", "position")
                                      if key in instance.__dict__}
        return instance

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        self._loaded_structure = {key: self.__dict__[key] for key in ("parent_id", "position")
                                  if key in self.__dict__}

    def clean(self):
        from .services import validate_parent

        super().clean()
        if not self.name.strip():
            raise ValidationError({"name": _("El nombre es obligatorio.")})
        if self.project_id:
            validate_project_action(self.project)
            if self.pk and not self._state.adding:
                original = type(self).objects.using(self._state.db).filter(pk=self.pk).values_list("project_id", flat=True).first()
                if original != self.project_id:
                    raise ValidationError({"project": _("No se permite trasladar ubicaciones a otro proyecto.")})
            validate_parent(self.project, self.pk, self.parent_id)

    def save(self, *args, **kwargs):
        from .services import save_location

        return save_location(self, *args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        from .services import delete_location

        return delete_location(self, using=using, keep_parents=keep_parents)
