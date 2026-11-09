from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import validate_project_action


class Organization(models.Model):
    class OrganizationType(models.TextChoices):
        RELIGIOUS = "RELIGIOUS", _("Religiosa")
        POLITICAL = "POLITICAL", _("Política")
        BROTHERHOOD = "BROTHERHOOD", _("Cofradía")
        GUILD = "GUILD", _("Gremio")
        MILITARY = "MILITARY", _("Militar")
        COMMERCIAL = "COMMERCIAL", _("Comercial")
        ACADEMIC = "ACADEMIC", _("Académica")
        SECRET_SOCIETY = "SECRET_SOCIETY", _("Sociedad secreta")
        OTHER = "OTHER", _("Otro")

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE,
                               related_name="organizations", verbose_name=_("Proyecto"))
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True,
                              related_name="children", verbose_name=_("Organización superior"))
    name = models.CharField(_("Nombre"), max_length=180)
    organization_type = models.CharField(_("Tipo"), max_length=20, choices=OrganizationType.choices,
                                        default=OrganizationType.OTHER)
    custom_organization_type = models.CharField(_("Tipo personalizado"), max_length=100, blank=True)
    short_description = models.CharField(_("Descripción breve"), max_length=300, blank=True)
    detailed_description = models.TextField(_("Desarrollo detallado"), blank=True)
    position = models.PositiveIntegerField(_("Posición"), blank=True, db_index=True)
    headquarters = models.ForeignKey("geography.GeographicLocation", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="headquartered_organizations", verbose_name=_("Sede principal"))
    created_at = models.DateTimeField(_("Creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Actualizado"), auto_now=True)

    class Meta:
        ordering = ["position", "pk"]
        verbose_name = _("organización")
        verbose_name_plural = _("organizaciones")
        indexes = [models.Index(fields=["project", "parent", "position"], name="org_project_parent_order")]
        constraints = [
            models.UniqueConstraint(fields=["project", "parent", "position"],
                                    nulls_distinct=False, name="org_sibling_position_unique"),
            models.CheckConstraint(condition=models.Q(position__gte=1), name="org_position_positive"),
            models.CheckConstraint(condition=~models.Q(name=""), name="org_name_required"),
            models.CheckConstraint(condition=models.Q(parent__isnull=True) | ~models.Q(parent=models.F("pk")), name="org_not_own_parent"),
            models.CheckConstraint(condition=models.Q(organization_type__in=[
                "RELIGIOUS", "POLITICAL", "BROTHERHOOD", "GUILD", "MILITARY", "COMMERCIAL", "ACADEMIC", "SECRET_SOCIETY", "OTHER",
            ]), name="org_type_valid"),
            models.CheckConstraint(condition=models.Q(organization_type="OTHER") | models.Q(custom_organization_type=""), name="org_custom_type_only_other"),
        ]

    def __str__(self):
        return self.name

    @property
    def type_label(self):
        if self.organization_type == self.OrganizationType.OTHER and self.custom_organization_type:
            return self.custom_organization_type
        return self.get_organization_type_display()

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_structure = {key: instance.__dict__[key] for key in ("parent_id", "position") if key in instance.__dict__}
        return instance

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        self._loaded_structure = {key: self.__dict__[key] for key in ("parent_id", "position") if key in self.__dict__}

    def clean(self):
        from apps.geography.models import GeographicLocation
        from .services import validate_parent

        super().clean()
        if not self.name or not self.name.strip():
            raise ValidationError({"name": _("El nombre es obligatorio.")})
        if self.organization_type != self.OrganizationType.OTHER:
            self.custom_organization_type = ""
        if self.project_id:
            validate_project_action(self.project)
            if self.pk:
                original = type(self).objects.using(self._state.db).filter(pk=self.pk).values_list("project_id", flat=True).first()
                if original is not None and original != self.project_id:
                    raise ValidationError(_("No se permite trasladar organizaciones a otro proyecto."))
            validate_parent(self.project, self.pk, self.parent_id)
        if self.headquarters_id and not GeographicLocation.objects.using(self._state.db).filter(
                pk=self.headquarters_id, project_id=self.project_id).exists():
            raise ValidationError({"headquarters": _("La sede debe pertenecer al mismo proyecto que la organización.")})

    def save(self, *args, **kwargs):
        from .services import save_organization

        return save_organization(self, *args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        from .services import delete_organization

        return delete_organization(self, using=using, keep_parents=keep_parents)


class CharacterOrganizationMembership(models.Model):
    class MembershipStatus(models.TextChoices):
        ACTIVE = "ACTIVE", _("Activa")
        FORMER = "FORMER", _("Anterior")
        HONORARY = "HONORARY", _("Honoraria")
        SUSPENDED = "SUSPENDED", _("Suspendida")
        UNKNOWN = "UNKNOWN", _("Desconocida")

    character = models.ForeignKey("characters.Character", on_delete=models.CASCADE,
                                 related_name="organization_memberships", verbose_name=_("Personaje"))
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT,
                                    related_name="memberships", verbose_name=_("Organización"))
    position_title = models.CharField(_("Cargo o función"), max_length=180, blank=True)
    membership_status = models.CharField(_("Estado"), max_length=12, choices=MembershipStatus.choices,
                                        default=MembershipStatus.ACTIVE)
    description = models.TextField(_("Descripción"), blank=True)
    joined_at_text = models.CharField(_("Ingreso (fecha narrativa)"), max_length=180, blank=True)
    left_at_text = models.CharField(_("Salida (fecha narrativa)"), max_length=180, blank=True)
    created_at = models.DateTimeField(_("Creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Actualizado"), auto_now=True)

    class Meta:
        ordering = ["character__name", "organization__name", "pk"]
        verbose_name = _("afiliación")
        verbose_name_plural = _("afiliaciones")
        constraints = [
            models.UniqueConstraint(fields=["character", "organization", "position_title", "membership_status", "joined_at_text", "left_at_text"],
                name="org_membership_exact_unique", violation_error_message=_("Ya existe una afiliación con el mismo personaje, organización, cargo, estado y período.")),
            models.CheckConstraint(condition=models.Q(membership_status__in=["ACTIVE", "FORMER", "HONORARY", "SUSPENDED", "UNKNOWN"]), name="org_membership_status_valid"),
        ]

    def __str__(self):
        return _("%(character)s - %(organization)s") % {"character": self.character, "organization": self.organization}

    def clean(self):
        super().clean()
        for key in ("position_title", "joined_at_text", "left_at_text"):
            setattr(self, key, (getattr(self, key) or "").strip())
        if self.organization_id:
            project = self.organization.project
            validate_project_action(project)
            if self.character_id and self.character.project_id != project.pk:
                raise ValidationError(_("El personaje y la organización deben pertenecer al mismo proyecto."))
            if self.pk:
                original = type(self).objects.using(self._state.db).filter(pk=self.pk).values_list("organization__project_id", flat=True).first()
                if original is not None and original != project.pk:
                    raise ValidationError(_("No se permite trasladar afiliaciones a otro proyecto."))

    def save(self, *args, **kwargs):
        from .membership_services import save_membership

        return save_membership(self, *args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        from .membership_services import delete_membership

        return delete_membership(self, using=using, keep_parents=keep_parents)
