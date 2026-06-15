from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import Project


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ("name", "description", "language", "locale")
        labels = {
            "name": _("Nombre"),
            "description": _("Descripción"),
            "language": _("Idioma"),
            "locale": _("Locale"),
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        if self.instance._state.adding and self.user and not Project.can_create_for_user(self.user):
            raise ValidationError(Project.limit_message_for_user(self.user))
        return cleaned_data

    def save(self, commit=True):
        project = super().save(commit=False)
        if project._state.adding:
            project.user = self.user
        if commit:
            project.save()
        return project
