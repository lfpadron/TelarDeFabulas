import hashlib
import json
from dataclasses import dataclass, fields
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import F, Q, Sum
from django.db.models.functions import Length
from django.http import Http404
from django.utils.translation import gettext_lazy as _, override

from apps.manuscripts.hierarchy import ordered_tree
from apps.manuscripts.models import ManuscriptNode, SceneVersion


@dataclass(frozen=True)
class StyleConfiguration:
    id: int
    name: str
    font_category: str
    font_heading: str
    font_body: str
    heading_size: str
    body_size: str
    line_spacing: str
    paragraph_spacing: str
    margin_top: str
    margin_bottom: str
    margin_left: str
    margin_right: str
    text_alignment: str
    first_line_indent: str
    scene_separator: str
    include_table_of_contents: bool
    include_page_numbers: bool
    config_json: dict


@dataclass(frozen=True)
class NarrativeNode:
    node_id: int
    node_type: str
    title: str
    display_title: str
    short_description: str
    position: int | None
    parent_id: int | None
    depth: int
    selected_version_id: int | None
    revision: int | None
    editorial_stage: str | None
    content: str

    @property
    def id(self):
        return self.node_id

    @property
    def export_depth(self):
        return self.depth

    @property
    def export_content(self):
        return self.content


@dataclass(frozen=True)
class NarrativeDocument:
    title: str
    locale: str
    creator: str
    style: StyleConfiguration
    nodes: tuple
    included_scene_count: int
    excluded_scene_count: int
    selection_truncated: bool = False


@dataclass(frozen=True)
class ReferenceSection:
    id: int
    title: str
    depth: int
    content: str
    source_kind: str = ""
    source_id: int | None = None
    parent_id: int | None = None
    position: int | None = None
    node_type = "REFERENCE"

    @property
    def display_title(self):
        return self.title

    @property
    def export_depth(self):
        return self.depth

    @property
    def export_content(self):
        return self.content


def capture_style_configuration(style):
    data = {field.name: getattr(style, field.name) for field in fields(StyleConfiguration)}
    return {key: str(value) if isinstance(value, Decimal) else value for key, value in data.items()}


def manifest_digest(manifest, *, enforce_limit=True):
    digest, size = hashlib.sha256(), 0
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for piece in encoder.iterencode(manifest):
        encoded = piece.encode("utf-8")
        size += len(encoded)
        if enforce_limit and size > settings.EXPORT_SNAPSHOT_MAX_BYTES:
            raise ValidationError(_("La selección supera el tamaño máximo de exportación. Selecciona un libro o capítulo más pequeño."))
        digest.update(encoded)
    return digest.hexdigest(), size


def select_structure(project, root_node=None, *, mode="WORK"):
    if mode not in ("WORK", "FINAL"):
        raise ValidationError(_("Modalidad de exportación no válida."))
    # Only metadata: scene text is loaded in one separate, selected-version query.
    nodes = list(ManuscriptNode.objects.filter(project=project).only(
        "id", "project_id", "parent_id", "node_type", "title", "position", "created_at",
    ).order_by("position", "created_at", "pk")[:settings.EXPORT_SNAPSHOT_MAX_NODES + 1])
    if len(nodes) > settings.EXPORT_SNAPSHOT_MAX_NODES:
        raise ValidationError(_("El proyecto supera el límite de nodos para exportación."))
    if root_node is not None:
        children = {}
        for node in nodes:
            children.setdefault(node.parent_id, []).append(node.pk)
        if root_node.pk not in {node.pk for node in nodes}:
            raise Http404(_("Nodo raíz no encontrado."))
        included, pending = set(), [root_node.pk]
        while pending:
            pk = pending.pop()
            if pk not in included:
                included.add(pk)
                pending.extend(children.get(pk, ()))
        nodes = [node for node in nodes if node.pk in included]
    scenes = [node.pk for node in nodes if node.node_type == "SCENE"]
    versions = SceneVersion.objects.filter(scene_id__in=scenes)
    if mode == "FINAL":
        versions = versions.filter(is_current_final=True)
    else:
        versions = versions.filter(Q(is_current_final=True) | Q(pk=F("scene__current_draft_version_id"), editorial_stage__in=["DRAFT", "REVIEW"]))
    selected, drafts = {}, {}
    for row in versions.values("id", "scene_id", "revision", "editorial_stage", "is_current_final", "scene__current_draft_version_id"):
        if row["is_current_final"]:
            selected[row["scene_id"]] = row
        if row["id"] == row["scene__current_draft_version_id"] and row["editorial_stage"] != "FINAL":
            drafts[row["scene_id"]] = row
    if mode == "WORK":
        selected.update(drafts)
        return ordered_tree(nodes), selected, len(scenes), 0
    if not selected:
        raise ValidationError(_("No hay escenas con versión definitiva vigente en esta selección."))
    by_id = {node.pk: node for node in nodes}
    keep = set(selected)
    for scene_id in selected:
        parent_id, seen = by_id[scene_id].parent_id, {scene_id}
        while parent_id in by_id:
            if parent_id in seen or by_id[parent_id].node_type not in ("BOOK", "PART", "CHAPTER"):
                raise ValidationError(_("La selección definitiva contiene una jerarquía heredada incompatible."))
            seen.add(parent_id)
            keep.add(parent_id)
            parent_id = by_id[parent_id].parent_id
    return ordered_tree([node for node in nodes if node.pk in keep]), selected, len(selected), len(scenes) - len(selected)


