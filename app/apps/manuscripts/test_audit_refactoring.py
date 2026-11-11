from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError, connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.characters.models import Character, CharacterMention
from apps.exports.models import ExportJob
from apps.notes.models import Note
from apps.projects.models import Project
from apps.styles.models import StyleTemplate

from .audit import (
    COMPATIBILITIES, SEVERITIES, _select_only, analyze_graph, analyze_inventory,
    inspect_file_metadata, render_markdown,
)
from .models import ManuscriptNode


def empty_inventory():
    return {**{key: [] for key in ("users", "projects", "nodes", "characters", "notes", "mentions", "exports")},
            "description_field_present": False}


def node(pk, kind="SCENE", parent=102, **overrides):
    return {"id": pk, "project_id": 10, "parent_id": parent, "node_type": kind,
            "status": "DRAFT", "position": 1, "word_count": 0, "is_publishable": False,
            "content_length": 0, "has_text": False, "title_empty": False, **overrides}


def tree_inventory():
    data = empty_inventory()
    data["users"] = [{"id": 1, "user_type": "FREE", "status": "ACTIVE", "is_active": True}]
    data["projects"] = [{"id": 10, "user_id": 1, "status": "ACTIVE"}]
    data["nodes"] = [node(100, "BOOK", None), node(101, "PART", 100), node(102, "CHAPTER", 101),
                     node(103, content_length=25, has_text=True, word_count=5)]
    return data


