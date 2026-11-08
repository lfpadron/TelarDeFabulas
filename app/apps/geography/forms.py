from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import validate_project_action

from .models import GeographicLocation
from .services import get_valid_parent_queryset


class GeographicLocationForm(forms.ModelForm):
    class Meta:
        model = GeographicLocation
        fields = ("parent", "name", "location_type", "custom_location_type", "short_description", "detailed_description")
        widgets = {"detailed_description": forms.Textarea(attrs={"rows": 12}),
                   "short_description": forms.Textarea(attrs={"rows": 2, "maxlength": 300})}

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        if self.instance.pk and self.instance.project_id != project.pk:
            raise ValidationError(_("La ubicación debe pertenecer al proyecto actual."))
        self.instance.project = project
        if self.instance.pk:
            # Structure is changed only by the move form, never by an old text form.
            self.fields.pop("parent")
        else:
            self.fields["parent"].queryset = get_valid_parent_queryset(project)
            self.fields["parent"].empty_label = _("Sin padre (raíz)")


class MoveLocationForm(forms.Form):
    parent = forms.ModelChoiceField(label=_("Ubicación padre"), queryset=GeographicLocation.objects.none(),
                                    required=False, empty_label=_("Sin padre (raíz)"))
    position = forms.IntegerField(label=_("Posición"), min_value=1, required=False)

    def __init__(self, *args, project, location, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        self.fields["parent"].queryset = get_valid_parent_queryset(project, location)
        if not self.is_bound:
            self.initial.update(parent=location.parent_id, position=location.position)

    def clean(self):
        cleaned = super().clean()
        validate_project_action(self.project)
        return cleaned
