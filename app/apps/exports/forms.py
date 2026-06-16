from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.manuscripts.models import ManuscriptNode
from apps.projects.models import Project
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
        )

    def clean(self):
        cleaned_data = super().clean()
        root_node = cleaned_data.get("root_node")
        style_template = cleaned_data.get("style_template")

        if self.project and self.project.status == Project.ProjectStatus.DELETED:
            raise ValidationError(_("No se puede exportar un proyecto eliminado."))

        if self.project and self.project.status == Project.ProjectStatus.PENDING_DELETION:
            raise ValidationError(_("No se puede exportar un proyecto pendiente de borrado."))

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
