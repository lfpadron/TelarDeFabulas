from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.projects.models import Project

from .models import Character, CharacterDramaticRole


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
