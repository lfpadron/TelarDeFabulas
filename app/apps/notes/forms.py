from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.characters.models import Character
from apps.manuscripts.models import ManuscriptNode
from apps.projects.models import Project

from .models import Note


class NoteForm(forms.ModelForm):
    class Meta:
        model = Note
        fields = ("note_type", "title", "content", "status", "priority", "node", "character")
        labels = {
            "note_type": _("Tipo"),
            "title": _("Título"),
            "content": _("Contenido"),
            "status": _("Estado"),
            "priority": _("Prioridad"),
            "node": _("Nodo de manuscrito"),
            "character": _("Personaje"),
        }
        widgets = {
            "content": forms.Textarea(attrs={"rows": 8}),
        }

    def __init__(self, *args, project=None, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)
        if project is not None:
            self.instance.project = project
            self.fields["node"].queryset = ManuscriptNode.objects.filter(project=project).order_by("parent_id", "position", "title")
            self.fields["character"].queryset = Character.objects.filter(project=project).order_by("name")
        else:
            self.fields["node"].queryset = ManuscriptNode.objects.none()
            self.fields["character"].queryset = Character.objects.none()
        self.fields["node"].required = False
        self.fields["character"].required = False

    def clean(self):
        cleaned_data = super().clean()
        node = cleaned_data.get("node")
        character = cleaned_data.get("character")
        if self.project and self.project.status in (
            Project.ProjectStatus.DELETED,
            Project.ProjectStatus.PENDING_DELETION,
        ):
            raise ValidationError(_("No se pueden crear o editar notas en proyectos eliminados o pendientes de borrado."))
        if node and node.project_id != self.project.id:
            raise ValidationError({"node": _("El nodo debe pertenecer al mismo proyecto que la nota.")})
        if character and character.project_id != self.project.id:
            raise ValidationError({"character": _("El personaje debe pertenecer al mismo proyecto que la nota.")})
        return cleaned_data

    def save(self, commit=True):
        note = super().save(commit=False)
        note.project = self.project
        if commit:
            note.save()
        return note
