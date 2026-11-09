from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import validate_project_action

from .models import WorldbuildingEntry as Entry
from .services import EDITABLE_FIELDS, RevisionConflict, check_revision, create_entry, update_entry


class EntryForm(forms.ModelForm):
    expected_revision = forms.IntegerField(label=_("Revisión original"), min_value=1,
                                          max_value=9223372036854775807, widget=forms.HiddenInput)

    class Meta:
        model = Entry
        fields = ("title", "category", "short_description", "content", "expected_revision")
        widgets = {"short_description": forms.Textarea(attrs={"rows": 3}),
                   "content": forms.Textarea(attrs={"rows": 18})}

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.revision_conflict = False
        if project is not None:
            if self.instance.pk and self.instance.project_id != project.pk:
                raise ValidationError(_("La entrada debe pertenecer al proyecto actual."))
            self.instance.project = project
        for key in ("title", "short_description", "content"):
            self.fields[key].strip = False
        if self.instance._state.adding:
            self.fields["expected_revision"].required = False
            self.initial["expected_revision"] = 1
        else:
            self.initial["expected_revision"] = self.instance.revision

    def clean(self):
        cleaned = super().clean()
        project = cleaned.get("project") or (self.instance.project if self.instance.project_id else None)
        if project is not None:
            validate_project_action(project)
        if self.instance.pk and "expected_revision" in cleaned:
            current = Entry.objects.filter(pk=self.instance.pk, project_id=self.instance.project_id).only("revision").first()
            try:
                if current is None:
                    raise RevisionConflict()
                check_revision(current, cleaned["expected_revision"])
            except RevisionConflict:
                self.revision_conflict = True
                raise
        return cleaned

    def save(self, commit=True, *, user=None):
        entry = super().save(commit=False)
        if not commit:
            return entry
        data = {key: self.cleaned_data[key] for key in EDITABLE_FIELDS}
        self.instance = (create_entry(entry.project, user=user, **data) if entry._state.adding else
                         update_entry(entry, expected_revision=self.cleaned_data["expected_revision"], user=user, **data))
        return self.instance


class AdminEntryForm(EntryForm):
    class Meta(EntryForm.Meta):
        fields = ("project", *EntryForm.Meta.fields)


class RevisionForm(forms.Form):
    expected_revision = forms.IntegerField(label=_("Revisión original"), min_value=1,
                                          max_value=9223372036854775807, widget=forms.HiddenInput)


class CategoryForm(RevisionForm):
    category = forms.ChoiceField(label=_("Categoría"), choices=Entry.Category.choices)


class EntryFilterForm(forms.Form):
    category = forms.ChoiceField(label=_("Categoría"), required=False,
        choices=[("", _("Todas")), *Entry.Category.choices])
    q = forms.CharField(label=_("Buscar por título o descripción"), required=False, max_length=200,
                        widget=forms.TextInput(attrs={"type": "search"}))
