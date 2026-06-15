from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Project(models.Model):
    class Language(models.TextChoices):
        ES = "es", _("Español")
        EN = "en", _("Inglés")

    class Locale(models.TextChoices):
        ES_MX = "es-mx", _("Español de México")
        EN_US = "en-us", _("English United States")

    class ProjectStatus(models.TextChoices):
        ACTIVE = "ACTIVE", _("Activo")
        FROZEN = "FROZEN", _("Congelado")
        PENDING_DELETION = "PENDING_DELETION", _("Pendiente de borrado")
        DELETED = "DELETED", _("Eliminado")

    COUNTED_STATUSES = (
        ProjectStatus.ACTIVE,
        ProjectStatus.FROZEN,
        ProjectStatus.PENDING_DELETION,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="projects",
        verbose_name=_("usuario"),
    )
    name = models.CharField(_("nombre"), max_length=180)
    description = models.TextField(_("descripción"), blank=True)
    language = models.CharField(
        _("idioma"),
        max_length=2,
        choices=Language.choices,
        default=Language.ES,
    )
    locale = models.CharField(
        _("locale"),
        max_length=5,
        choices=Locale.choices,
        default=Locale.ES_MX,
    )
    status = models.CharField(
        _("estado"),
        max_length=20,
        choices=ProjectStatus.choices,
        default=ProjectStatus.ACTIVE,
    )
    created_at = models.DateTimeField(_("creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado"), auto_now=True)
    frozen_at = models.DateTimeField(_("congelado"), null=True, blank=True)
    deletion_requested_at = models.DateTimeField(_("borrado solicitado"), null=True, blank=True)
    scheduled_deletion_at = models.DateTimeField(_("borrado programado"), null=True, blank=True)
    deleted_at = models.DateTimeField(_("eliminado"), null=True, blank=True)

    class Meta:
        verbose_name = _("proyecto")
        verbose_name_plural = _("proyectos")
        ordering = ["-created_at", "name"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self):
        return self.name

    @classmethod
    def limit_for_user(cls, user):
        user_type = getattr(user, "user_type", None)
        if user_type == "FREE":
            return 1
        if user_type == "PREMIUM":
            return 10
        return None

    @classmethod
    def counted_for_user(cls, user):
        return cls.objects.filter(user=user, status__in=cls.COUNTED_STATUSES)

    @classmethod
    def can_create_for_user(cls, user):
        limit = cls.limit_for_user(user)
        if limit is None:
            return True
        return cls.counted_for_user(user).count() < limit

    @classmethod
    def limit_message_for_user(cls, user):
        limit = cls.limit_for_user(user)
        if limit == 1:
            return _("Tu cuenta gratuita permite tener 1 proyecto no eliminado.")
        if limit == 10:
            return _("Tu cuenta premium permite tener hasta 10 proyectos no eliminados.")
        return _("Tu cuenta no tiene límite de proyectos en esta fase.")

    def mark_for_deletion(self):
        if self.status == self.ProjectStatus.DELETED:
            raise ValidationError(_("No se puede marcar para borrar un proyecto eliminado."))
        if self.status == self.ProjectStatus.PENDING_DELETION:
            raise ValidationError(_("El proyecto ya está pendiente de borrado."))

        now = timezone.now()
        self.status = self.ProjectStatus.PENDING_DELETION
        self.deletion_requested_at = now
        self.scheduled_deletion_at = now + timedelta(days=90)
        self.save(update_fields=["status", "deletion_requested_at", "scheduled_deletion_at", "updated_at"])

    def restore(self):
        if self.status == self.ProjectStatus.DELETED:
            raise ValidationError(_("No se puede restaurar un proyecto eliminado."))

        self.status = self.ProjectStatus.ACTIVE
        self.frozen_at = None
        self.deletion_requested_at = None
        self.scheduled_deletion_at = None
        self.save(
            update_fields=[
                "status",
                "frozen_at",
                "deletion_requested_at",
                "scheduled_deletion_at",
                "updated_at",
            ]
        )
