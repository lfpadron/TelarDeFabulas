from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.manuscripts.models import ManuscriptNode
from apps.core.permissions import Action, can_export_project, validate_project_action
from apps.styles.models import StyleTemplate

from .models import ExportJob


class ExportJobForm(forms.ModelForm):
    class Meta:
        model = ExportJob
        fields = ("root_node", "style_template", "format")
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
            self.fields["root_node"].queryset = ManuscriptNode.objects.filter(project=project).order_by(
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
            (ExportJob.ExportFormat.HTML, _("HTML")),
            (ExportJob.ExportFormat.DOCX, _("DOCX")),
            (ExportJob.ExportFormat.PDF, _("PDF")),
            (ExportJob.ExportFormat.EPUB, _("EPUB")),
        )

    def clean(self):
        cleaned_data = super().clean()
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
        export_job = super().save(commit=False)
        export_job.user = self.user
        export_job.project = self.project
        if commit:
            export_job.full_clean()
            export_job.save()
        return export_job


class ExportPreviewForm(forms.Form):
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
            self.fields["root_node"].queryset = ManuscriptNode.objects.filter(project=project).order_by(
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
