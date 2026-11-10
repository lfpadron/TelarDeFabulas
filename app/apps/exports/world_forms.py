from uuid import uuid4

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.permissions import can_export_project
from apps.styles.models import StyleTemplate
from apps.worldbuilding.models import WorldbuildingEntry
from .models import ExportJob
from .world_exports import ENTITY_MODELS, normalize_selection

SCOPE_FIELDS = {"CHARACTER": "character", "GEOGRAPHIC_LOCATION": "location", "ORGANIZATION": "organization",
    "WORLDBUILDING_ENTRY": "entry", "REFERENCE_MATERIAL": "reference"}
SCOPE_GROUPS = (
    (_("Personajes"), ("CHARACTERS_ALL", "CHARACTER")),
    (_("Geografía"), ("GEOGRAPHY_ALL", "GEOGRAPHIC_LOCATION")),
    (_("Organizaciones"), ("ORGANIZATIONS_ALL", "ORGANIZATION")),
    (_("Política, religión e historia"), ("WORLDBUILDING_ALL", "WORLDBUILDING_CATEGORY", "WORLDBUILDING_ENTRY")),
    (_("Referencias"), ("REFERENCES_ALL", "REFERENCE_MATERIAL")),
    (_("Compendio completo"), ("WORLD_COMPENDIUM",)),
)


class WorldExportForm(forms.Form):
    request_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid4)
    scope_kind = forms.ChoiceField(label=_("¿Qué deseas exportar?"), initial="WORLD_COMPENDIUM",
        choices=[(label, [(key, dict(ExportJob.ScopeKind.choices)[key]) for key in keys]) for label, keys in SCOPE_GROUPS])
    character = forms.ModelChoiceField(label=_("Personaje"), queryset=ENTITY_MODELS["CHARACTER"].objects.none(), required=False)
    location = forms.ModelChoiceField(label=_("Ubicación"), queryset=ENTITY_MODELS["GEOGRAPHIC_LOCATION"].objects.none(), required=False)
    organization = forms.ModelChoiceField(label=_("Organización"), queryset=ENTITY_MODELS["ORGANIZATION"].objects.none(), required=False)
    entry = forms.ModelChoiceField(label=_("Entrada"), queryset=WorldbuildingEntry.objects.none(), required=False)
    reference = forms.ModelChoiceField(label=_("Referencia"), queryset=ENTITY_MODELS["REFERENCE_MATERIAL"].objects.none(), required=False)
    category = forms.ChoiceField(label=_("Categoría"), choices=[("", "---------"), *WorldbuildingEntry.Category.choices], required=False)
    include_descendants = forms.BooleanField(label=_("Incluir elementos subordinados"), required=False)
    format = forms.ChoiceField(label=_("Formato"), choices=[(key, label) for key, label in ExportJob.ExportFormat.choices if key in ("MARKDOWN", "DOCX", "PDF")], initial="MARKDOWN")
    style_template = forms.ModelChoiceField(label=_("Estilo"), queryset=StyleTemplate.objects.none())
    notify_by_email = forms.BooleanField(label=_("Notificarme por correo cuando termine"), required=False, initial=True)

    def __init__(self, *args, user=None, project=None, **kwargs):
        self.user, self.project = user, project
        super().__init__(*args, **kwargs)
        for scope, key in SCOPE_FIELDS.items():
            self.fields[key].widget.attrs["data-scopes"] = scope
            if project is not None:
                title = "title" if key in ("entry", "reference") else "name"
                self.fields[key].queryset = ENTITY_MODELS[scope].objects.filter(project=project).only("id", title).order_by(title, "pk")
        self.fields["category"].widget.attrs["data-scopes"] = "WORLDBUILDING_CATEGORY"
        self.fields["include_descendants"].widget.attrs["data-scopes"] = "GEOGRAPHIC_LOCATION ORGANIZATION"
        if user is not None:
            self.fields["style_template"].queryset = StyleTemplate.objects.filter(Q(is_system=True) | Q(user=user)).order_by("-is_system", "name", "pk")
            if not self.is_bound:
                self.initial["style_template"] = self.fields["style_template"].queryset.first()

    def clean(self):
        data = super().clean()
        if not can_export_project(self.user, self.project):
            raise ValidationError(_("Solo puedes exportar un proyecto propio disponible."))
        scope = data.get("scope_kind")
        if scope is None:
            return data
        active = SCOPE_FIELDS.get(scope)
        for key in SCOPE_FIELDS.values():
            if key != active and data.get(key) is not None:
                self.add_error(key, _("Esta entidad no corresponde al alcance seleccionado."))
        entity = data.get(active) if active else None
        self.selection = normalize_selection(scope, entity.pk if entity else None, data.get("category", ""), data.get("include_descendants", False))
        return data

    def save(self):
        from .job_services import request_export
        return request_export(user=self.user, project=self.project, style_template=self.cleaned_data["style_template"],
            export_mode="REFERENCE", export_format=self.cleaned_data["format"], request_key=self.cleaned_data["request_key"],
            notify_by_email=self.cleaned_data["notify_by_email"], **self.selection)