def build_manifest(project, style, *, root_node=None, mode="WORK", creator="", max_nodes=None):
    ordered, versions, included, excluded = select_structure(project, root_node, mode=mode)
    limited = max_nodes is not None and len(ordered) > max_nodes
    if max_nodes is not None:
        ordered = ordered[:max_nodes]
    node_ids = [node.pk for node, _ in ordered]
    version_ids = [versions[pk]["id"] for pk in node_ids if pk in versions]
    source_nodes = ManuscriptNode.objects.filter(pk__in=node_ids)
    source_versions = SceneVersion.objects.filter(pk__in=version_ids)
    characters = source_nodes.aggregate(n=Sum(Length("title") + Length("short_description")))["n"] or 0
    if mode == "WORK":
        characters += source_nodes.exclude(node_type="SCENE").aggregate(n=Sum(Length("content")))["n"] or 0
    characters += source_versions.aggregate(n=Sum(Length("content")))["n"] or 0
    if characters > settings.EXPORT_SNAPSHOT_MAX_BYTES:
        raise ValidationError(_("El texto seleccionado supera el tamaño máximo de exportación."))
    metadata = {row["id"]: row for row in source_nodes.values("id", "short_description")}
    legacy = dict(source_nodes.exclude(node_type="SCENE").values_list("id", "content")) if mode == "WORK" else {}
    text = dict(source_versions.values_list("id", "content"))
    style_data = capture_style_configuration(style)
    entries = []
    with override(project.locale or "es-mx"):
        for node, depth in ordered:
            version = versions.get(node.pk)
            entries.append({
                "node_id": node.pk, "node_type": node.node_type, "title": node.title,
                "display_title": str(node.display_title), "short_description": metadata[node.pk]["short_description"],
                "position": node.position, "parent_id": node.parent_id, "depth": depth,
                "selected_version_id": version["id"] if version else None,
                "revision": version["revision"] if version else None,
                "editorial_stage": version["editorial_stage"] if version else None,
                "content": text[version["id"]] if version else legacy.get(node.pk, ""),
            })
        title = str(root_node.display_title) if root_node else project.name
    manifest = {
        "schema_version": 1, "project_id": project.pk, "root_node_id": root_node.pk if root_node else None,
        "export_mode": mode, "project_name": project.name, "title": title,
        "locale": project.locale or project.language or "es-mx", "creator": creator,
        "style_configuration": style_data, "ordered_nodes": entries,
        "selected_versions": [{"scene_id": entry["node_id"], "version_id": entry["selected_version_id"], "revision": entry["revision"]} for entry in entries if entry["selected_version_id"]],
        "included_scene_count": included, "excluded_scene_count": excluded, "preview_limited": limited,
    }
    manifest_digest(manifest)
    return manifest


def document_from_manifest(manifest):
    if manifest.get("schema_version") == 2 and manifest.get("export_mode") == "REFERENCE":
        return NarrativeDocument(title=manifest["title"], locale=manifest["locale"], creator=manifest["creator"],
            style=StyleConfiguration(**manifest["style_configuration"]),
            nodes=tuple(ReferenceSection(**section) for section in manifest["ordered_sections"]),
            included_scene_count=0, excluded_scene_count=0)
    if manifest.get("schema_version") != 1:
        raise ValidationError(_("La versión del snapshot no es compatible."))
    return NarrativeDocument(
        title=manifest["title"], locale=manifest["locale"], creator=manifest["creator"],
        style=StyleConfiguration(**manifest["style_configuration"]),
        nodes=tuple(NarrativeNode(**node) for node in manifest["ordered_nodes"]),
        included_scene_count=manifest["included_scene_count"], excluded_scene_count=manifest["excluded_scene_count"],
        selection_truncated=manifest.get("preview_limited", False),
    )


def get_export_document(job):
    from .models import ExportSnapshot

    try:
        snapshot = ExportSnapshot.objects.get(export_job_id=job.pk)
    except ExportSnapshot.DoesNotExist:
        raise ValidationError(_("Esta exportación histórica no tiene snapshot. Conserva su archivo o solicita una nueva exportación.")) from None
    checksum, size = manifest_digest(snapshot.manifest_json, enforce_limit=False)
    manifest = snapshot.manifest_json
    if (checksum != snapshot.checksum or size != snapshot.size_bytes
            or manifest["project_id"] != job.project_id or manifest["export_mode"] != job.export_mode
            or manifest["user_id"] != job.user_id or manifest["format"] != job.format
            or manifest["style_configuration"]["id"] != job.style_template_id):
        raise ValidationError(_("No se pudo verificar la integridad del snapshot."))
    if (manifest.get("selection", {}).get("scope_kind", "MANUSCRIPT") != job.scope_kind
            or (job.export_mode == "REFERENCE") != (manifest.get("schema_version") == 2)):
        raise ValidationError(_("El alcance no coincide con el snapshot original."))
    return document_from_manifest(manifest)
