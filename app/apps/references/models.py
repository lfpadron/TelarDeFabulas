from functools import reduce
from operator import or_

from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import validate_project_action
from .validators import DOCUMENT_TYPES, validate_source_url


TARGETS = {
    "manuscript_node": ("manuscripts.ManuscriptNode", "node", "manuscripts:detail", _("Manuscrito")),
    "character": ("characters.Character", "character", "characters:detail", _("Personaje")),
    "geographic_location": ("geography.GeographicLocation", "location", "geography:detail", _("Ubicación")),
    "organization": ("organizations.Organization", "organization", "organizations:detail", _("Organización")),
    "worldbuilding_entry": ("worldbuilding.WorldbuildingEntry", "worldbuilding", "worldbuilding:detail", _("Construcción de mundos")),
}


class ReferenceMaterial(models.Model):
    class MaterialType(models.TextChoices):
        BIBLIOGRAPHY = "BIBLIOGRAPHY", _("Bibliografía")
        LINK = "LINK", _("Enlace")
        IMAGE = "IMAGE", _("Imagen")
        DOCUMENT = "DOCUMENT", _("Documento")
        OTHER = "OTHER", _("Otro")

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="references", verbose_name=_("Proyecto"))
    material_type = models.CharField(_("Tipo"), max_length=16, choices=MaterialType.choices, default=MaterialType.BIBLIOGRAPHY)
    title = models.CharField(_("Título"), max_length=200)
    short_description = models.CharField(_("Descripción breve"), max_length=300, blank=True)
    notes = models.TextField(_("Notas"), blank=True)
    author = models.CharField(_("Autor"), max_length=200, blank=True)
    publication_year_text = models.CharField(_("Año de publicación"), max_length=120, blank=True)
    publisher = models.CharField(_("Editorial"), max_length=200, blank=True)
    source_url = models.URLField(_("Enlace externo"), max_length=2000, blank=True, validators=[validate_source_url])
    file = models.FileField(_("Archivo privado"), max_length=240, blank=True)
    file_size = models.PositiveBigIntegerField(_("Tamaño del archivo"), default=0, editable=False)
    mime_type = models.CharField(_("Tipo de archivo"), max_length=120, blank=True, editable=False)
    original_filename = models.CharField(_("Nombre original"), max_length=240, blank=True, editable=False)
    revision = models.PositiveBigIntegerField(_("Revisión"), default=1, editable=False)
    created_at = models.DateTimeField(_("Creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Actualizado"), auto_now=True)

    class Meta:
        ordering = ["-updated_at", "pk"]
        verbose_name = _("material de referencia")
        verbose_name_plural = _("materiales de referencia")
        indexes = [models.Index(fields=["project", "material_type", "-updated_at"], name="ref_project_type_updated")]
        constraints = [
            models.CheckConstraint(condition=models.Q(material_type__in=["BIBLIOGRAPHY", "LINK", "IMAGE", "DOCUMENT", "OTHER"]), name="ref_material_type_valid"),
            models.CheckConstraint(condition=models.Q(title__regex=r"\S"), name="ref_title_required"),
            models.CheckConstraint(condition=~models.Q(material_type="LINK") | ~models.Q(source_url=""), name="ref_link_url_required"),
            models.CheckConstraint(condition=~models.Q(material_type__in=["IMAGE", "DOCUMENT"]) | ~models.Q(file=""), name="ref_type_file_required"),
            models.CheckConstraint(condition=models.Q(revision__gte=1), name="ref_revision_positive"),
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
        errors = {}
        if not self.title or not self.title.strip():
            errors["title"] = _("El título no puede estar vacío ni contener solo espacios.")
        if self.material_type == self.MaterialType.LINK and not self.source_url:
            errors["source_url"] = _("Un enlace requiere una URL HTTP o HTTPS.")
        if self.material_type in (self.MaterialType.IMAGE, self.MaterialType.DOCUMENT) and not self.file:
            errors["file"] = _("Este tipo de referencia requiere un archivo.")
        if self.file and getattr(self.file, "_committed", False):
            if self.material_type == self.MaterialType.IMAGE and self.mime_type not in ("image/jpeg", "image/png", "image/webp"):
                errors["file"] = _("Una referencia de imagen requiere JPEG, PNG o WebP.")
            if self.material_type == self.MaterialType.DOCUMENT and self.mime_type not in DOCUMENT_TYPES.values():
                errors["file"] = _("Una referencia de documento requiere PDF, TXT, MD o DOCX.")
        if self.project_id:
            validate_project_action(self.project)
            if self.pk and type(self).objects.filter(pk=self.pk).exclude(project_id=self.project_id).exists():
                raise ValidationError(_("No se permite trasladar referencias a otro proyecto."))
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        from .services import save_reference
        return save_reference(self, *args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        from .services import delete_reference
        return delete_reference(self, using=using)


class ReferenceAssociation(models.Model):
    reference = models.ForeignKey(ReferenceMaterial, on_delete=models.CASCADE, related_name="associations", verbose_name=_("Referencia"))
    manuscript_node = models.ForeignKey("manuscripts.ManuscriptNode", on_delete=models.CASCADE, blank=True, null=True, related_name="reference_associations", verbose_name=_("Manuscrito"))
    character = models.ForeignKey("characters.Character", on_delete=models.CASCADE, blank=True, null=True, related_name="reference_associations", verbose_name=_("Personaje"))
    geographic_location = models.ForeignKey("geography.GeographicLocation", on_delete=models.CASCADE, blank=True, null=True, related_name="reference_associations", verbose_name=_("Ubicación"))
    organization = models.ForeignKey("organizations.Organization", on_delete=models.CASCADE, blank=True, null=True, related_name="reference_associations", verbose_name=_("Organización"))
    worldbuilding_entry = models.ForeignKey("worldbuilding.WorldbuildingEntry", on_delete=models.CASCADE, blank=True, null=True, related_name="reference_associations", verbose_name=_("Construcción de mundos"))
    description = models.CharField(_("Descripción del vínculo"), max_length=300, blank=True)
    created_at = models.DateTimeField(_("Creado"), auto_now_add=True)

    class Meta:
        ordering = ["pk"]
        verbose_name = _("asociación de referencia")
        verbose_name_plural = _("asociaciones de referencias")
        constraints = [models.CheckConstraint(condition=reduce(or_, (
            models.Q(**{f"{name}__isnull": name != selected for name in TARGETS}) for selected in TARGETS
        )), name="ref_exactly_one_entity"), *[
            models.UniqueConstraint(fields=["reference", name], condition=models.Q(**{f"{name}__isnull": False}), name=f"ref_unique_{name}") for name in TARGETS
        ]]

    def __str__(self):
        return str(self.reference)

    @property
    def target_field(self):
        return next((name for name in TARGETS if getattr(self, f"{name}_id")), None)

    @property
    def entity(self):
        return getattr(self, self.target_field) if self.target_field else None

    @property
    def entity_url(self):
        return reverse(TARGETS[self.target_field][2], args=[self.reference.project_id, self.entity.pk])

    def clean(self):
        super().clean()
        fields = [key for key in TARGETS if getattr(self, f"{key}_id")]
        if len(fields) != 1:
            raise ValidationError(_("Selecciona exactamente una entidad."))
        if self.reference_id:
            if self.entity.project_id != self.reference.project_id:
                raise ValidationError(_("La referencia y la entidad deben pertenecer al mismo proyecto."))
            validate_project_action(self.reference.project)
        if self.manuscript_node_id:
            from apps.manuscripts.visibility import require_visible_node
            require_visible_node(self.manuscript_node)

    def save(self, *args, **kwargs):
        from .services import save_association
        return save_association(self, *args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        from .services import detach_reference
        return detach_reference(self)


class ReferenceFileCleanup(models.Model):
    # No FK: cleanup must survive deletion of the reference and its project.
    project_id = models.PositiveBigIntegerField(db_index=True)
    name = models.CharField(max_length=240, unique=True)
    file_size = models.PositiveBigIntegerField(default=0)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_error = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
