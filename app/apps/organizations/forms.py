from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.characters.models import Character
from apps.core.permissions import local_project_relations, validate_project_action
from apps.geography.models import GeographicLocation

from .models import CharacterOrganizationMembership, Organization
from .services import get_valid_parent_queryset


class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ("parent", "name", "organization_type", "custom_organization_type", "headquarters", "short_description", "detailed_description")
        widgets = {"short_description": forms.Textarea(attrs={"rows": 2, "maxlength": 300}),
                   "detailed_description": forms.Textarea(attrs={"rows": 12})}

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.project_id != project.pk:
            raise ValidationError(_("La organización debe pertenecer al proyecto actual."))
        self.instance.project = project
        self.fields["headquarters"].queryset = local_project_relations(
            GeographicLocation.objects.filter(project=project)).only("id", "name").order_by("name", "pk")
        if self.instance.pk:
            self.fields.pop("parent")
        else:
            self.fields["parent"].queryset = get_valid_parent_queryset(project)
            self.fields["parent"].empty_label = _("Sin organización superior")


class MoveOrganizationForm(forms.Form):
    parent = forms.ModelChoiceField(label=_("Organización superior"), queryset=Organization.objects.none(),
                                    required=False, empty_label=_("Sin organización superior"))
    position = forms.IntegerField(label=_("Posición"), min_value=1, required=False)

    def __init__(self, *args, project, organization, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        self.fields["parent"].queryset = get_valid_parent_queryset(project, organization)
        if not self.is_bound:
            self.initial.update(parent=organization.parent_id, position=organization.position)

    def clean(self):
        cleaned = super().clean()
        validate_project_action(self.project)
        return cleaned


class MembershipForm(forms.ModelForm):
    class Meta:
        model = CharacterOrganizationMembership
        fields = ("character", "organization", "position_title", "membership_status", "joined_at_text", "left_at_text", "description")
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        if self.instance.pk and self.instance.organization.project_id != project.pk:
            raise ValidationError(_("La afiliación debe pertenecer al proyecto actual."))
        self.fields["character"].queryset = local_project_relations(
            Character.objects.filter(project=project)).only("id", "name").order_by("name", "pk")
        self.fields["organization"].queryset = local_project_relations(
            Organization.objects.filter(project=project)).only("id", "name").order_by("name", "pk")

    def clean(self):
        cleaned = super().clean()
        validate_project_action(self.project)
        for key in ("character", "organization"):
            obj = cleaned.get(key)
            if obj and obj.project_id != self.project.pk:
                raise ValidationError(_("El personaje y la organización deben pertenecer al proyecto actual."))
        return cleaned
