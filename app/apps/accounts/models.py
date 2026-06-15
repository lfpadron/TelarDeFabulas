from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_("El email es obligatorio."))
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("user_type", User.UserType.TECH_ADMIN)
        extra_fields.setdefault("status", User.UserStatus.ACTIVE)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("El superusuario debe tener is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("El superusuario debe tener is_superuser=True."))

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class PreferredLocale(models.TextChoices):
        ES_MX = "es-mx", _("Español de México")
        EN_US = "en-us", _("English United States")

    class UserType(models.TextChoices):
        FREE = "FREE", _("Gratuito")
        PREMIUM = "PREMIUM", _("Premium")
        BUSINESS_ADMIN = "BUSINESS_ADMIN", _("Admin negocio")
        TECH_ADMIN = "TECH_ADMIN", _("Admin técnico")

    class UserStatus(models.TextChoices):
        ACTIVE = "ACTIVE", _("Activo")
        FROZEN = "FROZEN", _("Congelado")
        PENDING_DELETION = "PENDING_DELETION", _("Pendiente de borrado")
        DELETED = "DELETED", _("Eliminado")

    email = models.EmailField(_("email"), unique=True)
    secondary_email = models.EmailField(_("email secundario"), blank=True)
    name = models.CharField(_("nombre"), max_length=255, blank=True)
    display_alias = models.CharField(_("alias visible"), max_length=150, blank=True)
    preferred_locale = models.CharField(
        _("idioma preferido"),
        max_length=5,
        choices=PreferredLocale.choices,
        default=PreferredLocale.ES_MX,
    )
    timezone = models.CharField(_("zona horaria"), max_length=64, default="America/Mexico_City")
    user_type = models.CharField(
        _("tipo de usuario"),
        max_length=20,
        choices=UserType.choices,
        default=UserType.FREE,
    )
    status = models.CharField(
        _("estado"),
        max_length=20,
        choices=UserStatus.choices,
        default=UserStatus.ACTIVE,
    )
    is_staff = models.BooleanField(
        _("staff"),
        default=False,
        help_text=_("Permite acceder al administrador de Django."),
    )
    is_active = models.BooleanField(
        _("activo para autenticación"),
        default=True,
        help_text=_("Desactiva el inicio de sesión sin borrar el usuario."),
    )
    created_at = models.DateTimeField(_("creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado"), auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _("usuario")
        verbose_name_plural = _("usuarios")
        ordering = ["email"]

    def __str__(self):
        return self.email

    @property
    def public_name(self):
        return self.display_alias or self.name or self.email
