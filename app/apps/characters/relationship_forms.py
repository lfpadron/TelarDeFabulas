from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import local_project_relations
from .models import Character, CharacterRelationship
from .relationship_services import EDITABLE_FIELDS, create_relationship, update_relationship


class CharacterRelationshipForm(forms.ModelForm):
    class Meta:
        model = CharacterRelationship
        fields = EDITABLE_FIELDS
        widgets = {"description": forms.Textarea(attrs={"rows": 8})}

    def __init__(self, *args, project=None, source_character=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project:
            if self.instance.pk and self.instance.project_id != project.pk:
                raise ValidationError(_("La relación debe pertenecer al proyecto actual."))
            self.instance.project = project
        if source_character:
            if source_character.project_id != self.instance.project_id:
                raise ValidationError(_("El personaje debe pertenecer al proyecto actual."))
            self.initial["source_character"] = source_character.pk
        if "description" in self.fields:
            self.fields["description"].strip = False
        if self.instance.project_id:
            choices = local_project_relations(Character.objects.filter(project_id=self.instance.project_id)).only("id", "name").order_by("name", "pk")
            for key in ("source_character", "target_character"):
                if key in self.fields:
                    self.fields[key].queryset = choices
        elif project is None:
            for key in ("source_character", "target_character"):
                self.fields[key].queryset = Character.objects.none()

    def save(self, commit=True, *, user=None):
        obj = super().save(commit=False)
        if not commit:
            return obj
        data = {key: getattr(obj, key) for key in EDITABLE_FIELDS}
        self.instance = (create_relationship(obj.project, user=user, **data) if obj._state.adding else
                         update_relationship(obj, user=user, **data))
        return self.instance


class AdminCharacterRelationshipForm(CharacterRelationshipForm):
    class Meta(CharacterRelationshipForm.Meta):
        fields = ("project", *EDITABLE_FIELDS)

    def __init__(self, *args, **kwargs):
        # The admin supplies already owner-scoped field querysets; narrow them by project.
        data = args[0] if args else kwargs.get("data")
        instance = kwargs.get("instance")
        scoped = {key: self.base_fields[key].queryset for key in ("source_character", "target_character") if key in self.base_fields}
        super().__init__(*args, **kwargs)
        project_id = instance.project_id if instance and instance.pk else (data.get("project") if data is not None else None)
        for key, query in scoped.items():
            if project_id is not None:
                query = query.filter(project_id=project_id) if str(project_id).isascii() and str(project_id).isdigit() and len(str(project_id)) <= 18 else query.none()
            self.fields[key].queryset = local_project_relations(query).only("id", "name").order_by("name", "pk")
