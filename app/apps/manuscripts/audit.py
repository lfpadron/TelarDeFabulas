"""Read-only inventory of legacy data; no business model methods are called."""

from collections import Counter, defaultdict, deque
from pathlib import Path, PurePosixPath
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.db.models import BooleanField, Case, Value, When
from django.db.models.functions import Length
from django.utils import timezone
from django.urls import Resolver404, resolve
from django.views.static import serve

from apps.characters.models import Character, CharacterMention
from apps.exports.models import ExportJob
from apps.notes.models import Note
from apps.projects.models import Project

from .models import ManuscriptNode
from .hierarchy import ALLOWED_CHILD_TYPES, CURRENT_TYPES


SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
COMPATIBILITIES = ("READY", "REQUIRES_MIGRATION", "REQUIRES_DECISION", "INVALID_DATA")
PARENT_TYPES = {kind: {parent for parent, children in ALLOWED_CHILD_TYPES.items() if kind in children} for kind in CURRENT_TYPES}
PARENT_TYPES["BOOK"] = {None}
ADVANCED_STAGES = {"FINISHED", "PUBLISHABLE", "PUBLISHED"}
EARLY_STAGES = {"PENDING", "IN_PROGRESS", "DRAFT", "REVIEW"}


def _select_only(execute, sql, params, many, context):
    if not sql.lstrip().upper().startswith("SELECT "):
        raise RuntimeError("La auditoria solo permite consultas SELECT.")
    return execute(sql, params, many, context)


def load_inventory():
    """Seven bulk ORM reads, with text reduced to lengths/booleans in SQL."""
    User = get_user_model()
    description_field = next(
        (field.name for field in ManuscriptNode._meta.fields if field.name == "short_description"), None
    )
    annotations = {
        "content_length": Length("content"),
        "has_text": Case(When(content__regex=r"\S", then=Value(True)), default=Value(False), output_field=BooleanField()),
        "title_empty": Case(When(title__regex=r"\S", then=Value(False)), default=Value(True), output_field=BooleanField()),
    }
    if description_field:
        annotations["description_empty"] = Case(
            When(**{f"{description_field}__regex": r"\S"}, then=Value(False)),
            default=Value(True), output_field=BooleanField(),
        )

    outer_transaction = connection.in_atomic_block
    with transaction.atomic():
        if connection.vendor == "postgresql" and not outer_transaction:
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        # The guard also protects nested test transactions, without changing their isolation.
        with connection.execute_wrapper(_select_only):
            data = {
                "users": list(User.objects.order_by("pk").values("id", "user_type", "status", "is_active")),
                "projects": list(Project.objects.order_by("pk").values("id", "user_id", "status")),
                "nodes": list(ManuscriptNode.objects.order_by("pk").annotate(**annotations).values(
                    "id", "project_id", "parent_id", "node_type", "status", "position", "word_count",
                    "is_publishable", *annotations,
                )),
                "characters": list(Character.objects.order_by("pk").values("id", "project_id", "image", "importance")),
                "notes": list(Note.objects.order_by("pk").values("id", "project_id", "node_id", "character_id", "status", "note_type")),
                "mentions": list(CharacterMention.objects.order_by("pk").values("id", "character_id", "node_id", "mention_type")),
                "exports": list(ExportJob.objects.order_by("pk").values(
                    "id", "user_id", "project_id", "root_node_id", "status", "format", "file",
                )),
            }
    data["description_field_present"] = bool(description_field)
    return data


def distribution(rows, field, allowed):
    counts = dict.fromkeys(allowed, 0)
    for row in rows:
        # Corrupt choice values must not leak arbitrary strings into the report.
        key = row[field] if row[field] in counts else "UNKNOWN"
        counts[key] = counts.get(key, 0) + 1
    return counts


class Findings:
    def __init__(self):
        self.items = {}

    def add(self, code, severity, compatibility, message, model=None, ids=()):
        item = self.items.setdefault(code, {
            "code": code, "severity": severity, "compatibility": compatibility,
            "message": message, "members": defaultdict(set),
        })
        if model:
            item["members"][model].update(ids)

    def records(self, compatibilities):
        return {
            (model, pk) for item in self.items.values() if item["compatibility"] in compatibilities
            for model, ids in item["members"].items() for pk in ids
        }

    def export(self):
        return [{
            "code": item["code"], "severity": item["severity"], "compatibility": item["compatibility"],
            "message": item["message"],
            "affected_records": {model: len(ids) for model, ids in sorted(item["members"].items())},
            "record_ids": {model: sorted(ids) for model, ids in sorted(item["members"].items()) if model != "users"},
        } for item in sorted(self.items.values(), key=lambda item: (SEVERITIES.index(item["severity"]), item["code"]))]


