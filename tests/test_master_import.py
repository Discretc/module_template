import sqlite3
import sys
import tempfile
import unittest
from io import BytesIO
from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import database  # noqa: E402
import import_excel  # noqa: E402
from rules import JointRuleConflictError, RuleValidationError  # noqa: E402


MASTER_HEADERS = [
    "Faculty_Code", "Faculty _Chn", "Faculty _Eng", "Faculty _Prt",
    "Prog_Code", "Prog_Chn", "Prog_Eng", "Prog_Prt", "Class_Code",
    "Module_Chn", "Module_Eng", "Module_Prt", "Prerequsite_Chn",
    "Prerequsite_Eng", "Prerequsite_Por", "Credits", "Durations",
    "Instructor_Chn", "Instructor_Eng", "Instructor_Prt", "Email",
    "Room_Chn", "Room_Eng", "Room_Prt", "Telephone", "Rule",
    "Joint_Relationship",
]
SUPPLIED_MASTER = Path("/Users/eve/Downloads/Master File to Elvis 20260902.xlsx")


def master_row(programme_code, programme_name, class_code, related="", rule=None, prerequisite=None):
    return [
        "FCA", "應用科學學院", "Faculty of Applied Sciences", "Faculdade de Ciências Aplicadas",
        programme_code, f"{programme_name}中", programme_name, f"{programme_name} PT", class_code,
        "模組", "Module", "Módulo", prerequisite, prerequisite, prerequisite,
        3, 45, "教師", "LECTURER", "DOCENTE", "lecturer@mpu.edu.mo",
        None, None, None, 85990000, rule, related,
    ]


