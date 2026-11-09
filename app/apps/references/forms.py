from django import forms
from django.apps import apps
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import local_project_relations, validate_project_action
from apps.core.widgets import PrivateFileInput
from .models import ReferenceAssociation, ReferenceMaterial, TARGETS
from .services import TEXT_FIELDS, ReferenceConflict, check_revision, check_upload_quota, create_reference, update_reference
from .validators import validate_reference_upload


class RevisionForm(forms.Form):
    expected_revision = forms.IntegerField(label=_("Revisión original"), min_value=1, max_value=9223372036854775807, widget=forms.HiddenInput)


class ReferenceForm(forms.ModelForm):
    expected_revision = RevisionForm.base_fields["expected_revision"]

    class Meta:
        model = ReferenceMaterial
        fields = (*TEXT_FIELDS, "file", "expected_revision")
        widgets = {"short_description": forms.Textarea(attrs={"rows": 3}), "notes": forms.Textarea(attrs={"rows": 12}),
                   "file": PrivateFileInput(attrs={"accept": ".jpg,.jpeg,.png,.webp,.pdf,.txt,.md,.docx"})}

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.revision_conflict = False
        if project:
            if self.instance.pk and self.instance.project_id != project.pk:
                raise ValidationError(_("La referencia debe pertenecer al proyecto actual."))
            self.instance.project = project
        for key in ("notes", "short_description"):
            if key in self.fields:
                self.fields[key].strip = False
        if "expected_revision" in self.fields:
            self.fields["expected_revision"].required = not self.instance._state.adding
            self.initial["expected_revision"] = self.instance.revision

    def clean_file(self):
        value = self.cleaned_data.get("file")
        if value and not getattr(value, "_committed", False):
            self.validated_upload = validate_reference_upload(value)
        return value

    def clean(self):
        data = super().clean()
        project = data.get("project") or (self.instance.project if self.instance.project_id else None)
        if project:
            validate_project_action(project)
            if hasattr(self, "validated_upload"):
                check_upload_quota(project, self.validated_upload.size)
                kind = data.get("material_type")
                image = self.validated_upload.mime_type.startswith("image/")
                if kind == "IMAGE" and not image or kind == "DOCUMENT" and image:
                    self.add_error("file", _("El archivo no corresponde al tipo de referencia seleccionado."))
        if self.instance.pk and "expected_revision" in data:
            current = ReferenceMaterial.objects.filter(pk=self.instance.pk, project_id=self.instance.project_id).only("revision").first()
            try:
                if current is None:
                    raise ReferenceConflict()
                check_revision(current, data["expected_revision"])
            except ReferenceConflict:
                self.revision_conflict = True
                raise
        return data

    def save(self, commit=True, *, user=None, entity=None):
        obj = super().save(commit=False)
        if not commit:
            return obj
        data = {key: self.cleaned_data[key] for key in TEXT_FIELDS}
        file = self.cleaned_data.get("file")
        data["clear_file"] = file is False
        if file and not getattr(file, "_committed", False):
            data["file"] = file
        self.instance = (create_reference(obj.project, user=user, entity=entity, **data) if obj._state.adding else
                         update_reference(obj, expected_revision=self.cleaned_data["expected_revision"], user=user, **data))
        return self.instance


class AdminReferenceForm(ReferenceForm):
    class Meta(ReferenceForm.Meta):
        fields = ("project", *ReferenceForm.Meta.fields)


class AssociationForm(forms.ModelForm):
    class Meta:
        model = ReferenceAssociation
        fields = ("reference", *TARGETS, "description")
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, project, reference=None, entity=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project
        self.fields["reference"].queryset = ReferenceMaterial.objects.filter(project=project).only("id", "title").order_by("title", "pk")
        if reference:
            self.instance.reference = reference
            self.fields["reference"].disabled = True
            self.initial["reference"] = reference.pk
        for key, (label, *_) in TARGETS.items():
            query = local_project_relations(apps.get_model(label).objects.filter(project=project))
            title = "title" if key in ("manuscript_node", "worldbuilding_entry") else "name"
            fields = ["id", title] + (["node_type"] if key == "manuscript_node" else [])
            self.fields[key].queryset = query.only(*fields).order_by(title, "pk")
        if entity is not None:
            from .services import entity_field
            selected = entity_field(entity)
            for key in TARGETS:
                setattr(self.instance, key, entity if key == selected else None)
                self.fields.pop(key)

    def clean(self):
        data = super().clean()
        validate_project_action(self.project)
        return data


class ReferenceFilterForm(forms.Form):
    q = forms.CharField(label=_("Buscar"), required=False, max_length=200, widget=forms.TextInput(attrs={"type": "search"}))
    material_type = forms.ChoiceField(label=_("Tipo"), required=False, choices=[("", _("Todos")), *ReferenceMaterial.MaterialType.choices])
