from django import forms
from django.utils.translation import gettext_lazy as _

from .models import StyleTemplate


class StyleTemplateForm(forms.ModelForm):
    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.instance.user = user
            self.instance.is_system = False

    class Meta:
        model = StyleTemplate
        fields = (
            "name",
            "description",
            "font_category",
            "font_heading",
            "font_body",
            "heading_size",
            "body_size",
            "line_spacing",
            "paragraph_spacing",
            "margin_top",
            "margin_bottom",
            "margin_left",
            "margin_right",
            "text_alignment",
            "first_line_indent",
            "scene_separator",
            "include_page_numbers",
            "include_table_of_contents",
            "config_json",
        )
        labels = {
            "name": _("Nombre"),
            "description": _("Descripción"),
            "font_category": _("Categoría tipográfica"),
            "font_heading": _("Fuente de títulos"),
            "font_body": _("Fuente de cuerpo"),
            "heading_size": _("Tamaño de títulos"),
            "body_size": _("Tamaño de cuerpo"),
            "line_spacing": _("Interlineado"),
            "paragraph_spacing": _("Espaciado entre párrafos"),
            "margin_top": _("Margen superior"),
            "margin_bottom": _("Margen inferior"),
            "margin_left": _("Margen izquierdo"),
            "margin_right": _("Margen derecho"),
            "text_alignment": _("Alineación de texto"),
            "first_line_indent": _("Sangría de primera línea"),
            "scene_separator": _("Separador de escena"),
            "include_page_numbers": _("Incluir números de página"),
            "include_table_of_contents": _("Incluir tabla de contenidos"),
            "config_json": _("Configuración JSON"),
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "config_json": forms.Textarea(attrs={"rows": 5}),
        }

    def save(self, commit=True):
        style = super().save(commit=False)
        if commit:
            style.save()
        return style