def analyze_graph(nodes):
    """Iterative O(nodes) traversal, including cycles disconnected from every root."""
    by_id = {node["id"]: node for node in nodes}
    children = defaultdict(list)
    for node in nodes:
        children[node["parent_id"]].append(node["id"])
    visited, cycles = set(), []
    for start in by_id:
        path, offsets = [], {}
        current = start
        while current in by_id and current not in visited:
            if current in offsets:
                cycles.append(sorted(path[offsets[current]:]))
                break
            offsets[current] = len(path)
            path.append(current)
            current = by_id[current]["parent_id"]
        visited.update(path)

    depths = {}
    pending = deque((pk, 0) for pk in children[None])
    while pending:
        pk, depth = pending.popleft()
        if pk in depths:
            continue
        depths[pk] = depth
        for child in children[pk]:
            if by_id[child]["project_id"] == by_id[pk]["project_id"]:
                pending.append((child, depth + 1))
    return {
        "cycles": sorted(cycles), "unreachable_node_ids": sorted(set(by_id) - depths.keys()),
        "max_depth_from_root": max(depths.values(), default=0),
    }


def inspect_file_metadata(storage, name, expected_prefix):
    """Never call open(), url(), listdir(), or inspect files outside storage."""
    suffix = PurePosixPath(name).suffix.lower()
    extension = suffix if re.fullmatch(r"\.[a-z0-9]{1,10}", suffix) else ("NONE" if not suffix else "OTHER")
    result = {"extension": extension, "outside_expected_location": False, "status": "UNKNOWN", "size_bytes": None}
    parts = name.split("/")
    if "\\" in name or ":" in name or "\x00" in name or any(part in ("", ".", "..") for part in parts):
        return {**result, "outside_expected_location": True, "status": "UNSAFE_PATH"}
    result["outside_expected_location"] = not name.startswith(expected_prefix)
    try:
        try:
            path = Path(storage.path(name)).resolve()
        except NotImplementedError:
            path = None
        if path is not None:
            root = Path(storage.location).resolve()
            if not path.is_relative_to(root):
                return {**result, "outside_expected_location": True, "status": "UNSAFE_PATH"}
            if path.exists() and not path.is_file():
                return {**result, "status": "NOT_A_FILE"}
        if not storage.exists(name):
            return {**result, "status": "MISSING"}
        size = storage.size(name)
        if not isinstance(size, int) or size < 0:
            return {**result, "status": "METADATA_ERROR"}
        return {**result, "status": "PRESENT", "size_bytes": size}
    except FileNotFoundError:
        return {**result, "status": "MISSING"}
    except Exception:
        # Backend errors can contain filenames, credentials or absolute paths.
        return {**result, "status": "METADATA_ERROR"}


