import uuid
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.manuscripts.models import ManuscriptNode
from apps.projects.models import Project


def character_image_upload_to(instance, filename):
    suffix = Path(filename).suffix.lower()
    return f"characters/{instance.project_id}/{uuid.uuid4()}{suffix}"


class Character(models.Model):
    class Importance(models.TextChoices):
        PRINCIPAL = "PRINCIPAL", _("Principal")
        SECUNDARIA = "SECUNDARIA", _("Secundaria")
        FIGURANTE = "FIGURANTE", _("Figurante")

    class NarrativeRole(models.TextChoices):
        PROTAGONISTA = "PROTAGONISTA", _("Protagonista")
        DEUTERAGONISTA = "DEUTERAGONISTA", _("Deuteragonista")
        TRITAGONISTA = "TRITAGONISTA", _("Tritagonista")
        ANTAGONISTA = "ANTAGONISTA", _("Antagonista")
        PERSONAJE_IMPORTANTE = "PERSONAJE_IMPORTANTE", _("Personaje importante")
        SECUNDARIO = "SECUNDARIO", _("Secundario")
        INCIDENTAL = "INCIDENTAL", _("Incidental")
        OTRO = "OTRO", _("Otro")

    class CompletionStatus(models.TextChoices):
        DRAFT = "DRAFT", _("Borrador")
        PARTIAL = "PARTIAL", _("Parcial")
        COMPLETE = "COMPLETE", _("Completo")

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="characters",
        verbose_name=_("proyecto"),
    )
    name = models.CharField(_("nombre"), max_length=180)
    alias = models.CharField(_("alias"), max_length=180, blank=True)
    image = models.FileField(
        _("imagen"),
        upload_to=character_image_upload_to,
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["jpg", "jpeg", "png", "gif", "webp"],
                message=_("Sube una imagen JPG, JPEG, PNG, GIF o WEBP."),
            )
        ],
    )
    importance = models.CharField(
        _("importancia"),
        max_length=20,
        choices=Importance.choices,
        default=Importance.SECUNDARIA,
    )
    narrative_role = models.CharField(
        _("rol narrativo"),
        max_length=30,
        choices=NarrativeRole.choices,
        default=NarrativeRole.SECUNDARIO,
    )
    custom_narrative_role = models.CharField(_("rol narrativo personalizado"), max_length=180, blank=True)
    physical_description = models.TextField(_("descripción física"), blank=True)
    psychological_description = models.TextField(_("descripción psicológica"), blank=True)
    biography = models.TextField(_("biografía"), blank=True)
    motivations = models.TextField(_("motivaciones"), blank=True)
    goals = models.TextField(_("objetivos"), blank=True)
    fears = models.TextField(_("miedos"), blank=True)
    virtues = models.TextField(_("virtudes"), blank=True)
    flaws = models.TextField(_("defectos"), blank=True)
    character_arc = models.TextField(_("arco del personaje"), blank=True)
    notes = models.TextField(_("notas"), blank=True)
    completion_status = models.CharField(
        _("estado de construcción"),
        max_length=20,
        choices=CompletionStatus.choices,
        default=CompletionStatus.DRAFT,
    )
    created_at = models.DateTimeField(_("creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado"), auto_now=True)

    class Meta:
        verbose_name = _("personaje")
        verbose_name_plural = _("personajes")
        ordering = ["project", "name"]
        indexes = [
            models.Index(fields=["project", "name"]),
            models.Index(fields=["project", "importance"]),
            models.Index(fields=["project", "narrative_role"]),
        ]

    def __str__(self):
        return self.name

    @property
    def completion_percentage(self):
        fields_by_importance = {
            self.Importance.PRINCIPAL: (
                "name",
                "physical_description",
                "psychological_description",
                "biography",
                "motivations",
                "goals",
                "fears",
                "virtues",
                "flaws",
                "character_arc",
            ),
            self.Importance.SECUNDARIA: (
                "name",
                "physical_description",
                "biography",
                "motivations",
                "goals",
                "notes",
            ),
            self.Importance.FIGURANTE: (
                "name",
                "physical_description",
                "notes",
            ),
        }
        fields = fields_by_importance.get(self.importance, fields_by_importance[self.Importance.SECUNDARIA])
        filled = sum(1 for field in fields if str(getattr(self, field, "")).strip())
        return int(round((filled * 100) / len(fields)))

    def clean(self):
        super().clean()
        if self.project_id and self.project.status in (
            Project.ProjectStatus.DELETED,
            Project.ProjectStatus.PENDING_DELETION,
        ):
            raise ValidationError(_("No se pueden crear o editar personajes en proyectos eliminados o pendientes de borrado."))
        if self.narrative_role != self.NarrativeRole.OTRO:
            self.custom_narrative_role = ""

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CharacterDramaticRole(models.Model):
    class DramaticRole(models.TextChoices):
        HEROE = "HEROE", _("Héroe")
        HEROINA = "HEROINA", _("Heroína")
        VILLANO = "VILLANO", _("Villano")
        INTERES_ROMANTICO = "INTERES_ROMANTICO", _("Interés romántico")
        MENTOR = "MENTOR", _("Mentor")
        ALIADO = "ALIADO", _("Aliado")
        RIVAL = "RIVAL", _("Rival")
        TRAIDOR = "TRAIDOR", _("Traidor")
        PROTEGIDO = "PROTEGIDO", _("Protegido")
        CATALIZADOR = "CATALIZADOR", _("Catalizador")
        NARRADOR = "NARRADOR", _("Narrador")
        ALIVIO_COMICO = "ALIVIO_COMICO", _("Alivio cómico")
        OTRO = "OTRO", _("Otro")

    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name="dramatic_roles",
        verbose_name=_("personaje"),
    )
    role = models.CharField(_("papel dramático"), max_length=30, choices=DramaticRole.choices)
    custom_role = models.CharField(_("papel personalizado"), max_length=180, blank=True)
    created_at = models.DateTimeField(_("creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado"), auto_now=True)

    class Meta:
        verbose_name = _("papel dramático")
        verbose_name_plural = _("papeles dramáticos")
        ordering = ["character", "role"]

    def __str__(self):
        if self.role == self.DramaticRole.OTRO and self.custom_role:
            return f"{self.character} - {self.custom_role}"
        return f"{self.character} - {self.get_role_display()}"

    def clean(self):
        super().clean()
        if self.role != self.DramaticRole.OTRO:
            self.custom_role = ""

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class CharacterMention(models.Model):
    class MentionType(models.TextChoices):
        APPEARS = "APPEARS", _("Aparece")
        MENTIONED = "MENTIONED", _("Mencionado")
        POV = "POV", _("Punto de vista")
        NARRATOR = "NARRATOR", _("Narrador")
        IMPORTANT_FOR_SCENE = "IMPORTANT_FOR_SCENE", _("Importante para la escena")

    character = models.ForeignKey(
        Character,
        on_delete=models.CASCADE,
        related_name="mentions",
        verbose_name=_("personaje"),
    )
    node = models.ForeignKey(
        ManuscriptNode,
        on_delete=models.CASCADE,
        related_name="character_mentions",
        verbose_name=_("nodo de manuscrito"),
    )
    mention_type = models.CharField(_("tipo de mención"), max_length=30, choices=MentionType.choices)
    created_at = models.DateTimeField(_("creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado"), auto_now=True)

    class Meta:
        verbose_name = _("mención de personaje")
        verbose_name_plural = _("menciones de personajes")
        ordering = ["character", "node", "mention_type"]

    def __str__(self):
        return f"{self.character} - {self.node} ({self.get_mention_type_display()})"

    def clean(self):
        super().clean()
        if self.character_id and self.node_id and self.character.project_id != self.node.project_id:
            raise ValidationError(_("El personaje y el nodo deben pertenecer al mismo proyecto."))

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
