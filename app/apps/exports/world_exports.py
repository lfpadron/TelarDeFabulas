"""Bounded, project-local capture. The caller holds the Project and style locks."""

from collections import defaultdict
from dataclasses import asdict
from types import SimpleNamespace
from urllib.parse import parse_qsl, unquote, urlsplit
import ipaddress
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, Q, Sum, Value
from django.db.models.functions import Coalesce, Length
from django.http import Http404
from django.utils.translation import gettext_lazy as _, override

from apps.characters.models import Character, CharacterDramaticRole, CharacterRelationship
from apps.core.permissions import Action, local_project_relations, validate_project_action
from apps.core.trees import build_tree_events, descendant_ids
from apps.geography.models import GeographicLocation
from apps.organizations.models import Organization, CharacterOrganizationMembership
from apps.references.models import ReferenceMaterial, ReferenceAssociation, TARGETS
from apps.references.selectors import local_associations
from apps.references.validators import safe_original_filename, validate_source_url
from apps.worldbuilding.models import WorldbuildingEntry

from .models import ExportJob
from .snapshots import ReferenceSection, capture_style_configuration, manifest_digest

ENTITY_MODELS = {
    "CHARACTER": Character, "GEOGRAPHIC_LOCATION": GeographicLocation, "ORGANIZATION": Organization,
    "WORLDBUILDING_ENTRY": WorldbuildingEntry, "REFERENCE_MATERIAL": ReferenceMaterial,
}
ENTITY_FIELDS = {
    "CHARACTER": ("name", "alias", "importance", "narrative_role", "custom_narrative_role", "residence_id",
        "physical_description", "psychological_description", "biography", "motivations", "goals", "fears", "virtues", "flaws", "character_arc", "notes"),
    "GEOGRAPHIC_LOCATION": ("name", "location_type", "custom_location_type", "short_description", "detailed_description", "parent_id", "position"),
    "ORGANIZATION": ("name", "organization_type", "custom_organization_type", "short_description", "detailed_description", "headquarters_id", "parent_id", "position"),
    "WORLDBUILDING_ENTRY": ("title", "category", "short_description", "content", "position"),
    "REFERENCE_MATERIAL": ("title", "material_type", "author", "publication_year_text", "publisher", "source_url", "short_description", "notes",
        "original_filename", "mime_type", "file_size"),
}
TARGET_KINDS = {"character": "CHARACTER", "geographic_location": "GEOGRAPHIC_LOCATION",
    "organization": "ORGANIZATION", "worldbuilding_entry": "WORLDBUILDING_ENTRY"}


def normalize_selection(scope_kind, entity_id=None, category="", include_descendants=False):
    if scope_kind not in ExportJob.ScopeKind.values or scope_kind == "MANUSCRIPT":
        raise ValidationError(_("Selecciona un alcance válido del universo narrativo."))
    if scope_kind in ENTITY_MODELS:
        if (isinstance(entity_id, bool) or len(str(entity_id)) > 19 or not str(entity_id).isascii()
                or not str(entity_id).isdigit() or not 0 < int(entity_id) <= 9223372036854775807):
            raise ValidationError(_("Selecciona una entidad válida."))
        entity_id = int(entity_id)
    elif entity_id is not None:
        raise ValidationError(_("Este alcance no admite una entidad individual."))
    if (scope_kind == "WORLDBUILDING_CATEGORY" and category not in WorldbuildingEntry.Category.values
            or scope_kind != "WORLDBUILDING_CATEGORY" and category):
        raise ValidationError(_("La categoría no corresponde al alcance seleccionado."))
    if not isinstance(include_descendants, bool) or include_descendants and scope_kind not in ("GEOGRAPHIC_LOCATION", "ORGANIZATION"):
        raise ValidationError(_("Solo una ubicación u organización individual admite elementos subordinados."))
    return {"scope_kind": str(scope_kind), "entity_id": entity_id, "category": category, "include_descendants": include_descendants}