def audit_files(data, findings, storages):
    records, sizes, metadata_cache = [], {}, {}
    for model, field in (("characters", "image"), ("exports", "file")):
        storage = storages[model]
        for row in data[model]:
            name = row[field]
            if not name:
                continue
            prefix = f"characters/{row['project_id']}/" if model == "characters" else f"exports/{row['user_id']}/{row['project_id']}/"
            key = (id(storage), name)
            cache_key = (*key, prefix)
            if cache_key not in metadata_cache:
                metadata_cache[cache_key] = inspect_file_metadata(storage, name, prefix)
            metadata = metadata_cache[cache_key]
            records.append({"model": model, "record_id": row["id"], **metadata})
            if metadata["size_bytes"] is not None:
                sizes[key] = metadata["size_bytes"]
            if metadata["outside_expected_location"]:
                findings.add("FILE_OUTSIDE_EXPECTED_LOCATION", "HIGH", "INVALID_DATA",
                             "Referencia de archivo fuera de su ubicacion esperada; no se muestra su ruta.", model, [row["id"]])
            if metadata["status"] == "MISSING":
                findings.add("FILE_MISSING", "HIGH", "INVALID_DATA", "Archivo referenciado no encontrado.", model, [row["id"]])
            elif metadata["status"] in ("METADATA_ERROR", "UNKNOWN"):
                findings.add("FILE_METADATA_UNAVAILABLE", "MEDIUM", "REQUIRES_DECISION",
                             "No se pudo verificar metadata de archivo; no equivale a archivo faltante.", model, [row["id"]])
            elif metadata["status"] == "NOT_A_FILE":
                findings.add("FILE_NOT_REGULAR", "HIGH", "INVALID_DATA", "La referencia no corresponde a un archivo regular.", model, [row["id"]])
    return {
        "referenced_files": len(records), "unique_references": len({(id(storages[model]), row[field])
            for model, field in (("characters", "image"), ("exports", "file")) for row in data[model] if row[field]}),
        "by_model": dict(Counter(row["model"] for row in records)),
        "by_status": dict(Counter(row["status"] for row in records)),
        "extensions": dict(sorted(Counter(row["extension"] for row in records).items())),
        "outside_expected_location": sum(row["outside_expected_location"] for row in records),
        "known_unique_size_bytes": sum(sizes.values()), "unique_files_with_known_size": len(sizes),
        "records": records,
        "limitations": ["Solo metadata de referencias en DB; no se abren archivos ni se enumeran huerfanos.",
                        "Tamano parcial si hay archivos no verificables; filesystem y DB no comparten snapshot."],
    }


def has_public_media_route():
    try:
        match = resolve("/" + settings.MEDIA_URL.strip("/") + "/__audit_route_check__")
    except Resolver404:
        return False
    return match.func is serve and match.kwargs.get("document_root") == settings.MEDIA_ROOT