def write_fixture(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "工作表1"
    sheet.append(MASTER_HEADERS)
    sheet.append(master_row("P1", "Bachelor One", "COMP1000-111", "COMP1000-112", 2))
    sheet.append(master_row("P2", "Bachelor Two", "COMP1000-112", "COMP1000-111", 2))
    sheet.append(master_row("P3", "Master Three", "DATA5000-111", rule=1, prerequisite=" "))
    workbook.save(path)


class MasterImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workbook = self.root / "master.xlsx"
        self.database = self.root / "module_outlines.db"
        write_fixture(self.workbook)
        self.original_db_path = database.DB_PATH
        database.DB_PATH = self.database

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        self.temp.cleanup()

    def test_authoritative_column_mapping_is_complete_and_exact(self):
        self.assertEqual(MASTER_HEADERS, list(import_excel.COLUMN_MAP.values()))

    def test_import_faculty_rules_and_joint_grouping(self):
        result = import_excel.import_data(str(self.workbook), self.database)
        self.assertEqual(1, result["faculties"])
        self.assertEqual(3, result["programmes"])
        self.assertEqual(3, result["classes"])
        self.assertEqual(2, result["outlines"])
        self.assertEqual(1, result["joint_groups"])
        self.assertEqual([], result["warnings"])

        faculties = database.get_faculties()
        self.assertEqual("Faculty of Applied Sciences", faculties[0]["name_en"])
        grouped = database.get_classes_full()
        self.assertEqual(2, len(grouped))
        joint = next(item for item in grouped if item["joint_class"])
        self.assertEqual(["COMP1000-111", "COMP1000-112"], joint["class_codes"])
        self.assertEqual("Bachelor One / Bachelor Two", joint["prog_name_en"])
        self.assertEqual(2, joint["rule_code"])
        standalone = next(item for item in grouped if not item["joint_class"])
        self.assertEqual("", standalone["joint_relationship"])
        self.assertEqual("", standalone["medium_of_instruction"])
        conn = sqlite3.connect(self.database)
        stored_medium = conn.execute(
            "SELECT medium_of_instruction FROM classes WHERE class_code = 'DATA5000-111'"
        ).fetchone()[0]
        conn.close()
        self.assertIsNone(stored_medium)
        self.assertEqual(
            [
                {"class_code": "COMP1000-111", "programme": "Bachelor One"},
                {"class_code": "COMP1000-112", "programme": "Bachelor Two"},
            ],
            joint["programme_class_pairs_en"],
        )

    def test_excel_numeric_integer_values_import_as_rule_codes(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(MASTER_HEADERS)
        sheet.append(master_row("P1", "Bachelor One", "COMP1000-111", rule=2))
        sheet.append(master_row("P1", "Bachelor One", "COMP1000-112", rule=2.0))
        workbook.save(self.workbook)

        import_excel.import_data(str(self.workbook), self.database)
        conn = sqlite3.connect(self.database)
        values = [row[0] for row in conn.execute("SELECT rule_code FROM classes ORDER BY class_code")]
        conn.close()
        self.assertEqual([2, 2], values)

    def test_optional_teaching_language_is_preserved_when_explicitly_supplied(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(MASTER_HEADERS + ["Teaching_Language"])
        sheet.append(master_row("P1", "Bachelor One", "COMP1000-111", rule=2) + ["Cantonese"])
        workbook.save(self.workbook)

        import_excel.import_data(str(self.workbook), self.database)
        conn = sqlite3.connect(self.database)
        value = conn.execute("SELECT medium_of_instruction FROM classes").fetchone()[0]
        conn.close()
        self.assertEqual("Cantonese", value)

    def test_programme_filter_returns_one_complete_joint_outline(self):
        import_excel.import_data(str(self.workbook), self.database)
        programmes = database.get_programmes()
        first_programme = next(item for item in programmes if item["code"] == "P1")
        choices = database.get_classes(programme_id=first_programme["id"])
        self.assertEqual(1, len(choices))
        self.assertEqual("COMP1000-111, COMP1000-112", choices[0]["class_code"])
        generated = database.get_classes_full(programme_id=first_programme["id"])
        self.assertEqual(1, len(generated))
        self.assertEqual(2, generated[0]["joint_member_count"])

    def test_dynamic_years_include_imported_and_future_values(self):
        import_excel.import_data(str(self.workbook), self.database)
        conn = sqlite3.connect(self.database)
        conn.execute("UPDATE classes SET academic_year = '2035/2036' WHERE class_code = 'DATA5000-111'")
        conn.commit()
        conn.close()
        result = database.get_academic_years(date(2026, 9, 8))
        self.assertEqual("2026/2027", result["default"])
        self.assertIn("2029/2030", result["years"])
        self.assertIn("2035/2036", result["years"])

    def test_existing_database_without_rule_is_flagged_for_review(self):
        conn = sqlite3.connect(self.database)
        conn.executescript(
            """
            CREATE TABLE faculties (id INTEGER PRIMARY KEY, code TEXT UNIQUE, name_en TEXT, name_zh TEXT, name_pt TEXT);
            CREATE TABLE programmes (id INTEGER PRIMARY KEY, code TEXT UNIQUE, name_en TEXT, name_zh TEXT, name_pt TEXT, degree_level TEXT, faculty_id INTEGER);
            CREATE TABLE classes (id INTEGER PRIMARY KEY, class_code TEXT UNIQUE, module_code TEXT, programme_id INTEGER);
            INSERT INTO faculties VALUES (1, 'FCA', 'Faculty', '', '');
            INSERT INTO programmes VALUES (1, 'P1', 'Programme', '', '', 'bachelor', 1);
            INSERT INTO classes VALUES (1, 'COMP1000-111', 'COMP1000', 1);
            """
        )
        conn.close()
        with self.assertRaisesRegex(database.RuleMigrationRequiredError, "requires review"):
            database.init_db(self.database, seed=False)
        conn = sqlite3.connect(self.database)
        count = conn.execute("SELECT COUNT(*) FROM classes").fetchone()[0]
        review = conn.execute(
            "SELECT class_code, reason FROM rule_migration_review"
        ).fetchall()
        conn.close()
        self.assertEqual(1, count)
        self.assertEqual("COMP1000-111", review[0][0])
        self.assertIn("blank", review[0][1])

    def test_valid_legacy_marking_rule_is_migrated_without_data_loss(self):
        conn = sqlite3.connect(self.database)
        conn.executescript(
            """
            CREATE TABLE faculties (id INTEGER PRIMARY KEY, code TEXT UNIQUE, name_en TEXT, name_zh TEXT, name_pt TEXT);
            CREATE TABLE programmes (id INTEGER PRIMARY KEY, code TEXT UNIQUE, name_en TEXT, name_zh TEXT, name_pt TEXT, degree_level TEXT, faculty_id INTEGER);
            CREATE TABLE classes (id INTEGER PRIMARY KEY, class_code TEXT UNIQUE, module_code TEXT, marking_rule INTEGER, programme_id INTEGER);
            INSERT INTO faculties VALUES (1, 'FCA', 'Faculty', '', '');
            INSERT INTO programmes VALUES (1, 'P1', 'Programme', '', '', 'bachelor', 1);
            INSERT INTO classes VALUES (1, 'COMP1000-111', 'COMP1000', 2, 1);
            """
        )
        conn.close()
        database.init_db(self.database, seed=False)
        conn = sqlite3.connect(self.database)
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(classes)")}
        value = conn.execute("SELECT rule_code FROM classes").fetchone()[0]
        table_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='classes'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(2, value)
        self.assertEqual(1, columns["rule_code"][3])
        self.assertNotIn("marking_rule", columns)
        self.assertIn("CHECK (rule_code IN (1, 2, 3, 4))", table_sql)
        self.assertIsNone(columns["medium_of_instruction"][4])

        database.init_db(self.database, seed=False)
        conn = sqlite3.connect(self.database)
        repeated = conn.execute(
            "SELECT class_code, module_code, rule_code, programme_id FROM classes"
        ).fetchall()
        conn.close()
        self.assertEqual([("COMP1000-111", "COMP1000", 2, 1)], repeated)

    def test_legacy_medium_default_is_removed_without_overwriting_real_values(self):
        conn = sqlite3.connect(self.database)
        conn.executescript(
            """
            CREATE TABLE faculties (id INTEGER PRIMARY KEY, code TEXT UNIQUE, name_en TEXT, name_zh TEXT, name_pt TEXT);
            CREATE TABLE programmes (id INTEGER PRIMARY KEY, code TEXT UNIQUE, name_en TEXT, name_zh TEXT, name_pt TEXT, degree_level TEXT, faculty_id INTEGER);
            CREATE TABLE classes (
                id INTEGER PRIMARY KEY,
                class_code TEXT NOT NULL UNIQUE,
                module_code TEXT NOT NULL,
                medium_of_instruction TEXT DEFAULT 'English',
                rule_code INTEGER NOT NULL CHECK (rule_code IN (1, 2, 3, 4)),
                programme_id INTEGER NOT NULL
            );
            INSERT INTO faculties VALUES (1, 'FCA', 'Faculty', '', '');
            INSERT INTO programmes VALUES (1, 'P1', 'Programme', '', '', 'bachelor', 1);
            INSERT INTO classes VALUES (1, 'COMP1000-111', 'COMP1000', 'Cantonese', 2, 1);
            """
        )
        conn.close()

        database.init_db(self.database, seed=False)
        database.init_db(self.database, seed=False)
        conn = sqlite3.connect(self.database)
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(classes)")}
        value = conn.execute(
            "SELECT medium_of_instruction FROM classes WHERE class_code = 'COMP1000-111'"
        ).fetchone()[0]
        conn.close()
        self.assertIsNone(columns["medium_of_instruction"][4])
        self.assertEqual("Cantonese", value)

    def test_legacy_marking_rule_excel_header_normalizes_to_rule_code(self):
        workbook = Workbook()
        sheet = workbook.active
        headers = ["Marking_Rule" if header == "Rule" else header for header in MASTER_HEADERS]
        sheet.append(headers)
        sheet.append(master_row("P1", "Bachelor One", "COMP1000-111", rule="Rule TWO"))
        workbook.save(self.workbook)

        import_excel.import_data(str(self.workbook), self.database)
        conn = sqlite3.connect(self.database)
        value = conn.execute("SELECT rule_code FROM classes").fetchone()[0]
        conn.close()
        self.assertEqual(2, value)

    def test_database_constraint_rejects_invalid_rule_codes(self):
        database.init_db(self.database, seed=False)
        conn = sqlite3.connect(self.database)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO faculties (code) VALUES ('FCA')")
        conn.execute(
            "INSERT INTO programmes (code, degree_level, faculty_id) VALUES ('P1', 'bachelor', 1)"
        )
        for value in (None, 0, 5):
            with self.subTest(value=value), self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO classes (class_code, module_code, rule_code, programme_id) VALUES (?, ?, ?, 1)",
                    (f"C{value}", "C", value),
                )
        conn.close()

    def test_conflicting_joint_rules_are_reported(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(MASTER_HEADERS)
        sheet.append(master_row("P1", "Bachelor One", "COMP1000-111", "COMP1000-112", 2))
        sheet.append(master_row("P2", "Bachelor Two", "COMP1000-112", "COMP1000-111", 3))
        workbook.save(self.workbook)
        import_excel.import_data(str(self.workbook), self.database)
        choice = database.get_classes()[0]
        self.assertTrue(choice["rule_conflict"])
        self.assertEqual(
            [
                {"class_code": "COMP1000-111", "rule_code": 2},
                {"class_code": "COMP1000-112", "rule_code": 3},
            ],
            choice["rule_conflicts"],
        )
        with self.assertRaisesRegex(JointRuleConflictError, "conflicting Rule"):
            database.get_classes_full()


class RuleNormalizationTests(unittest.TestCase):
    def test_numeric_and_legacy_rule_values(self):
        cases = [
            (1, 1), (2.0, 2), ("3", 3), ("4.0", 4),
            ("Rule 1", 1), ("Rule ONE", 1), ("ONE", 1),
            ("two", 2), ("THREE", 3), ("four", 4), ("一", 1), ("規則四", 4),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(expected, import_excel.normalize_rule(value))

    def test_invalid_rule_values_are_rejected(self):
        for value in (None, "", "  ", "unknown", "Rule FIVE", 0, 5, -1, 2.5, "3.2"):
            with self.subTest(value=value), self.assertRaises(RuleValidationError):
                import_excel.normalize_rule(value)

    def test_invalid_import_is_atomic_and_reports_rows(self):
        for value in (None, "unknown", 2.5, 5):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                workbook_path = root / "invalid.xlsx"
                database_path = root / "existing.db"
                database_path.write_bytes(b"existing database sentinel")
                workbook = Workbook()
                sheet = workbook.active
                sheet.append(MASTER_HEADERS)
                sheet.append(master_row("P1", "Bachelor One", "COMP1000-111", rule=value))
                workbook.save(workbook_path)
                with self.assertRaisesRegex(ValueError, r"row 2 \(COMP1000-111\)"):
                    import_excel.import_data(str(workbook_path), database_path)
                self.assertEqual(b"existing database sentinel", database_path.read_bytes())

    @unittest.skipUnless(SUPPLIED_MASTER.exists(), "supplied master workbook is unavailable")
    def test_supplied_master_has_canonical_headers_and_only_rule_value_errors(self):
        frame = pd.read_excel(SUPPLIED_MASTER, sheet_name=0, dtype=object)
        frame.columns = [str(column).strip() for column in frame.columns]
        import_excel._validate_headers(frame)
        with self.assertRaisesRegex(ValueError, "Invalid Rule values; import was not applied") as error:
            import_excel.import_data(str(SUPPLIED_MASTER), Path(tempfile.gettempdir()) / "unused-master.db")
        self.assertNotIn("no column named", str(error.exception).casefold())


class AdminImportContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app

        cls.app_module = app
        cls.client = app.app.test_client()

    def test_required_excel_columns_endpoint_uses_importer_mapping(self):
        response = self.client.get("/api/column-format")
        self.assertEqual(200, response.status_code)
        self.assertEqual(import_excel.COLUMN_MAP, response.get_json())
        self.assertEqual("Rule", response.get_json()["rule_code"])
        self.assertEqual("Joint_Relationship", response.get_json()["joint_relationship"])
        source = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn('fetch("/api/column-format")', source)
        self.assertNotIn("Marking_Rule</strong>", source)

    def test_upload_endpoint_returns_rule_validation_not_sqlite_schema_error(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(MASTER_HEADERS)
        sheet.append(master_row("P1", "Bachelor One", "COMP1000-111", rule=None))
        payload = BytesIO()
        workbook.save(payload)
        payload.seek(0)

        response = self.client.post(
            "/api/import-excel",
            data={"file": (payload, "master.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(400, response.status_code)
        message = response.get_json()["error"]
        self.assertIn("row 2 (COMP1000-111): Rule is blank", message)
        self.assertNotIn("no column named", message.casefold())


if __name__ == "__main__":
    unittest.main()
