from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.projects.models import Project

from .models import ManuscriptNode


class ManuscriptNodeForm(forms.ModelForm):
    class Meta:
        model = ManuscriptNode
        fields = (
            "parent",
            "node_type",
            "title",
            "content",
            "status",
            "position",
            "is_publishable",
        )
        labels = {
            "parent": _("Padre"),
            "node_type": _("Tipo de nodo"),
            "title": _("Título"),
            "content": _("Contenido"),
            "status": _("Estado"),
            "position": _("Posición"),
            "is_publishable": _("Es publicable"),
        }
        widgets = {
            "content": forms.Textarea(attrs={"rows": 10}),
        }

    def __init__(self, *args, project=None, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)
        if project is not None:
            self.instance.project = project
        parent_queryset = ManuscriptNode.objects.none()
        if project is not None:
            parent_queryset = ManuscriptNode.objects.filter(project=project).order_by("parent_id", "position", "title")
        if self.instance.pk:
            parent_queryset = parent_queryset.exclude(pk__in={self.instance.pk, *self.instance.descendant_ids()})
        self.fields["parent"].queryset = parent_queryset
        self.fields["parent"].required = False
        self.fields["position"].required = False

    def clean(self):
        cleaned_data = super().clean()
        parent = cleaned_data.get("parent")
        if self.project and self.project.status in (
            Project.ProjectStatus.DELETED,
            Project.ProjectStatus.PENDING_DELETION,
        ):
            raise ValidationError(_("No se pueden crear o editar nodos en proyectos eliminados o pendientes de borrado."))
        if parent and parent.project_id != self.project.id:
            raise ValidationError({"parent": _("El nodo padre debe pertenecer al mismo proyecto.")})
        if parent and self.instance.pk and parent.pk == self.instance.pk:
            raise ValidationError({"parent": _("Un nodo no puede ser su propio padre.")})
        if parent and self.instance.pk and parent.pk in self.instance.descendant_ids():
            raise ValidationError({"parent": _("Un nodo no puede tener como padre a uno de sus descendientes.")})
        return cleaned_data

    def save(self, commit=True):
        node = super().save(commit=False)
        node.project = self.project
        if commit:
            node.save()
        return node