def analyze_inventory(data, storages):
    findings = Findings()
    users, projects, nodes = data["users"], data["projects"], data["nodes"]
    project_map = {row["id"]: row for row in projects}
    user_ids = {row["id"] for row in users}
    node_map = {row["id"]: row for row in nodes}
    character_map = {row["id"]: row for row in data["characters"]}
    project_counts = Counter(row["user_id"] for row in projects)
    node_counts = Counter(row["project_id"] for row in nodes)
    book_counts = Counter(row["project_id"] for row in nodes if row["node_type"] == "BOOK")
    hierarchy_affected = set()

    def node_finding(code, severity, compatibility, message, ids, hierarchy=False):
        if ids:
            findings.add(code, severity, compatibility, message, "nodes", ids)
            if hierarchy:
                hierarchy_affected.update(ids)

    for project in projects:
        if project["user_id"] not in user_ids:
            findings.add("PROJECT_OWNER_MISSING", "CRITICAL", "INVALID_DATA", "Proyecto sin propietario existente.", "projects", [project["id"]])
        if not book_counts[project["id"]]:
            findings.add("PROJECT_WITHOUT_BOOK", "MEDIUM", "REQUIRES_DECISION", "Proyecto sin libro; requiere decidir su estructura inicial.", "projects", [project["id"]])
    for model in ("nodes", "characters", "notes", "exports"):
        missing = [row["id"] for row in data[model] if row["project_id"] not in project_map]
        if missing:
            findings.add("PROJECT_REFERENCE_MISSING", "CRITICAL", "INVALID_DATA", "Registro apunta a proyecto inexistente.", model, missing)

    position_groups = defaultdict(list)
    for node in nodes:
        pk, parent_id, kind = node["id"], node["parent_id"], node["node_type"]
        parent = node_map.get(parent_id)
        if kind not in ManuscriptNode.NodeType.values:
            node_finding("NODE_TYPE_UNKNOWN", "HIGH", "INVALID_DATA", "Tipo de nodo no reconocido.", [pk], True)
        if node["status"] not in ManuscriptNode.NodeStatus.values:
            node_finding("NODE_STATUS_UNKNOWN", "HIGH", "INVALID_DATA", "Estado editorial no reconocido.", [pk])
        if parent_id is not None and parent is None:
            node_finding("PARENT_MISSING", "CRITICAL", "INVALID_DATA", "Nodo con padre inexistente.", [pk], True)
        if parent and parent["project_id"] != node["project_id"]:
            node_finding("PARENT_PROJECT_MISMATCH", "CRITICAL", "INVALID_DATA", "Padre y nodo pertenecen a proyectos distintos.", [pk], True)
        if kind in PARENT_TYPES:
            valid = parent_id is None if kind == "BOOK" else parent is not None and parent["node_type"] in PARENT_TYPES[kind]
            if not valid:
                node_finding(f"{kind}_INVALID_PARENT", "HIGH", "REQUIRES_MIGRATION", "Padre incompatible con la jerarquia objetivo; conservar identidad al migrar.", [pk], True)
        position = node["position"]
        if not isinstance(position, int) or isinstance(position, bool) or position < 1:
            node_finding("POSITION_INVALID", "HIGH", "INVALID_DATA", "Posicion nula, no entera o menor que uno.", [pk], True)
        else:
            position_groups[(node["project_id"], parent_id, position)].append(pk)
    duplicate_positions = [
        {"project_id": project, "parent_id": parent, "position": position, "node_ids": sorted(ids)}
        for (project, parent, position), ids in position_groups.items() if len(ids) > 1
    ]
    node_finding("POSITION_DUPLICATE", "HIGH", "INVALID_DATA", "Hermanos comparten posicion.",
                 [pk for group in duplicate_positions for pk in group["node_ids"]], True)
    graph = analyze_graph(nodes)
    node_finding("CYCLE", "CRITICAL", "INVALID_DATA", "Ciclo en el arbol; el recorrido no es seguro.",
                 [pk for cycle in graph["cycles"] for pk in cycle], True)
    node_finding("UNREACHABLE_NODE", "HIGH", "INVALID_DATA", "Nodo no alcanzable desde una raiz de su proyecto.", graph["unreachable_node_ids"], True)

    scenes = [row for row in nodes if row["node_type"] == "SCENE"]
    fragments = [row["id"] for row in nodes if row["node_type"] == "FRAGMENT"]
    non_scene_text = [row["id"] for row in nodes if row["node_type"] != "SCENE" and row["has_text"]]
    advanced = [row["id"] for row in scenes if row["status"] in ADVANCED_STAGES]
    flag_ambiguities = [row["id"] for row in scenes if
        (row["is_publishable"] and row["status"] in EARLY_STAGES) or
        (not row["is_publishable"] and row["status"] in {"PUBLISHABLE", "PUBLISHED"})]
    empty_scenes = [row["id"] for row in scenes if not row["has_text"]]
    node_finding("SCENE_VERSION_REQUIRED", "LOW", "REQUIRES_MIGRATION", "Copiar escenas a versiones preservando texto e ID; SceneVersion aun no existe.", [row["id"] for row in scenes])
    node_finding("FRAGMENT_PRESENT", "HIGH", "REQUIRES_DECISION", "Conservar FRAGMENT hasta aprobar conversion o compatibilidad.", fragments, True)
    node_finding("NON_SCENE_CONTENT", "HIGH", "REQUIRES_DECISION", "Texto fuera de escenas requiere destino y orden aprobados; no convertirlo en descripcion.", non_scene_text)
    node_finding("EDITORIAL_MAPPING_AMBIGUOUS", "HIGH", "REQUIRES_DECISION", "FINISHED, PUBLISHABLE y PUBLISHED no se convierten automaticamente en FINAL.", advanced)
    node_finding("PUBLISHABLE_FLAG_AMBIGUOUS", "MEDIUM", "REQUIRES_DECISION", "Estado y bandera publicable requieren conciliacion explicita.", flag_ambiguities)
    node_finding("EMPTY_SCENE", "MEDIUM", "REQUIRES_DECISION", "Escena vacia o con solo espacios; conservarla y decidir etapa inicial.", empty_scenes)
    empty_titles = [row["id"] for row in nodes if row["title_empty"]]
    node_finding("TITLE_REQUIRED_EMPTY", "HIGH", "INVALID_DATA", "Titulo vacio en un nodo distinto de SCENE.", [pk for pk in empty_titles if node_map[pk]["node_type"] != "SCENE"])
    node_finding("OPTIONAL_SCENE_TITLE", "LOW", "READY", "La arquitectura objetivo permite escenas sin titulo.", [pk for pk in empty_titles if node_map[pk]["node_type"] == "SCENE"])
    if not data["description_field_present"]:
        findings.add("DESCRIPTION_FIELD_ABSENT", "LOW", "REQUIRES_MIGRATION", "ManuscriptNode no tiene short_description; no se inventa un conteo de descripciones vacias.", "nodes", node_map)

    dependencies = audit_references(data, node_map, project_map, character_map, hierarchy_affected, findings)
    files = audit_files(data, findings, storages)
    if settings.DEBUG and has_public_media_route():
        findings.add("DEBUG_MEDIA_ROUTE", "HIGH", "REQUIRES_MIGRATION", "Con DEBUG, la configuracion actual sirve media directamente; requiere proteccion en otra fase. No se probaron URLs ni se publicaron archivos.")
    if users:
        findings.add("LEGACY_SUBSCRIPTION_POLICY", "MEDIUM", "REQUIRES_DECISION", "Los tipos actuales no prueban pago ni vigencia; decidir trial y tratamiento de cuentas heredadas.", "users", user_ids)
    if data["exports"]:
        findings.add("EXPORT_LIFECYCLE_MIGRATION", "LOW", "REQUIRES_MIGRATION", "Migrar estados de exportacion y retencion sin regenerar ni borrar archivos historicos.", "exports", [row["id"] for row in data["exports"]])

    lengths = [row["content_length"] or 0 for row in nodes]
    buckets = {"0": 0, "1-1000": 0, "1001-10000": 0, "10001-100000": 0, ">100000": 0}
    for length in lengths:
        bucket = "0" if length == 0 else "1-1000" if length <= 1000 else "1001-10000" if length <= 10000 else "10001-100000" if length <= 100000 else ">100000"
        buckets[bucket] += 1
    findings.add("READ_ONLY_INVENTORY", "LOW", "READY", "Inventario sin correcciones; conteos de categorias disjuntas y hallazgos potencialmente superpuestos.")
    exported_findings = findings.export()
    model_counts = {model: len(data[model]) for model in ("users", "projects", "nodes", "characters", "notes", "mentions", "exports")}
    migration_records = findings.records({"REQUIRES_MIGRATION"})
    decision_records = findings.records({"REQUIRES_DECISION"})
    invalid_records = findings.records({"INVALID_DATA"})
    User = get_user_model()
    return {
        "schema_version": 1, "generated_at": timezone.now().isoformat(), "scope": "ALL_PROJECTS",
        "summary": {
            "records_by_model": model_counts, "records_analyzed": sum(model_counts.values()),
            "records_requiring_migration": len(migration_records), "records_requiring_decision": len(decision_records),
            "invalid_records": len(invalid_records), "potentially_problematic_records": len(decision_records | invalid_records),
            "finding_count": len(exported_findings),
            "findings_by_severity": dict(Counter(item["severity"] for item in exported_findings)),
            "findings_by_compatibility": dict(Counter(item["compatibility"] for item in exported_findings)),
            "counting_note": "Registros unicos por (modelo,id) en cada indicador; indicadores pueden solaparse. Hallazgos de esquema/configuracion pueden afectar cero registros.",
        },
        "users": {
            "total": len(users), "by_type": distribution(users, "user_type", User.UserType.values),
            "by_status": distribution(users, "status", User.UserStatus.values),
            "administrators": sum(row["user_type"] in {"TECH_ADMIN", "BUSINESS_ADMIN"} for row in users),
            "authentication_active": sum(row["is_active"] for row in users),
            "project_counts": {"zero": sum(project_counts[row["id"]] == 0 for row in users),
                               "one": sum(project_counts[row["id"]] == 1 for row in users),
                               "multiple": sum(project_counts[row["id"]] > 1 for row in users)},
            "project_count_policy": "Incluye todos los estados; no aplica cupos ni calcula vencimientos.",
        },
        "projects": {
            "total": len(projects), "by_status": distribution(projects, "status", Project.ProjectStatus.values),
            "with_manuscript": sum(node_counts[row["id"]] > 0 for row in projects),
            "without_manuscript": sum(node_counts[row["id"]] == 0 for row in projects),
            "per_project": [{"project_id": row["id"], "books": book_counts[row["id"]], "nodes": node_counts[row["id"]]} for row in projects],
        },
        "manuscripts": {
            "total": len(nodes), "by_type": distribution(nodes, "node_type", ManuscriptNode.NodeType.values),
            "by_status": distribution(nodes, "status", ManuscriptNode.NodeStatus.values),
            "root_node_ids": [row["id"] for row in nodes if row["parent_id"] is None],
            "roots": sum(row["parent_id"] is None for row in nodes), "with_parent": sum(row["parent_id"] is not None for row in nodes),
            "with_content": sum(row["has_text"] for row in nodes), "without_content": sum(not row["has_text"] for row in nodes),
            "whitespace_only": sum(not row["has_text"] and (row["content_length"] or 0) > 0 for row in nodes),
            "approximate_words": sum(row["word_count"] for row in nodes), "word_count_source": "Contador persistido; no recalculado ni corregido.",
            "content_lengths": {"unit": "characters", "total": sum(lengths), "min": min(lengths, default=0), "max": max(lengths, default=0), "buckets": buckets},
            "empty_title_ids": empty_titles, "description_field_present": data["description_field_present"],
            "empty_descriptions": sum(row.get("description_empty", False) for row in nodes) if data["description_field_present"] else None,
            "hierarchy": {**graph, "duplicate_positions": duplicate_positions, "affected_node_ids": sorted(hierarchy_affected)},
        },
        "scene_version_readiness": {
            "total_scenes": len(scenes), "with_text": sum(row["has_text"] for row in scenes), "empty": len(empty_scenes),
            "non_scene_with_text": len(non_scene_text), "non_scene_with_text_ids": non_scene_text,
            "fragment_ids": fragments, "advanced_stages": len(advanced), "advanced_stage_ids": advanced,
            "early_stages": sum(row["status"] in EARLY_STAGES for row in scenes),
            "by_status": distribution(scenes, "status", ManuscriptNode.NodeStatus.values),
            "flag_ambiguity_ids": flag_ambiguities,
        },
        "characters": {"total": len(data["characters"]), "with_image": sum(bool(row["image"]) for row in data["characters"]),
                       "by_importance": distribution(data["characters"], "importance", Character.Importance.values)},
        "notes": {"total": len(data["notes"]), "with_node": sum(row["node_id"] is not None for row in data["notes"]),
                  "with_character": sum(row["character_id"] is not None for row in data["notes"])},
        "mentions": {"total": len(data["mentions"]), "by_type": distribution(data["mentions"], "mention_type", CharacterMention.MentionType.values)},
        "exports": {"total": len(data["exports"]), "with_root": sum(row["root_node_id"] is not None for row in data["exports"]),
                    "without_root": sum(row["root_node_id"] is None for row in data["exports"]),
                    "by_status": distribution(data["exports"], "status", ExportJob.ExportStatus.values),
                    "by_format": distribution(data["exports"], "format", ExportJob.ExportFormat.values),
                    "root_null_note": "NULL puede ser proyecto completo o una raiz borrada; no se puede reconstruir la intencion desde estos datos."},
        "dependencies": dependencies, "files": files, "findings": exported_findings,
        "subscription_readiness": {
            "trial": "REQUIRES_DECISION", "monthly": "REQUIRES_MIGRATION", "annual": "REQUIRES_MIGRATION",
            "manual_payment": "REQUIRES_MIGRATION", "stripe": "REQUIRES_MIGRATION",
            "expired_read_only": "REQUIRES_MIGRATION", "one_year_retention": "REQUIRES_DECISION",
            "note": "No existen fechas de trial, pagos o suscripciones. No se infiere vigencia de user_type/status.",
        },
        "limitations": ["No incluye tablas de sesiones, permisos, estilos o papeles dramaticos en el total analizado.",
                        "No incluye nombres, emails, titulos, texto, nombres de archivo ni rutas de media.",
                        "Compatibilidad objetivo no implica corrupcion del modelo actual; no se ejecuta ninguna migracion."],
    }


