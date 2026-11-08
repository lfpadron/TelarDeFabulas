from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import validate_project_action

from .models import ManuscriptNode
from .hierarchy import CURRENT_TYPES
from .services import get_valid_parent_queryset, validate_parent_for_node


class ManuscriptNodeForm(forms.ModelForm):
    class Meta:
        model = ManuscriptNode
        fields = (
            "parent",
            "node_type",
            "title",
            "short_description",
            "content",
            "status",
            "position",
            "is_publishable",
        )
        labels = {
            "parent": _("Padre"),
            "node_type": _("Tipo de nodo"),
            "title": _("Título"),
            "short_description": _("Descripción breve"),
            "content": _("Contenido"),
            "status": _("Estado"),
            "position": _("Posición"),
            "is_publishable": _("Es publicable"),
        }
        widgets = {
            "short_description": forms.Textarea(attrs={"rows": 3}),
            "content": forms.Textarea(attrs={"rows": 10}),
        }

    def __init__(self, *args, project=None, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)
        if project is not None:
            self.instance.project = project
        if self.instance.pk:
            # Moving has its own form; text edits never submit an old parent or position.
            for field in ("parent", "node_type", "position"):
                self.fields.pop(field)
            kind = self.instance.node_type
        else:
            kind = self.data.get("node_type") if self.is_bound else self.initial.get("node_type", "BOOK")
            self.fields["node_type"].choices = [(value, label) for value, label in ManuscriptNode.NodeType.choices if value in CURRENT_TYPES]
            if project is not None:
                self.fields["parent"].queryset = get_valid_parent_queryset(project, node_type=kind)
            else:
                self.fields["parent"].queryset = ManuscriptNode.objects.none()
            self.fields["parent"].required = kind != "BOOK"
            self.fields["position"].required = False
        self.fields["title"].required = kind != "SCENE"

    def clean(self):
        cleaned_data = super().clean()
        parent = cleaned_data.get("parent")
        if self.project:
            validate_project_action(self.project)
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
            if node.pk:
                node.save(update_fields=[*self.fields, "updated_at"])
            else:
                node.save()
        return node


class ManuscriptNodeMoveForm(forms.Form):
    parent = forms.ModelChoiceField(
        label=_("Nuevo padre"),
        queryset=ManuscriptNode.objects.none(),
        required=False,
        empty_label=_("Raíz del manuscrito"),
    )
    position = forms.IntegerField(
        label=_("Nueva posición"),
        required=False,
        min_value=1,
        help_text=_("Déjalo vacío para mover el nodo al final de sus hermanos."),
    )

    def __init__(self, *args, project=None, node=None, **kwargs):
        self.project = project
        self.node = node
        super().__init__(*args, **kwargs)
        if project is not None:
            self.fields["parent"].queryset = get_valid_parent_queryset(project, node)
        if node is not None:
            self.fields["parent"].required = node.node_type != "BOOK"

    def clean(self):
        cleaned_data = super().clean()
        parent = cleaned_data.get("parent")
        if self.project:
            validate_project_action(self.project)
        if parent and self.project and parent.project_id != self.project.id:
            raise ValidationError({"parent": _("El nuevo padre debe pertenecer al mismo proyecto.")})
        if parent and self.node and parent.pk == self.node.pk:
            raise ValidationError({"parent": _("Un nodo no puede moverse dentro de sí mismo.")})
        if parent and self.node and parent.pk in self.node.descendant_ids():
            raise ValidationError({"parent": _("Un nodo no puede moverse debajo de uno de sus descendientes.")})
        if self.node and "parent" in cleaned_data:
            validate_parent_for_node(self.node, parent)
        return cleaned_data