class CaptureBudget:
    def __init__(self):
        self.seen = set()
        self.source_bytes = 0

    def read(self, query, fields):
        fields = tuple(dict.fromkeys(("id", *fields)))
        lengths = Value(0)
        for lookup in fields:
            model = query.model
            for part in lookup.split("__"):
                field = model._meta.get_field(part)
                model = field.related_model
            if isinstance(field, (models.CharField, models.TextField)):
                lengths += Coalesce(Length(lookup), 0)
        totals = query.order_by().aggregate(count=Count("pk"), characters=Sum(lengths))
        if totals["count"] > settings.EXPORT_SNAPSHOT_MAX_NODES or (totals["characters"] or 0) + self.source_bytes > settings.EXPORT_SNAPSHOT_MAX_BYTES:
            raise ValidationError(_("La selección supera los límites de exportación. Selecciona un alcance más pequeño."))
        rows = []
        for row in query.values(*fields).iterator(chunk_size=200):
            self.seen.add((query.model._meta.label, row["id"]))
            self.source_bytes += sum(len(value.encode("utf-8")) for value in row.values() if isinstance(value, str))
            if len(self.seen) > settings.EXPORT_SNAPSHOT_MAX_NODES or self.source_bytes > settings.EXPORT_SNAPSHOT_MAX_BYTES:
                raise ValidationError(_("La selección supera los límites de exportación. Selecciona un alcance más pequeño."))
            rows.append(row)
        return rows


def checked(query, valid=None):
    valid = local_project_relations(query) if valid is None else valid
    if query.exclude(pk__in=valid.values("pk")).exists():
        raise ValidationError(_("La selección contiene asociaciones entre proyectos. Requiere revisión."))
    return valid


def public_source_url(value):
    if not value:
        return ""
    try:
        validate_source_url(value)
        parts = urlsplit(value)
        host = (parts.hostname or "").lower()
        if parts.username or parts.password or host == "localhost" or host.endswith(".localhost"):
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass
        path = unquote(parts.path).lower()
        keys = [key.lower().replace("-", "_") for key, _ in parse_qsl(parts.query) + parse_qsl(parts.fragment)]
        if ("/private_media/" in path or "/media/" in path or "/download/" in path and "/projects/" in path
                or any(key in {"auth", "authorization", "key", "api_key", "apikey", "sig", "sas", "sessionid"} or any(secret in key for secret in
                    ("token", "signature", "credential", "password", "secret")) for key in keys)):
            return ""
        return value
    except (ValidationError, ValueError):
        return ""


def label_value(model, row, field_name):
    field = model._meta.get_field(field_name)
    value = row.get(field_name)
    if value is None or value == "":
        return ""
    value = dict(field.flatchoices).get(value, value) if field.choices else value
    return f"{str(field.verbose_name).capitalize()}: {value}"


def field_text(model, row, names):
    return "\n\n".join(text for key in names if (text := label_value(model, row, key)))


