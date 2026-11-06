"""Regression contracts for the October 2026 master workbook."""
import io
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from docx import Document
from openpyxl import Workbook

from test_master_import import MASTER_HEADERS, SUPPLIED_MASTER, master_row
from test_generator import ROOT, sample_class
import database
import generator
import import_excel


def row(code="A-111", **values):
    result = dict(zip(MASTER_HEADERS, master_row("P1", "Bachelor One", code, rule=2)))
    result.update(values)
    return result


def write_rows(path, rows, omitted=()):
    book = Workbook()
    headers = [header for header in MASTER_HEADERS if header not in omitted]
    book.active.append(headers)
    for item in rows:
        book.active.append([item.get(header) for header in headers])
    book.save(path)


class RepeatedRecordsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "test.db"
        self.xlsx = self.root / "master.xlsx"
        self.patch = patch.object(database, "DB_PATH", self.db)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def load(self, rows, omitted=()):
        write_rows(self.xlsx, rows, omitted)
        return import_excel.import_data(self.xlsx, self.db)

    def test_one_two_many_teachers_deduplicated_in_source_order(self):
        for count in (1, 2, 18):
            with self.subTest(count=count):
                rows = [row(Instructor_Eng=f"Teacher {i}", Instructor_Chn=f"教師{i}",
                            Instructor_Prt=f"Docente {i}", Email=f"{i}@example.test",
                            Room_Chn=f"房間{i}", Room_Eng="wrong", Room_Prt="errado", Telephone=1000+i)
                        for i in range(count)]
                summary = self.load(rows + rows[:1] + rows[-1:])
                self.assertEqual((count+2, 1, count, 0),
                                 tuple(summary[key] for key in ("total_rows", "classes", "instructors", "skipped")))
                cls = database.get_classes_full()[0]
                self.assertEqual(count, len(cls["instructors"]))
                for i, teacher in enumerate(cls["instructors"]):
                    self.assertEqual((f"Teacher {i}", f"{i}@example.test", f"房間{i}", str(1000+i)),
                                     tuple(teacher[key] for key in ("name_en", "email", "room_zh", "telephone")))
                for lang in ("en", "zh", "pt"):
                    context = generator._build_context(cls, lang)
                    names = [f"{i+1}. " if count>1 else "" for i in range(count)]
                    expected = "\n".join(prefix+cls["instructors"][i][f"name_{lang}"] for i, prefix in enumerate(names))
                    self.assertEqual(expected, context["instructor"])
                    doc = Document(io.BytesIO(generator._render_one(cls, lang)))
                    text = "\n".join(cell.text for table in doc.tables for r in table.rows for cell in r.cells)
                    self.assertIn(expected, text)
                    self.assertNotIn("wrong", text)
                    self.assertNotIn("errado", text)
                    for i in range(count):
                        self.assertIn(f"{i}@example.test", text)
                        self.assertIn(f"房間{i}", text)
                        self.assertIn(str(1000+i), text)

    def test_shared_contacts_are_unique_and_keep_owner_labels(self):
        self.load([row(Instructor_Eng="Ada", Email="a@x", Room_Chn="Shared", Telephone=None),
                   row(Instructor_Eng="Bob", Email=None, Room_Chn="Shared", Telephone=123)])
        context = generator._build_context(database.get_classes_full()[0], "en")
        self.assertEqual("1. Ada\n2. Bob", context["instructor"])
        self.assertEqual("[1] a@x", context["email"])
        self.assertEqual("[1, 2] Shared", context["office"])
        self.assertEqual("[2] 123", context["office_phone"])

    def test_contact_only_records_keep_distinct_owner_numbers(self):
        cls = sample_class(instructors=[
            {"email": "a@x", "room_zh": "Room A"},
            {"email": "b@x", "room_zh": "Room B"},
        ])
        context = generator._build_context(cls, "en")
        self.assertEqual("1.\n2.", context["instructor"])
        self.assertEqual("[1] a@x\n[2] b@x", context["email"])
        self.assertEqual("[1] Room A\n[2] Room B", context["office"])

    def test_teacher_name_fallback_preserves_available_source_name(self):
        for lang in ("en", "zh", "pt"):
            cls = sample_class(instructors=[{"name_zh": "教師", "email": "a@x"}])
            self.assertEqual("教師", generator._build_context(cls, lang)["instructor"])

    def test_room_chn_and_document_medium_in_actual_word_cells(self):
        self.load([row(Room_Chn="教研樓 E1208A", Room_Eng="English room", Room_Prt="PT room")])
        cls = database.get_classes_full()[0]
        for lang, medium in (("en", "English"), ("zh", "中文"), ("pt", "Português")):
            doc = Document(io.BytesIO(generator._render_one(cls, lang)))
            self.assertEqual(medium, doc.tables[0].cell(4, 1).text)
            self.assertEqual("教研樓 E1208A", doc.tables[0].cell(7, 1).text)

    def test_room_translations_are_optional_but_prerequisite_code_is_required(self):
        self.load([row(Room_Chn="A")], omitted=("Room_Eng", "Room_Prt"))
        with self.assertRaisesRegex(ValueError, "Prerequsite_Code"):
            self.load([row()], omitted=("Prerequsite_Code",))

    def test_prerequisite_pairs_localized_unique_stable_and_null_safe(self):
        self.load([
            row(Prerequsite_Code="COMP2116", Prerequsite_Eng="Software Engineering", Prerequsite_Chn="軟件工程", Prerequsite_Por="Engenharia de Software"),
            row(Prerequsite_Code="COMP3114", Prerequsite_Eng="Information System Project", Prerequsite_Chn="資訊系統專題", Prerequsite_Por="Projecto de Sistemas"),
            row(Prerequsite_Code="COMP2116", Prerequsite_Eng="Software Engineering", Prerequsite_Chn="軟件工程", Prerequsite_Por="Engenharia de Software"),
        ])
        cls = database.get_classes_full()[0]
        self.assertEqual(["COMP2116", "COMP3114"], [p["prerequisite_code"] for p in cls["prerequisites"]])
        for lang, expected in (
            ("en", "Software Engineering (COMP2116), Information System Project (COMP3114)"),
            ("zh", "軟件工程 (COMP2116), 資訊系統專題 (COMP3114)"),
            ("pt", "Engenharia de Software (COMP2116), Projecto de Sistemas (COMP3114)"),
        ):
            doc = Document(io.BytesIO(generator._render_one(cls, lang)))
            self.assertEqual(expected, doc.tables[0].cell(3, 1).text)

    def test_prerequisite_code_only_name_only_and_legacy_fallback(self):
        cases = [
            ({"prerequisite_code": "C101"}, "C101"),
            ({"name_en": "English only"}, "English only"),
            ({"prerequisite_code": "C101", "name_en": "English only"}, "English only (C101)"),
        ]
        for record, expected in cases:
            for lang in ("en", "zh", "pt"):
                context = generator._build_context(sample_class(prerequisites=[record]), lang)
                self.assertEqual(expected, context["prerequisites"])
        for missing in (None, float("nan"), "", "None", "NaN", "無", "Nil", "Não tem"):
            for lang, expected in generator.PREREQUISITE_DEFAULTS.items():
                cls = sample_class(prerequisites=[{"prerequisite_code": missing, "name_en": missing}])
                self.assertEqual(expected, generator._build_context(cls, lang)["prerequisites"])

    def test_same_name_different_codes_are_distinct_pairs(self):
        cls = sample_class(prerequisites=[{"prerequisite_code": code, "name_en": "Module"} for code in ("C1", "C2", "C1")])
        self.assertEqual("Module (C1), Module (C2)", generator._build_context(cls, "en")["prerequisites"])

    def test_joint_edges_across_rows_unique_packages_and_frontend_choices(self):
        summary = self.load([
            row(Joint_Relationship="A-111, B-111, B-111"),
            row(Joint_Relationship="C-111; B-111"), row(Joint_Relationship=None),
            row("B-111"), row("C-111"),
        ])
        self.assertEqual((5, 3, 1, 1), tuple(summary[k] for k in ("total_rows", "classes", "outlines", "joint_groups")))
        choices = database.get_classes()
        self.assertEqual(["A-111", "B-111", "C-111"], [c["class_code"] for c in choices])
        with sqlite3.connect(self.db) as conn:
            self.assertEqual("B-111, C-111", conn.execute("SELECT joint_relationship FROM classes WHERE class_code='A-111'").fetchone()[0])
        groups = database.get_classes_full()
        with zipfile.ZipFile(generator.generate_batch(groups, output_dir=self.root/"out")) as outer:
            self.assertEqual(["A-111.zip", "B-111.zip", "C-111.zip"], outer.namelist())
            for package in outer.namelist():
                with zipfile.ZipFile(io.BytesIO(outer.read(package))) as inner:
                    self.assertEqual(3, len(inner.namelist()))
                    for name in inner.namelist():
                        doc = Document(io.BytesIO(inner.read(name)))
                        self.assertEqual("A-111, B-111, C-111", doc.tables[0].cell(1, 1).text)

    def test_conflicts_reject_entire_import_and_preserve_existing_database(self):
        self.load([row("EXISTING-111")])
        original = self.db.read_bytes()
        for field, value in (
            ("Credits", 4), ("Durations", 90), ("Rule", 4),
            ("Faculty_Code", "OTHER"), ("Faculty _Eng", "Other faculty"),
            ("Prog_Code", "OTHER"), ("Prog_Prt", "Other programme"),
            ("Module_Eng", "Other module"), ("Module_Chn", "其他"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError) as error:
                    self.load([row(), row(**{field: value})])
                message = str(error.exception)
                self.assertIn("Class_Code A-111", message)
                self.assertIn(field, message)
                self.assertIn("rows [2]", message)
                self.assertIn("rows [3]", message)
                self.assertEqual(original, self.db.read_bytes())

    def test_normalized_identical_rules_pass(self):
        self.assertEqual(1, self.load([row(Rule="Rule TWO"), row(Rule=2.0)])["classes"])

    def test_class_specific_programme_names_preserved_and_reported(self):
        result = self.load([row(Prog_Prt="Curso A"), row("B-111", Prog_Prt="Curso B")])
        self.assertIn("class-specific Prog_Prt", result["warnings"][0])
        self.assertEqual(["Curso A", "Curso B"], [c["prog_name_pt"] for c in database.get_classes_full()])

    def test_child_migration_is_idempotent_and_preserves_existing_records(self):
        self.load([row(Instructor_Eng="One", Prerequsite_Code="P1", Prerequsite_Eng="First"),
                   row(Instructor_Eng="Two", Prerequsite_Code="P2", Prerequsite_Eng="Second")])
        def contents():
            with sqlite3.connect(self.db) as conn:
                self.assertEqual([], conn.execute("PRAGMA foreign_key_check").fetchall())
                return [conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall() for table in ("classes", "class_instructors", "class_prerequisites")]
        before = contents()
        database.init_db(self.db, seed=False)
        database.init_db(self.db, seed=False)
        self.assertEqual(before, contents())

    def test_legacy_scalar_contacts_and_prerequisites_backfilled(self):
        self.load([row(Room_Chn="Room", Prerequsite_Eng="Legacy")])
        with sqlite3.connect(self.db) as conn:
            conn.execute("DROP TABLE class_instructors")
            conn.execute("DROP TABLE class_prerequisites")
        database.init_db(self.db, seed=False)
        database.init_db(self.db, seed=False)
        cls = database.get_classes_full()[0]
        self.assertEqual(1, len(cls["instructors"]))
        self.assertEqual("Room", cls["instructors"][0]["room_zh"])
        self.assertEqual("Legacy", cls["prerequisites"][0]["name_en"])

    @unittest.skipUnless(SUPPLIED_MASTER.exists(), "authoritative workbook unavailable")
    def test_authoritative_workbook_exact_counts_and_records(self):
        import pandas as pd
        frame = pd.read_excel(SUPPLIED_MASTER, dtype=object)
        self.assertEqual(MASTER_HEADERS, list(frame.columns))
        self.assertEqual("Prerequsite_Code", frame.columns[12])
        result = import_excel.import_data(SUPPLIED_MASTER, self.db)
        self.assertEqual((54, 11, 6, 3, 30, 5, 0), tuple(result[k] for k in ("total_rows", "classes", "outlines", "joint_groups", "instructors", "prerequisites", "skipped")))
        self.assertEqual(8, len(result["repeated_classes"]))
        self.assertEqual(36, result["repeated_classes"]["COMP4299-431"])
        self.assertEqual(11, len(database.get_classes()))
        project = next(c for c in database.get_classes_full() if c["class_code"]=="COMP4299-431")
        self.assertEqual(18, len(project["instructors"]))
        self.assertEqual(["COMP2116", "COMP3114"], [p["prerequisite_code"] for p in project["prerequisites"]])

    def test_api_import_summary_choices_filters_and_generation(self):
        import app
        write_rows(self.xlsx, [row(), row(), row("B-111")])
        client = app.app.test_client()
        with patch.object(import_excel, "DB_PATH", self.db), patch.object(app, "DATABASE_STARTUP_ERROR", None), patch.object(generator, "OUTPUT_DIR", self.root/"api"):
            response = client.post("/api/import-excel", data={"file": (io.BytesIO(self.xlsx.read_bytes()), "master.xlsx")})
            self.assertEqual(200, response.status_code)
            self.assertEqual((3, 2), tuple(response.json[k] for k in ("total_rows", "classes")))
            faculties = client.get("/api/faculties").json
            programmes = client.get(f"/api/programmes?faculty_id={faculties[0]['id']}").json
            choices = client.get(f"/api/classes?programme_id={programmes[0]['id']}").json
            self.assertEqual(2, len(choices))
            response = client.post("/api/generate", json={"faculty_id":faculties[0]["id"], "academic_year":"2026/2027", "semester":"1"})
            self.assertEqual(200, response.status_code)
            with zipfile.ZipFile(io.BytesIO(response.data)) as outer:
                self.assertEqual(["A-111.zip", "B-111.zip"], outer.namelist())
            response.close()

    def test_template_admin_environment_loaded_at_process_start(self):
        secret = secrets.token_urlsafe(32)
        code = '''
import os, sys
from unittest.mock import patch
sys.path.insert(0, 'backend')
import database
database.DB_PATH = os.environ['TEST_DATABASE_PATH']
import app
client = app.app.test_client()
secret = os.environ['TEMPLATE_ADMIN_TOKEN']
assert app.app.config['TEMPLATE_ADMIN_TOKEN'] == secret
with patch.object(app, 'update_templates', return_value='test-backup') as update:
    for header in ('', 'Bearer incorrect'):
        response = client.post('/api/templates/convert', headers={'Authorization': header})
        assert response.status_code == 401
        assert secret not in response.get_data(as_text=True)
    update.assert_not_called()
    response = client.post('/api/templates/convert', headers={'Authorization': 'Bearer '+secret})
    assert response.status_code == 200
    update.assert_called_once()
    assert secret not in response.get_data(as_text=True)
assert secret not in client.get('/').get_data(as_text=True)
with patch.dict(app.app.config, TEMPLATE_ADMIN_TOKEN=''):
    assert client.post('/api/templates/convert').status_code == 503
'''
        env = {**os.environ, "TEMPLATE_ADMIN_TOKEN":secret, "TEMPLATE_STORAGE_DIR":str(self.root/"templates"), "TEST_DATABASE_PATH":str(self.db)}
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr.replace(secret, "[redacted]"))


if __name__ == "__main__":
    unittest.main()