@override_settings(DEBUG=False)
class AuditAnalysisTests(SimpleTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.storage = FileSystemStorage(location=self.temporary.name)
        self.data = tree_inventory()

    def report(self, data=None):
        return analyze_inventory(data if data is not None else self.data,
                                 {"characters": self.storage, "exports": self.storage})

    def codes(self, report=None):
        return {item["code"] for item in (report or self.report())["findings"]}

    def test_empty_database_inventory(self):
        report = self.report(empty_inventory())
        self.assertEqual(report["summary"]["records_analyzed"], 0)
        self.assertEqual(report["projects"]["total"], 0)
        self.assertEqual(report["manuscripts"]["content_lengths"]["max"], 0)

    def test_project_without_manuscript(self):
        self.data["nodes"] = []
        report = self.report()
        self.assertEqual(report["projects"]["without_manuscript"], 1)
        self.assertIn("PROJECT_WITHOUT_BOOK", self.codes(report))

    def test_valid_tree(self):
        report = self.report()
        self.assertEqual(report["manuscripts"]["roots"], 1)
        self.assertEqual(report["manuscripts"]["hierarchy"]["affected_node_ids"], [])
        self.assertEqual(report["manuscripts"]["approximate_words"], 5)
        self.assertEqual(report["projects"]["per_project"], [{"project_id": 10, "books": 1, "nodes": 4}])

    def test_invalid_hierarchy_reports_every_target_rule(self):
        for kind, parent in (("BOOK", 102), ("PART", None), ("CHAPTER", None), ("SCENE", 100)):
            with self.subTest(kind=kind):
                data = tree_inventory()
                data["nodes"].append(node(104, kind, parent, position=2))
                self.assertIn(f"{kind}_INVALID_PARENT", self.codes(self.report(data)))

    def test_fragment_and_non_scene_text_need_decisions(self):
        self.data["nodes"].append(node(104, "FRAGMENT", 103, has_text=True, content_length=10))
        self.data["nodes"][0].update(has_text=True, content_length=12)
        report = self.report()
        self.assertIn("FRAGMENT_PRESENT", self.codes(report))
        self.assertEqual(report["scene_version_readiness"]["non_scene_with_text_ids"], [100, 104])
        self.assertEqual(report["scene_version_readiness"]["fragment_ids"], [104])

    def test_finished_does_not_become_final(self):
        self.data["nodes"][-1].update(status="FINISHED", is_publishable=True)
        report = self.report()
        self.assertEqual(report["scene_version_readiness"]["advanced_stage_ids"], [103])
        finding = next(item for item in report["findings"] if item["code"] == "EDITORIAL_MAPPING_AMBIGUOUS")
        self.assertEqual(finding["compatibility"], "REQUIRES_DECISION")
        self.assertNotIn("FINAL", report["scene_version_readiness"]["by_status"])

    def test_empty_scene_and_whitespace_are_counted(self):
        self.data["nodes"][-1].update(has_text=False, content_length=3)
        report = self.report()
        self.assertEqual(report["scene_version_readiness"]["empty"], 1)
        self.assertEqual(report["manuscripts"]["whitespace_only"], 1)
        self.assertEqual(report["manuscripts"]["without_content"], 4)

    def test_positions_include_root_duplicates_and_invalid_values(self):
        self.data["nodes"].extend([node(104, "BOOK", None), node(105, position=None),
                                   node(106, position=0), node(107, position=-1)])
        report = self.report()
        self.assertIn("POSITION_INVALID", self.codes(report))
        self.assertEqual(report["manuscripts"]["hierarchy"]["duplicate_positions"][0]["node_ids"], [100, 104])

    def test_orphan_parent_and_cross_project(self):
        self.data["nodes"] += [node(104, "CHAPTER", 999), node(105, "CHAPTER", 100, project_id=20)]
        self.data["projects"].append({"id": 20, "user_id": 1, "status": "ACTIVE"})
        self.assertTrue({"PARENT_MISSING", "PARENT_PROJECT_MISMATCH", "UNREACHABLE_NODE"} <= self.codes())

    def test_cycle_disconnected_from_roots(self):
        self.data["nodes"] += [node(104, parent=105), node(105, parent=104), node(106, parent=104, position=2)]
        graph = self.report()["manuscripts"]["hierarchy"]
        self.assertEqual(graph["cycles"], [[104, 105]])
        self.assertEqual(graph["unreachable_node_ids"], [104, 105, 106])

    def test_deep_chain_does_not_use_python_recursion(self):
        nodes = [node(pk, parent=pk - 1 if pk else None) for pk in range(3000)]
        graph = analyze_graph(nodes)
        self.assertEqual(graph["max_depth_from_root"], 2999)
        self.assertEqual(graph["unreachable_node_ids"], [])

    def add_references(self):
        self.data["characters"] = [{"id": 20, "project_id": 10, "image": "", "importance": "PRINCIPAL"}]
        self.data["notes"] = [{"id": 30, "project_id": 10, "node_id": 103, "character_id": 20, "status": "OPEN", "note_type": "NOTE"}]
        self.data["mentions"] = [{"id": 40, "node_id": 103, "character_id": 20, "mention_type": "APPEARS"}]
        self.data["exports"] = [{"id": 50, "project_id": 10, "user_id": 1, "root_node_id": 103, "status": "PENDING", "format": "HTML", "file": ""}]

    def test_notes_mentions_and_exports_linked_to_node(self):
        self.add_references()
        report = self.report()
        self.assertEqual(report["notes"]["with_node"], 1)
        self.assertEqual(report["mentions"]["total"], 1)
        self.assertEqual(report["exports"]["with_root"], 1)
        self.assertEqual(report["dependencies"]["by_node"], [{"node_id": 103, "notes": 1, "mentions": 1, "exports": 1, "total": 3}])
        self.assertEqual(report["dependencies"]["nodes_with_multiple_references"], [103])

    def test_hierarchy_risk_includes_references_of_descendants(self):
        self.add_references()
        self.data["nodes"][1]["parent_id"] = None
        report = self.report()
        self.assertEqual(report["dependencies"]["references_under_affected_hierarchy"], {"notes": 1, "mentions": 1, "exports": 1})

    def test_invalid_references_and_duplicate_mentions(self):
        self.add_references()
        self.data["notes"][0]["node_id"] = 999
        self.data["characters"][0]["project_id"] = 90
        self.data["mentions"].append({**self.data["mentions"][0], "id": 41})
        codes = self.codes()
        self.assertTrue({"NODE_REFERENCE_MISSING", "REFERENCE_PROJECT_MISMATCH", "DUPLICATE_MENTION"} <= codes)

    def test_missing_file_metadata(self):
        self.add_references()
        self.data["characters"][0]["image"] = "characters/10/missing.png"
        self.data["exports"][0]["file"] = "exports/1/10/missing.html"
        report = self.report()
        self.assertEqual(report["files"]["referenced_files"], 2)
        self.assertEqual(report["files"]["by_status"], {"MISSING": 2})
        self.assertEqual(report["files"]["extensions"], {".html": 1, ".png": 1})

    def test_file_metadata_never_opens_content_and_counts_unique_bytes(self):
        self.add_references()
        target = Path(self.temporary.name) / "characters/10/private.png"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"private-image")
        self.data["characters"][0]["image"] = "characters/10/private.png"
        self.data["characters"].append({**self.data["characters"][0], "id": 21})
        with patch.object(self.storage, "open", side_effect=AssertionError("Do not open media")):
            report = self.report()
        self.assertEqual(report["files"]["referenced_files"], 2)
        self.assertEqual(report["files"]["unique_files_with_known_size"], 1)
        self.assertEqual(report["files"]["known_unique_size_bytes"], len(b"private-image"))
        self.assertNotIn("private.png", json.dumps(report))
        self.assertNotIn(self.temporary.name, json.dumps(report))

    def test_unsafe_paths_are_not_inspected(self):
        for name in ("../outside.png", "/outside.png", "C:/private.png", "characters\\private.png"):
            with self.subTest(name=name), patch.object(self.storage, "exists") as exists:
                metadata = inspect_file_metadata(self.storage, name, "characters/10/")
                self.assertEqual(metadata["status"], "UNSAFE_PATH")
                exists.assert_not_called()

    def test_backend_failure_is_not_reported_as_missing_or_leaked(self):
        with patch.object(self.storage, "exists", side_effect=OSError("secret/path")):
            result = inspect_file_metadata(self.storage, "characters/10/image.png", "characters/10/")
        self.assertEqual(result["status"], "METADATA_ERROR")
        self.assertNotIn("secret/path", json.dumps(result))

    def test_empty_descriptions_are_unknown_when_field_is_absent(self):
        report = self.report()
        self.assertIsNone(report["manuscripts"]["empty_descriptions"])
        self.assertIn("DESCRIPTION_FIELD_ABSENT", self.codes(report))

    def test_titles_distinguish_optional_scenes(self):
        self.data["nodes"][0]["title_empty"] = True
        self.data["nodes"][-1]["title_empty"] = True
        report = self.report()
        self.assertEqual(report["manuscripts"]["empty_title_ids"], [100, 103])
        self.assertIn("TITLE_REQUIRED_EMPTY", self.codes(report))
        self.assertIn("OPTIONAL_SCENE_TITLE", self.codes(report))

    def test_users_are_aggregated_including_zero_and_multiple_projects(self):
        self.data["users"].append({"id": 2, "user_type": "TECH_ADMIN", "status": "FROZEN", "is_active": True})
        self.data["projects"].append({"id": 11, "user_id": 1, "status": "DELETED"})
        report = self.report()
        self.assertEqual(report["users"]["project_counts"], {"zero": 1, "one": 0, "multiple": 1})
        self.assertEqual(report["users"]["administrators"], 1)
        self.assertEqual(report["users"]["by_status"]["FROZEN"], 1)
        for finding in report["findings"]:
            self.assertNotIn("users", finding["record_ids"])

    def test_privacy_and_source_values_unchanged(self):
        self.data["users"][0].update(email="secret@example.com", name="Secret real name")
        self.data["nodes"][0].update(title="Secret title", content="Secret literary text", status="secret@example.com")
        before = deepcopy(self.data)
        report = self.report()
        output = json.dumps(report) + render_markdown(report)
        for text in ("secret@example.com", "Secret real name", "Secret title", "Secret literary text"):
            self.assertNotIn(text, output)
        self.assertEqual(self.data, before)
        self.assertEqual(report["manuscripts"]["by_status"]["UNKNOWN"], 1)
        for finding in report["findings"]:
            self.assertIn(finding["severity"], SEVERITIES)
            self.assertIn(finding["compatibility"], COMPATIBILITIES)

    def test_summary_deduplicates_records_across_findings(self):
        self.data["nodes"][-1].update(status="FINISHED", has_text=False)
        report = self.report()
        self.assertEqual(report["summary"]["records_requiring_decision"], 2)  # One scene and one user.
        self.assertEqual(report["summary"]["records_requiring_migration"], 4)

    def test_sql_guard_blocks_writes_before_execution(self):
        execute = Mock()
        for sql in ("UPDATE manuscripts_manuscriptnode SET position=1", "DELETE FROM notes_note", "INSERT INTO projects_project VALUES (1)", "DROP TABLE accounts_user"):
            with self.subTest(sql=sql), self.assertRaises(RuntimeError):
                _select_only(execute, sql, None, False, {})
        execute.assert_not_called()


