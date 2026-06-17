from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.manuscripts.models import ManuscriptNode
from apps.projects.models import Project

from .models import Character, CharacterDramaticRole, CharacterMention


class CharacterForm(forms.ModelForm):
    dramatic_roles = forms.MultipleChoiceField(
        label=_("Papeles dramáticos"),
        required=False,
        choices=(),
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Character
        fields = (
            "name",
            "alias",
            "image",
            "importance",
            "narrative_role",
            "custom_narrative_role",
            "physical_description",
            "psychological_description",
            "biography",
            "motivations",
            "goals",
            "fears",
            "virtues",
            "flaws",
            "character_arc",
            "notes",
            "completion_status",
        )
        labels = {
            "name": _("Nombre"),
            "alias": _("Alias"),
            "image": _("Imagen"),
            "importance": _("Importancia narrativa"),
            "narrative_role": _("Rol narrativo"),
            "custom_narrative_role": _("Rol narrativo personalizado"),
            "physical_description": _("Descripción física"),
            "psychological_description": _("Descripción psicológica"),
            "biography": _("Biografía"),
            "motivations": _("Motivaciones"),
            "goals": _("Objetivos"),
            "fears": _("Miedos"),
            "virtues": _("Virtudes"),
            "flaws": _("Defectos"),
            "character_arc": _("Arco del personaje"),
            "notes": _("Notas"),
            "completion_status": _("Estado de construcción"),
        }
        widgets = {
            "physical_description": forms.Textarea(attrs={"rows": 4}),
            "psychological_description": forms.Textarea(attrs={"rows": 4}),
            "biography": forms.Textarea(attrs={"rows": 5}),
            "motivations": forms.Textarea(attrs={"rows": 3}),
            "goals": forms.Textarea(attrs={"rows": 3}),
            "fears": forms.Textarea(attrs={"rows": 3}),
            "virtues": forms.Textarea(attrs={"rows": 3}),
            "flaws": forms.Textarea(attrs={"rows": 3}),
            "character_arc": forms.Textarea(attrs={"rows": 5}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, project=None, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)
        if project is not None:
            self.instance.project = project
        self.fields["dramatic_roles"].choices = [
            choice
            for choice in CharacterDramaticRole.DramaticRole.choices
            if choice[0] != CharacterDramaticRole.DramaticRole.OTRO
        ]
        if self.instance.pk:
            self.fields["dramatic_roles"].initial = list(
                self.instance.dramatic_roles.exclude(role=CharacterDramaticRole.DramaticRole.OTRO).values_list("role", flat=True)
            )

    def clean(self):
        cleaned_data = super().clean()
        if self.project and self.project.status in (
            Project.ProjectStatus.DELETED,
            Project.ProjectStatus.PENDING_DELETION,
        ):
            raise ValidationError(_("No se pueden crear o editar personajes en proyectos eliminados o pendientes de borrado."))
        return cleaned_data

    def save(self, commit=True):
        character = super().save(commit=False)
        character.project = self.project
        if commit:
            character.save()
            selected_roles = self.cleaned_data.get("dramatic_roles", [])
            character.dramatic_roles.exclude(role=CharacterDramaticRole.DramaticRole.OTRO).delete()
            for role in selected_roles:
                CharacterDramaticRole.objects.create(character=character, role=role)
        return character


class CharacterMentionForm(forms.ModelForm):
    class Meta:
        model = CharacterMention
        fields = ("character", "node", "mention_type")
        labels = {
            "character": _("Personaje"),
            "node": _("Nodo de manuscrito"),
            "mention_type": _("Tipo de mención"),
        }

    def __init__(self, *args, project=None, initial_character=None, initial_node=None, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)
        if project is not None:
            self.fields["character"].queryset = Character.objects.filter(project=project).order_by("name")
            self.fields["node"].queryset = ManuscriptNode.objects.filter(project=project).order_by(
                "parent_id",
                "position",
                "title",
            )
        else:
            self.fields["character"].queryset = Character.objects.none()
            self.fields["node"].queryset = ManuscriptNode.objects.none()

        if initial_character is not None and not self.is_bound:
            self.initial["character"] = initial_character.pk
        if initial_node is not None and not self.is_bound:
            self.initial["node"] = initial_node.pk
        if not self.is_bound and not self.instance.pk:
            self.initial["mention_type"] = CharacterMention.MentionType.APPEARS

    def clean(self):
        cleaned_data = super().clean()
        character = cleaned_data.get("character")
        node = cleaned_data.get("node")
        mention_type = cleaned_data.get("mention_type")

        if self.project and self.project.status in (
            Project.ProjectStatus.DELETED,
            Project.ProjectStatus.PENDING_DELETION,
        ):
            raise ValidationError(_("No se pueden gestionar menciones en proyectos eliminados o pendientes de borrado."))

        if character and self.project and character.project_id != self.project.id:
            raise ValidationError({"character": _("El personaje debe pertenecer al proyecto actual.")})

        if node and self.project and node.project_id != self.project.id:
            raise ValidationError({"node": _("El nodo debe pertenecer al proyecto actual.")})

        if character and node and character.project_id != node.project_id:
            raise ValidationError(_("El personaje y el nodo deben pertenecer al mismo proyecto."))

        if character and node and mention_type:
            duplicate_mentions = CharacterMention.objects.filter(
                character=character,
                node=node,
                mention_type=mention_type,
            )
            if self.instance.pk:
                duplicate_mentions = duplicate_mentions.exclude(pk=self.instance.pk)
            if duplicate_mentions.exists():
                raise ValidationError(_("Ya existe una mención idéntica para este personaje, nodo y tipo."))

        return cleaned_data
