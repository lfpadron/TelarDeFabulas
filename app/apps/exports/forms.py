from uuid import uuid4

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.manuscripts.models import ManuscriptNode
from apps.core.permissions import Action, can_export_project, validate_project_action
from apps.styles.models import StyleTemplate

from .models import ExportJob


class ExportJobForm(forms.ModelForm):
    request_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid4)
    selection_confirmation = forms.CharField(widget=forms.HiddenInput, required=False)
    export_mode = forms.ChoiceField(label=_("Modalidad"), choices=ExportJob.ExportMode.choices[:2],
                                    widget=forms.RadioSelect, initial="WORK", required=False)
    class Meta:
        model = ExportJob
        fields = ("root_node", "style_template", "format", "export_mode", "notify_by_email")
        labels = {
            "root_node": _("Nodo raíz"),
            "style_template": _("Estilo"),
            "format": _("Formato"),
        }

    def __init__(self, *args, user=None, project=None, **kwargs):
        self.user = user
        self.project = project
        super().__init__(*args, **kwargs)
        if user is not None:
            self.instance.user = user
        if project is not None:
            self.instance.project = project
            self.fields["root_node"].queryset = ManuscriptNode.objects.filter(project=project).visible().only("id", "project_id", "title", "node_type", "position").order_by(
                "parent_id",
                "position",
                "title",
            )
        else:
            self.fields["root_node"].queryset = ManuscriptNode.objects.none()

        if user is not None:
            self.fields["style_template"].queryset = StyleTemplate.objects.filter(
                Q(is_system=True) | Q(user=user)
            ).order_by("-is_system", "name")
        else:
            self.fields["style_template"].queryset = StyleTemplate.objects.none()

        self.fields["root_node"].required = False
        self.fields["format"].choices = (
            (ExportJob.ExportFormat.MARKDOWN, _("Markdown")),
            (ExportJob.ExportFormat.DOCX, _("DOCX")),
            (ExportJob.ExportFormat.PDF, _("PDF")),
        )
        self.initial["format"] = ExportJob.ExportFormat.MARKDOWN

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data["export_mode"] = cleaned_data.get("export_mode") or "WORK"
        root_node = cleaned_data.get("root_node")
        style_template = cleaned_data.get("style_template")

        if self.project:
            validate_project_action(self.project, Action.EXPORT)
            if self.user and not can_export_project(self.user, self.project):
                raise ValidationError(_("Solo puedes exportar proyectos propios."))

        if root_node and self.project and root_node.project_id != self.project.id:
            raise ValidationError({"root_node": _("El nodo raíz debe pertenecer al mismo proyecto.")})

        if style_template and self.user and not (style_template.is_system or style_template.user_id == self.user.id):
            raise ValidationError({"style_template": _("El estilo debe ser del sistema o propio.")})

        return cleaned_data

    def save(self, commit=True):
        from .job_services import request_export

        if not commit:
            raise ValueError("Export requests must be saved atomically with their snapshot.")
        return request_export(user=self.user, project=self.project,
                              style_template=self.cleaned_data["style_template"],
                              root_node=self.cleaned_data["root_node"],
                              export_format=self.cleaned_data["format"], export_mode=self.cleaned_data["export_mode"],
                              request_key=self.cleaned_data["request_key"],
                              notify_by_email=self.cleaned_data["notify_by_email"],
                              expected_counts=getattr(self, "expected_counts", None))


class ExportPreviewForm(forms.Form):
    export_mode = forms.ChoiceField(label=_("Modalidad"), choices=ExportJob.ExportMode.choices[:2],
                                    widget=forms.RadioSelect, initial="WORK", required=False)
    root_node = forms.ModelChoiceField(
        label=_("Nodo raíz"),
        queryset=ManuscriptNode.objects.none(),
        required=False,
    )
    style_template = forms.ModelChoiceField(
        label=_("Estilo"),
        queryset=StyleTemplate.objects.none(),
        required=True,
    )

    def __init__(self, *args, user=None, project=None, **kwargs):
        self.user = user
        self.project = project
        super().__init__(*args, **kwargs)
        if project is not None:
            self.fields["root_node"].queryset = ManuscriptNode.objects.filter(project=project).visible().only("id", "project_id", "title", "node_type", "position").order_by(
                "parent_id",
                "position",
                "title",
            )
        if user is not None:
            self.fields["style_template"].queryset = StyleTemplate.objects.filter(
                Q(is_system=True) | Q(user=user)
            ).order_by("-is_system", "name")

    def clean(self):
        cleaned_data = super().clean()
        cleaned_data["export_mode"] = cleaned_data.get("export_mode") or "WORK"
        root_node = cleaned_data.get("root_node")
        style_template = cleaned_data.get("style_template")

        if self.project:
            validate_project_action(self.project, Action.EXPORT)
            if self.user and not can_export_project(self.user, self.project):
                raise ValidationError(_("Solo puedes previsualizar proyectos propios."))

        if root_node and self.project and root_node.project_id != self.project.id:
            raise ValidationError({"root_node": _("El nodo raíz debe pertenecer al mismo proyecto.")})

        if style_template and self.user and not (style_template.is_system or style_template.user_id == self.user.id):
            raise ValidationError({"style_template": _("El estilo debe ser del sistema o propio.")})

        return cleaned_data