@override_settings(DEBUG=False)
class AuditCommandTests(SimpleTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        loader = patch("apps.manuscripts.audit.load_inventory", return_value=tree_inventory())
        loader.start()
        self.addCleanup(loader.stop)

    def invoke(self, **options):
        output = StringIO()
        call_command("audit_refactoring", stdout=output, **options)
        return output.getvalue()

    def test_default_summary(self):
        self.assertIn("Registros analizados: 6", self.invoke())

    def test_json_generation(self):
        report = json.loads(self.invoke(format="json"))
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["manuscripts"]["by_type"]["SCENE"], 1)

    def test_markdown_generation(self):
        output = self.invoke(format="markdown")
        self.assertTrue(output.startswith("# Telar de Fabulas"))
        for section in ("users", "projects", "manuscripts", "characters", "notes", "mentions", "exports", "files", "findings"):
            self.assertIn(f"## {section}", output)

    def test_output_infers_json_and_writes_only_report(self):
        target = Path(self.temporary.name) / "inventory.json"
        self.invoke(output=str(target))
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["projects"]["total"], 1)
        self.assertEqual(list(target.parent.iterdir()), [target])

    def test_output_markdown(self):
        target = Path(self.temporary.name) / "inventory.md"
        self.invoke(format="markdown", output=str(target))
        self.assertTrue(target.read_text(encoding="utf-8").startswith("# Telar"))

    def test_existing_file_is_never_overwritten(self):
        target = Path(self.temporary.name) / "existing.json"
        target.write_text("original", encoding="utf-8")
        with self.assertRaises(CommandError):
            self.invoke(output=str(target))
        self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_media_and_static_output_are_rejected(self):
        for setting in ("MEDIA_ROOT", "STATIC_ROOT"):
            with self.subTest(setting=setting), override_settings(**{setting: self.temporary.name}):
                with self.assertRaises(CommandError):
                    self.invoke(output=str(Path(self.temporary.name) / "inventory.json"))
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [])

    def test_bad_extension_and_format_mismatch_are_rejected(self):
        for name, output_format in (("source.py", "json"), ("inventory.md", "json")):
            with self.subTest(name=name), self.assertRaises(CommandError):
                self.invoke(format=output_format, output=str(Path(self.temporary.name) / name))

    def test_database_unavailable_does_not_create_fake_empty_report(self):
        target = Path(self.temporary.name) / "inventory.json"
        with patch("apps.manuscripts.audit.load_inventory", side_effect=OperationalError("private-host")):
            with self.assertRaises(CommandError) as error:
                self.invoke(output=str(target))
        self.assertNotIn("private-host", str(error.exception))
        self.assertFalse(target.exists())