def audit_references(data, nodes, projects, characters, hierarchy_affected, findings):
    reference_counts = defaultdict(lambda: Counter({"notes": 0, "mentions": 0, "exports": 0}))
    for model, node_field in (("notes", "node_id"), ("mentions", "node_id"), ("exports", "root_node_id")):
        for row in data[model]:
            node_id = row[node_field]
            if node_id is not None:
                reference_counts[node_id][model] += 1
                if node_id not in nodes:
                    findings.add("NODE_REFERENCE_MISSING", "CRITICAL", "INVALID_DATA", "Relacion apunta a nodo inexistente.", model, [row["id"]])
            character = characters.get(row.get("character_id"))
            if model in ("notes", "mentions") and row.get("character_id") is not None and character is None:
                findings.add("CHARACTER_REFERENCE_MISSING", "CRITICAL", "INVALID_DATA", "Relacion apunta a personaje inexistente.", model, [row["id"]])
            project_id = character["project_id"] if model == "mentions" and character else row.get("project_id")
            if node_id in nodes and project_id is not None and nodes[node_id]["project_id"] != project_id:
                findings.add("REFERENCE_PROJECT_MISMATCH", "CRITICAL", "INVALID_DATA", "Relacion cruza proyectos distintos.", model, [row["id"]])
            if model == "notes" and character and character["project_id"] != row["project_id"]:
                findings.add("REFERENCE_PROJECT_MISMATCH", "CRITICAL", "INVALID_DATA", "Relacion cruza proyectos distintos.", model, [row["id"]])
            if model == "exports" and row["project_id"] in projects and row["user_id"] != projects[row["project_id"]]["user_id"]:
                findings.add("EXPORT_OWNER_MISMATCH", "CRITICAL", "INVALID_DATA", "Exportacion y proyecto tienen propietarios distintos.", model, [row["id"]])
            if model == "exports" and row["status"] == "DONE" and not row["file"]:
                findings.add("EXPORT_DONE_WITHOUT_FILE", "HIGH", "INVALID_DATA", "Exportacion DONE sin referencia de archivo.", model, [row["id"]])
    triples = defaultdict(list)
    for row in data["mentions"]:
        triples[(row["character_id"], row["node_id"], row["mention_type"])].append(row["id"])
    duplicates = [sorted(ids) for ids in triples.values() if len(ids) > 1]
    if duplicates:
        findings.add("DUPLICATE_MENTION", "HIGH", "INVALID_DATA", "Menciones duplicadas de personaje, nodo y tipo.", "mentions", [pk for ids in duplicates for pk in ids])

    affected = set(hierarchy_affected)
    children = defaultdict(list)
    for row in nodes.values():
        children[row["parent_id"]].append(row["id"])
    pending = deque(affected)
    while pending:
        for child in children[pending.popleft()]:
            if child not in affected:
                affected.add(child)
                pending.append(child)
    linked = [{"node_id": pk, **counts, "total": sum(counts.values())} for pk, counts in sorted(reference_counts.items())]
    affected_counts = {model: sum(row[model] for row in linked if row["node_id"] in affected) for model in ("notes", "mentions", "exports")}
    return {
        "by_node": linked, "nodes_with_multiple_references": [row["node_id"] for row in linked if row["total"] > 1],
        "duplicate_mention_groups": duplicates, "references_under_affected_hierarchy": affected_counts,
        "affected_node_ids_with_references": [row["node_id"] for row in linked if row["node_id"] in affected],
        "note": "Incluye descendientes de nodos a revisar; conservar PK evita perder relaciones al mover.",
    }