class WorldCapture:
    def __init__(self, project, selection):
        self.project, self.selection = project, selection
        self.budget = CaptureBudget()
        self.sections, self.render_bytes = [], 0
        self.selected = {key: [] for key in ENTITY_MODELS}
        self.trees = {}
        self.tree_order = {}
        self.related_references = defaultdict(list)
        self.associations = []
        self.relationships, self.memberships, self.roles = [], [], []

    def read_entities(self, kind, query):
        return self.budget.read(checked(query), ENTITY_FIELDS[kind])

    def tree(self, kind):
        if kind not in self.trees:
            rows = self.budget.read(ENTITY_MODELS[kind].objects.filter(project=self.project).order_by("position", "pk"),
                ("parent_id", "name", "position"))
            error = _("La jerarquía contiene un ciclo o un padre fuera del proyecto. Requiere revisión.")
            events = build_tree_events([SimpleNamespace(**row, pk=row["id"]) for row in rows], "node", error, error)
            depth, ordered = 0, []
            for event in events:
                if event["kind"] == "open":
                    ordered.append((event["node"].pk, depth))
                    depth += 1
                else:
                    depth -= 1
            self.trees[kind] = {row["id"]: row for row in rows}
            self.tree_order[kind] = ordered
        return self.trees[kind]

    def path(self, kind, pk):
        tree, names = self.tree(kind), []
        while pk is not None:
            if pk not in tree:
                raise ValidationError(_("La ruta de la entidad no pertenece al proyecto."))
            row = tree[pk]
            names.append(row["name"])
            pk = row["parent_id"]
        return " / ".join(reversed(names))

    def select(self):
        scope, entity_id = self.selection["scope_kind"], self.selection["entity_id"]
        all_scopes = {"CHARACTER": "CHARACTERS_ALL", "GEOGRAPHIC_LOCATION": "GEOGRAPHY_ALL", "ORGANIZATION": "ORGANIZATIONS_ALL",
            "WORLDBUILDING_ENTRY": "WORLDBUILDING_ALL", "REFERENCE_MATERIAL": "REFERENCES_ALL"}
        for kind, model in ENTITY_MODELS.items():
            if scope not in (kind, all_scopes[kind], "WORLD_COMPENDIUM") and not (kind == "WORLDBUILDING_ENTRY" and scope == "WORLDBUILDING_CATEGORY"):
                continue
            query = model.objects.filter(project=self.project)
            if scope == kind and not query.filter(pk=entity_id).exists():
                raise Http404(_("Entidad no encontrada en este proyecto."))
            if kind in ("GEOGRAPHIC_LOCATION", "ORGANIZATION"):
                tree = self.tree(kind)
                ids = set(tree)
                if scope == kind:
                    ids = descendant_ids(((pk, row["parent_id"]) for pk, row in tree.items()), entity_id) if self.selection["include_descendants"] else {entity_id}
                rows = {row["id"]: row for row in self.read_entities(kind, query.filter(pk__in=ids))}
                ordered = [(pk, depth) for pk, depth in self.tree_order[kind] if pk in rows]
                base_depth = ordered[0][1] if scope == kind else 0
                self.selected[kind] = [{**rows[pk], "depth": depth - base_depth} for pk, depth in ordered]
            else:
                if scope == kind:
                    query = query.filter(pk=entity_id)
                if scope == "WORLDBUILDING_CATEGORY":
                    query = query.filter(category=self.selection["category"])
                order = ("name", "pk") if kind == "CHARACTER" else ("category", "position", "pk") if kind == "WORLDBUILDING_ENTRY" else ("title", "pk")
                self.selected[kind] = self.read_entities(kind, query.order_by(*order))
        if not any(self.selected.values()):
            raise ValidationError(_("No hay entidades para exportar en este alcance."))

    def capture_connections(self):
        character_ids = [row["id"] for row in self.selected["CHARACTER"]]
        organization_ids = [row["id"] for row in self.selected["ORGANIZATION"]]
        if character_ids:
            self.roles = self.budget.read(CharacterDramaticRole.objects.filter(character_id__in=character_ids).order_by("role", "pk"),
                ("character_id", "role", "custom_role"))
            query = CharacterRelationship.objects.filter(project=self.project).filter(Q(source_character_id__in=character_ids) | Q(target_character_id__in=character_ids))
            self.relationships = self.budget.read(checked(query, query.filter(source_character__project=self.project, target_character__project=self.project)).order_by(
                "source_character__name", "target_character__name", "relationship_type", "pk"),
                ("source_character_id", "target_character_id", "source_character__name", "target_character__name", "relationship_type", "custom_relationship_type", "description", "is_reciprocal"))
        if character_ids or organization_ids:
            query = CharacterOrganizationMembership.objects.filter(Q(character_id__in=character_ids) | Q(organization_id__in=organization_ids))
            self.memberships = self.budget.read(checked(query, query.filter(character__project=self.project, organization__project=self.project)).order_by(
                "character__name", "organization__name", "pk"), ("character_id", "organization_id", "character__name", "organization__name",
                "position_title", "membership_status", "description", "joined_at_text", "left_at_text"))
        reference_ids = {row["id"] for row in self.selected["REFERENCE_MATERIAL"]}
        association_scope = Q(reference_id__in=reference_ids)
        for target, kind in TARGET_KINDS.items():
            association_scope |= Q(**{f"{target}_id__in": [row["id"] for row in self.selected[kind]]})
        query = ReferenceAssociation.objects.filter(association_scope)
        fields = ("reference_id", "description", *[f"{key}_id" for key in TARGETS],
            "manuscript_node__title", "character__name", "geographic_location__name", "organization__name", "worldbuilding_entry__title")
        self.associations = self.budget.read(checked(query, local_associations(query.filter(reference__project=self.project))).order_by("pk"), fields)
        reference_ids.update(row["reference_id"] for row in self.associations)
        loaded = {row["id"] for row in self.selected["REFERENCE_MATERIAL"]}
        if reference_ids - loaded:
            self.selected["REFERENCE_MATERIAL"].extend(self.read_entities("REFERENCE_MATERIAL",
                ReferenceMaterial.objects.filter(project=self.project, pk__in=reference_ids - loaded).order_by("title", "pk")))
        self.selected["REFERENCE_MATERIAL"].sort(key=lambda row: (row["title"], row["id"]))
        # Include all destinations of each captured reference, using metadata only.
        if reference_ids:
            query = ReferenceAssociation.objects.filter(reference_id__in=reference_ids)
            self.associations = self.budget.read(checked(query, local_associations(query.filter(reference__project=self.project))).order_by("pk"), fields)
        titles = {row["id"]: row["title"] for row in self.selected["REFERENCE_MATERIAL"]}
        for row in self.associations:
            target = next(key for key in TARGETS if row[f"{key}_id"] is not None)
            self.related_references[(target, row[f"{target}_id"])].append((titles[row["reference_id"]], row["description"]))

    def add(self, title, depth, content="", *, kind="", row=None):
        row = row or {}
        section = asdict(ReferenceSection(id=len(self.sections) + 1, title=str(title), depth=depth, content=str(content), source_kind=kind,
            source_id=row.get("id"), parent_id=row.get("parent_id"), position=row.get("position")))
        self.render_bytes += len(json.dumps(section, ensure_ascii=False).encode("utf-8"))
        if self.render_bytes > settings.EXPORT_SNAPSHOT_MAX_BYTES:
            raise ValidationError(_("El documento supera el tamaño máximo de exportación. Selecciona un alcance más pequeño."))
        self.sections.append(section)

    def references_for(self, target, pk):
        return "\n\n".join(f"{_('Referencia')}: {title}" + (f"\n{description}" if description else "")
            for title, description in self.related_references[(target, pk)])

    def relationship_text(self, row):
        kind = row["custom_relationship_type"] if row["relationship_type"] == "OTHER" else dict(CharacterRelationship.RelationshipType.choices)[row["relationship_type"]]
        arrow = "\u2194" if row["is_reciprocal"] else "\u2192"
        return f"{row['source_character__name']} {arrow} {row['target_character__name']}: {kind}" + (f"\n{row['description']}" if row["description"] else "")

    def characters(self, depth):
        rows = self.selected["CHARACTER"]
        if not rows:
            return
        self.add(_("Personajes"), depth)
        roles, memberships = defaultdict(list), defaultdict(list)
        for role in self.roles:
            roles[role["character_id"]].append(role["custom_role"] if role["role"] == "OTRO" and role["custom_role"] else str(dict(CharacterDramaticRole.DramaticRole.choices)[role["role"]]))
        for membership in self.memberships:
            memberships[membership["character_id"]].append(membership)
        for row in rows:
            names = [key for key in ENTITY_FIELDS["CHARACTER"] if key not in ("residence_id", "custom_narrative_role")]
            text = field_text(Character, row, names)
            if row["narrative_role"] == "OTRO" and row["custom_narrative_role"]:
                text += "\n\n" + label_value(Character, row, "custom_narrative_role")
            if roles[row["id"]]:
                text += f"\n\n{_('Papeles dramáticos')}: " + "; ".join(roles[row["id"]])
            if row["residence_id"]:
                text += f"\n\n{_('Residencia')}: {self.path('GEOGRAPHIC_LOCATION', row['residence_id'])}"
            text += "\n\n" + self.references_for("character", row["id"])
            self.add(row["name"], depth + 1, text.rstrip(), kind="CHARACTER", row=row)
            if memberships[row["id"]]:
                self.add(_("Afiliaciones"), depth + 2, "\n\n".join(f"{m['organization__name']}\n" + field_text(CharacterOrganizationMembership, m,
                    ("position_title", "membership_status", "joined_at_text", "left_at_text", "description")) for m in memberships[row["id"]]))
            if self.selection["scope_kind"] == "CHARACTER":
                groups = ((_('Relaciones salientes'), [r for r in self.relationships if not r["is_reciprocal"] and r["source_character_id"] == row["id"]]),
                    (_('Relaciones entrantes'), [r for r in self.relationships if not r["is_reciprocal"] and r["target_character_id"] == row["id"]]),
                    (_('Relaciones mutuas'), [r for r in self.relationships if r["is_reciprocal"]]))
                for title, relations in groups:
                    if relations:
                        self.add(title, depth + 2, "\n\n".join(self.relationship_text(r) for r in relations))
        if self.selection["scope_kind"] != "CHARACTER" and self.relationships:
            self.add(_("Relaciones entre personajes"), depth + 1, "\n\n".join(self.relationship_text(row) for row in self.relationships))

    def geography(self, depth):
        rows = self.selected["GEOGRAPHIC_LOCATION"]
        if not rows:
            return
        self.add(_("Geografía"), depth)
        ids = [row["id"] for row in rows]
        residents = self.budget.read(Character.objects.filter(project=self.project, residence_id__in=ids).order_by("name", "pk"), ("residence_id", "name"))
        organizations = self.budget.read(checked(Organization.objects.filter(project=self.project, headquarters_id__in=ids)).order_by("name", "pk"), ("headquarters_id", "name"))
        by_residence, by_headquarters = defaultdict(list), defaultdict(list)
        for item in residents:
            by_residence[item["residence_id"]].append(item["name"])
        for item in organizations:
            by_headquarters[item["headquarters_id"]].append(item["name"])
        for row in rows:
            text = field_text(GeographicLocation, row, ("location_type", "custom_location_type", "short_description", "detailed_description"))
            text += f"\n\n{_('Ruta geográfica')}: {self.path('GEOGRAPHIC_LOCATION', row['id'])}"
            for label, values in ((_('Habitantes'), by_residence[row["id"]]), (_('Organizaciones con sede aquí'), by_headquarters[row["id"]])):
                if values:
                    text += f"\n\n{label}:\n" + "\n".join(values)
            text += "\n\n" + self.references_for("geographic_location", row["id"])
            self.add(row["name"], depth + 1 + row["depth"], text.rstrip(), kind="GEOGRAPHIC_LOCATION", row=row)

    def organizations(self, depth):
        rows = self.selected["ORGANIZATION"]
        if not rows:
            return
        self.add(_("Organizaciones"), depth)
        memberships = defaultdict(lambda: defaultdict(list))
        for item in self.memberships:
            memberships[item["organization_id"]][(item["character__name"], item["character_id"])].append(item)
        tree = self.tree("ORGANIZATION")
        for row in rows:
            text = field_text(Organization, row, ("organization_type", "custom_organization_type", "short_description", "detailed_description"))
            text += f"\n\n{_('Ruta de organización')}: {self.path('ORGANIZATION', row['id'])}"
            if row["parent_id"]:
                text += f"\n\n{_('Organización superior')}: {tree[row['parent_id']]['name']}"
            if row["headquarters_id"]:
                text += f"\n\n{_('Sede')}: {self.path('GEOGRAPHIC_LOCATION', row['headquarters_id'])}"
            text += "\n\n" + self.references_for("organization", row["id"])
            level = depth + 1 + row["depth"]
            self.add(row["name"], level, text.rstrip(), kind="ORGANIZATION", row=row)
            if memberships[row["id"]]:
                entries = []
                for (name, _pk), records in memberships[row["id"]].items():
                    entries.append(name + "\n" + "\n\n".join(field_text(CharacterOrganizationMembership, item,
                        ("position_title", "membership_status", "joined_at_text", "left_at_text", "description")) for item in records))
                self.add(_("Integrantes"), level + 1, "\n\n".join(entries))

    def worldbuilding(self, depth):
        for category, title in WorldbuildingEntry.Category.choices:
            rows = [row for row in self.selected["WORLDBUILDING_ENTRY"] if row["category"] == category]
            if rows:
                self.add(title, depth)
                for row in rows:
                    text = field_text(WorldbuildingEntry, row, ("category", "short_description", "content"))
                    text += "\n\n" + self.references_for("worldbuilding_entry", row["id"])
                    self.add(row["title"], depth + 1, text.rstrip(), kind="WORLDBUILDING_ENTRY", row=row)

    def references(self, depth):
        rows = self.selected["REFERENCE_MATERIAL"]
        if not rows:
            return
        self.add(_("Referencias y materiales"), depth)
        associations = defaultdict(list)
        for item in self.associations:
            target = next(key for key in TARGETS if item[f"{key}_id"] is not None)
            field = "title" if target in ("manuscript_node", "worldbuilding_entry") else "name"
            name = item[f"{target}__{field}"] or f"#{item[f'{target}_id']}"
            associations[item["reference_id"]].append(f"{TARGETS[target][3]}: {name}" + (f"\n{item['description']}" if item["description"] else ""))
        for row in rows:
            row = {**row, "source_url": public_source_url(row["source_url"])}
            try:
                if row["original_filename"]:
                    safe_original_filename(row["original_filename"])
            except ValidationError:
                row["original_filename"] = row["mime_type"] = ""
            names = [name for name in ENTITY_FIELDS["REFERENCE_MATERIAL"] if name not in ("title", "file_size")]
            text = field_text(ReferenceMaterial, row, names)
            if associations[row["id"]]:
                text += f"\n\n{_('Entidades vinculadas')}:\n" + "\n\n".join(associations[row["id"]])
            self.add(row["title"], depth + 1, text, kind="REFERENCE_MATERIAL", row=row)


