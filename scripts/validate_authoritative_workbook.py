"""Import a supplied master into an isolated DB and verify real DOCX/ZIP output.

Usage: python scripts/validate_authoritative_workbook.py master.xlsx [--output-dir output/master-validation]
Rendering is a separate visual QA step; this script does not claim layout review.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch
import zipfile

import pandas as pd
from docx import Document

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import database
import generator
from import_excel import import_data
from rules import get_rule_paragraphs


def verify_doc(payload, cls, lang):
    generator._validate_rendered_docx(payload)
    doc = Document(io.BytesIO(payload))
    context = generator._build_context(cls, lang)
    table = doc.tables[0]
    for row, col, field in (
        (1, 1, "module_code"), (3, 1, "prerequisites"),
        (4, 1, "medium_of_instruction"), (6, 1, "instructor"),
        (6, 4 if lang == "pt" else 3, "email"), (7, 1, "office"),
        (7, 4 if lang == "pt" else 3, "office_phone"),
    ):
        assert table.cell(row, col).text == context[field], (cls["class_code"], lang, field)
    assert doc.paragraphs[1].text.strip() == context["programme_name"]
    visible = "\n".join(p.text for p in doc.paragraphs)
    for paragraph in get_rule_paragraphs(cls["rule_code"], lang):
        assert paragraph in visible
    assert len(table.rows) == 8
    assert len(table.columns) == (5 if lang == "pt" else 4)
    for cell in (table.cell(3, 1), table.cell(6, 1), table.cell(7, 1)):
        assert "()" not in cell.text
    return doc


def validate(workbook, output):
    output.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(workbook.read_bytes()).hexdigest()
    frame = pd.read_excel(workbook, dtype=object)
    report = {"workbook": workbook.name, "source_sha256": digest,
              "columns": list(frame.columns), "prerequisite_code_column_1based": list(frame.columns).index("Prerequsite_Code")+1}
    db_path = output / "validation.db"
    report["import"] = import_data(workbook, db_path)
    with patch.object(database, "DB_PATH", db_path):
        database.init_db(db_path, seed=False)
        groups = database.get_classes_full()
        choices = database.get_classes()
        assert len(choices) == frame.Class_Code.nunique()
        assert len({c["class_code"] for c in choices}) == len(choices)
        by_code = {code: group for group in groups for code in group["class_codes"]}
        batch = generator.generate_batch(groups, academic_year="2026/2027", semester="1", output_dir=output)
        zip_path = output / "authoritative_packages.zip"
        zip_path.write_bytes(batch.getvalue())
        verified = 0
        with zipfile.ZipFile(batch) as outer:
            assert set(outer.namelist()) == {code+".zip" for code in by_code}
            for package in outer.namelist():
                code = package[:-4]
                cls = {**by_code[code], "academic_year":"2026/2027", "semester":"1"}
                with zipfile.ZipFile(io.BytesIO(outer.read(package))) as inner:
                    assert inner.namelist() == [f"{code}_{lang.upper()}.docx" for lang in ("en", "zh", "pt")]
                    for lang in ("en", "zh", "pt"):
                        verify_doc(inner.read(f"{code}_{lang.upper()}.docx"), cls, lang)
                        verified += 1
        scenarios = {
            "single_teacher": "COMP6131-111",
            "multiple_teachers": "PPOL8101-111",
            "multiple_prerequisites": "COMP4299-431",
            "joint_class": "JAPN1102-211",
            "no_prerequisite": "COMP1121-111",
        }
        representative = output / "representative"
        representative.mkdir(exist_ok=True)
        for scenario, code in scenarios.items():
            cls = {**by_code[code], "academic_year":"2026/2027", "semester":"1"}
            for lang in ("en", "zh", "pt"):
                payload = generator._render_one(cls, lang)
                verify_doc(payload, cls, lang)
                (representative / f"{scenario}_{lang.upper()}.docx").write_bytes(payload)
        import app
        with patch.object(app, "DATABASE_STARTUP_ERROR", None):
            client = app.app.test_client()
            smoke = {path: client.get(path).status_code for path in ("/", "/api/faculties", "/api/programmes", "/api/classes", "/api/academic-years", "/api/column-format", "/api/rules")}
            assert all(status == 200 for status in smoke.values()), smoke
            assert len(client.get("/api/classes").json) == len(choices)
            assert client.get("/api/column-format").json["prerequisite_code"] == "Prerequsite_Code"
            report["api_smoke"] = smoke
        report["groups"] = [{"codes":g["class_codes"], "instructors":len(g["instructors"]),
                            "prerequisites":len(g["prerequisites"]), "rule":g["rule_code"]} for g in groups]
        report["verified_docx"] = verified
        report["zip_packages"] = len(by_code)
        report["representative_scenarios"] = scenarios
        report["representative_docx"] = len(scenarios)*3
    with sqlite3.connect(db_path) as conn:
        report["database_counts"] = {table:conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                                     for table in ("faculties", "programmes", "classes", "class_instructors", "class_prerequisites")}
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert digest == hashlib.sha256(workbook.read_bytes()).hexdigest(), "Source workbook was changed"
    (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT/"output/master-validation")
    args = parser.parse_args()
    validate(args.workbook, args.output_dir)
