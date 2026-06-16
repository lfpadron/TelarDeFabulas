from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class StyleTemplate(models.Model):
    class FontCategory(models.TextChoices):
        SERIF = "SERIF", _("Serif")
        SANS_SERIF = "SANS_SERIF", _("Sans serif")

    class TextAlignment(models.TextChoices):
        LEFT = "LEFT", _("Izquierda")
        JUSTIFY = "JUSTIFY", _("Justificado")
        CENTER = "CENTER", _("Centrado")
        RIGHT = "RIGHT", _("Derecha")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="style_templates",
        null=True,
        blank=True,
        verbose_name=_("usuario"),
    )
    name = models.CharField(_("nombre"), max_length=180)
    description = models.TextField(_("descripción"), blank=True)
    is_system = models.BooleanField(_("es del sistema"), default=False)
    font_category = models.CharField(
        _("categoría tipográfica"),
        max_length=20,
        choices=FontCategory.choices,
        default=FontCategory.SERIF,
    )
    font_heading = models.CharField(_("fuente de títulos"), max_length=120, default="Libre Baskerville")
    font_body = models.CharField(_("fuente de cuerpo"), max_length=120, default="Merriweather")
    heading_size = models.DecimalField(_("tamaño de títulos"), max_digits=5, decimal_places=2, default=Decimal("18.00"))
    body_size = models.DecimalField(_("tamaño de cuerpo"), max_digits=5, decimal_places=2, default=Decimal("12.00"))
    line_spacing = models.DecimalField(_("interlineado"), max_digits=4, decimal_places=2, default=Decimal("1.50"))
    paragraph_spacing = models.DecimalField(_("espaciado entre párrafos"), max_digits=5, decimal_places=2, default=Decimal("8.00"))
    margin_top = models.DecimalField(_("margen superior"), max_digits=5, decimal_places=2, default=Decimal("25.00"))
    margin_bottom = models.DecimalField(_("margen inferior"), max_digits=5, decimal_places=2, default=Decimal("25.00"))
    margin_left = models.DecimalField(_("margen izquierdo"), max_digits=5, decimal_places=2, default=Decimal("25.00"))
    margin_right = models.DecimalField(_("margen derecho"), max_digits=5, decimal_places=2, default=Decimal("25.00"))
    text_alignment = models.CharField(
        _("alineación de texto"),
        max_length=10,
        choices=TextAlignment.choices,
        default=TextAlignment.JUSTIFY,
    )
    first_line_indent = models.DecimalField(_("sangría de primera línea"), max_digits=5, decimal_places=2, default=Decimal("0.00"))
    scene_separator = models.CharField(_("separador de escena"), max_length=80, default="***", blank=True)
    include_page_numbers = models.BooleanField(_("incluir números de página"), default=True)
    include_table_of_contents = models.BooleanField(_("incluir tabla de contenidos"), default=False)
    config_json = models.JSONField(_("configuración JSON"), default=dict, blank=True)
    created_at = models.DateTimeField(_("creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado"), auto_now=True)

    class Meta:
        verbose_name = _("plantilla de estilo")
        verbose_name_plural = _("plantillas de estilo")
        ordering = ["-is_system", "name"]
        indexes = [
            models.Index(fields=["is_system", "name"]),
            models.Index(fields=["user", "name"]),
            models.Index(fields=["font_category"]),
        ]

    def __str__(self):
        return self.name

    @property
    def style_type_label(self):
        if self.is_system:
            return _("Sistema")
        return _("Personal")

    def clean(self):
        super().clean()
        errors = {}

        if self.is_system and self.user_id is not None:
            errors["user"] = _("Un estilo del sistema no puede tener usuario.")
        if not self.is_system and self.user_id is None:
            errors["user"] = _("Un estilo personalizado debe tener usuario.")

        positive_fields = ("heading_size", "body_size", "line_spacing")
        for field in positive_fields:
            value = getattr(self, field)
            if value is not None and value <= 0:
                errors[field] = _("Este valor debe ser mayor que cero.")

        non_negative_fields = (
            "paragraph_spacing",
            "margin_top",
            "margin_bottom",
            "margin_left",
            "margin_right",
            "first_line_indent",
        )
        for field in non_negative_fields:
            value = getattr(self, field)
            if value is not None and value < 0:
                errors[field] = _("Este valor debe ser mayor o igual que cero.")

        if self.config_json is None:
            self.config_json = {}
        if not isinstance(self.config_json, dict):
            errors["config_json"] = _("La configuración JSON debe ser un objeto.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