def build_world_manifest(project, style, *, selection, creator=""):
    validate_project_action(project, Action.EXPORT)
    selection = normalize_selection(**selection)
    with override(project.locale or project.language or "es-mx"):
        capture = WorldCapture(project, selection)
        capture.select()
        capture.capture_connections()
        title = str(dict(ExportJob.ScopeKind.choices)[selection["scope_kind"]])
        if selection["scope_kind"] in ENTITY_MODELS:
            selected = capture.selected[selection["scope_kind"]][0]
            title = selected.get("name", selected.get("title"))
        if selection["scope_kind"] == "WORLDBUILDING_CATEGORY":
            title = str(dict(WorldbuildingEntry.Category.choices)[selection["category"]])
        capture.add(title, 0, f"{_('Proyecto')}: {project.name}")
        for render in (capture.characters, capture.geography, capture.organizations, capture.worldbuilding, capture.references):
            render(1)
        manifest = {"schema_version": 2, "export_mode": "REFERENCE", "root_node_id": None, "selection": selection,
            "project_id": project.pk, "project_name": project.name, "title": title, "locale": project.locale or project.language or "es-mx",
            "creator": creator, "style_configuration": capture_style_configuration(style), "ordered_sections": capture.sections,
            "included_entity_count": sum(len(rows) for rows in capture.selected.values()), "included_scene_count": 0, "excluded_scene_count": 0}
    manifest_digest(manifest)
    return manifest