@override_settings(DEBUG=False)
class AuditDatabaseTests(TestCase):
    """Run against the configured test database, never the business database."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(email="audit@example.com", password="test-password")
        self.project = Project.objects.create(user=self.user, name="Private project")
        self.book = ManuscriptNode.objects.create(project=self.project, node_type="BOOK", title="Private book")
        self.chapter = ManuscriptNode.objects.create(project=self.project, parent=self.book, node_type="CHAPTER", title="Chapter")
        self.scene = ManuscriptNode.objects.create(project=self.project, parent=self.chapter, node_type="SCENE", title="Scene", content="Private scene text.")
        self.character = Character.objects.create(project=self.project, name="Private character")
        self.note = Note.objects.create(project=self.project, node=self.scene, title="Private note", content="Private note text")
        self.mention = CharacterMention.objects.create(character=self.character, node=self.scene, mention_type="APPEARS")
        self.style = StyleTemplate.objects.create(name="Audit style", is_system=True)
        self.export = ExportJob.objects.create(user=self.user, project=self.project, root_node=self.scene, style_template=self.style)

    def report(self):
        output = StringIO()
        call_command("audit_refactoring", format="json", stdout=output)
        return json.loads(output.getvalue())

    def snapshot(self):
        return {model._meta.label: list(model.objects.order_by("pk").values())
                for model in (get_user_model(), Project, ManuscriptNode, Character, Note, CharacterMention, StyleTemplate, ExportJob)}

    def test_orm_inventory_and_relations(self):
        report = self.report()
        self.assertEqual(report["summary"]["records_analyzed"], 9)
        self.assertEqual(report["manuscripts"]["with_content"], 1)
        self.assertEqual(report["notes"]["with_node"], 1)
        self.assertEqual(report["dependencies"]["nodes_with_multiple_references"], [self.scene.pk])
        self.assertNotIn("Private", json.dumps(report))

    def test_all_database_values_unchanged_and_no_dml(self):
        before = self.snapshot()
        with CaptureQueriesContext(connection) as queries:
            self.report()
        self.assertEqual(self.snapshot(), before)
        for query in queries:
            self.assertTrue(query["sql"].lstrip().upper().startswith(("SELECT", "SAVEPOINT", "RELEASE", "SET TRANSACTION")), query["sql"])

    def test_number_of_selects_does_not_grow_per_node(self):
        with CaptureQueriesContext(connection) as initial:
            self.report()
        ManuscriptNode.objects.bulk_create([
            ManuscriptNode(project=self.project, parent=self.chapter, node_type="SCENE", title=f"Scene {index}", position=index + 2)
            for index in range(40)
        ])
        with CaptureQueriesContext(connection) as extended:
            self.report()
        count = lambda queries: sum(query["sql"].lstrip().upper().startswith("SELECT") for query in queries)
        self.assertEqual(count(initial), 7)
        self.assertEqual(count(extended), 7)

    def test_cycle_and_invalid_positions_in_database_are_not_repaired(self):
        ManuscriptNode.objects.filter(pk=self.book.pk).update(parent=self.scene, position=0)
        before = self.snapshot()
        report = self.report()
        self.assertEqual(report["manuscripts"]["hierarchy"]["cycles"], [sorted([self.book.pk, self.chapter.pk, self.scene.pk])])
        self.assertEqual(self.snapshot(), before)

    def test_sql_whitespace_lengths_and_empty_descriptions(self):
        ManuscriptNode.objects.filter(pk=self.scene.pk).update(content=" \n\t", title="")
        report = self.report()
        self.assertEqual(report["manuscripts"]["whitespace_only"], 1)
        self.assertEqual(report["manuscripts"]["empty_title_ids"], [self.scene.pk])
        self.assertEqual(report["manuscripts"]["empty_descriptions"], 3)

    def test_missing_media_in_database(self):
        with tempfile.TemporaryDirectory() as root, override_settings(MEDIA_ROOT=root):
            Character.objects.filter(pk=self.character.pk).update(image=f"characters/{self.project.pk}/missing.png")
            report = self.report()
        self.assertEqual(report["files"]["by_status"], {"MISSING": 1})

    def test_new_empty_database_tables_are_reported_as_zero(self):
        # Clear only this test's fixtures, in dependency order; the command does not delete.
        self.export.delete()
        self.note.delete()
        self.mention.delete()
        ManuscriptNode.objects.filter(pk=self.scene.pk).delete()
        ManuscriptNode.objects.filter(pk=self.chapter.pk).delete()
        ManuscriptNode.objects.filter(pk=self.book.pk).delete()
        self.character.delete()
        self.project.delete()
        self.style.delete()
        self.user.delete()
        report = self.report()
        self.assertEqual(report["summary"]["records_analyzed"], 0)