def build_audit_report():
    data = load_inventory()
    return analyze_inventory(data, {
        "characters": Character._meta.get_field("image").storage,
        "exports": ExportJob._meta.get_field("file").storage,
    })


def render_summary(report):
    summary = report["summary"]
    return "\n".join([
        "Telar de Fabulas - Inventario de solo lectura",
        f"Fecha: {report['generated_at']}",
        f"Registros analizados: {summary['records_analyzed']}",
        *(f"  {model}: {count}" for model, count in summary["records_by_model"].items()),
        f"Requieren migracion: {summary['records_requiring_migration']}",
        f"Requieren decision: {summary['records_requiring_decision']}",
        f"Registros invalidos: {summary['invalid_records']}",
        f"Potencialmente problematicos: {summary['potentially_problematic_records']}",
        *(f"  {severity}: {summary['findings_by_severity'].get(severity, 0)} hallazgos" for severity in SEVERITIES),
        "Hallazgos:", *(f"  {item['severity']} / {item['compatibility']}: {item['code']}" for item in report["findings"]),
        "Use --format json o --format markdown para el detalle. No se modificaron registros.",
    ])


def render_markdown(report):
    import json

    lines = ["# Telar de Fabulas: inventario de datos", "", "Informe de solo lectura. Identificadores internos; sin contenido ni datos personales.", ""]
    for section, value in report.items():
        lines.extend([f"## {section}", ""])
        if isinstance(value, dict):
            lines.extend(["| Indicador | Valor |", "| --- | --- |"])
            for key, item in value.items():
                cell = json.dumps(item, ensure_ascii=True).replace("|", "\\|")
                lines.append(f"| {key} | {cell} |")
        elif isinstance(value, list):
            for item in value:
                lines.append("- " + json.dumps(item, ensure_ascii=True))
        else:
            lines.append(str(value))
        lines.append("")
    return "\n".join(lines)
